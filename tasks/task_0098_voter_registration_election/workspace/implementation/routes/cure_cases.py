"""CureCase endpoints (PRD §3.4)."""

from flask import Blueprint, g, request

import db
from errors import (
    APIError, invalid_request, not_found, invalid_state, segregation,
)
import errors as E
from middleware import require_roles
from response import ok_object, ok_array
from services import serialize
from services.common import (
    get_json_body, require_fields, paginate, parse_iso, clock_now,
)

bp = Blueprint("cure_cases", __name__)

DECISIONS = {"SUBMIT_RESPONSE", "APPROVE", "DENY"}


@bp.route("/cure-cases/<cid>", methods=["GET"])
def get_cure_case(cid):
    require_roles("ElectionAdmin", "ElectionOfficial", "Voter")
    c = db.cure_cases.get(cid)
    if c is None:
        raise not_found("Cure case not found.")
    return ok_object(serialize.cure_case_view(c))


@bp.route("/cure-cases", methods=["GET"])
def list_cure_cases():
    require_roles("ElectionAdmin", "ElectionOfficial")
    ballot_id = request.args.get("ballot_id")
    election_id = request.args.get("election_id")
    status = request.args.get("status")
    rows = list(db.cure_cases.values())
    if ballot_id is not None:
        rows = [r for r in rows if r["ballot_id"] == ballot_id]
    if election_id is not None:
        rows = [r for r in rows if r.get("election_id") == election_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, limit, offset, total, has_more = paginate(rows)
    return ok_array([serialize.cure_case_view(r) for r in page],
                    limit=limit, offset=offset, total_count=total, has_more=has_more)


def _reviewer_of(case):
    """X-User-ID that reviewed the ballot's underlying registration, if any."""
    ballot = db.ballots.get(case["ballot_id"])
    if ballot is None:
        return None
    reg = db.registrations.get(ballot["registration_id"])
    if reg is None:
        return None
    return reg.get("reviewed_by_user_id")


@bp.route("/cure-cases/<cid>/transition", methods=["POST"])
def transition_cure_case(cid):
    require_roles("Voter", "ElectionOfficial")
    c = db.cure_cases.get(cid)
    if c is None:
        raise not_found("Cure case not found.")
    body = get_json_body()
    require_fields(body, "decision")
    decision = body["decision"]
    if decision not in DECISIONS:
        raise invalid_request("Unknown decision.")

    election = db.elections.get(c.get("election_id"))
    ballot = db.ballots.get(c["ballot_id"])

    if decision == "SUBMIT_RESPONSE":
        # State (priority 4).
        if c["status"] != "OPEN":
            raise invalid_state("Cure case is not OPEN.")
        # Cure deadline (priority 7): strict < deadline.
        if election is not None and clock_now() >= parse_iso(election["cure_deadline"]):
            raise APIError(E.ERR_CURE_DEADLINE_PASSED,
                           "Cure deadline has passed.", 422)
        c["voter_response_text"] = body.get("voter_response_text")
        c["status"] = "RESPONSE_SUBMITTED"
        db.stamp_update(c)
        if ballot is not None and ballot["cure_status"] == "FLAGGED":
            ballot["cure_status"] = "CURE_PENDING"
            db.stamp_update(ballot)
        return ok_object(serialize.cure_case_view(c))

    if decision == "APPROVE":
        # SUBMIT_RESPONSE is the only role allowed to Voter; APPROVE/DENY are
        # ElectionOfficial-only (RBAC priority 2).
        if g.user_role != "ElectionOfficial":
            from errors import unauthorized
            raise unauthorized("Only an ElectionOfficial may adjudicate a cure.")
        if c["status"] != "RESPONSE_SUBMITTED":
            raise invalid_state("Cure case is not RESPONSE_SUBMITTED.")
        # Segregation of duties (priority 5) checked before time window (priority 7).
        if g.user_id == _reviewer_of(c):
            raise segregation(
                "Registration reviewer may not adjudicate this voter's cure.")
        if election is not None and clock_now() >= parse_iso(election["cure_deadline"]):
            raise APIError(E.ERR_CURE_DEADLINE_PASSED,
                           "Cure deadline has passed.", 422)
        c["adjudicated_by_user_id"] = g.user_id
        c["status"] = "APPROVED"
        db.stamp_update(c)
        if ballot is not None and ballot["cure_status"] == "CURE_PENDING":
            ballot["cure_status"] = "CURED"
            db.stamp_update(ballot)
        return ok_object(serialize.cure_case_view(c))

    if decision == "DENY":
        if g.user_role != "ElectionOfficial":
            from errors import unauthorized
            raise unauthorized("Only an ElectionOfficial may adjudicate a cure.")
        if c["status"] != "RESPONSE_SUBMITTED":
            raise invalid_state("Cure case is not RESPONSE_SUBMITTED.")
        if g.user_id == _reviewer_of(c):
            raise segregation(
                "Registration reviewer may not adjudicate this voter's cure.")
        c["adjudicated_by_user_id"] = g.user_id
        c["status"] = "DENIED"
        db.stamp_update(c)
        # Depth-3 cascade: CURE_PENDING -> CURE_FAILED -> request REJECTED.
        if ballot is not None and ballot["cure_status"] == "CURE_PENDING":
            ballot["cure_status"] = "CURE_FAILED"
            ballot["request_status"] = "REJECTED"
            db.stamp_update(ballot)
        return ok_object(serialize.cure_case_view(c))

    raise invalid_request("Unsupported decision.")
