"""Configuration surface: the logical clock, cycles, criteria, blocs, cases,
candidates and electors."""
from flask import Blueprint

import auth
import clock
import db
import derive
import lookup
import payload
import response
import serialize
from auth import (
    ROLE_ADMIN,
    ROLE_AUDITOR,
    ROLE_CURATOR,
    ROLE_ELECTOR,
    ROLE_SCREENER,
)
from errors import fail

bp = Blueprint("config", __name__)

CATEGORIES = ("PLAYER", "COACH", "CONTRIBUTOR")
PATHWAYS = ("MODERN", "VETERANS", "POSTHUMOUS", "SPECIAL")

YEAR_MIN = 1900
YEAR_MAX = 2200

CYCLE_STATUSES = (
    "SETUP",
    "NOMINATIONS_OPEN",
    "SCREENING",
    "BALLOTING",
    "CERTIFIED",
    "CEREMONY_PLANNED",
    "CLOSED",
)

LIVE_CANDIDACY_STATES = ("SUBMITTED", "SCREENING", "INFO_REQUESTED", "ADVANCED", "ON_BALLOT")


# ------------------------------------------------------------- logical clock


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    auth.caller(*auth.ALL_ROLES)
    data = payload.body()
    instant = payload.req_ts(data, "current_utc")
    clock.set_now(instant)
    return response.ok({})


# ------------------------------------------------------------ induction cycles


@bp.route("/induction-cycles", methods=["POST"])
def create_cycle():
    auth.caller(ROLE_ADMIN)
    data = payload.body()
    cycle_year = payload.req_int(data, "cycle_year", minimum=YEAR_MIN, maximum=YEAR_MAX)
    sport_code = payload.req_str(data, "sport_code", allow_empty=False)
    travel_budget_cents = payload.opt_int(data, "travel_budget_cents", default=0, minimum=0)
    escort_pool_size = payload.opt_int(data, "escort_pool_size", default=0, minimum=0)
    max_inductees = payload.opt_int(data, "max_inductees", default=5, minimum=1)

    for row in db.cycles.values():
        if row["sport_code"] == sport_code and row["cycle_year"] == cycle_year:
            fail(
                "ERR_DUPLICATE_CONFIGURATION",
                "A cycle already exists for %s %d." % (sport_code, cycle_year),
            )

    row = db.stamp(
        {
            "cycle_year": cycle_year,
            "sport_code": sport_code,
            "max_inductees": max_inductees,
            "status": "SETUP",
            "current_round": 0,
            "nomination_count": 0,
            "advanced_candidacy_count": 0,
            "special_election_used": 0,
            "credentialed_roster_count": 0,
            "ceremony_date": None,
            "ceremony_venue": None,
            "travel_budget_cents": travel_budget_cents,
            "travel_committed_cents": 0,
            "escort_pool_size": escort_pool_size,
            "austerity_tier": "FULL",
            "induction_count": 0,
            "ceremony_ready_count": 0,
        }
    )
    db.cycles[row["id"]] = row
    return response.created(serialize.cycle(row))


@bp.route("/induction-cycles", methods=["GET"])
def list_cycles():
    auth.caller(*auth.ALL_ROLES)
    return lookup.listing(
        db.cycles,
        [("sport_code", "sport_code", "str"), ("status", "status", "str")],
        serialize.cycle,
    )


@bp.route("/induction-cycles/<row_id>", methods=["GET"])
def read_cycle(row_id):
    auth.caller(*auth.ALL_ROLES)
    return response.ok(serialize.cycle(lookup.cycle(row_id)))


# ----------------------------------------------------------- eligibility rules


@bp.route("/eligibility-rules", methods=["POST"])
def create_rule():
    auth.caller(ROLE_ADMIN)
    data = payload.body()
    category = payload.req_enum(data, "category", CATEGORIES)
    pathway = payload.req_enum(data, "pathway", PATHWAYS)
    waiting_period_years = payload.req_int(data, "waiting_period_years", minimum=0)
    min_career_seasons = payload.req_int(data, "min_career_seasons", minimum=0)
    min_career_metric = payload.req_num(data, "min_career_metric", minimum=0)
    max_ballot_appearances = payload.req_int(data, "max_ballot_appearances", minimum=1)
    election_threshold_pct = payload.req_num(data, "election_threshold_pct", maximum=1)
    if election_threshold_pct <= 0:
        fail("ERR_INVALID_REQUEST", "Field 'election_threshold_pct' must be greater than 0.")
    carryover_min_pct = payload.req_num(data, "carryover_min_pct", minimum=0, maximum=1)
    runoff_floor_pct = payload.req_num(data, "runoff_floor_pct", minimum=0, maximum=1)

    for row in db.eligibility_rules.values():
        if row["category"] == category and row["pathway"] == pathway:
            fail(
                "ERR_DUPLICATE_CONFIGURATION",
                "An eligibility rule already governs %s / %s." % (category, pathway),
            )

    row = db.stamp(
        {
            "category": category,
            "pathway": pathway,
            "waiting_period_years": waiting_period_years,
            "min_career_seasons": min_career_seasons,
            "min_career_metric": min_career_metric,
            "max_ballot_appearances": max_ballot_appearances,
            "election_threshold_pct": election_threshold_pct,
            "carryover_min_pct": carryover_min_pct,
            "runoff_floor_pct": runoff_floor_pct,
        },
        versioned=False,
    )
    db.eligibility_rules[row["id"]] = row
    return response.created(serialize.eligibility_rule(row))


@bp.route("/eligibility-rules", methods=["GET"])
def list_rules():
    auth.caller(ROLE_ADMIN, ROLE_SCREENER, ROLE_ELECTOR, ROLE_AUDITOR)
    return lookup.listing(
        db.eligibility_rules,
        [("category", "category", "str"), ("pathway", "pathway", "str")],
        serialize.eligibility_rule,
    )


@bp.route("/eligibility-rules/<row_id>", methods=["GET"])
def read_rule(row_id):
    auth.caller(ROLE_ADMIN, ROLE_SCREENER, ROLE_AUDITOR)
    return response.ok(serialize.eligibility_rule(lookup.eligibility_rule(row_id)))


# ---------------------------------------------------------------- voter blocs


@bp.route("/voter-blocs", methods=["POST"])
def create_bloc():
    auth.caller(ROLE_ADMIN)
    data = payload.body()
    bloc_code = payload.req_str(data, "bloc_code", allow_empty=False)
    name = payload.req_str(data, "name", allow_empty=False)
    seat_cap = payload.req_int(data, "seat_cap", minimum=1)
    min_participation_pct = payload.req_num(data, "min_participation_pct", minimum=0, maximum=1)

    for row in db.voter_blocs.values():
        if row["bloc_code"] == bloc_code:
            fail("ERR_DUPLICATE_CONFIGURATION", "Bloc code '%s' is already taken." % bloc_code)

    row = db.stamp(
        {
            "bloc_code": bloc_code,
            "name": name,
            "seat_cap": seat_cap,
            "min_participation_pct": min_participation_pct,
            "seats_filled": 0,
        },
        versioned=False,
    )
    db.voter_blocs[row["id"]] = row
    return response.created(serialize.voter_bloc(row))


@bp.route("/voter-blocs", methods=["GET"])
def list_blocs():
    auth.caller(ROLE_ADMIN, ROLE_AUDITOR)
    return lookup.listing(
        db.voter_blocs, [("bloc_code", "bloc_code", "str")], serialize.voter_bloc
    )


@bp.route("/voter-blocs/<row_id>", methods=["GET"])
def read_bloc(row_id):
    auth.caller(ROLE_ADMIN, ROLE_AUDITOR)
    return response.ok(serialize.voter_bloc(lookup.voter_bloc(row_id)))


# -------------------------------------------------------------- exhibit cases


@bp.route("/exhibit-cases", methods=["POST"])
def create_case():
    auth.caller(ROLE_CURATOR, ROLE_ADMIN)
    data = payload.body()
    case_code = payload.req_str(data, "case_code", allow_empty=False)
    capacity_artifacts = payload.req_int(data, "capacity_artifacts", minimum=1)
    changeover_buffer_days = payload.req_int(data, "changeover_buffer_days", minimum=0)

    for row in db.exhibit_cases.values():
        if row["case_code"] == case_code:
            fail("ERR_DUPLICATE_CONFIGURATION", "Case code '%s' is already taken." % case_code)

    row = db.stamp(
        {
            "case_code": case_code,
            "capacity_artifacts": capacity_artifacts,
            "changeover_buffer_days": changeover_buffer_days,
            "artifacts_installed": 0,
        }
    )
    db.exhibit_cases[row["id"]] = row
    return response.created(serialize.exhibit_case(row))


@bp.route("/exhibit-cases", methods=["GET"])
def list_cases():
    auth.caller(ROLE_ADMIN, ROLE_CURATOR, ROLE_AUDITOR)
    return lookup.listing(
        db.exhibit_cases, [("case_code", "case_code", "str")], serialize.exhibit_case
    )


@bp.route("/exhibit-cases/<row_id>", methods=["GET"])
def read_case(row_id):
    auth.caller(ROLE_ADMIN, ROLE_CURATOR, ROLE_AUDITOR)
    return response.ok(serialize.exhibit_case(lookup.exhibit_case(row_id)))


# ----------------------------------------------------------------- candidates


@bp.route("/candidates", methods=["POST"])
def create_candidate():
    auth.caller(ROLE_ADMIN)
    data = payload.body()
    full_name = payload.req_str(data, "full_name", allow_empty=False)
    category = payload.req_enum(data, "category", CATEGORIES)
    retirement_year = payload.req_int(data, "retirement_year", minimum=YEAR_MIN, maximum=YEAR_MAX)
    career_seasons = payload.req_int(data, "career_seasons", minimum=0)
    career_metric_value = payload.req_num(data, "career_metric_value", minimum=0)
    is_deceased = payload.opt_bool(data, "is_deceased", default=False)
    death_year = payload.opt_int(data, "death_year", default=None)
    if is_deceased and death_year is None:
        fail("ERR_INVALID_REQUEST", "Field 'death_year' is required when 'is_deceased' is true.")

    row = db.stamp(
        {
            "full_name": full_name,
            "category": category,
            "retirement_year": retirement_year,
            "career_seasons": career_seasons,
            "career_metric_value": career_metric_value,
            "is_deceased": is_deceased,
            "death_year": death_year,
            "hof_status": "NOT_INDUCTED",
            "permanently_ineligible_reason": None,
            "ballot_appearances_used": 0,
            "veterans_eligible_from_year": None,
        }
    )
    db.candidates[row["id"]] = row
    return response.created(serialize.candidate(row))


@bp.route("/candidates", methods=["GET"])
def list_candidates():
    auth.caller(*auth.ALL_ROLES)
    return lookup.listing(
        db.candidates,
        [
            ("category", "category", "str"),
            ("hof_status", "hof_status", "str"),
            ("is_deceased", "is_deceased", "bool"),
        ],
        serialize.candidate,
    )


@bp.route("/candidates/<row_id>", methods=["GET"])
def read_candidate(row_id):
    auth.caller(*auth.ALL_ROLES)
    return response.ok(serialize.candidate(lookup.candidate(row_id)))


@bp.route("/candidates/<row_id>", methods=["PATCH"])
def patch_candidate(row_id):
    """A biographical correction; hof_status, ballot_appearances_used and
    veterans_eligible_from_year are outcomes of the election machinery and are
    left exactly as they were."""
    auth.caller(ROLE_ADMIN)
    data = payload.body()
    career_seasons = payload.opt_int(data, "career_seasons", default=None, minimum=0)
    career_metric_value = payload.opt_num(data, "career_metric_value", default=None, minimum=0)
    is_deceased = payload.opt_bool(data, "is_deceased", default=None)
    death_year = payload.opt_int(data, "death_year", default=None)

    row = lookup.candidate(row_id)

    resulting_deceased = row["is_deceased"] if is_deceased is None else is_deceased
    resulting_death_year = row["death_year"] if death_year is None else death_year
    if resulting_deceased and resulting_death_year is None:
        fail("ERR_INVALID_REQUEST", "Field 'death_year' is required when 'is_deceased' is true.")

    if career_seasons is not None:
        row["career_seasons"] = career_seasons
    if career_metric_value is not None:
        row["career_metric_value"] = career_metric_value
    if is_deceased is not None:
        row["is_deceased"] = is_deceased
    if death_year is not None:
        row["death_year"] = death_year
    db.touch(row)
    return response.ok(serialize.candidate(row))


@bp.route("/candidates/<row_id>/permanent-ineligibility", methods=["POST"])
def bar_candidate(row_id):
    """The one destructive act in this domain: it cascades to every live
    candidacy and to every slot printed on a DRAFT or OPEN ballot."""
    auth.caller(ROLE_ADMIN)
    data = payload.body()
    reason = payload.req_str(data, "permanently_ineligible_reason", allow_empty=False)

    candidate = lookup.candidate(row_id)

    candidate["hof_status"] = "PERMANENTLY_INELIGIBLE"
    candidate["permanently_ineligible_reason"] = reason
    db.touch(candidate)

    struck_candidacy_ids = []
    touched_cycles = []
    for candidacy in db.creation_order(
        [c for c in db.candidacies.values() if c["candidate_id"] == candidate["id"]]
    ):
        if candidacy["status"] not in LIVE_CANDIDACY_STATES:
            continue
        candidacy["status"] = "STRUCK"
        db.touch(candidacy)
        struck_candidacy_ids.append(candidacy["id"])
        if candidacy["cycle_id"] not in touched_cycles:
            touched_cycles.append(candidacy["cycle_id"])

    if struck_candidacy_ids:
        slots = [
            s
            for s in db.ballot_slots.values()
            if s["candidacy_id"] in struck_candidacy_ids and s["status"] != "STRUCK"
        ]
        for slot in db.creation_order(slots):
            ballot = db.ballots.get(slot["ballot_id"])
            if ballot is None or ballot["voting_status"] not in ("DRAFT", "OPEN"):
                continue
            slot["status"] = "STRUCK"
            slot["votes_received"] = 0
            slot["vote_pct"] = 0.0
            db.touch(slot)
            derive.recompute_ballot_counters(ballot, bump=False)
            derive.recompute_slot_votes(ballot)
            db.touch(ballot)

    for cycle_id in touched_cycles:
        cycle = db.cycles.get(cycle_id)
        if cycle is not None:
            derive.recompute_cycle(cycle)

    return response.ok(serialize.candidate(candidate))


# ------------------------------------------------------------------- electors


@bp.route("/electors", methods=["POST"])
def create_elector():
    auth.caller(ROLE_ADMIN)
    data = payload.body()
    full_name = payload.req_str(data, "full_name", allow_empty=False)
    bloc_id = payload.req_id(data, "bloc_id")
    credential_expires_on = payload.req_ts(data, "credential_expires_on")
    is_screening_member = payload.opt_bool(data, "is_screening_member", default=False)

    lookup.voter_bloc(bloc_id)

    row = db.stamp(
        {
            "full_name": full_name,
            "bloc_id": bloc_id,
            "is_screening_member": is_screening_member,
            "credential_expires_on": credential_expires_on,
            "status": "PROVISIONAL",
            "consecutive_missed_cycles": 0,
            "last_participated_cycle_year": None,
            "suspension_reason": None,
        }
    )
    db.electors[row["id"]] = row
    return response.created(serialize.elector(row))


@bp.route("/electors", methods=["GET"])
def list_electors():
    auth.caller(ROLE_ADMIN, ROLE_AUDITOR)
    return lookup.listing(
        db.electors,
        [
            ("bloc_id", "bloc_id", "str"),
            ("status", "status", "str"),
            ("is_screening_member", "is_screening_member", "bool"),
        ],
        serialize.elector,
    )


@bp.route("/electors/<row_id>", methods=["GET"])
def read_elector(row_id):
    auth.caller(ROLE_ADMIN, ROLE_SCREENER, ROLE_ELECTOR, ROLE_AUDITOR)
    return response.ok(serialize.elector(lookup.elector(row_id)))


@bp.route("/electors/<row_id>/credential", methods=["POST"])
def credential_elector(row_id):
    """PROVISIONAL -> CREDENTIALED.  Credential liveness (band 8) is evaluated
    before the bloc seat arithmetic (band 10), per the ladder of PRD 2.11."""
    auth.caller(ROLE_ADMIN)
    data = payload.body()
    replacement = payload.opt_ts(data, "credential_expires_on", default=None)

    elector = lookup.elector(row_id)
    if elector["status"] != "PROVISIONAL":
        fail("ERR_INVALID_ELECTOR_STATE", "Only a PROVISIONAL elector may be credentialed.")

    if replacement is not None:
        elector["credential_expires_on"] = replacement
    if elector["credential_expires_on"] <= clock.now():
        fail("ERR_CREDENTIAL_EXPIRED", "The credential expiry is not later than the current instant.")

    bloc = lookup.voter_bloc(elector["bloc_id"])
    if bloc["seats_filled"] >= bloc["seat_cap"]:
        fail("ERR_BLOC_SEATS_EXHAUSTED", "Bloc '%s' has no free seat." % bloc["bloc_code"])

    elector["status"] = "CREDENTIALED"
    db.touch(elector)
    derive.recompute_bloc(bloc)
    derive.recompute_roster_counts_everywhere()
    return response.ok(serialize.elector(elector))


@bp.route("/electors/<row_id>/suspend", methods=["POST"])
def suspend_elector(row_id):
    """CREDENTIALED -> SUSPENDED.  Discipline holds the bloc seat."""
    auth.caller(ROLE_ADMIN)
    data = payload.body()
    reason = payload.req_str(data, "suspension_reason", allow_empty=False)

    elector = lookup.elector(row_id)
    if elector["status"] != "CREDENTIALED":
        fail("ERR_INVALID_ELECTOR_STATE", "Only a CREDENTIALED elector may be suspended.")

    elector["status"] = "SUSPENDED"
    elector["suspension_reason"] = reason
    db.touch(elector)
    derive.recompute_bloc(lookup.voter_bloc(elector["bloc_id"]))
    derive.recompute_roster_counts_everywhere()
    return response.ok(serialize.elector(elector))


@bp.route("/electors/<row_id>/reinstate", methods=["POST"])
def reinstate_elector(row_id):
    """SUSPENDED -> CREDENTIALED."""
    auth.caller(ROLE_ADMIN)
    data = payload.body()
    replacement = payload.opt_ts(data, "credential_expires_on", default=None)

    elector = lookup.elector(row_id)
    if elector["status"] != "SUSPENDED":
        fail("ERR_INVALID_ELECTOR_STATE", "Only a SUSPENDED elector may be reinstated.")

    if replacement is not None:
        elector["credential_expires_on"] = replacement
    if elector["credential_expires_on"] <= clock.now():
        fail("ERR_CREDENTIAL_EXPIRED", "The credential expiry is not later than the current instant.")

    elector["status"] = "CREDENTIALED"
    elector["suspension_reason"] = None
    db.touch(elector)
    derive.recompute_bloc(lookup.voter_bloc(elector["bloc_id"]))
    derive.recompute_roster_counts_everywhere()
    return response.ok(serialize.elector(elector))
