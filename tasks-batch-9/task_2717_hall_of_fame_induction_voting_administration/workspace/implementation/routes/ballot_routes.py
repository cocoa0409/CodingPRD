"""Ballot construction, certification, closing, tabulation and audit
(PRD 3.5, 3.7)."""
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
from auth import ROLE_ADMIN, ROLE_AUDITOR
from errors import fail

bp = Blueprint("ballots", __name__)

AUDIT_DECISIONS = ("REJECT", "CERTIFY")
MAX_ROUNDS = calc.MAX_ROUNDS
MIN_RUNOFF_CONTENDERS = calc.MIN_RUNOFF_CONTENDERS


@bp.route("/ballots", methods=["POST"])
def create_ballot():
    auth.caller(ROLE_ADMIN)
    data = payload.body()
    cycle_id = payload.req_id(data, "cycle_id")
    opens_at = payload.req_ts(data, "opens_at")
    closes_at = payload.req_ts(data, "closes_at")
    expected_cycle_version = payload.req_int(data, "expected_cycle_version")

    cycle = lookup.cycle(cycle_id)

    if cycle["status"] not in ("SCREENING", "BALLOTING"):
        fail("ERR_INVALID_CYCLE_STATE", "A ballot may only be printed from SCREENING or BALLOTING.")

    existing = derive.ballots_of(cycle["id"])
    for ballot in existing:
        if ballot["voting_status"] in ("DRAFT", "OPEN"):
            fail("ERR_INVALID_BALLOT_STATE", "A live ballot already exists for this cycle.")

    newest = existing[-1] if existing else None
    scenario = "FIRST"
    if cycle["status"] == "BALLOTING":
        if newest is None:
            fail("ERR_INVALID_BALLOT_STATE", "The cycle is balloting but holds no ballot.")
        if newest["tally_status"] == "AUDIT_CERTIFIED" and newest["outcome"] == "RUNOFF_REQUIRED":
            scenario = "RUNOFF"
        elif newest["voting_status"] == "EXPIRED":
            scenario = "REPLACEMENT"
        else:
            fail(
                "ERR_INVALID_BALLOT_STATE",
                "The newest ballot neither requires a runoff nor has expired.",
            )

    if expected_cycle_version != cycle["version"]:
        fail("ERR_STALE_CYCLE_VERSION", "The cycle has advanced since it was read.")

    # --- slate source
    if scenario == "FIRST":
        source = [c for c in derive.candidacies_of(cycle["id"]) if c["status"] == "ADVANCED"]
        round_number = 1
    elif scenario == "RUNOFF":
        carried = [s for s in derive.slots_of(newest["id"]) if s["status"] == "CARRIED_TO_RUNOFF"]
        source = []
        for slot in carried:
            candidacy = db.candidacies.get(slot["candidacy_id"])
            if candidacy is not None:
                source.append(candidacy)
        source = db.creation_order(source)
        round_number = cycle["current_round"]
    else:
        source = [c for c in derive.candidacies_of(cycle["id"]) if c["status"] == "ON_BALLOT"]
        round_number = newest["round_number"]

    if not source:
        fail("ERR_NO_SLATE_AVAILABLE", "The applicable slate source yields no candidacy.")

    if opens_at >= closes_at:
        fail("ERR_INVALID_TIME_WINDOW", "'opens_at' must be strictly before 'closes_at'.")

    ballot = db.stamp(
        {
            "cycle_id": cycle["id"],
            "round_number": round_number,
            "voting_status": "DRAFT",
            "tally_status": "NOT_TALLIED",
            "opens_at": opens_at,
            "closes_at": closes_at,
            "max_votes_per_elector": 0,
            "slot_count": 0,
            "ballots_cast": 0,
            "total_selections_counted": 0,
            "credentialed_roster_at_close": 0,
            "threshold_votes_provisional": 0,
            "threshold_votes_final": 0,
            "elected_slot_count": 0,
            "outcome": None,
            "tallied_by_user_id": None,
            "audit_note": None,
        }
    )
    db.ballots[ballot["id"]] = ballot

    for candidacy in source:
        candidate = db.candidates.get(candidacy["candidate_id"])
        if scenario == "FIRST":
            candidacy["status"] = "ON_BALLOT"
            candidacy["appearance_number"] = candidate["ballot_appearances_used"] + 1
            db.touch(candidacy)
        slot = db.stamp(
            {
                "ballot_id": ballot["id"],
                "candidacy_id": candidacy["id"],
                "candidate_name_snapshot": candidate["full_name"],
                "pathway_snapshot": candidacy["pathway"],
                "candidacy_version_pinned": candidacy["version"],
                "votes_received": 0,
                "vote_pct": 0.0,
                "status": "LISTED",
            }
        )
        db.ballot_slots[slot["id"]] = slot

    listed = [s for s in derive.slots_of(ballot["id"]) if s["status"] == "LISTED"]
    ballot["max_votes_per_elector"] = calc.max_votes_per_elector_for_round(listed, round_number)
    derive.recompute_ballot_counters(ballot, bump=False)

    if scenario == "FIRST":
        cycle["status"] = "BALLOTING"
        cycle["current_round"] = 1
    derive.recompute_cycle(cycle, bump=False)
    db.touch(cycle)

    return response.created(serialize.ballot(ballot))


@bp.route("/ballots", methods=["GET"])
def list_ballots():
    auth.caller(*auth.ALL_ROLES)
    return lookup.listing(
        db.ballots,
        [
            ("cycle_id", "cycle_id", "str"),
            ("round_number", "round_number", "int"),
            ("voting_status", "voting_status", "str"),
            ("tally_status", "tally_status", "str"),
        ],
        serialize.ballot,
    )


@bp.route("/ballots/<row_id>", methods=["GET"])
def read_ballot(row_id):
    auth.caller(*auth.ALL_ROLES)
    return response.ok(serialize.ballot(lookup.ballot(row_id)))


@bp.route("/ballots/<row_id>/certify", methods=["POST"])
def certify_slate(row_id):
    """DRAFT -> OPEN."""
    auth.caller(ROLE_ADMIN)
    ballot = lookup.ballot(row_id)
    if ballot["voting_status"] != "DRAFT":
        fail("ERR_INVALID_BALLOT_STATE", "Only a DRAFT ballot may be certified for voting.")
    derive.recompute_ballot_counters(ballot, bump=False)
    if ballot["slot_count"] < 1:
        fail("ERR_INVALID_BALLOT_STATE", "The ballot carries no listed slot.")
    now = clock.now()
    if now < ballot["opens_at"] or now >= ballot["closes_at"]:
        fail("ERR_INVALID_BALLOT_STATE", "The logical clock is outside the declared window.")

    ballot["voting_status"] = "OPEN"
    db.touch(ballot)
    return response.ok(serialize.ballot(ballot))


@bp.route("/ballots/<row_id>/close", methods=["POST"])
def close_ballot(row_id):
    """OPEN -> CLOSED before closes_at, OPEN -> EXPIRED at or after it."""
    auth.caller(ROLE_ADMIN)
    ballot = lookup.ballot(row_id)
    if ballot["voting_status"] != "OPEN":
        fail("ERR_INVALID_BALLOT_STATE", "Only an OPEN ballot may be closed.")

    now = clock.now()
    ballot["voting_status"] = "CLOSED" if now < ballot["closes_at"] else "EXPIRED"
    ballot["credentialed_roster_at_close"] = derive.roster_at(now)
    db.touch(ballot)
    return response.ok(serialize.ballot(ballot))


@bp.route("/ballots/<row_id>/tally", methods=["POST"])
def tally_ballot(row_id):
    """The draft tally with the turnout-based provisional threshold."""
    actor = auth.caller(ROLE_ADMIN)
    ballot = lookup.ballot(row_id)

    if ballot["voting_status"] == "EXPIRED":
        fail("ERR_BALLOT_EXPIRED", "An expired ballot is never tabulated.")
    if ballot["voting_status"] != "CLOSED":
        fail("ERR_INVALID_BALLOT_STATE", "The draft tally requires a CLOSED ballot.")
    if ballot["tally_status"] not in ("NOT_TALLIED", "AUDIT_REJECTED"):
        fail("ERR_INVALID_TALLY_STATE", "The draft tally requires NOT_TALLIED or AUDIT_REJECTED.")

    derive.recompute_ballot_counters(ballot, bump=False)
    if ballot["ballots_cast"] == 0:
        fail("ERR_NO_BALLOTS_CAST", "No counted submission exists on this ballot.")

    pct = calc.house_threshold_pct()

    derive.recompute_slot_votes(ballot)
    ballot["threshold_votes_provisional"] = calc.ceil_votes(ballot["ballots_cast"], pct)
    ballot["tallied_by_user_id"] = actor.user_id
    ballot["tally_status"] = "PENDING_AUDIT"
    db.touch(ballot)
    return response.ok(serialize.ballot(ballot))


def _bloc_quorum(ballot, counted):
    """Every bloc holding at least one seat must have reached its floor."""
    for bloc in db.sort_rows(list(db.voter_blocs.values())):
        if bloc["seats_filled"] < 1:
            continue
        participating = 0
        for submission in counted:
            elector = db.electors.get(submission["elector_id"])
            if elector is not None and elector["bloc_id"] == bloc["id"]:
                participating += 1
        share = calc.dec(participating) / calc.dec(bloc["seats_filled"])
        if share < calc.dec(bloc["min_participation_pct"]):
            fail(
                "ERR_BLOC_QUORUM_NOT_MET",
                "Bloc '%s' fell short of its participation floor." % bloc["bloc_code"],
            )


@bp.route("/ballots/<row_id>/audit-decision", methods=["POST"])
def audit_decision(row_id):
    actor = auth.caller(ROLE_AUDITOR)
    data = payload.body()
    decision = payload.req_enum(data, "decision", AUDIT_DECISIONS)
    invalidate_ids = payload.opt_id_list(data, "invalidate_submission_ids", default=[])
    audit_note = payload.opt_str(data, "audit_note", default=None)

    ballot = lookup.ballot(row_id)
    for submission_id in invalidate_ids:
        submission = lookup.vote_submission(submission_id)
        if submission["ballot_id"] != ballot["id"]:
            fail("ERR_BALLOT_NOT_FOUND", "Submission '%s' is not on this ballot." % submission_id)

    if ballot["voting_status"] == "EXPIRED":
        fail("ERR_BALLOT_EXPIRED", "An expired ballot is never audited.")
    if ballot["tally_status"] != "PENDING_AUDIT":
        fail("ERR_INVALID_TALLY_STATE", "An audit decision requires PENDING_AUDIT.")
    if actor.user_id == ballot["tallied_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES", "The operator who produced the tally may not audit it.")

    if decision == "REJECT":
        targets = db.creation_order(
            [db.vote_submissions[i] for i in dict.fromkeys(invalidate_ids)]
        )
        for submission in targets:
            if submission["status"] != "COUNTED":
                continue
            submission["status"] = "INVALIDATED"
            submission["invalidated_reason"] = audit_note
            db.touch(submission)
        derive.recompute_ballot_counters(ballot, bump=False)
        derive.recompute_slot_votes(ballot)
        ballot["threshold_votes_provisional"] = 0
        ballot["tallied_by_user_id"] = None
        ballot["tally_status"] = "AUDIT_REJECTED"
        if audit_note is not None:
            ballot["audit_note"] = audit_note
        db.touch(ballot)
        return response.ok(serialize.ballot(ballot))

    # --- CERTIFY
    cycle = lookup.cycle(ballot["cycle_id"])
    counted = derive.counted_submissions_of(ballot["id"])
    _bloc_quorum(ballot, counted)

    pct = calc.house_threshold_pct()
    listed = [s for s in derive.slots_of(ballot["id"]) if s["status"] == "LISTED"]

    rules = {}
    for slot in listed:
        candidacy = db.candidacies.get(slot["candidacy_id"])
        candidate = db.candidates.get(candidacy["candidate_id"])
        rule = calc.rule_for(candidate["category"], candidacy["pathway"])
        if rule is None:
            fail(
                "ERR_ELIGIBILITY_RULE_NOT_FOUND",
                "No eligibility rule governs %s / %s."
                % (candidate["category"], candidacy["pathway"]),
            )
        rules[slot["id"]] = rule

    threshold_final = calc.ceil_votes(ballot["credentialed_roster_at_close"], pct)

    def rank_key(slot):
        candidacy = db.candidacies[slot["candidacy_id"]]
        return (-slot["votes_received"], candidacy["created_at"], candidacy["_seq"])

    ranked = sorted(
        [s for s in listed if s["votes_received"] >= threshold_final], key=rank_key
    )
    already_elected = len(
        [c for c in derive.candidacies_of(cycle["id"]) if c["status"] == "ELECTED"]
    )
    seats = cycle["max_inductees"] - already_elected
    elected = ranked[: min(seats, len(ranked))] if seats > 0 else []
    elected_ids = set(s["id"] for s in elected)

    carry = [
        s
        for s in listed
        if s["id"] not in elected_ids
        and calc.dec(s["vote_pct"]) >= calc.dec(rules[s["id"]]["runoff_floor_pct"])
    ]

    # The outcome is resolved before any slot status is written.
    if elected:
        outcome = "ELECTION_COMPLETE"
    elif ballot["round_number"] < MAX_ROUNDS and len(carry) >= MIN_RUNOFF_CONTENDERS:
        outcome = "RUNOFF_REQUIRED"
    else:
        outcome = "NO_ELECTION"

    carry_ids = set(s["id"] for s in carry) if outcome == "RUNOFF_REQUIRED" else set()

    for slot in listed:
        if slot["id"] in elected_ids:
            slot["status"] = "ELECTED"
        elif slot["id"] in carry_ids:
            slot["status"] = "CARRIED_TO_RUNOFF"
        else:
            slot["status"] = "NOT_ELECTED"
        db.touch(slot)

        candidacy = db.candidacies.get(slot["candidacy_id"])
        if candidacy is None:
            continue
        candidacy["latest_round_votes"] = slot["votes_received"]
        candidacy["latest_round_pct"] = slot["vote_pct"]
        if (
            slot["status"] == "NOT_ELECTED"
            and outcome == "RUNOFF_REQUIRED"
            and candidacy["status"] == "ON_BALLOT"
        ):
            candidacy["status"] = "ELIMINATED"
        db.touch(candidacy)

    ballot["threshold_votes_final"] = threshold_final
    ballot["elected_slot_count"] = len(elected)
    ballot["outcome"] = outcome
    ballot["tally_status"] = "AUDIT_CERTIFIED"
    if audit_note is not None:
        ballot["audit_note"] = audit_note
    db.touch(ballot)

    if outcome == "RUNOFF_REQUIRED":
        cycle["current_round"] = cycle["current_round"] + 1
        db.touch(cycle)

    return response.ok(serialize.ballot(ballot))


# ------------------------------------------------------------------ slot reads


@bp.route("/ballot-slots", methods=["GET"])
def list_slots():
    auth.caller(*auth.ALL_ROLES)
    return lookup.listing(
        db.ballot_slots,
        [
            ("ballot_id", "ballot_id", "str"),
            ("candidacy_id", "candidacy_id", "str"),
            ("status", "status", "str"),
        ],
        serialize.ballot_slot,
    )


@bp.route("/ballot-slots/<row_id>", methods=["GET"])
def read_slot(row_id):
    auth.caller(*auth.ALL_ROLES)
    return response.ok(serialize.ballot_slot(lookup.ballot_slot(row_id)))
