"""Payment retrieval + reversal (three-aggregate cascade)."""

from flask import Blueprint, request

import db
from auth import require_role
from clock import get_now, get_now_iso, sweep_time_transitions
from entities import bump
from errors import raise_error
from response import success
from services import assessment as assessment_svc
from services import homeowner as homeowner_svc
from utils import parse_iso, require_json, require_str, require_fields

bp = Blueprint("payments", __name__)


@bp.route("/payments/<pid>", methods=["GET"])
@require_role("Homeowner", "BoardMember", "HOAManager")
def get_payment(pid):
    p = db.payments.get(pid)
    if not p:
        raise_error("ERR_NOT_FOUND", "payment not found")
    return success(p)


@bp.route("/payments/<pid>/reverse", methods=["POST"])
@require_role("HOAManager")
def reverse_payment(pid):
    body = require_json(request)
    require_fields(body, "reversal_reason")
    reason = require_str(body, "reversal_reason", allow_empty=True)

    p = db.payments.get(pid)
    if not p:
        raise_error("ERR_NOT_FOUND", "payment not found")

    if p["status"] != "POSTED":
        raise_error("ERR_INVALID_STATE", "only POSTED payments may be reversed")

    a = db.assessments.get(p["assessment_id"])
    if not a:
        # Should not happen — assessments never get deleted.
        raise_error("ERR_INVALID_STATE", "assessment no longer exists")

    now_iso = get_now_iso()
    now_dt = get_now()

    prior_paid = a["amount_paid_cents"]
    was_paid = a["status"] == "PAID"

    # Flip payment.
    p["status"] = "REVERSED"
    p["reversal_reason"] = reason
    bump(p, now_iso)

    # Cascade link 1: reduce assessment.amount_paid_cents.
    a["amount_paid_cents"] = max(0, prior_paid - p["amount_cents"])

    # State transition on Assessment.
    new_paid = a["amount_paid_cents"]
    outstanding_total = a["amount_due_cents"] + a.get("late_fee_cents", 0)
    if was_paid and new_paid < outstanding_total:
        # PAID -> OVERDUE if clock >= due_date; else PAID -> PARTIALLY_PAID.
        due = parse_iso(a["due_date"])
        if now_dt >= due:
            a["status"] = "OVERDUE"
            assessment_svc.restamp_late_fee(a, now_iso)
        else:
            a["status"] = "PARTIALLY_PAID"
    elif a["status"] == "PARTIALLY_PAID" and new_paid == 0:
        # Down to zero — treat as OPEN if before due_date, else OVERDUE.
        due = parse_iso(a["due_date"])
        if now_dt >= due:
            a["status"] = "OVERDUE"
            assessment_svc.restamp_late_fee(a, now_iso)
        else:
            a["status"] = "OPEN"
    # Otherwise: reverting a partial payment on an already-PARTIALLY_PAID/OVERDUE assessment
    # leaves the status as-is.

    bump(a, now_iso)

    # Cascade links 2 & 3: homeowner recompute + property recompute.
    homeowner_svc.recompute_owner_and_property(a["property_id"], now_iso)

    return success(p)
