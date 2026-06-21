"""Election endpoints + simulated-clock endpoint (PRD §3.1, §3.5, §2.4)."""

from flask import Blueprint, g, request

import db
from errors import (
    APIError, invalid_request, not_found, invalid_state,
    APIError as _AE,
)
import errors as E
from middleware import require_roles
from response import ok_object, ok_array
from services import serialize
from services.common import (
    get_json_body, require_fields, paginate, parse_iso, clock_now,
    recompute_election_counts,
)

bp = Blueprint("elections", __name__)

VALID_STATUSES = {"SCHEDULED", "REGISTRATION_OPEN", "VOTING_OPEN",
                  "POLLS_CLOSED", "CERTIFIED"}


def _validate_dt(body, field):
    require_fields(body, field)
    try:
        parse_iso(body[field])
    except (ValueError, TypeError):
        raise invalid_request(f"{field} must be a valid ISO 8601 timestamp.")
    return body[field]


@bp.route("/elections", methods=["POST"])
def create_election():
    require_roles("ElectionAdmin")
    body = get_json_body()
    require_fields(body, "name", "election_date", "registration_deadline",
                   "absentee_request_deadline", "cure_deadline",
                   "early_voting_start", "early_voting_end")
    if not isinstance(body["name"], str) or not body["name"].strip():
        raise invalid_request("name must be a non-empty string.")
    for f in ("election_date", "registration_deadline", "absentee_request_deadline",
              "cure_deadline", "early_voting_start", "early_voting_end"):
        _validate_dt(body, f)

    row = {
        "name": body["name"],
        "election_date": body["election_date"],
        "registration_deadline": body["registration_deadline"],
        "absentee_request_deadline": body["absentee_request_deadline"],
        "cure_deadline": body["cure_deadline"],
        "early_voting_start": body["early_voting_start"],
        "early_voting_end": body["early_voting_end"],
        "status": "SCHEDULED",
        "total_registered": 0,
        "total_ballots_accepted": 0,
    }
    db.stamp_create_full(row)
    db.elections[row["id"]] = row
    return ok_object(serialize.election_view(row), 201)


@bp.route("/elections/<eid>", methods=["GET"])
def get_election(eid):
    require_roles("ElectionAdmin", "ElectionOfficial", "Canvasser", "PollWorker")
    e = db.elections.get(eid)
    if e is None:
        raise not_found("Election not found.")
    return ok_object(serialize.election_view(e))


@bp.route("/elections", methods=["GET"])
def list_elections():
    require_roles("ElectionAdmin", "ElectionOfficial", "Canvasser", "PollWorker")
    status = request.args.get("status")
    rows = list(db.elections.values())
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, limit, offset, total, has_more = paginate(rows)
    return ok_array([serialize.election_view(r) for r in page],
                    limit=limit, offset=offset, total_count=total, has_more=has_more)


def _cure_sweep(election):
    """POLLS_CLOSED side effect: expire past-deadline cure cases and cascade."""
    now = clock_now()
    deadline = parse_iso(election["cure_deadline"])
    eid = election["id"]
    for c in db.cure_cases.values():
        if c.get("election_id") != eid:
            continue
        if c["status"] not in ("OPEN", "RESPONSE_SUBMITTED"):
            continue
        if now < deadline:
            continue
        # Expire this cure case (depth-3 cascade).
        c["status"] = "EXPIRED"
        db.stamp_update(c)
        ballot = db.ballots.get(c["ballot_id"])
        if ballot is not None:
            ballot["cure_status"] = "CURE_FAILED"
            ballot["request_status"] = "REJECTED"
            db.stamp_update(ballot)


@bp.route("/elections/<eid>/transition", methods=["POST"])
def transition_election(eid):
    require_roles("ElectionAdmin")
    e = db.elections.get(eid)
    if e is None:
        raise not_found("Election not found.")
    body = get_json_body()
    require_fields(body, "target_status")
    target = body["target_status"]
    if target not in VALID_STATUSES:
        raise invalid_request("Unknown target_status.")

    cur = e["status"]
    now = clock_now()

    if target == "REGISTRATION_OPEN":
        if cur != "SCHEDULED":
            raise invalid_state("Election is not SCHEDULED.")
    elif target == "VOTING_OPEN":
        if cur != "REGISTRATION_OPEN":
            raise invalid_state("Election is not REGISTRATION_OPEN.")
        if now < parse_iso(e["early_voting_start"]):
            raise APIError(E.ERR_VOTING_NOT_OPEN,
                           "Cannot open voting before early_voting_start.", 422)
    elif target == "POLLS_CLOSED":
        if cur != "VOTING_OPEN":
            raise invalid_state("Election is not VOTING_OPEN.")
        if now < parse_iso(e["election_date"]):
            raise APIError(E.ERR_VOTING_NOT_OPEN,
                           "Cannot close polls before election_date.", 422)
    elif target == "CERTIFIED":
        if cur != "POLLS_CLOSED":
            raise invalid_state("Election is not POLLS_CLOSED.")
        precincts = [p for p in db.precincts.values() if p["election_id"] == eid]
        if any(p["tally_status"] != "TALLIED" for p in precincts):
            raise APIError(E.ERR_PRECINCTS_NOT_TALLIED,
                           "Every precinct must be TALLIED before certification.", 409)
        if any(rc["election_id"] == eid and rc["status"] in
               ("REQUESTED", "MACHINE_DONE", "HAND_DONE", "BOTH_DONE")
               for rc in db.recount_cases.values()):
            raise APIError(E.ERR_RECOUNT_IN_PROGRESS,
                           "A recount is still in progress.", 409)
    else:
        raise invalid_request("Unsupported target_status for election.")

    # Apply
    if target == "POLLS_CLOSED":
        _cure_sweep(e)
    e["status"] = target
    db.stamp_update(e)
    return ok_object(serialize.election_view(e))


@bp.route("/_clock/set", methods=["POST"])
def set_clock():
    require_roles("ElectionAdmin")
    body = get_json_body()
    require_fields(body, "current_utc")
    try:
        parse_iso(body["current_utc"])
    except (ValueError, TypeError):
        raise invalid_request("current_utc must be a valid ISO 8601 timestamp.")
    db.set_clock(body["current_utc"])
    return ok_object(serialize.clock_view())
