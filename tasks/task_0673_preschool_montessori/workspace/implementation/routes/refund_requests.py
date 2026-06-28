"""RefundRequest endpoints + lifecycle (PRD §3.8, §3.9)."""
from flask import Blueprint

import errors
from db import db, new_common_fields, touch
from middleware import get_auth, require_role
from response import object_response, array_response
from services import calc
from services.common import (
    get_json_body, require_fields, require_enum, parse_pagination,
    sort_created_asc, paginate, serialize, serialize_list, str_arg, optional_enum,
)

bp = Blueprint("refund_requests", __name__)

METHODS = {"FORWARD", "CHRONOLOGICAL"}
REFUND_STATUSES = {"COMPUTED", "APPROVED", "PAID", "VOID"}
RW_ROLES = {"Registrar", "Parent"}


def _get_rr_or_404(rr_id):
    rr = db.refund_requests.get(rr_id)
    if rr is None:
        raise errors.not_found("Refund request not found.")
    return rr


@bp.route("/refund-requests", methods=["POST"])
def create_refund_request():
    _, role = get_auth()
    require_role(role, {"Registrar"})
    body = get_json_body()
    require_fields(body, ["enrollment_id", "effective_date", "method"])

    enrollment_id = body["enrollment_id"]
    if not isinstance(enrollment_id, str):
        raise errors.invalid_request("enrollment_id must be a string.")
    effective_date = body["effective_date"]
    if not isinstance(effective_date, str):
        raise errors.invalid_request("effective_date must be an ISO 8601 string.")
    from db import parse_iso
    try:
        parse_iso(effective_date)
    except (ValueError, TypeError):
        raise errors.invalid_request("effective_date must be a valid ISO 8601 instant.")
    method = require_enum(body, "method", METHODS)

    enr = db.enrollments.get(enrollment_id)
    if enr is None:
        raise errors.not_found("enrollment_id does not exist.")

    # Eligibility (priority 15): enrollment WITHDRAWN; only one non-VOID per enrollment.
    if enr["placement_status"] != "WITHDRAWN":
        raise errors.refund_not_eligible()
    for rr in db.refund_requests.values():
        if rr["enrollment_id"] == enrollment_id and rr["status"] != "VOID":
            raise errors.refund_not_eligible()

    earned, refund_cents, balance_due = calc.compute_refund(enr, effective_date, method)

    rr = new_common_fields()
    rr.update({
        "enrollment_id": enrollment_id,
        "effective_date": effective_date,
        "method": method,
        "status": "COMPUTED",
        "earned_cents": earned,
        "refund_cents": refund_cents,
        "balance_due_cents": balance_due,
    })
    db.refund_requests[rr["id"]] = rr
    return object_response(serialize(rr), 201)


@bp.route("/refund-requests/<rr_id>", methods=["GET"])
def get_refund_request(rr_id):
    _, role = get_auth()
    require_role(role, RW_ROLES)
    return object_response(serialize(_get_rr_or_404(rr_id)), 200)


@bp.route("/refund-requests", methods=["GET"])
def list_refund_requests():
    _, role = get_auth()
    require_role(role, RW_ROLES)
    limit, offset = parse_pagination()
    enrollment_id = str_arg("enrollment_id")
    status = optional_enum(str_arg("status"), REFUND_STATUSES, "status")

    records = list(db.refund_requests.values())
    if enrollment_id is not None:
        records = [r for r in records if r["enrollment_id"] == enrollment_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    records = sort_created_asc(records)
    page, total = paginate(records, limit, offset)
    return array_response(serialize_list(page), limit, offset, total)


@bp.route("/refund-requests/<rr_id>/approve", methods=["POST"])
def approve(rr_id):
    _, role = get_auth()
    require_role(role, {"Registrar"})
    rr = _get_rr_or_404(rr_id)
    if rr["status"] != "COMPUTED":
        raise errors.invalid_state()
    enr = db.enrollments.get(rr["enrollment_id"])
    if enr is None or enr["placement_status"] != "WITHDRAWN":
        raise errors.invalid_state()
    rr["status"] = "APPROVED"
    touch(rr)
    return object_response(serialize(rr), 200)


@bp.route("/refund-requests/<rr_id>/pay", methods=["POST"])
def pay(rr_id):
    _, role = get_auth()
    require_role(role, {"Registrar"})
    rr = _get_rr_or_404(rr_id)
    if rr["status"] != "APPROVED":
        raise errors.invalid_state()

    enr = db.enrollments.get(rr["enrollment_id"])

    # Compensation: mark CAPTURED payments REFUNDED in creation order
    # (created_at ASC, ties by created_at then deposit-before-installment),
    # accumulating whole payments without exceeding refund_cents.
    captured = [
        p for p in db.payments.values()
        if p["enrollment_id"] == rr["enrollment_id"] and p["status"] == "CAPTURED"
    ]

    def order_key(p):
        kind_rank = 0 if p["kind"] == "DEPOSIT" else 1
        return (p["created_at"], kind_rank, p.get("_seq", 0))

    captured.sort(key=order_key)

    prior_paid_to_date = enr["paid_to_date_cents"]
    remaining = rr["refund_cents"]
    for p in captured:
        if remaining <= 0:
            break
        p["status"] = "REFUNDED"
        touch(p)
        remaining -= p["amount_cents"]

    # PRD §3.9: recompute paid_to_date so that the relationship between
    # paid_to_date_cents and refund_cents is preserved — the new paid-to-date
    # equals the prior paid-to-date less the refunded amount (refund_cents).
    enr["paid_to_date_cents"] = prior_paid_to_date - rr["refund_cents"]
    # Settle billing (defined transition: WITHDRAWN + {ACTIVE,PAST_DUE} -> SETTLED).
    enr["billing_status"] = "SETTLED"
    touch(enr)

    rr["status"] = "PAID"
    touch(rr)
    return object_response(serialize(rr), 200)


@bp.route("/refund-requests/<rr_id>/void", methods=["POST"])
def void(rr_id):
    _, role = get_auth()
    require_role(role, {"Registrar"})
    rr = _get_rr_or_404(rr_id)
    if rr["status"] != "COMPUTED":
        raise errors.invalid_state()
    rr["status"] = "VOID"
    touch(rr)
    return object_response(serialize(rr), 200)
