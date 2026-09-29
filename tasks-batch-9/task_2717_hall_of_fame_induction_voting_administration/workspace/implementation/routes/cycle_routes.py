"""Cycle lifecycle transitions (PRD 3.1, 3.4, 3.8, 3.9)."""
from flask import Blueprint

import auth
import calc
import clock
import db
import derive
import lookup
import payload
import response
import serialize
from auth import ROLE_ADMIN
from errors import fail

bp = Blueprint("cycles", __name__)

VETERANS_MIN_YEARS = calc.VETERANS_MIN_YEARS
VETERANS_COOLDOWN_YEARS = calc.VETERANS_COOLDOWN_YEARS
LAPSE_MISSED_CYCLES = calc.LAPSE_MISSED_CYCLES

FINAL_OUTCOMES = ("ELECTION_COMPLETE", "NO_ELECTION")


@bp.route("/induction-cycles/<row_id>/open-nominations", methods=["POST"])
def open_nominations(row_id):
    """SETUP -> NOMINATIONS_OPEN.  The eligibility-rule table must not be empty;
    that existence check (band 5) precedes the cycle-state check (band 6)."""
    auth.caller(ROLE_ADMIN)
    cycle = lookup.cycle(row_id)

    if not db.eligibility_rules:
        fail(
            "ERR_ELIGIBILITY_RULE_NOT_FOUND",
            "No eligibility rule has been published; criteria must exist before intake opens.",
        )
    if cycle["status"] != "SETUP":
        fail("ERR_INVALID_CYCLE_STATE", "Nominations may only be opened from SETUP.")

    cycle["status"] = "NOMINATIONS_OPEN"
    cycle["credentialed_roster_count"] = derive.credentialed_roster_size()
    derive.recompute_cycle(cycle, bump=False)
    db.touch(cycle)
    return response.ok(serialize.cycle(cycle))


@bp.route("/induction-cycles/<row_id>/close-nominations", methods=["POST"])
def close_nominations(row_id):
    """NOMINATIONS_OPEN -> SCREENING, sweeping every SUBMITTED candidacy into
    SCREENING in ascending created_at order."""
    auth.caller(ROLE_ADMIN)
    cycle = lookup.cycle(row_id)
    if cycle["status"] != "NOMINATIONS_OPEN":
        fail("ERR_INVALID_CYCLE_STATE", "Nominations may only be closed from NOMINATIONS_OPEN.")

    for candidacy in derive.candidacies_of(cycle["id"]):
        if candidacy["status"] == "SUBMITTED":
            candidacy["status"] = "SCREENING"
            db.touch(candidacy)

    cycle["status"] = "SCREENING"
    derive.recompute_cycle(cycle, bump=False)
    db.touch(cycle)
    return response.ok(serialize.cycle(cycle))


@bp.route("/induction-cycles/<row_id>/certify-election", methods=["POST"])
def certify_election(row_id):
    """BALLOTING -> CERTIFIED: elect the certified slots, create inductions,
    resolve carryover and expiration, then run roster maintenance."""
    auth.caller(ROLE_ADMIN)
    cycle = lookup.cycle(row_id)
    if cycle["status"] != "BALLOTING":
        fail("ERR_INVALID_CYCLE_STATE", "The election may only be certified from BALLOTING.")

    final = derive.newest_ballot_of(cycle["id"])
    if (
        final is None
        or final["tally_status"] != "AUDIT_CERTIFIED"
        or final["outcome"] not in FINAL_OUTCOMES
    ):
        fail(
            "ERR_ELECTION_NOT_FINAL",
            "The newest ballot is not audit-certified with a final outcome.",
        )

    elected_slots = [s for s in derive.slots_of(final["id"]) if s["status"] == "ELECTED"]
    elected_candidacy_ids = set(s["candidacy_id"] for s in elected_slots)
    unresolved = [
        c
        for c in derive.candidacies_of(cycle["id"])
        if c["status"] in ("ON_BALLOT", "ELIMINATED") and c["id"] not in elected_candidacy_ids
    ]

    # Resolve every rule the carryover machinery needs before anything mutates.
    rules = {}
    for candidacy in unresolved:
        candidate = db.candidates.get(candidacy["candidate_id"])
        rule = calc.rule_for(candidate["category"], candidacy["pathway"])
        if rule is None:
            fail(
                "ERR_ELIGIBILITY_RULE_NOT_FOUND",
                "No eligibility rule governs %s / %s."
                % (candidate["category"], candidacy["pathway"]),
            )
        rules[candidacy["id"]] = rule

    # --- elected candidacies become inductions
    for slot in elected_slots:
        candidacy = db.candidacies.get(slot["candidacy_id"])
        if candidacy is None or candidacy["status"] != "ON_BALLOT":
            continue
        candidate = db.candidates[candidacy["candidate_id"]]
        candidacy["status"] = "ELECTED"
        db.touch(candidacy)
        candidate["hof_status"] = "INDUCTED"
        candidate["ballot_appearances_used"] = candidate["ballot_appearances_used"] + 1
        db.touch(candidate)
        induction = db.stamp(
            {
                "cycle_id": cycle["id"],
                "candidacy_id": candidacy["id"],
                "candidate_id": candidate["id"],
                "status": "ANNOUNCED",
                "travel_status": "PENDING",
                "artifact_status": "AWAITED",
                "exhibit_status": "NOT_PLANNED",
                "delegation_type": (
                    "POSTHUMOUS_DELEGATION" if candidate["is_deceased"] else "LIVING"
                ),
                "artifact_count": 0,
                "ceremony_ready": False,
            }
        )
        db.inductions[induction["id"]] = induction

    # --- carryover and expiration for every scored candidacy that lost
    for candidacy in unresolved:
        candidate = db.candidates[candidacy["candidate_id"]]
        rule = rules[candidacy["id"]]
        candidate["ballot_appearances_used"] = candidate["ballot_appearances_used"] + 1
        if candidate["ballot_appearances_used"] >= rule["max_ballot_appearances"]:
            resolved = "EXPIRED"
        elif calc.dec(candidacy["latest_round_pct"]) >= calc.dec(rule["carryover_min_pct"]):
            resolved = "CARRYOVER_ELIGIBLE"
        else:
            resolved = "EXPIRED"
        if resolved == "EXPIRED":
            candidate["veterans_eligible_from_year"] = max(
                candidate["retirement_year"] + VETERANS_MIN_YEARS,
                cycle["cycle_year"] + VETERANS_COOLDOWN_YEARS,
            )
        db.touch(candidate)
        candidacy["status"] = resolved
        db.touch(candidacy)

    # --- roster maintenance
    certified_ballot_ids = set(
        b["id"] for b in derive.ballots_of(cycle["id"]) if b["tally_status"] == "AUDIT_CERTIFIED"
    )
    participants = set()
    for submission in db.vote_submissions.values():
        if submission["status"] == "COUNTED" and submission["ballot_id"] in certified_ballot_ids:
            participants.add(submission["elector_id"])

    for elector in db.creation_order(
        [e for e in db.electors.values() if e["status"] == "CREDENTIALED"]
    ):
        if elector["id"] in participants:
            changed = (
                elector["consecutive_missed_cycles"] != 0
                or elector["last_participated_cycle_year"] != cycle["cycle_year"]
            )
            elector["consecutive_missed_cycles"] = 0
            elector["last_participated_cycle_year"] = cycle["cycle_year"]
            if changed:
                db.touch(elector)
        else:
            elector["consecutive_missed_cycles"] = elector["consecutive_missed_cycles"] + 1
            if elector["consecutive_missed_cycles"] >= LAPSE_MISSED_CYCLES:
                elector["status"] = "LAPSED"
            db.touch(elector)

    derive.recompute_all_blocs()

    cycle["status"] = "CERTIFIED"
    derive.recompute_cycle(cycle, bump=False)
    db.touch(cycle)
    derive.recompute_roster_counts_everywhere()
    return response.ok(serialize.cycle(cycle))


@bp.route("/induction-cycles/<row_id>/ceremony", methods=["PATCH"])
def plan_ceremony(row_id):
    """CERTIFIED -> CEREMONY_PLANNED."""
    auth.caller(ROLE_ADMIN)
    data = payload.body()
    ceremony_date = payload.req_ts(data, "ceremony_date")
    ceremony_venue = payload.req_str(data, "ceremony_venue", allow_empty=False)
    travel_budget_cents = payload.opt_int(data, "travel_budget_cents", default=None, minimum=0)
    escort_pool_size = payload.opt_int(data, "escort_pool_size", default=None, minimum=0)

    cycle = lookup.cycle(row_id)
    if cycle["status"] != "CERTIFIED":
        fail("ERR_INVALID_CYCLE_STATE", "The ceremony may only be planned from CERTIFIED.")
    if cycle["induction_count"] < 1:
        fail("ERR_INVALID_CYCLE_STATE", "The cycle has no induction to plan a ceremony for.")
    if ceremony_date <= clock.now():
        fail("ERR_INVALID_TIME_WINDOW", "The ceremony date must be later than the current instant.")

    cycle["ceremony_date"] = ceremony_date
    cycle["ceremony_venue"] = ceremony_venue
    if travel_budget_cents is not None:
        cycle["travel_budget_cents"] = travel_budget_cents
    if escort_pool_size is not None:
        cycle["escort_pool_size"] = escort_pool_size
    cycle["status"] = "CEREMONY_PLANNED"
    derive.recompute_cycle(cycle, bump=False)
    db.touch(cycle)
    return response.ok(serialize.cycle(cycle))


@bp.route("/induction-cycles/<row_id>/hold-ceremony", methods=["POST"])
def hold_ceremony(row_id):
    """CEREMONY_PLANNED -> CLOSED, enshrining every induction of the cycle."""
    auth.caller(ROLE_ADMIN)
    cycle = lookup.cycle(row_id)
    if cycle["status"] != "CEREMONY_PLANNED":
        fail("ERR_INVALID_CYCLE_STATE", "The ceremony may only be held from CEREMONY_PLANNED.")

    derive.recompute_cycle(cycle, bump=False)
    if cycle["ceremony_date"] is None or clock.now() < cycle["ceremony_date"]:
        fail("ERR_CEREMONY_DATE_NOT_REACHED", "The stored ceremony date has not been reached.")
    if cycle["ceremony_ready_count"] != cycle["induction_count"]:
        fail("ERR_INDUCTIONS_NOT_READY", "Not every induction of this cycle is ceremony-ready.")

    for induction in derive.inductions_of(cycle["id"]):
        if induction["status"] == "ANNOUNCED":
            induction["status"] = "ENSHRINED"
            db.touch(induction)

    cycle["status"] = "CLOSED"
    db.touch(cycle)
    return response.ok(serialize.cycle(cycle))
