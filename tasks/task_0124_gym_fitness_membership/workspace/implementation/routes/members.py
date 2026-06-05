"""Member endpoints: register, activate, freeze, unfreeze, cancel (PRD §3.2-§3.7)."""
from datetime import timedelta

from flask import Blueprint, request

import db
import constants
import errors
import lookups
import models
from middleware import authenticate, require_role, require_owner
from response import success
from services import calc
from services import member_ops
from util import require_str, require_int, parse_dt, parse_pagination, paginate

bp = Blueprint("members", __name__)


@bp.route("/members", methods=["POST"])
def register_member():
    caller = authenticate()
    require_role(caller, ["StaffManager"])
    body = request.get_json(silent=True) or {}

    # Required fields + well-formedness (priority 4) — but existence (priority 3)
    # of FKs must precede ERR_INVALID_REQUEST per §2.10. We validate presence/type
    # of scalars, resolve FKs (404), then duplicate-email (409), then plan-archived.
    plan_id = require_str(body, "plan_id")
    home_location_id = require_str(body, "home_location_id")
    full_name = require_str(body, "full_name")
    email = require_str(body, "email")
    period_start = parse_dt(_required(body, "period_start"), "period_start")
    period_end = parse_dt(_required(body, "period_end"), "period_end")
    due_date = parse_dt(_required(body, "due_date"), "due_date")

    # Existence of FKs (priority 3) left-to-right: plan then location.
    plan = lookups.get_plan(plan_id)
    location = lookups.get_location(home_location_id)

    # period_end strictly after period_start (priority 4).
    if period_end <= period_start:
        errors.raise_error(errors.ERR_INVALID_REQUEST, "period_end must be after period_start")

    # Email unique across non-archived members (priority 5).
    for m in db.store.members.values():
        if m["email"] == email:
            errors.raise_error(errors.ERR_DUPLICATE_EMAIL, "Email already in use")

    # Plan not archived (priority 6).
    if plan["archived"]:
        errors.raise_error(errors.ERR_PLAN_ARCHIVED, "Plan is archived")

    now = db.now()
    signed_at = now
    cooling_off_ends_at = signed_at + timedelta(days=constants.COOLING_OFF_DAYS)
    term_ends_at = member_ops.add_months(signed_at, plan["contract_term_months"])

    member = models.stamp_new({
        "plan_id": plan_id,
        "home_location_id": home_location_id,
        "full_name": full_name,
        "email": email,
        "membership_status": "PENDING",
        "dues_status": "CURRENT",
        "class_credits_remaining": 0,
        "guest_passes_remaining": 0,
        "wallet_credit_cents": 0,
        "cumulative_freeze_days": 0,
        "past_due_since": None,
        "contract_status": "IN_COOLING_OFF",
        "contract_term_months": plan["contract_term_months"],
        "signed_at": signed_at,
        "cooling_off_ends_at": cooling_off_ends_at,
        "term_ends_at": term_ends_at,
    })
    db.store.members[member["id"]] = member

    # Create the joining invoice (OPEN, provisional daily proration). PRD §3.2.
    gross = calc.dues_proration_provisional(plan["monthly_dues_cents"], period_start, period_end)
    # No wallet credit at registration (wallet is 0).
    invoice = models.stamp_new({
        "member_id": member["id"],
        "period_start": period_start,
        "period_end": period_end,
        "gross_amount_cents": gross,
        "wallet_applied_cents": 0,
        "amount_due_cents": gross,
        "status": "OPEN",
        "due_date": due_date,
    })
    db.store.dues_invoices[invoice["id"]] = invoice

    return success(models.serialize_member(member), status=201)


@bp.route("/members/<member_id>", methods=["GET"])
def get_member(member_id):
    caller = authenticate()
    require_role(caller, ["StaffManager", "Member"])
    member = lookups.get_member(member_id)
    # Member may read only their own record (id == X-User-ID).
    require_owner(caller, member["id"])
    return success(models.serialize_member(member), status=200)


@bp.route("/members", methods=["GET"])
def list_members():
    caller = authenticate()
    require_role(caller, ["StaffManager"])
    items = list(db.store.members.values())
    plan_id = request.args.get("plan_id")
    home_location_id = request.args.get("home_location_id")
    membership_status = request.args.get("membership_status")
    dues_status = request.args.get("dues_status")
    if plan_id is not None:
        items = [m for m in items if m["plan_id"] == plan_id]
    if home_location_id is not None:
        items = [m for m in items if m["home_location_id"] == home_location_id]
    if membership_status is not None:
        items = [m for m in items if m["membership_status"] == membership_status]
    if dues_status is not None:
        items = [m for m in items if m["dues_status"] == dues_status]
    limit, offset = parse_pagination(request.args)
    page, pagination = paginate(items, limit, offset)
    return success([models.serialize_member(m) for m in page], status=200, pagination=pagination)


@bp.route("/members/<member_id>/activate", methods=["POST"])
def activate_member(member_id):
    caller = authenticate()
    require_role(caller, ["StaffManager"])
    member = lookups.get_member(member_id)

    # State validity (priority 8): must be PENDING.
    if member["membership_status"] != "PENDING":
        errors.raise_error(errors.ERR_INVALID_STATE, "Member is not PENDING")

    # Activation requires the joining (first) invoice PAID (priority 9).
    if not _first_invoice_paid(member["id"]):
        errors.raise_error(errors.ERR_ACTIVATION_NOT_PAID, "Joining invoice is not PAID")

    member["membership_status"] = "ACTIVE"
    models.touch(member)
    return success(models.serialize_member(member), status=200)


@bp.route("/members/<member_id>/freeze", methods=["POST"])
def freeze_member(member_id):
    caller = authenticate()
    require_role(caller, ["StaffManager"])
    member = lookups.get_member(member_id)
    body = request.get_json(silent=True) or {}
    freeze_days = require_int(body, "freeze_days", minimum=0)

    # State validity (priority 8): must be ACTIVE.
    if member["membership_status"] != "ACTIVE":
        errors.raise_error(errors.ERR_INVALID_STATE, "Member is not ACTIVE")

    # Freeze blocked by dues (priority 12): dues must be CURRENT or PAST_DUE.
    if member["dues_status"] not in ("CURRENT", "PAST_DUE"):
        errors.raise_error(errors.ERR_FREEZE_BLOCKED_BY_DUES, "Member dues status blocks freeze")

    # Freeze cap (priority 20).
    plan = db.store.membership_plans.get(member["plan_id"])
    cap = plan["max_freeze_days_per_term"] if plan else 0
    if member["cumulative_freeze_days"] + freeze_days > cap:
        errors.raise_error(errors.ERR_FREEZE_CAP_EXCEEDED, "Freeze span exceeds the contract-term cap")

    member["membership_status"] = "FROZEN"
    member["cumulative_freeze_days"] += freeze_days
    models.touch(member)

    # Cancel future BOOKED bookings on SCHEDULED sessions starting after now.
    member_ops.freeze_cascade(member)

    return success(models.serialize_member(member), status=200)


@bp.route("/members/<member_id>/unfreeze", methods=["POST"])
def unfreeze_member(member_id):
    caller = authenticate()
    require_role(caller, ["StaffManager"])
    member = lookups.get_member(member_id)

    if member["membership_status"] != "FROZEN":
        errors.raise_error(errors.ERR_INVALID_STATE, "Member is not FROZEN")

    member["membership_status"] = "ACTIVE"
    models.touch(member)
    return success(models.serialize_member(member), status=200)


@bp.route("/members/<member_id>/cancel", methods=["POST"])
def cancel_member(member_id):
    caller = authenticate()
    require_role(caller, ["StaffManager", "Member"])
    member = lookups.get_member(member_id)
    require_owner(caller, member["id"])

    # Permitted from any non-terminal lifecycle state (priority 8).
    if member["membership_status"] == "CANCELLED":
        errors.raise_error(errors.ERR_INVALID_STATE, "Member is already CANCELLED")

    now = db.now()
    member["membership_status"] = "CANCELLED"
    # Contract -> TERMINATED unless already FULFILLED (PRD §3.7).
    if member["contract_status"] != "FULFILLED":
        member["contract_status"] = "TERMINATED"

    # Settlement (PRD §3.7 / SCAFFOLD cancellation_settlement).
    _apply_settlement(member, now)

    models.touch(member)

    # Cleanup cascade.
    member_ops.cancel_member_cascade(member)

    return success(models.serialize_member(member), status=200)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _required(body, field):
    if not isinstance(body, dict) or field not in body or body[field] is None:
        errors.raise_error(errors.ERR_INVALID_REQUEST, "Missing required field '%s'" % field)
    return body[field]


def _member_invoices_sorted(member_id):
    inv = [i for i in db.store.dues_invoices.values() if i["member_id"] == member_id]
    inv.sort(key=lambda i: (i["created_at"], i["_seq"]))
    return inv


def _first_invoice_paid(member_id):
    inv = _member_invoices_sorted(member_id)
    if not inv:
        return False
    return inv[0]["status"] == "PAID"


def _apply_settlement(member, now):
    plan = db.store.membership_plans.get(member["plan_id"])
    etf = plan["early_termination_fee_cents"] if plan else 0

    if now <= member["cooling_off_ends_at"]:
        # Cooling-off variant: full refund of PAID dues, zero ETF.
        refund = sum(i["gross_amount_cents"] for i in db.store.dues_invoices.values()
                     if i["member_id"] == member["id"] and i["status"] == "PAID")
        early_fee = 0
    elif now <= member["term_ends_at"]:
        # Mid-term variant: zero refund, flat ETF.
        refund = 0
        early_fee = etf
    else:
        # Post-term variant: zero refund, zero ETF.
        refund = 0
        early_fee = 0

    net = refund - early_fee
    if net > 0:
        member["wallet_credit_cents"] += net
    elif net < 0:
        # Bill the fee as a new OPEN invoice for abs(net).
        amount = -net
        invoice = models.stamp_new({
            "member_id": member["id"],
            "period_start": now,
            "period_end": now + timedelta(days=1),
            "gross_amount_cents": amount,
            "wallet_applied_cents": 0,
            "amount_due_cents": amount,
            "status": "OPEN",
            "due_date": now,
        })
        db.store.dues_invoices[invoice["id"]] = invoice
