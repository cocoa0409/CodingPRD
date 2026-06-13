"""Billing-statement endpoints (PRD §3.10)."""

from flask import Blueprint, request

import db
import errors
from middleware import get_identity, require_role
from response import object_response
from services import common
from services import calculations as calc

bp = Blueprint("billing", __name__)


@bp.route("/accounts/<account_id>/billing-statements", methods=["POST"])
def issue_statement(account_id):
    _, role = get_identity()
    require_role(role, {"BillingAdmin"})
    acc = common.get_account_or_404(account_id)
    body = common.get_json_body()
    cycle_index = common.require_int(body, "cycle_index", minimum=0)
    proration_mode = common.require_str(body, "proration_mode")
    if proration_mode not in ("FULL_CYCLE", "PRORATED"):
        raise errors.validation("proration_mode must be FULL_CYCLE or PRORATED")
    days_in_cycle = common.optional_int(body, "days_in_cycle", 30, minimum=28)
    active_days = common.optional_int(body, "active_days", 30, minimum=0)

    # PRORATED requires active_days in 0..days_in_cycle.
    if proration_mode == "PRORATED":
        if active_days < 0 or active_days > days_in_cycle:
            raise errors.invalid_proration()

    # Duplicate cycle: an ISSUED statement already exists for this cycle_index.
    for s in db.billing_statements.values():
        if (s["account_id"] == account_id and s["cycle_index"] == cycle_index
                and s["status"] == "ISSUED"):
            raise errors.duplicate_statement_cycle()

    charges = calc.compute_statement(acc, cycle_index, proration_mode,
                                     days_in_cycle, active_days)

    created_at, updated_at, version = db.stamp_new()
    stmt = {
        "id": db.new_id(),
        "account_id": account_id,
        "cycle_index": cycle_index,
        "proration_mode": proration_mode,
        "days_in_cycle": days_in_cycle,
        "active_days": active_days,
        "status": "ISSUED",
        "package_charge_cents": charges["package_charge_cents"],
        "addon_charge_cents": charges["addon_charge_cents"],
        "equipment_charge_cents": charges["equipment_charge_cents"],
        "regional_sports_fee_cents": charges["regional_sports_fee_cents"],
        "visit_charge_cents": charges["visit_charge_cents"],
        "promo_discount_cents": charges["promo_discount_cents"],
        "etf_charge_cents": charges["etf_charge_cents"],
        "total_cents": charges["total_cents"],
        "created_at": created_at,
        "updated_at": updated_at,
        "version": version,
    }
    db.billing_statements[stmt["id"]] = stmt
    return object_response(stmt, 201)


@bp.route("/accounts/<account_id>/billing-statements", methods=["GET"])
def list_statements(account_id):
    user_id, role = get_identity()
    require_role(role, {"BillingAdmin", "CustomerServiceAgent", "Subscriber"})
    common.resolve_account(role, user_id, account_id)
    items = [s for s in db.billing_statements.values() if s["account_id"] == account_id]
    cycle_index = request.args.get("cycle_index")
    if cycle_index is not None:
        try:
            ci = int(cycle_index)
        except ValueError:
            raise errors.validation("cycle_index must be an integer")
        items = [s for s in items if s["cycle_index"] == ci]
    status = request.args.get("status")
    if status is not None:
        items = [s for s in items if s["status"] == status]
    return common.paginate_and_respond(items)


@bp.route("/accounts/<account_id>/billing-statements/<bid>", methods=["GET"])
def get_statement(account_id, bid):
    user_id, role = get_identity()
    require_role(role, {"BillingAdmin", "CustomerServiceAgent", "Subscriber"})
    common.resolve_account(role, user_id, account_id)
    stmt = db.billing_statements.get(bid)
    if stmt is None or stmt["account_id"] != account_id:
        raise errors.subresource_not_found("Billing statement not found under account")
    return object_response(stmt, 200)
