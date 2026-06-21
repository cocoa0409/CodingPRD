"""RefundRequest approval/rejection + refund computation (PRD §3.5, §3.6)."""
from datetime import timedelta

from flask import Blueprint, request

import errors
from db import db, touch
from middleware import require_role
from response import success
from services import serialize
from services.calc import refund_amounts
from services.common import parse_pagination, sort_by_created, paginate, lookup
from services.derive import enrollment_attendance
from services.timeutil import parse_dt

bp = Blueprint("refunds", __name__)


@bp.get("/refund-requests/<rid>")
def get_refund(rid):
    require_role("ComplianceOfficer", "AdmissionsOfficer", "Student")
    r = lookup(db.refund_requests, rid)
    return success(serialize.refund_view(r))


@bp.get("/refund-requests")
def list_refunds():
    require_role("ComplianceOfficer", "AdmissionsOfficer")
    limit, offset = parse_pagination()
    enrollment_id = request.args.get("enrollment_id")
    status = request.args.get("status")
    rows = list(db.refund_requests.values())
    if enrollment_id is not None:
        rows = [r for r in rows if r["enrollment_id"] == enrollment_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows = sort_by_created(rows)
    window, pg = paginate(rows, limit, offset)
    return success([serialize.refund_view(r) for r in window], pagination=pg)


def _linked_deposit(enrollment_id):
    return next((d for d in db.deposits.values()
                 if d["enrollment_id"] == enrollment_id), None)


@bp.post("/refund-requests/<rid>/approve")
def approve_refund(rid):
    require_role("ComplianceOfficer")
    r = lookup(db.refund_requests, rid)
    if r["status"] != "PENDING":
        raise errors.invalid_state(f"Refund is {r['status']}, expected PENDING")
    enrollment = db.enrollments.get(r["enrollment_id"])

    # business checks in order: cooling-off timing, then deposit state (PRD §3.5)
    if r["reason"] == "COOLING_OFF":
        requested_at = parse_dt(r["requested_at"], "requested_at")
        enrolled_at = parse_dt(enrollment["enrolled_at"], "enrolled_at")
        if (requested_at - enrolled_at) > timedelta(days=14):
            raise errors.ApiError(errors.ERR_COOLING_OFF_EXPIRED, 409,
                                  "Cooling-off window (14 days) has expired")

    dep = _linked_deposit(r["enrollment_id"])
    if dep is None or dep["status"] != "HELD":
        raise errors.ApiError(errors.ERR_DEPOSIT_ALREADY_RESOLVED, 409,
                              "Deposit is not HELD")

    cohort = db.cohorts.get(enrollment["cohort_id"]) if enrollment else None
    _, progress = enrollment_attendance(enrollment["id"]) if enrollment else (0, 0)
    tuition_sticker = cohort["tuition_sticker_cents"] if cohort else 0

    gross, net = refund_amounts(r["reason"], dep["amount_cents"], tuition_sticker, progress)
    r["gross_refund_cents"] = gross
    r["net_refund_cents"] = net
    r["status"] = "APPROVED"
    touch(r)

    dep["status"] = "REFUNDED"
    dep["refunded_amount_cents"] = net
    touch(dep)
    return success(serialize.refund_view(r))


@bp.post("/refund-requests/<rid>/reject")
def reject_refund(rid):
    require_role("ComplianceOfficer")
    r = lookup(db.refund_requests, rid)
    if r["status"] != "PENDING":
        raise errors.invalid_state(f"Refund is {r['status']}, expected PENDING")
    r["status"] = "REJECTED"
    touch(r)
    dep = _linked_deposit(r["enrollment_id"])
    if dep is not None and dep["status"] == "HELD":
        dep["status"] = "FORFEITED"
        dep["refunded_amount_cents"] = 0
        touch(dep)
    return success(serialize.refund_view(r))
