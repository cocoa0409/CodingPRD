"""RiskAcceptance lifecycle (PRD §3.6): REQUESTED -> APPROVED / REJECTED,
with requester/decider segregation of duties, the expected_cycle_version OCC
guard, and the expiry check at decision time.
"""
from flask import Blueprint, g

import db
import errors
import helpers
import util
from errors import ApiError
from middleware import body, require_roles
from response import ok
from serializers import serialize

bp = Blueprint("acceptances", __name__,
               url_prefix="/vsa/vendors/<vid>/cycles/<cid>/risk-acceptances")


def _resolve(vid, cid):
    vendor = helpers.get_vendor(vid)
    cycle = helpers.get_cycle_for_vendor(vendor, cid)
    return vendor, cycle


def _get_acceptance(cycle, rid):
    return helpers.get_child(db.acceptances, "cycle_id", cycle, rid,
                             "RiskAcceptance")


@bp.post("")
@require_roles("RiskAnalyst")
def create_acceptance(vid, cid):
    vendor, cycle = _resolve(vid, cid)
    data = body()
    exception_ids = data.get("exception_ids")
    justification = data.get("justification")
    controls = data.get("compensating_controls")
    expires_at = data.get("expires_at")
    if not isinstance(exception_ids, list) or not exception_ids:
        raise ApiError(errors.ERR_INVALID_REQUEST, 422,
                       "exception_ids must be a non-empty list")
    if not isinstance(justification, str) or not justification:
        raise ApiError(errors.ERR_INVALID_REQUEST, 422, "justification is required")
    if not isinstance(controls, list):
        raise ApiError(errors.ERR_INVALID_REQUEST, 422,
                       "compensating_controls must be a list")
    if not util.is_dt(expires_at):
        raise ApiError(errors.ERR_INVALID_REQUEST, 422,
                       "expires_at must be an ISO 8601 datetime")
    # Deadline (priority 7): the acceptance must expire in the future.
    if not util.parse_dt(expires_at) > util.now():
        raise ApiError(errors.ERR_DEADLINE_PASSED, 422,
                       "expires_at must lie in the future")
    # Referential integrity (priority 10).
    for eid in exception_ids:
        exc = db.exceptions.get(eid)
        if (exc is None or exc["cycle_id"] != cid
                or exc["status"] not in ("OPEN", "IN_REMEDIATION")):
            raise ApiError(errors.ERR_REFERENTIAL_INTEGRITY, 422,
                           "Every referenced exception must belong to the "
                           "cycle and be OPEN or IN_REMEDIATION")
    acceptance = {
        "cycle_id": cid,
        "exception_ids": list(exception_ids),
        "justification": justification,
        "compensating_controls": controls,
        "expires_at": util.iso(util.parse_dt(expires_at)),
        "status": "REQUESTED",
        "decided_by": None,
        "_requested_by": g.user_id,
        "_vendor_id": vid,
    }
    helpers.stamp_new("acceptances", acceptance)
    db.acceptances[acceptance["id"]] = acceptance
    return ok(serialize("acceptance", acceptance), 201)


def _check_not_expired(acceptance):
    """Priority 19: a decision on an acceptance whose expires_at has passed
    (sweep not yet fired) is rejected."""
    try:
        expires = util.parse_dt(acceptance["expires_at"])
    except (ValueError, TypeError):
        return
    if util.now() > expires:
        raise ApiError(errors.ERR_ACCEPTANCE_EXPIRED, 422,
                       "Risk acceptance expires_at has passed")


@bp.post("/<rid>/approve")
@require_roles("SecurityApprover")
def approve_acceptance(vid, cid, rid):
    vendor, cycle = _resolve(vid, cid)
    acceptance = _get_acceptance(cycle, rid)
    if acceptance["status"] != "REQUESTED":
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "Only a REQUESTED acceptance can be approved")
    # Segregation of duties (priority 5): approver != requester.
    if g.user_id == acceptance.get("_requested_by"):
        raise ApiError(errors.ERR_SEGREGATION_OF_DUTIES, 422,
                       "Acceptance approver must differ from its requester")
    data = body()
    # OCC (priority 6): expected_cycle_version is a non-optional guard.
    if "expected_cycle_version" in data and data["expected_cycle_version"] is not None:
        expected = data["expected_cycle_version"]
        if not isinstance(expected, int) or isinstance(expected, bool):
            raise ApiError(errors.ERR_INVALID_REQUEST, 422,
                           "expected_cycle_version must be an integer")
        if expected != cycle["version"]:
            raise ApiError(errors.ERR_STALE_CYCLE_VERSION, 412,
                           "Cycle version has advanced beyond expected_cycle_version")
    else:
        raise ApiError(errors.ERR_INVALID_REQUEST, 422,
                       "expected_cycle_version is required")
    # Referential integrity (priority 10): exceptions still dischargable.
    for eid in acceptance["exception_ids"]:
        exc = db.exceptions.get(eid)
        if (exc is None or exc["cycle_id"] != cid
                or exc["status"] not in ("OPEN", "IN_REMEDIATION")):
            raise ApiError(errors.ERR_REFERENTIAL_INTEGRITY, 422,
                           "Every referenced exception must still be OPEN "
                           "or IN_REMEDIATION")
    _check_not_expired(acceptance)
    acceptance["status"] = "APPROVED"
    acceptance["decided_by"] = g.user_id
    closed = 0
    for eid in acceptance["exception_ids"]:
        exc = db.exceptions[eid]
        exc["status"] = "CLOSED_ACCEPTED"
        helpers.touch("exceptions", exc)
        closed += 1
    cycle["open_exception_count"] -= closed
    cycle["acceptance_required"] = True
    helpers.touch("acceptances", acceptance)
    helpers.touch("cycles", cycle)
    return ok(serialize("acceptance", acceptance))


@bp.post("/<rid>/reject")
@require_roles("SecurityApprover")
def reject_acceptance(vid, cid, rid):
    vendor, cycle = _resolve(vid, cid)
    acceptance = _get_acceptance(cycle, rid)
    if acceptance["status"] != "REQUESTED":
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "Only a REQUESTED acceptance can be rejected")
    if g.user_id == acceptance.get("_requested_by"):
        raise ApiError(errors.ERR_SEGREGATION_OF_DUTIES, 422,
                       "Acceptance rejecter must differ from its requester")
    _check_not_expired(acceptance)
    acceptance["status"] = "REJECTED"
    acceptance["decided_by"] = g.user_id
    helpers.touch("acceptances", acceptance)
    return ok(serialize("acceptance", acceptance))
