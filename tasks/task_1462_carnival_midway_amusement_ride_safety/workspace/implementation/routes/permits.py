"""Permits: read, list, approve, deny. Approval carries OCC on the fair version
and the segregation-of-duties rule against the conducting inspector."""
from flask import Blueprint

import db
from db import store, serialize, touch
from errors import (
    raise_err,
    ERR_PERMIT_INVALID_STATE,
    ERR_STALE_FAIR_VERSION,
    ERR_INSPECTION_REQUIRED,
    ERR_PERMIT_APPROVER_CONFLICT,
)
from helpers import get_or_404, paginate, qparam
from middleware import authenticate, scope_to_fair
from response import ok
from services.calculations import permit_fee, fair_wide_failure_count
from services.cascades import license_verified_rides
from validators import get_body, reject_unknown, req_int, req_str

bp = Blueprint("permits", __name__)

ALL = ["StateProgramAdmin", "StateInspector", "FairManager", "RideOperator", "TicketClerk", "CrewMember"]


def _latest_passed_fair_wide(fair_id, since_iso):
    """Latest FAIR_WIDE appointment COMPLETED_PASS with completed_at >= since_iso."""
    matches = [
        a
        for a in store["appointments"].values()
        if a["fair_id"] == fair_id
        and a["scope"] == "FAIR_WIDE"
        and a["status"] == "COMPLETED_PASS"
        and a["completed_at"] is not None
        and a["completed_at"] >= since_iso
    ]
    if not matches:
        return None
    matches.sort(key=lambda a: (a["completed_at"], a["_seq"]))
    return matches[-1]


@bp.get("/permits/<pid>")
def get_permit(pid):
    ctx = authenticate(ALL)
    permit = get_or_404("permits", pid)
    scope_to_fair(ctx, permit["fair_id"])
    return ok(serialize(permit))


@bp.get("/permits")
def list_permits():
    authenticate(ALL)
    return paginate(
        "permits",
        {
            "fair_id": qparam("fair_id"),
            "status": qparam("status"),
            "approved_by_inspector_id": qparam("approved_by_inspector_id"),
        },
    )


@bp.post("/permits/<pid>/approve")
def approve_permit(pid):
    ctx = authenticate(["StateInspector"])
    permit = get_or_404("permits", pid)
    body = get_body()
    reject_unknown(body, {"expected_fair_version"})
    expected = req_int(body, "expected_fair_version")
    if permit["status"] != "PENDING":
        raise_err(ERR_PERMIT_INVALID_STATE, "Only a PENDING permit can be approved")
    fair = db.get("fairs", permit["fair_id"])
    if expected != fair["version"]:
        raise_err(ERR_STALE_FAIR_VERSION, "expected_fair_version does not match the fair's current version")
    latest_pass = _latest_passed_fair_wide(fair["id"], permit["created_at"])
    if latest_pass is None:
        raise_err(ERR_INSPECTION_REQUIRED, "No passed fair-wide inspection on or after the permit was opened")
    if ctx["user_id"] == latest_pass["inspector_id"]:
        raise_err(ERR_PERMIT_APPROVER_CONFLICT, "The approver cannot be the inspector who conducted the latest passed fair-wide inspection")

    failures = fair_wide_failure_count(fair["id"])
    final_fee, billable = permit_fee(fair["id"], failures)
    permit["final_fee_cents"] = final_fee
    permit["billable_ride_count"] = billable
    permit["reinspection_failure_count"] = failures
    permit["approved_by_inspector_id"] = ctx["user_id"]
    permit["decided_at"] = db.now_iso()
    permit["status"] = "APPROVED"
    touch(permit)

    fair["status"] = "PERMITTED"
    touch(fair)
    license_verified_rides(fair["id"])
    return ok(serialize(permit))


@bp.post("/permits/<pid>/deny")
def deny_permit(pid):
    ctx = authenticate(["StateInspector"])
    permit = get_or_404("permits", pid)
    body = get_body()
    reject_unknown(body, {"reason"})
    reason = req_str(body, "reason")
    if permit["status"] != "PENDING":
        raise_err(ERR_PERMIT_INVALID_STATE, "Only a PENDING permit can be denied")
    fair = db.get("fairs", permit["fair_id"])
    latest_pass = _latest_passed_fair_wide(fair["id"], permit["created_at"])
    if latest_pass is not None and ctx["user_id"] == latest_pass["inspector_id"]:
        raise_err(ERR_PERMIT_APPROVER_CONFLICT, "The denier cannot be the inspector who conducted the latest passed fair-wide inspection")

    permit["denial_reason"] = reason
    permit["decided_at"] = db.now_iso()
    permit["status"] = "DENIED"
    touch(permit)

    fair["status"] = "SETUP"
    touch(fair)
    return ok(serialize(permit))
