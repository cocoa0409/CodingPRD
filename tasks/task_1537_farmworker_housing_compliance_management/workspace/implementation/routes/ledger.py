"""Charge ledger entries: post, list, get, void."""

from flask import Blueprint

import clock
import db
from errors import err
from middleware import require_roles, get_auth
from response import success_object, success_list
from services import core
from services import calculations
from validate import (
    get_body, require_string, require_enum, optional_string, optional_int,
    parse_pagination, get_filter, sort_and_paginate,
)

bp = Blueprint("ledger", __name__)

ENTRY_TYPES = {"RENT", "UTILITY_OVERAGE", "DAMAGE", "SUBSIDY_CREDIT", "PAYMENT"}
POSTABLE_TYPES = {"RENT", "UTILITY_OVERAGE", "DAMAGE", "SUBSIDY_CREDIT"}
UTILITY_TYPES = {"ELECTRIC", "GAS", "WATER"}


def _view(e):
    return {
        "id": e["id"],
        "tenancy_id": e["tenancy_id"],
        "entry_type": e["entry_type"],
        "amount_cents": e["amount_cents"],
        "usage_lines": e["usage_lines"],
        "source_work_order_id": e["source_work_order_id"],
        "description": e["description"],
        "charge_date": e["charge_date"],
        "status": e["status"],
        "void_reason": e["void_reason"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def _validate_usage_lines(lines):
    if not isinstance(lines, list):
        raise err("ERR_INVALID_REQUEST", "usage_lines must be a list")
    for line in lines:
        if not isinstance(line, dict):
            raise err("ERR_INVALID_REQUEST", "each usage line must be an object")
        ut = line.get("utility_type")
        if ut not in UTILITY_TYPES:
            raise err("ERR_INVALID_REQUEST", "usage line utility_type must be ELECTRIC, GAS, or WATER")
        uu = line.get("usage_units")
        if isinstance(uu, bool) or not isinstance(uu, int) or uu < 0:
            raise err("ERR_INVALID_REQUEST", "usage line usage_units must be a non-negative integer")


@bp.route("/charge-ledger-entries", methods=["POST"])
def create_entry():
    require_roles("OperatorAdmin")
    body = get_body()
    tenancy_id = require_string(body, "tenancy_id")
    entry_type = require_enum(body, "entry_type", ENTRY_TYPES)
    description = optional_string(body, "description")

    if entry_type == "PAYMENT":
        raise err("ERR_INVALID_REQUEST", "PAYMENT entries arise only through the payroll-payment capability")

    # Conditional field rules (priority 3).
    amount = body.get("amount_cents")
    usage_lines = body.get("usage_lines")
    source_wo = body.get("source_work_order_id")

    if entry_type == "UTILITY_OVERAGE":
        if amount is not None:
            raise err("ERR_INVALID_REQUEST", "amount_cents is forbidden for UTILITY_OVERAGE")
        if source_wo is not None:
            raise err("ERR_INVALID_REQUEST", "source_work_order_id is forbidden for UTILITY_OVERAGE")
        if usage_lines is None:
            raise err("ERR_INVALID_REQUEST", "usage_lines is required for UTILITY_OVERAGE")
        _validate_usage_lines(usage_lines)
    elif entry_type == "DAMAGE":
        if source_wo is None:
            raise err("ERR_INVALID_REQUEST", "source_work_order_id is required for DAMAGE")
        if usage_lines is not None:
            raise err("ERR_INVALID_REQUEST", "usage_lines is forbidden for DAMAGE")
        if amount is None:
            raise err("ERR_INVALID_REQUEST", "amount_cents is required for DAMAGE")
        if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
            raise err("ERR_INVALID_REQUEST", "amount_cents must be a positive integer")
    else:  # RENT, SUBSIDY_CREDIT
        if usage_lines is not None:
            raise err("ERR_INVALID_REQUEST", "usage_lines is forbidden for this entry type")
        if source_wo is not None:
            raise err("ERR_INVALID_REQUEST", "source_work_order_id is forbidden for this entry type")
        if amount is None:
            raise err("ERR_INVALID_REQUEST", "amount_cents is required")
        if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
            raise err("ERR_INVALID_REQUEST", "amount_cents must be a positive integer")

    # Existence: tenancy.
    t = db.tenancies.get(tenancy_id)
    if t is None:
        raise err("ERR_TENANCY_NOT_FOUND")

    # Tenancy must be ACTIVE or NOTICE (priority 7.5).
    if t["status"] not in ("ACTIVE", "NOTICE"):
        raise err("ERR_INVALID_STATE", "Ledger entries require tenancy in ACTIVE or NOTICE")

    # DAMAGE work-order gate (priority 16).
    if entry_type == "DAMAGE":
        wo = db.work_orders.get(source_wo)
        if wo is None:
            raise err("ERR_WORK_ORDER_NOT_FOUND")
        if wo["status"] not in ("VERIFIED", "CLOSED"):
            raise err("ERR_WORK_ORDER_NOT_VERIFIED")

    # Compute amount for UTILITY_OVERAGE.
    if entry_type == "UTILITY_OVERAGE":
        amount = calculations.utility_overage_charge(usage_lines)

    now = db.now_ts()
    e = {
        "id": db.new_id(),
        "tenancy_id": tenancy_id,
        "entry_type": entry_type,
        "amount_cents": amount,
        "usage_lines": usage_lines,
        "source_work_order_id": source_wo,
        "description": description,
        "charge_date": clock.today_iso(),
        "status": "POSTED",
        "void_reason": None,
        "payment_purpose": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.ledger_entries[e["id"]] = e
    core.recompute_tenancy_ledger(tenancy_id)
    t["version"] += 1
    t["updated_at"] = db.now_ts()
    return success_object(_view(e), status=201)


@bp.route("/charge-ledger-entries", methods=["GET"])
def list_entries():
    get_auth()
    limit, offset = parse_pagination()
    items = list(db.ledger_entries.values())
    tenancy_f = get_filter("tenancy_id")
    type_f = get_filter("entry_type")
    status_f = get_filter("status")
    swo_f = get_filter("source_work_order_id")
    if tenancy_f is not None:
        items = [e for e in items if e["tenancy_id"] == tenancy_f]
    if type_f is not None:
        items = [e for e in items if e["entry_type"] == type_f]
    if status_f is not None:
        items = [e for e in items if e["status"] == status_f]
    if swo_f is not None:
        items = [e for e in items if e.get("source_work_order_id") == swo_f]
    page, total = sort_and_paginate(items, limit, offset)
    return success_list([_view(e) for e in page], total, limit, offset)


@bp.route("/charge-ledger-entries/<eid>", methods=["GET"])
def get_entry(eid):
    get_auth()
    e = db.ledger_entries.get(eid)
    if e is None:
        raise err("ERR_NOT_FOUND")
    return success_object(_view(e))


@bp.route("/charge-ledger-entries/<eid>/void", methods=["POST"])
def void_entry(eid):
    require_roles("OperatorAdmin")
    body = get_body()
    void_reason = require_string(body, "void_reason")
    e = db.ledger_entries.get(eid)
    if e is None:
        raise err("ERR_NOT_FOUND")
    if e["status"] != "POSTED":
        raise err("ERR_ENTRY_ALREADY_VOIDED")
    now = db.now_ts()
    e["status"] = "VOIDED"
    e["void_reason"] = void_reason
    e["updated_at"] = now
    core.recompute_tenancy_ledger(e["tenancy_id"])
    t = db.tenancies.get(e["tenancy_id"])
    if t is not None:
        t["version"] += 1
        t["updated_at"] = now
    return success_object(_view(e))
