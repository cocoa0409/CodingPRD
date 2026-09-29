"""Clock, Election and Contest endpoints."""

from datetime import timedelta

from flask import Blueprint

from db import (
    clock_now,
    db,
    dt_of,
    insert,
    iso,
    now_iso,
    parse_date,
    set_fields,
    touch,
)
from errors import fail
from middleware import ROLE_ELECTIONS_DIRECTOR, SIX_ROLES, guard
from response import object_response
from routes.common import list_endpoint, lookup, single
from services import calc
from services.domain import (
    CONTEST_WINDOW_DAYS,
    TERMINAL_AUDIT_STATES,
    TERMINAL_RECOUNT_STATES,
    actions_of_discrepancy,
    audits_of_election,
    contests_of_election,
    discrepancies_of_tally,
    election_derived,
    project_audit_timeline,
    recompute_contest_margin,
    recompute_election,
    recompute_election_status,
    recounts_of_contest,
    tallies_of_audit,
)
from validate import (
    body,
    opt_bool,
    opt_dt,
    opt_str,
    req_date,
    req_dt,
    req_enum,
    req_int,
    req_list,
    req_str,
    req_vote_map,
)

bp = Blueprint("elections", __name__)

ELECTION_STATUSES = ("OPEN", "CANVASSED", "CERTIFIED")
TIMELINE_STATUSES = ("ON_TRACK", "AT_RISK", "BREACHED")
CONTEST_STATUSES = ("PENDING_CANVASS", "CANVASSED", "CERTIFIED")
CONTEST_TYPES = ("CANDIDATE", "MEASURE")


# ---------------------------------------------------------------------------
# logical clock
# ---------------------------------------------------------------------------


@bp.post("/_clock/set_current_utc")
@guard([ROLE_ELECTIONS_DIRECTOR])
def set_clock():
    data = body()
    current = req_dt(data, "current_utc")
    db.clock = current
    touched_elections = []
    for audit in list(db.audits.values()):
        if audit["status"] in TERMINAL_AUDIT_STATES:
            continue
        project_audit_timeline(audit)
        contest = db.contests.get(audit["contest_id"])
        if contest is not None:
            election = db.elections.get(contest["election_id"])
            if election is not None and election["id"] not in touched_elections:
                touched_elections.append(election["id"])
    for election_id in touched_elections:
        recompute_election(db.elections.get(election_id))
    return object_response({"current_utc": iso(current)})


# ---------------------------------------------------------------------------
# elections
# ---------------------------------------------------------------------------


@bp.post("/elections")
@guard([ROLE_ELECTIONS_DIRECTOR])
def create_election():
    data = body()
    jurisdiction_code = req_str(data, "jurisdiction_code", 1, 16)
    election_name = req_str(data, "election_name", 1, 120)
    election_date_raw, election_date = req_date(data, "election_date")
    deadline = req_dt(data, "certification_deadline_at")

    if deadline <= election_date:
        fail("ERR_INVALID_TIME_WINDOW",
             "certification_deadline_at must be after the election date.")

    row = insert(
        "elections",
        {
            "jurisdiction_code": jurisdiction_code,
            "election_name": election_name,
            "election_date": election_date_raw,
            "certification_deadline_at": iso(deadline),
            "effective_certification_deadline_at": None,
            "contest_window_ends_at": None,
            "status": "OPEN",
            "timeline_status": "ON_TRACK",
            "certification_risk_flag": False,
            "open_audit_count": 0,
            "open_recount_count": 0,
            "certified_at": None,
        },
    )
    set_fields(row, election_derived(row))
    return single(row, 201)


@bp.get("/elections")
@guard(SIX_ROLES)
def list_elections():
    return list_endpoint(
        "elections",
        {
            "jurisdiction_code": ("jurisdiction_code", None),
            "status": ("status", ELECTION_STATUSES),
        },
    )


@bp.get("/elections/<election_id>")
@guard(SIX_ROLES)
def get_election(election_id):
    return single(lookup("elections", election_id))


@bp.patch("/elections/<election_id>")
@guard([ROLE_ELECTIONS_DIRECTOR])
def patch_election(election_id):
    data = body()
    election_name = opt_str(data, "election_name", 1, 120)
    deadline = opt_dt(data, "certification_deadline_at")

    election = lookup("elections", election_id)
    if election["status"] == "CERTIFIED":
        fail("ERR_ELECTION_ALREADY_CERTIFIED")

    if deadline is not None:
        election_date = parse_date(election["election_date"])
        if deadline <= election_date:
            fail("ERR_INVALID_TIME_WINDOW",
                 "certification_deadline_at must be after the election date.")

    updates = {}
    if election_name is not None:
        updates["election_name"] = election_name
    deadline_changed = False
    if deadline is not None:
        new_deadline = iso(deadline)
        deadline_changed = new_deadline != election["certification_deadline_at"]
        updates["certification_deadline_at"] = new_deadline

    if set_fields(election, updates):
        touch(election)

    if deadline_changed:
        for audit in audits_of_election(election):
            if audit["status"] in TERMINAL_AUDIT_STATES:
                continue
            project_audit_timeline(audit)
    recompute_election(election)
    return single(election)


@bp.post("/elections/<election_id>/certify")
@guard([ROLE_ELECTIONS_DIRECTOR])
def certify_election(election_id):
    election = lookup("elections", election_id)

    if election["status"] != "CANVASSED":
        fail("ERR_INVALID_ELECTION_STATE")
    for contest in contests_of_election(election):
        if contest["status"] != "CANVASSED":
            fail("ERR_INVALID_CONTEST_STATE")

    audits = audits_of_election(election)
    for audit in audits:
        if audit["status"] not in TERMINAL_AUDIT_STATES:
            fail("ERR_AUDIT_NOT_TERMINAL")
    for contest in contests_of_election(election):
        for recount in recounts_of_contest(contest):
            if recount["status"] not in TERMINAL_RECOUNT_STATES:
                fail("ERR_RECOUNT_NOT_TERMINAL")

    effective = dt_of(election["effective_certification_deadline_at"])
    if effective is not None and clock_now() >= effective:
        fail("ERR_CERTIFICATION_DEADLINE_PASSED")

    discrepancies = []
    for audit in audits:
        for tally in tallies_of_audit(audit):
            discrepancies.extend(discrepancies_of_tally(tally))
    for row in discrepancies:
        if row["status"] in ("OPEN", "ESCALATED"):
            fail("ERR_UNRESOLVED_DISCREPANCY")
    for row in discrepancies:
        for action in actions_of_discrepancy(row):
            if action["category"] == "EQUIPMENT" and action["status"] not in (
                "VERIFIED",
                "CANCELLED",
            ):
                fail("ERR_EQUIPMENT_ACTION_UNVERIFIED")

    election["status"] = "CERTIFIED"
    election["certified_at"] = now_iso()
    election["certification_risk_flag"] = False
    if effective is not None:
        election["contest_window_ends_at"] = iso(
            effective + timedelta(days=CONTEST_WINDOW_DAYS)
        )
    touch(election)
    for contest in contests_of_election(election):
        if contest["status"] != "CERTIFIED":
            contest["status"] = "CERTIFIED"
            touch(contest)
    return single(election)


# ---------------------------------------------------------------------------
# contests
# ---------------------------------------------------------------------------


@bp.post("/contests")
@guard([ROLE_ELECTIONS_DIRECTOR])
def create_contest():
    data = body()
    election_id = req_str(data, "election_id", 1, None)
    contest_label = req_str(data, "contest_label", 1, 32)
    office_name = req_str(data, "office_name", 1, None)
    contest_type = req_enum(data, "contest_type", CONTEST_TYPES)
    candidate_names = req_list(data, "candidate_names", 2, 10)
    for name in candidate_names:
        if not isinstance(name, str) or len(name) == 0:
            fail("ERR_VALIDATION", "candidate_names must contain non-empty strings.")
    if len(set(candidate_names)) != len(candidate_names):
        fail("ERR_VALIDATION", "candidate_names must be unique.")
    ballots_cast = req_int(data, "ballots_cast", 1, None)
    cvr_available = opt_bool(data, "cvr_available", False)

    election = lookup("elections", election_id)
    if election["status"] == "CERTIFIED":
        fail("ERR_ELECTION_ALREADY_CERTIFIED")

    for contest in contests_of_election(election):
        if contest["contest_label"] == contest_label:
            fail("ERR_DUPLICATE_CONTEST_LABEL")

    row = insert(
        "contests",
        {
            "election_id": election_id,
            "contest_label": contest_label,
            "office_name": office_name,
            "contest_type": contest_type,
            "candidate_names": list(candidate_names),
            "ballots_cast": ballots_cast,
            "cvr_available": cvr_available,
            "reported_votes": None,
            "winner_name": None,
            "runner_up_name": None,
            "margin_votes": None,
            "margin_pct": None,
            "automatic_recount_required": False,
            "recount_request_deadline_at": None,
            "canvassed_at": None,
            "status": "PENDING_CANVASS",
            "open_recount_count": 0,
        },
    )
    return single(row, 201)


@bp.get("/contests")
@guard(SIX_ROLES)
def list_contests():
    return list_endpoint(
        "contests",
        {
            "election_id": ("election_id", None),
            "status": ("status", CONTEST_STATUSES),
            "contest_type": ("contest_type", CONTEST_TYPES),
        },
        sort_keys=("contest_label",),
    )


@bp.get("/contests/<contest_id>")
@guard(SIX_ROLES)
def get_contest(contest_id):
    return single(lookup("contests", contest_id))


@bp.post("/contests/<contest_id>/canvass-results")
@guard([ROLE_ELECTIONS_DIRECTOR])
def canvass_contest(contest_id):
    data = body()
    reported_votes = req_vote_map(data, "reported_votes")

    contest = lookup("contests", contest_id)
    if contest["status"] != "PENDING_CANVASS":
        fail("ERR_INVALID_CONTEST_STATE")
    election = db.elections.get(contest["election_id"])
    if election is not None and election["status"] != "OPEN":
        fail("ERR_INVALID_ELECTION_STATE")

    if set(reported_votes.keys()) != set(contest["candidate_names"]):
        fail("ERR_CANDIDATE_NAME_UNKNOWN")

    if sum(reported_votes.values()) > contest["ballots_cast"]:
        fail("ERR_BALLOT_ACCOUNTING_EXCEEDED")

    now = clock_now()
    contest["reported_votes"] = dict(reported_votes)
    recompute_contest_margin(contest)
    contest["canvassed_at"] = iso(now)
    contest["recount_request_deadline_at"] = iso(
        now + timedelta(days=calc.RECOUNT_REQUEST_WINDOW_DAYS)
    )
    contest["status"] = "CANVASSED"
    touch(contest)

    recompute_election_status(election)
    recompute_election(election)
    return single(contest)
