"""RentalContract endpoints: fetch, list, return, damage-reports, settle,
void, ledger."""
from flask import Blueprint, request

import db
import lookup
import validate as V
from errors import err
from middleware import authenticate, require_role
from response import success, list_success
from serialize import public, public_list
from services import calc, domain

bp = Blueprint("contracts", __name__)

ALL_ROLES = {"FleetManager", "LocationAgent", "Customer"}


def _ownership_check(role, user_id, contract):
    """Customer may only read a contract whose reservation they own."""
    if role == "Customer":
        res = db.reservations.get(contract["reservation_id"])
        if res is None or res["customer_id"] != user_id:
            raise err("ERR_NOT_RESOURCE_OWNER", "Contract does not belong to this customer.")


@bp.route("/rental/contracts/<rid>", methods=["GET"])
def get_contract(rid):
    user_id, role = authenticate()
    require_role(role, ALL_ROLES)
    c = lookup.require_contract(rid)
    _ownership_check(role, user_id, c)
    return success(public(c))


@bp.route("/rental/contracts", methods=["GET"])
def list_contracts():
    user_id, role = authenticate()
    require_role(role, ALL_ROLES)
    limit, offset = V.parse_pagination()
    rows = db.contracts.all()
    if role == "Customer":
        owned = {r["id"] for r in db.reservations.items.values()
                 if r["customer_id"] == user_id}
        rows = [c for c in rows if c["reservation_id"] in owned]
    for field in ("reservation_id", "equipment_id", "status"):
        val = request.args.get(field)
        if val:
            rows = [c for c in rows if c.get(field) == val]
    page, total = V.paginate(rows, limit, offset)
    return list_success(public_list(page), limit, offset, total)


# ============================ return ============================
@bp.route("/rental/contracts/<rid>/return", methods=["POST"])
def return_contract(rid):
    _, role = authenticate()
    require_role(role, {"LocationAgent"})
    c = lookup.require_contract(rid)
    body = V.get_json()
    V.require_fields(body, ["return_odometer_miles", "return_fuel_eighths", "actual_return_at"])
    return_odo = V.require_int(body, "return_odometer_miles", minimum=0)
    return_fuel = V.require_int(body, "return_fuel_eighths", minimum=0)
    if return_fuel > 8:
        raise err("ERR_INVALID_REQUEST", "return_fuel_eighths must be 0..8.")
    V.parse_datetime(body, "actual_return_at")  # validate shape

    # State (priority 9).
    if c["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Contract must be ACTIVE to return.")

    # Odometer regression (priority 12).
    if return_odo < c["pickup_odometer_miles"]:
        raise err("ERR_ODOMETER_REGRESSION", "Return odometer below pickup odometer.")

    res = db.reservations.get(c["reservation_id"])
    dropoff = db.locations.get(res["dropoff_location_id"])

    # Drop-off OPEN + capacity (priority 16).
    if dropoff["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Drop-off location is not OPEN.")
    if dropoff["on_lot_count"] >= dropoff["lot_capacity"]:
        raise err("ERR_RETURN_LOT_FULL", "Drop-off lot is full.")

    # Commit.
    c["return_odometer_miles"] = return_odo
    c["return_fuel_eighths"] = return_fuel
    c["actual_return_at"] = body["actual_return_at"]
    c["miles_driven"] = return_odo - c["pickup_odometer_miles"]

    eq = db.equipment.get(c["equipment_id"])
    if eq is not None:
        eq["status"] = "AVAILABLE"
        eq["current_location_id"] = res["dropoff_location_id"]
        eq["odometer_miles"] = return_odo
        eq["fuel_level_eighths"] = return_fuel
        db.touch(eq)
        domain.recompute_on_lot_count(res["dropoff_location_id"])

    # Branch clean vs damaged.
    if domain.damage_reports_for(rid):
        c["status"] = "RETURNED_DAMAGED"
    else:
        c["status"] = "RETURNED_CLEAN"
    db.touch(c)
    return success(public(c))


# ============================ damage reports ============================
@bp.route("/rental/contracts/<rid>/damage-reports", methods=["POST"])
def file_damage(rid):
    _, role = authenticate()
    require_role(role, {"LocationAgent"})
    c = lookup.require_contract(rid)
    body = V.get_json()
    V.require_fields(body, ["assessed_cost_cents", "description"])
    assessed = V.require_int(body, "assessed_cost_cents", minimum=1)
    description = V.require_str(body, "description")

    # State (priority 9): only while ACTIVE.
    if c["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Damage may only be filed on an ACTIVE contract.")

    row = db.make_common(db.damage_reports, versioned=False)
    row.update({
        "contract_id": rid,
        "assessed_cost_cents": assessed,
        "description": description,
    })
    db.damage_reports.put(row)
    return success(public(row), status=201)


@bp.route("/rental/contracts/<rid>/damage-reports", methods=["GET"])
def list_damage(rid):
    user_id, role = authenticate()
    require_role(role, ALL_ROLES)
    c = lookup.require_contract(rid)
    _ownership_check(role, user_id, c)
    limit, offset = V.parse_pagination()
    rows = domain.damage_reports_for(rid)
    page, total = V.paginate(rows, limit, offset)
    return list_success(public_list(page), limit, offset, total)


# ============================ settle ============================
@bp.route("/rental/contracts/<rid>/settle", methods=["POST"])
def settle_contract(rid):
    _, role = authenticate()
    require_role(role, {"LocationAgent"})
    c = lookup.require_contract(rid)
    body = V.get_json()
    V.require_fields(body, ["expected_contract_version"])
    expected_version = V.require_int(body, "expected_contract_version")

    # State (priority 9).
    if c["status"] not in ("RETURNED_CLEAN", "RETURNED_DAMAGED"):
        raise err("ERR_INVALID_STATE", "Contract must be returned before settlement.")

    # OCC (priority 20) — last gate.
    if expected_version != c["version"]:
        raise err("ERR_STALE_VERSION", "Contract version is stale.")

    res = db.reservations.get(c["reservation_id"])
    klass = db.equipment_classes.get(res["equipment_class_id"])
    customer = db.customers.get(res["customer_id"])
    coverage_plan = None
    if res.get("coverage_plan_id"):
        coverage_plan = db.coverage_plans.get(res["coverage_plan_id"])
    addon_rows = domain.addons_for(res["id"])
    supply_rows = domain.supply_lines_for(res["id"])
    # Snapshot returnable flag onto each supply line for the calculation.
    for s in supply_rows:
        supply = db.supplies.get(s["supply_id"])
        s["_returnable"] = bool(supply and supply["returnable"])
    damage_rows = domain.damage_reports_for(rid)

    result = calc.contract_settlement(c, res, klass, customer, coverage_plan,
                                      addon_rows, supply_rows, damage_rows)

    # Apply refunded_units to the returnable supply lines (cascade).
    refund_map = dict(result["refund_assignments"])
    for s in supply_rows:
        units = refund_map.get(s["id"], 0)
        if units:
            s["refunded_units"] = units
            db.touch(s)

    # Emit ledger lines (cascade).
    for kind, amount in result["components"]:
        entry = db.make_common(db.ledger, versioned=False)
        entry.update({
            "contract_id": rid,
            "kind": kind,
            "amount_cents": amount,
        })
        db.ledger.put(entry)

    c["settlement_total_cents"] = result["settlement_total_cents"]
    c["damage_charge_cents"] = result["damage_charge_cents"]
    c["status"] = "SETTLED"
    db.touch(c)

    # Bubble-up: reservation fulfillment DISPATCHED -> COMPLETED.
    if res["fulfillment_status"] == "DISPATCHED":
        res["fulfillment_status"] = "COMPLETED"
        db.touch(res)

    return success(public(c))


# ============================ void ============================
@bp.route("/rental/contracts/<rid>/void", methods=["POST"])
def void_contract(rid):
    _, role = authenticate()
    require_role(role, {"FleetManager"})
    c = lookup.require_contract(rid)

    if c["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Only an ACTIVE contract may be voided.")

    res = db.reservations.get(c["reservation_id"])
    eq = db.equipment.get(c["equipment_id"])
    if eq is not None:
        eq["status"] = "AVAILABLE"
        eq["current_location_id"] = res["pickup_location_id"]
        db.touch(eq)
        domain.recompute_on_lot_count(res["pickup_location_id"])

    res["fulfillment_status"] = "AWAITING_DISPATCH"
    res["assigned_equipment_id"] = None
    db.touch(res)

    c["status"] = "VOID"
    db.touch(c)
    return success(public(c))


# ============================ ledger ============================
@bp.route("/rental/contracts/<rid>/ledger", methods=["GET"])
def list_ledger(rid):
    user_id, role = authenticate()
    require_role(role, ALL_ROLES)
    c = lookup.require_contract(rid)
    _ownership_check(role, user_id, c)
    limit, offset = V.parse_pagination()
    rows = [e for e in db.ledger.all() if e["contract_id"] == rid]
    page, total = V.paginate(rows, limit, offset)
    return list_success(public_list(page), limit, offset, total)
