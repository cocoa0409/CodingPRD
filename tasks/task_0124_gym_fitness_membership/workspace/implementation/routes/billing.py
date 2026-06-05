"""DuesInvoice endpoints (PRD §3.8) and the delinquency recovery on pay (§3.4)."""
from flask import Blueprint, request

import db
import errors
import lookups
import models
from middleware import authenticate, require_role, require_owner
from response import success
from services import calc
from util import (require_str, parse_dt, parse_pagination, paginate)

bp = Blueprint("billing", __name__)


@bp.route("/dues-invoices", methods=["POST"])
def create_invoice():
    caller = authenticate()
    require_role(caller, ["StaffManager"])
    body = request.get_json(silent=True) or {}

    member_id = require_str(body, "member_id")
    period_start_raw = _required(body, "period_start")
    period_end_raw = _required(body, "period_end")
    due_date_raw = _required(body, "due_date")

    member = lookups.get_member(member_id)

    period_start = parse_dt(period_start_raw, "period_start")
    period_end = parse_dt(period_end_raw, "period_end")
    due_date = parse_dt(due_date_raw, "due_date")
    if period_end <= period_start:
        errors.raise_error(errors.ERR_INVALID_REQUEST, "period_end must be after period_start")

    plan = db.store.membership_plans.get(member["plan_id"])
    base = plan["monthly_dues_cents"] if plan else 0
    # Recurring posting uses the provisional daily-calendar proration. The final
    # fixed-30 variant is only applied at cycle reconciliation, which the API
    # surface does not expose; provisional is what is pinned here. PRD §3.8.
    gross = calc.dues_proration_provisional(base, period_start, period_end)

    # Apply wallet credit at posting time. PRD §3.8.
    wallet = member["wallet_credit_cents"]
    wallet_applied = min(wallet, gross)
    amount_due = gross - wallet_applied
    if amount_due < 0:
        amount_due = 0
    member["wallet_credit_cents"] = wallet - wallet_applied
    if wallet_applied > 0:
        models.touch(member)

    rec = models.stamp_new({
        "member_id": member_id,
        "period_start": period_start,
        "period_end": period_end,
        "gross_amount_cents": gross,
        "wallet_applied_cents": wallet_applied,
        "amount_due_cents": amount_due,
        "status": "OPEN",
        "due_date": due_date,
    })
    db.store.dues_invoices[rec["id"]] = rec
    return success(models.serialize_dues_invoice(rec), status=201)


@bp.route("/dues-invoices/<invoice_id>", methods=["GET"])
def get_invoice(invoice_id):
    caller = authenticate()
    require_role(caller, ["StaffManager", "Member"])
    rec = lookups.get_dues_invoice(invoice_id)
    require_owner(caller, rec["member_id"])
    return success(models.serialize_dues_invoice(rec), status=200)


@bp.route("/dues-invoices", methods=["GET"])
def list_invoices():
    caller = authenticate()
    require_role(caller, ["StaffManager", "Member"])
    items = list(db.store.dues_invoices.values())
    if caller.is_member:
        items = [i for i in items if i["member_id"] == caller.user_id]
    member_id = request.args.get("member_id")
    status = request.args.get("status")
    if member_id is not None:
        items = [i for i in items if i["member_id"] == member_id]
    if status is not None:
        items = [i for i in items if i["status"] == status]
    limit, offset = parse_pagination(request.args)
    page, pagination = paginate(items, limit, offset)
    return success([models.serialize_dues_invoice(i) for i in page], status=200, pagination=pagination)


@bp.route("/dues-invoices/<invoice_id>/pay", methods=["POST"])
def pay_invoice(invoice_id):
    caller = authenticate()
    require_role(caller, ["StaffManager", "Member"])
    rec = lookups.get_dues_invoice(invoice_id)
    require_owner(caller, rec["member_id"])

    if rec["status"] != "OPEN":
        errors.raise_error(errors.ERR_INVALID_STATE, "Invoice is not OPEN")

    rec["status"] = "PAID"
    models.touch(rec)

    member = db.store.members.get(rec["member_id"])
    if member is not None:
        plan = db.store.membership_plans.get(member["plan_id"])
        member["class_credits_remaining"] = plan["included_class_credits"] if plan else 0
        member["guest_passes_remaining"] = plan["guest_passes_per_cycle"] if plan else 0
        models.touch(member)
        # Delinquency recovery: if no OPEN invoice now has due_date before clock.
        _maybe_clear_delinquency(member)

    return success(models.serialize_dues_invoice(rec), status=200)


@bp.route("/dues-invoices/<invoice_id>/void", methods=["POST"])
def void_invoice(invoice_id):
    caller = authenticate()
    require_role(caller, ["StaffManager"])
    rec = lookups.get_dues_invoice(invoice_id)

    if rec["status"] != "OPEN":
        errors.raise_error(errors.ERR_INVALID_STATE, "Invoice is not OPEN")

    rec["status"] = "VOID"
    models.touch(rec)
    return success(models.serialize_dues_invoice(rec), status=200)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _required(body, field):
    if not isinstance(body, dict) or field not in body or body[field] is None:
        errors.raise_error(errors.ERR_INVALID_REQUEST, "Missing required field '%s'" % field)
    return body[field]


def _maybe_clear_delinquency(member):
    if member["dues_status"] == "CURRENT":
        return
    clock = db.now()
    still_overdue = any(
        i["member_id"] == member["id"] and i["status"] == "OPEN" and i["due_date"] < clock
        for i in db.store.dues_invoices.values()
    )
    if not still_overdue:
        member["dues_status"] = "CURRENT"
        member["past_due_since"] = None
        models.touch(member)
