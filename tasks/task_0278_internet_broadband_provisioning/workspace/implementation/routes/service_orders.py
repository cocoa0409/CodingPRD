"""ServiceOrder endpoints (PRD §3.2)."""
from flask import Blueprint, request

import db
from clock import get_clock
from db import touch
from errors import err
from middleware import get_user_context, require_role
from response import object_response, array_response
from services.helpers import (get_json_body, lookup, require_fields,
                              require_enum, paginate, sorted_by_created,
                              check_owner)
from services.serialize import public, public_list
from services import domain
from timeutil import format_iso, parse_iso

bp = Blueprint("service_orders", __name__)

ORDER_TYPE = {"NEW_INSTALL", "TRANSFER_IN", "UPGRADE"}
INSTALL_MODE = {"TECH_INSTALL", "SELF_INSTALL"}


@bp.route("/service-orders", methods=["POST"])
def create_service_order():
    uid, role = get_user_context()
    require_role(role, {"Customer", "ProvisioningAgent"})
    body = get_json_body()
    require_fields(body, ["account_id", "order_type", "install_mode",
                          "requested_plan_id"])
    account = lookup(db.accounts, body["account_id"])
    order_type = require_enum(body, "order_type", ORDER_TYPE)
    install_mode = require_enum(body, "install_mode", INSTALL_MODE)
    plan = lookup(db.service_plans, body["requested_plan_id"])
    check_owner(role, uid, account)
    rec = db.make_record({
        "account_id": account["id"],
        "order_type": order_type,
        "install_mode": install_mode,
        "requested_plan_id": plan["id"],
        "equipment_unit_id": None,
        "status": "DRAFT",
    }, versioned=db.VERSIONED)
    db.service_orders[rec["id"]] = rec
    return object_response(public(rec), 201)


@bp.route("/service-orders/<rid>", methods=["GET"])
def get_service_order(rid):
    uid, role = get_user_context()
    require_role(role, {"Customer", "ProvisioningAgent", "NetworkOps", "Dispatcher"})
    rec = lookup(db.service_orders, rid)
    account = db.accounts.get(rec["account_id"])
    if account is not None:
        check_owner(role, uid, account)
    return object_response(public(rec), 200)


@bp.route("/service-orders", methods=["GET"])
def list_service_orders():
    _uid, role = get_user_context()
    require_role(role, {"Customer", "ProvisioningAgent", "NetworkOps", "Dispatcher"})
    recs = list(db.service_orders.values())
    for f in ("account_id", "requested_plan_id", "equipment_unit_id", "status"):
        val = request.args.get(f)
        if val is not None:
            recs = [r for r in recs if r.get(f) == val]
    recs = sorted_by_created(recs)
    window, limit, offset, total, has_more = paginate(recs)
    return array_response(public_list(window), limit, offset, total, has_more, 200)


@bp.route("/service-orders/<rid>/ship-kit", methods=["POST"])
def ship_kit(rid):
    _uid, role = get_user_context()
    require_role(role, {"ProvisioningAgent"})
    get_json_body()
    rec = lookup(db.service_orders, rid)
    if rec["status"] != "DRAFT":
        err("ERR_INVALID_STATE", "Order must be DRAFT to ship a kit.")
    if rec["install_mode"] != "SELF_INSTALL":
        err("ERR_INVALID_STATE", "Ship-kit requires a SELF_INSTALL order.")
    account = db.accounts.get(rec["account_id"])
    address = db.service_addresses.get(account["service_address_id"]) if account else None
    plan = db.service_plans.get(rec["requested_plan_id"])
    # Gate order (§3.12): serviceability before speed, then self-install eligibility.
    if address is None or address["coverage_status"] != "SERVICEABLE":
        err("ERR_ADDRESS_NOT_SERVICEABLE", "Address is not SERVICEABLE.")
    if plan is not None and plan["download_mbps"] > address["max_serviceable_mbps"]:
        err("ERR_PLAN_EXCEEDS_SERVICEABLE_SPEED",
            "Requested plan exceeds the address serviceable speed.")
    if not address["self_install_eligible"]:
        err("ERR_SELF_INSTALL_NOT_ELIGIBLE",
            "Address is not eligible for self-install.")
    rec["status"] = "KIT_SHIPPED"
    touch(rec)
    return object_response(public(rec), 200)


@bp.route("/service-orders/<rid>/activate", methods=["POST"])
def activate(rid):
    uid, role = get_user_context()
    require_role(role, {"Customer", "ProvisioningAgent"})
    get_json_body()
    rec = lookup(db.service_orders, rid)
    account = db.accounts.get(rec["account_id"])
    if account is not None:
        check_owner(role, uid, account)
    # State precondition: SCHEDULED or KIT_SHIPPED.
    if rec["status"] not in ("SCHEDULED", "KIT_SHIPPED"):
        err("ERR_INVALID_STATE", "Order must be SCHEDULED or KIT_SHIPPED to activate.")
    # SCHEDULED requires its appointment COMPLETED.
    if rec["status"] == "SCHEDULED":
        appt = _appointment_for_order(rec["id"])
        if appt is None or appt["status"] != "COMPLETED":
            err("ERR_INVALID_STATE",
                "Scheduled order requires a COMPLETED install appointment.")
    # Select an IN_INVENTORY unit to assign (join point).
    unit = _pick_inventory_unit()
    if unit is None:
        err("ERR_NO_EQUIPMENT_AVAILABLE",
            "No IN_INVENTORY equipment unit available to assign.")
    now = get_clock().now()
    now_iso = format_iso(now)

    # Assign + lease the unit.
    unit["status"] = "LEASED"
    unit["account_id"] = account["id"]
    unit["leased_at_iso"] = now_iso
    touch(unit)

    rec["equipment_unit_id"] = unit["id"]
    rec["status"] = "ACTIVATED"
    touch(rec)

    # Activate the account.
    account["status"] = "ACTIVE"
    account["service_state"] = "ONLINE"
    account["contract_start_iso"] = now_iso
    account["equipment_unit_id"] = unit["id"]
    touch(account)

    # Create OPEN billing cycle: start = now, end = now + 30 days.
    end = now + _timedelta_days(30)
    cycle = db.make_record({
        "account_id": account["id"],
        "cycle_start_iso": now_iso,
        "cycle_end_iso": format_iso(end),
        "usage_gb": 0,
        "billing_state": "OPEN",
        "throttle_state": "UNCAPPED",
        "overage_charge_cents": 0,
        "total_due_cents": 0,
    }, versioned=db.VERSIONED)
    db.billing_cycles[cycle["id"]] = cycle

    return object_response(public(rec), 200)


@bp.route("/service-orders/<rid>/cancel", methods=["POST"])
def cancel(rid):
    _uid, role = get_user_context()
    require_role(role, {"ProvisioningAgent"})
    get_json_body()
    rec = lookup(db.service_orders, rid)
    if rec["status"] not in ("DRAFT", "SCHEDULED", "KIT_SHIPPED"):
        err("ERR_INVALID_STATE", "Order cannot be cancelled from its current state.")
    if rec["status"] == "SCHEDULED":
        # Cascade: BOOKED appointment -> CANCELLED, slot booked_count -= 1.
        appt = _appointment_for_order(rec["id"])
        if appt is not None and appt["status"] == "BOOKED":
            appt["status"] = "CANCELLED"
            touch(appt)
            _release_slot(appt["install_slot_id"])
    elif rec["status"] == "KIT_SHIPPED":
        # Release the reserved equipment unit back to IN_INVENTORY.
        if rec.get("equipment_unit_id"):
            unit = db.equipment_units.get(rec["equipment_unit_id"])
            if unit is not None:
                unit["status"] = "IN_INVENTORY"
                unit["account_id"] = None
                touch(unit)
    rec["status"] = "CANCELLED"
    touch(rec)
    return object_response(public(rec), 200)


# --- helpers ---

def _appointment_for_order(order_id):
    appts = [a for a in db.install_appointments.values()
             if a["service_order_id"] == order_id]
    # Prefer the non-cancelled / active appointment.
    active = [a for a in appts if a["status"] in ("BOOKED", "COMPLETED")]
    pool = active if active else appts
    if not pool:
        return None
    pool = sorted(pool, key=lambda a: (a["created_at"], a["id"]))
    return pool[-1]


def _pick_inventory_unit():
    units = [u for u in db.equipment_units.values()
             if u["status"] == "IN_INVENTORY"]
    if not units:
        return None
    units = sorted(units, key=lambda u: (u["created_at"], u["id"]))
    return units[0]


def _release_slot(slot_id):
    slot = db.install_slots.get(slot_id)
    if slot is None:
        return
    slot["booked_count"] = max(0, slot["booked_count"] - 1)
    if slot["booked_count"] < slot["capacity"]:
        slot["status"] = "OPEN"
    touch(slot)


def _timedelta_days(n):
    from datetime import timedelta
    return timedelta(days=n)
