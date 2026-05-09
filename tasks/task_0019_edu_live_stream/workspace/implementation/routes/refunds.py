"""RefundRequest endpoints."""
import datetime

from flask import Blueprint, request

from db import bump, iso_now_ms, make_common_fields, store
from errors import raise_api
from middleware import require_roles
from response import list_success, success
from services import audit
from services.lookup import get_enrollment, get_refund_request
from services.pagination import paginate, parse_pagination
from services.refund import compute_final, compute_provisional

refunds_bp = Blueprint("refunds", __name__)


def _iso_to_unix(s: str) -> int:
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return int(datetime.datetime.fromisoformat(s).timestamp())


@refunds_bp.route("/enrollments/<enrollment_id>/refund-requests", methods=["POST"])
def create_refund_request(enrollment_id):
    user_id, _ = require_roles("Student")
    enr = get_enrollment(enrollment_id)
    if enr["student_id"] != user_id:
        raise_api("ERR_FORBIDDEN_NOT_OWNER", "Not the enrollment owner")
    if enr["payment_status"] != "PAID":
        raise_api("ERR_REFUND_ALREADY_REQUESTED", "Enrollment not in PAID state")
    # idempotency: at most one non-terminal RefundRequest
    for r in store.refund_requests.values():
        if r["enrollment_id"] == enrollment_id and r["status"] == "PENDING":
            raise_api("ERR_REFUND_ALREADY_REQUESTED", "Pending refund already exists")

    body = request.get_json(silent=True) or {}
    kits = body.get("materials_kit_count", 0)
    try:
        kits = int(kits)
    except (TypeError, ValueError):
        raise_api("ERR_INVALID_PRICING", "materials_kit_count must be integer")
    if kits < 0:
        raise_api("ERR_INVALID_PRICING", "materials_kit_count must be >= 0")

    requested_at = iso_now_ms()
    requested_unix = _iso_to_unix(requested_at)
    amount, prog = compute_provisional(enr, requested_unix, kits)

    r = {
        **make_common_fields(),
        "enrollment_id": enrollment_id,
        "course_id": enr["course_id"],
        "requested_at": requested_at,
        "status": "PENDING",
        "provisional_amount_cents": amount,
        "provisional_progress_percent": prog,
        "final_amount_cents": None,
        "materials_kit_count": kits,
        "rejection_reason": None,
    }
    store.refund_requests[r["id"]] = r
    enr["payment_status"] = "REFUND_PENDING"
    bump(enr)
    audit.append(
        actor_role="Student",
        actor_id=user_id,
        action="REFUND_REQUESTED",
        subject_type="REFUND_REQUEST",
        subject_id=r["id"],
        detail={
            "enrollment_id": enrollment_id,
            "provisional_amount_cents": amount,
            "provisional_progress_percent": prog,
        },
    )
    return success(dict(r), http_status=201)


@refunds_bp.route("/refund-requests/<rr_id>/approve", methods=["POST"])
def approve_refund(rr_id):
    user_id, _ = require_roles("AcademicAdmin")
    r = get_refund_request(rr_id)
    if r["status"] != "PENDING":
        raise_api("ERR_REFUND_NOT_PENDING", "RefundRequest must be PENDING")
    enr = get_enrollment(r["enrollment_id"])
    course = store.courses.get(r["course_id"])
    if course and course.get("posture") == "FROZEN":
        raise_api("ERR_COURSE_FROZEN", "Course is frozen")

    approval_iso = iso_now_ms()
    approval_unix = _iso_to_unix(approval_iso)
    kits = int(r.get("materials_kit_count", 0))
    final_amount = compute_final(enr, approval_unix, approval_iso, kits)

    r["status"] = "APPROVED"
    r["final_amount_cents"] = final_amount
    bump(r)

    enr["payment_status"] = "REFUNDED"
    enr["learning_status"] = "WITHDRAWN"
    enr["refund_amount_cents"] = final_amount
    bump(enr)

    audit.append(
        actor_role="AcademicAdmin",
        actor_id=user_id,
        action="REFUND_APPROVED",
        subject_type="REFUND_REQUEST",
        subject_id=r["id"],
        detail={
            "enrollment_id": enr["id"],
            "final_amount_cents": final_amount,
        },
    )
    return success(dict(r))


@refunds_bp.route("/refund-requests/<rr_id>/reject", methods=["POST"])
def reject_refund(rr_id):
    user_id, _ = require_roles("AcademicAdmin")
    r = get_refund_request(rr_id)
    if r["status"] != "PENDING":
        raise_api("ERR_REFUND_NOT_PENDING", "RefundRequest must be PENDING")
    body = request.get_json(silent=True) or {}
    reason = body.get("rejection_reason")
    if not reason or not isinstance(reason, str):
        raise_api("ERR_REFUND_REJECTION_REASON_REQUIRED", "rejection_reason required")
    enr = get_enrollment(r["enrollment_id"])
    r["status"] = "REJECTED"
    r["rejection_reason"] = reason
    bump(r)
    enr["payment_status"] = "PAID"
    bump(enr)
    audit.append(
        actor_role="AcademicAdmin",
        actor_id=user_id,
        action="REFUND_REJECTED",
        subject_type="REFUND_REQUEST",
        subject_id=r["id"],
        detail={"enrollment_id": enr["id"], "reason": reason},
    )
    return success(dict(r))


@refunds_bp.route("/refund-requests", methods=["GET"])
def list_refund_requests():
    require_roles("AcademicAdmin")
    limit, offset = parse_pagination()
    items = list(store.refund_requests.values())
    status = request.args.get("status")
    if status:
        items = [r for r in items if r["status"] == status]
    enrollment_id = request.args.get("enrollment_id")
    if enrollment_id:
        items = [r for r in items if r["enrollment_id"] == enrollment_id]
    items.sort(key=lambda r: r["created_at"])
    page, total = paginate(items, limit, offset)
    return list_success([dict(r) for r in page], limit, offset, total)
