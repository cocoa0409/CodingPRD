"""Assessment CRUD + pay + place-lien + payment listing."""

from datetime import timedelta

from flask import Blueprint, request

import db
from auth import require_role
from clock import get_now, get_now_iso, sweep_time_transitions
from entities import bump, new_assessment, new_payment
from errors import raise_error
from response import success
from services import calc
from services import property as property_svc
from services import homeowner as homeowner_svc
from utils import (paginate, parse_iso, require_enum, require_fields, require_int,
                   require_str, optional_str, require_json)

bp = Blueprint("assessments", __name__)


# ---------------- Create assessment ---------------- #

@bp.route("/assessments", methods=["POST"])
@require_role("HOAManager")
def create_assessment():
    body = require_json(request)
    require_fields(body, "property_id", "billing_period_start", "billing_period_end", "due_date")
    property_id = require_str(body, "property_id")
    bps = require_str(body, "billing_period_start")
    bpe = require_str(body, "billing_period_end")
    due_date = require_str(body, "due_date")
    prorate_from = optional_str(body, "prorate_from", default=None)

    # Body FK -> Property
    prop = db.properties.get(property_id)
    if not prop:
        raise_error("ERR_FK_NOT_FOUND", "property_id does not resolve")

    # Parse timestamps (raises ERR_INVALID_REQUEST on bad format)
    parse_iso(bps)
    parse_iso(bpe)
    parse_iso(due_date)
    if prorate_from is not None:
        parse_iso(prorate_from)

    # Stamp amount_due_cents from proration.
    amount_due = calc.assessment_prorate(
        monthly_dues_cents=prop["monthly_dues_cents"],
        billing_start_iso=bps,
        billing_end_iso=bpe,
        prorate_from_iso=prorate_from,
    )

    now_iso = get_now_iso()
    row = new_assessment(
        property_id=property_id,
        billing_period_start_iso=bps,
        billing_period_end_iso=bpe,
        due_date_iso=due_date,
        prorate_from_iso=prorate_from,
        amount_due_cents=amount_due,
        now_iso=now_iso,
    )
    db.assessments[row["id"]] = row

    # Recompute ONLY the property's derived total_outstanding_cents so it reflects the
    # new assessment immediately. Per PRD §2.6 the homeowner's delinquency_score/standing
    # are recomputed only on the enumerated triggers (state transition, payment
    # post/reversal, fine, adjudication, ARC approval); creating an assessment is not one
    # of them. Recomputing the homeowner here would prematurely flip standing off a
    # not-yet-overdue OPEN assessment and corrupt the "current standing" multiplier that
    # the later OPEN->OVERDUE transition reads for the late-fee calculation (PRD §3.2).
    property_svc.recompute(prop, now_iso)

    # Per PRD §3.2/§3.9 the OPEN->OVERDUE auto-transition fires only when the logical
    # clock ADVANCES past due_date (the set_current_utc capability), never as a side
    # effect of creating the assessment. A freshly created assessment therefore keeps its
    # initial OPEN status even when the current clock is already past due_date; it
    # transitions (and stamps its late fee at the then-current day count) on the next
    # clock advance. Hence no sweep here.
    return success(db.assessments[row["id"]], status=201)


# ---------------- Get assessment ---------------- #

@bp.route("/assessments/<aid>", methods=["GET"])
@require_role("Homeowner", "BoardMember", "HOAManager")
def get_assessment(aid):
    sweep_time_transitions()
    a = db.assessments.get(aid)
    if not a:
        raise_error("ERR_NOT_FOUND", "assessment not found")
    return success(a)


# ---------------- Pay assessment ---------------- #

@bp.route("/assessments/<aid>/pay", methods=["POST"])
@require_role("Homeowner", "HOAManager")
def pay_assessment(aid):
    body = require_json(request)
    # PRD §2.8: malformed payloads are 400 before the priority sequence starts.
    require_fields(body, "amount_cents", "method")
    amount = require_int(body, "amount_cents", minimum=1)
    method = require_enum(body, "method", {"MANUAL", "AUTOPAY"})

    sweep_time_transitions()
    a = db.assessments.get(aid)
    if not a:
        raise_error("ERR_NOT_FOUND", "assessment not found")

    # State precondition: any non-terminal, non-lien assessment accepts payment.
    # Terminal PAID and ON_LIEN reject with ERR_INVALID_STATE.
    if a["status"] not in ("OPEN", "PARTIALLY_PAID", "OVERDUE", "DELINQUENT"):
        raise_error("ERR_INVALID_STATE", f"cannot pay assessment in status {a['status']}")

    # Overpayment guard (priority 14).
    outstanding_total = a["amount_due_cents"] + a.get("late_fee_cents", 0)
    new_paid = a["amount_paid_cents"] + amount
    if new_paid > outstanding_total:
        raise_error("ERR_OVERPAYMENT", "payment exceeds outstanding balance")

    now_iso = get_now_iso()

    p = new_payment(aid, amount, method, now_iso)
    db.payments[p["id"]] = p

    a["amount_paid_cents"] = new_paid

    if new_paid == outstanding_total:
        a["status"] = "PAID"
    elif a["status"] == "OPEN":
        # PRD §3.2 names OPEN -> PARTIALLY_PAID for less-than-full payments.
        a["status"] = "PARTIALLY_PAID"
    # OVERDUE / PARTIALLY_PAID: status unchanged on partial payment (PRD §3.2 does
    # not declare an OVERDUE -> PARTIALLY_PAID transition; late_fee_cents remains
    # stamped on the row).

    bump(a, now_iso)

    # Cascades: property + homeowner recompute.
    homeowner_svc.recompute_owner_and_property(a["property_id"], now_iso)

    return success(p, status=201)


# ---------------- Place lien ---------------- #

@bp.route("/assessments/<aid>/place-lien", methods=["POST"])
@require_role("HOAManager")
def place_lien(aid):
    require_json(request)
    sweep_time_transitions()
    a = db.assessments.get(aid)
    if not a:
        raise_error("ERR_NOT_FOUND", "assessment not found")

    if a["status"] != "DELINQUENT":
        raise_error("ERR_INVALID_STATE", "assessment must be DELINQUENT to place a lien")

    due = parse_iso(a["due_date"])
    if get_now() < due + timedelta(days=90):
        raise_error("ERR_INVALID_STATE", "assessment must be >= 90 days past due")

    now_iso = get_now_iso()
    a["status"] = "ON_LIEN"
    bump(a, now_iso)

    homeowner_svc.recompute_owner_and_property(a["property_id"], now_iso)
    return success(a)


# ---------------- List payments against an assessment ---------------- #

@bp.route("/assessments/<aid>/payments", methods=["GET"])
@require_role("Homeowner", "BoardMember", "HOAManager")
def list_assessment_payments(aid):
    if aid not in db.assessments:
        raise_error("ERR_NOT_FOUND", "assessment not found")
    items = [p for p in db.payments.values() if p["assessment_id"] == aid]
    items.sort(key=lambda r: r["created_at"])
    page, meta = paginate(items, request)
    return success(page, is_array=True, pagination=meta)
