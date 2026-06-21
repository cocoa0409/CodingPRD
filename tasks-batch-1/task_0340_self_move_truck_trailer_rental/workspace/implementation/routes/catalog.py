"""Catalog/configuration endpoints: locations, equipment classes, coverage
plans, supplies, customers."""
from flask import Blueprint, request

import db
import lookup
import validate as V
from errors import err
from middleware import authenticate, require_role
from response import success, list_success
from serialize import public, public_list
from services import domain

bp = Blueprint("catalog", __name__)

ALL_ROLES = {"FleetManager", "LocationAgent", "Customer"}


# ============================ RentalLocation ============================
@bp.route("/rental/locations", methods=["POST"])
def create_location():
    _, role = authenticate()
    require_role(role, {"FleetManager"})
    body = V.get_json()
    V.require_fields(body, ["name", "state_code", "lot_capacity"])
    name = V.require_str(body, "name")
    if not (1 <= len(name) <= 120):
        raise err("ERR_INVALID_REQUEST", "name must be 1..120 chars.")
    state_code = V.require_str(body, "state_code")
    if not V.STATE_RE.match(state_code):
        raise err("ERR_INVALID_REQUEST", "state_code must be exactly 2 uppercase letters.")
    lot_capacity = V.require_int(body, "lot_capacity", minimum=1)
    accepts = V.optional_bool(body, "accepts_one_way_dropoff", True)
    status = V.optional_enum(body, "status", {"OPEN", "CLOSED"}, "OPEN")

    row = db.make_common(db.locations)
    row.update({
        "name": name,
        "state_code": state_code,
        "lot_capacity": lot_capacity,
        "on_lot_count": 0,
        "accepts_one_way_dropoff": accepts,
        "status": status,
    })
    db.locations.put(row)
    return success(public(row), status=201)


@bp.route("/rental/locations/<rid>", methods=["GET"])
def get_location(rid):
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    row = lookup.require_location(rid)
    return success(public(row))


@bp.route("/rental/locations", methods=["GET"])
def list_locations():
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    limit, offset = V.parse_pagination()
    rows = db.locations.all()
    if request.args.get("state_code"):
        rows = [r for r in rows if r["state_code"] == request.args["state_code"]]
    if request.args.get("status"):
        rows = [r for r in rows if r["status"] == request.args["status"]]
    page, total = V.paginate(rows, limit, offset)
    return list_success(public_list(page), limit, offset, total)


@bp.route("/rental/locations/<rid>/availability", methods=["GET"])
def location_availability(rid):
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    loc = lookup.require_location(rid)
    class_filter = request.args.get("equipment_class_id")
    if class_filter:
        lookup.require_class(class_filter)
        class_ids = [class_filter]
    else:
        class_ids = [c["id"] for c in db.equipment_classes.all()]
    classes = {}
    for cid in class_ids:
        classes[cid] = {
            "available_count": domain.available_count(rid, cid),
            "reserved_count": domain.reserved_count(rid, cid),
            "lot_occupancy_count": domain.lot_occupancy_count(rid, cid),
        }
    data = {
        "location_id": rid,
        "on_lot_count": loc["on_lot_count"],
        "lot_capacity": loc["lot_capacity"],
        "classes": classes,
    }
    return success(data)


# ============================ EquipmentClass ============================
@bp.route("/rental/equipment-classes", methods=["POST"])
def create_class():
    _, role = authenticate()
    require_role(role, {"FleetManager"})
    body = V.get_json()
    V.require_fields(body, ["code", "category", "daily_rate_cents",
                            "mileage_rate_cents", "one_way_flat_cents",
                            "fuel_capacity_gallons"])
    code = V.require_str(body, "code")
    if not V.CLASS_CODE_RE.match(code):
        raise err("ERR_INVALID_REQUEST", "code must be uppercase alnum+underscore, 1..32.")
    category = V.require_enum(body, "category", {"TRUCK", "TRAILER", "TOW"})
    daily_rate = V.require_int(body, "daily_rate_cents", minimum=0)
    mileage_rate = V.require_int(body, "mileage_rate_cents", minimum=0)
    one_way_flat = V.require_int(body, "one_way_flat_cents", minimum=0)
    fuel_cap = V.require_number(body, "fuel_capacity_gallons", minimum=0)
    requires_coverage = V.optional_bool(body, "requires_coverage", False)

    for c in db.equipment_classes.items.values():
        if c["code"] == code:
            raise err("ERR_INVALID_REQUEST", "EquipmentClass code must be unique.")

    row = db.make_common(db.equipment_classes)
    row.update({
        "code": code,
        "category": category,
        "daily_rate_cents": daily_rate,
        "mileage_rate_cents": mileage_rate,
        "one_way_flat_cents": one_way_flat,
        "fuel_capacity_gallons": fuel_cap,
        "requires_coverage": requires_coverage,
    })
    db.equipment_classes.put(row)
    return success(public(row), status=201)


@bp.route("/rental/equipment-classes/<rid>", methods=["GET"])
def get_class(rid):
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    return success(public(lookup.require_class(rid)))


@bp.route("/rental/equipment-classes", methods=["GET"])
def list_classes():
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    limit, offset = V.parse_pagination()
    rows = db.equipment_classes.all()
    if request.args.get("category"):
        rows = [r for r in rows if r["category"] == request.args["category"]]
    page, total = V.paginate(rows, limit, offset)
    return list_success(public_list(page), limit, offset, total)


# ============================ CoveragePlan ============================
@bp.route("/rental/coverage-plans", methods=["POST"])
def create_coverage():
    _, role = authenticate()
    require_role(role, {"FleetManager"})
    body = V.get_json()
    V.require_fields(body, ["code", "daily_fee_cents", "damage_deductible_cents"])
    code = V.require_str(body, "code")
    if not V.UPPER_CODE_RE.match(code):
        raise err("ERR_INVALID_REQUEST", "code must be uppercase, 1..32.")
    daily_fee = V.require_int(body, "daily_fee_cents", minimum=0)
    deductible = V.require_int(body, "damage_deductible_cents", minimum=0)
    active = V.optional_bool(body, "active", True)

    for c in db.coverage_plans.items.values():
        if c["code"] == code:
            raise err("ERR_INVALID_REQUEST", "CoveragePlan code must be unique.")

    row = db.make_common(db.coverage_plans)
    row.update({
        "code": code,
        "daily_fee_cents": daily_fee,
        "damage_deductible_cents": deductible,
        "active": active,
    })
    db.coverage_plans.put(row)
    return success(public(row), status=201)


@bp.route("/rental/coverage-plans", methods=["GET"])
def list_coverage():
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    limit, offset = V.parse_pagination()
    rows = db.coverage_plans.all()
    if request.args.get("active") is not None and request.args.get("active") != "":
        want = request.args.get("active").lower() == "true"
        rows = [r for r in rows if r["active"] == want]
    page, total = V.paginate(rows, limit, offset)
    return list_success(public_list(page), limit, offset, total)


# ============================ MovingSupply ============================
@bp.route("/rental/supplies", methods=["POST"])
def create_supply():
    _, role = authenticate()
    require_role(role, {"FleetManager"})
    body = V.get_json()
    V.require_fields(body, ["sku", "unit_price_cents", "stock_qty"])
    sku = V.require_str(body, "sku")
    if not (1 <= len(sku) <= 32):
        raise err("ERR_INVALID_REQUEST", "sku must be 1..32 chars.")
    unit_price = V.require_int(body, "unit_price_cents", minimum=0)
    stock = V.require_int(body, "stock_qty", minimum=0)
    returnable = V.optional_bool(body, "returnable", False)

    for s in db.supplies.items.values():
        if s["sku"] == sku:
            raise err("ERR_INVALID_REQUEST", "MovingSupply sku must be unique.")

    row = db.make_common(db.supplies)
    row.update({
        "sku": sku,
        "unit_price_cents": unit_price,
        "stock_qty": stock,
        "returnable": returnable,
    })
    db.supplies.put(row)
    return success(public(row), status=201)


@bp.route("/rental/supplies/<rid>", methods=["GET"])
def get_supply(rid):
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    return success(public(lookup.require_supply(rid)))


@bp.route("/rental/supplies", methods=["GET"])
def list_supplies():
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    limit, offset = V.parse_pagination()
    rows = db.supplies.all()
    if request.args.get("returnable") is not None and request.args.get("returnable") != "":
        want = request.args.get("returnable").lower() == "true"
        rows = [r for r in rows if r["returnable"] == want]
    page, total = V.paginate(rows, limit, offset)
    return list_success(public_list(page), limit, offset, total)


@bp.route("/rental/supplies/<rid>/line-items", methods=["GET"])
def list_supply_line_items(rid):
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    lookup.require_supply(rid)
    limit, offset = V.parse_pagination()
    rows = [s for s in db.supply_lines.all() if s["supply_id"] == rid]
    page, total = V.paginate(rows, limit, offset)
    return list_success(public_list(page), limit, offset, total)


# ============================ Customer ============================
@bp.route("/rental/customers", methods=["POST"])
def create_customer():
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    body = V.get_json()
    V.require_fields(body, ["email", "full_name"])
    email = V.require_str(body, "email")
    if not V.EMAIL_RE.match(email):
        raise err("ERR_INVALID_REQUEST", "email must be a valid email.")
    full_name = V.require_str(body, "full_name")
    license_verified = V.optional_bool(body, "license_verified", False)
    loyalty = V.optional_enum(body, "loyalty_tier",
                              {"STANDARD", "SILVER", "GOLD"}, "STANDARD")

    for c in db.customers.items.values():
        if c["email"] == email:
            raise err("ERR_INVALID_REQUEST", "email must be unique.")

    row = db.make_common(db.customers)
    row.update({
        "email": email,
        "full_name": full_name,
        "license_verified": license_verified,
        "loyalty_tier": loyalty,
    })
    db.customers.put(row)
    return success(public(row), status=201)


@bp.route("/rental/customers/<rid>", methods=["GET"])
def get_customer(rid):
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    return success(public(lookup.require_customer(rid)))


@bp.route("/rental/customers/<rid>/verify-license", methods=["POST"])
def verify_license(rid):
    _, role = authenticate()
    require_role(role, {"FleetManager", "LocationAgent"})
    cust = lookup.require_customer(rid)
    cust["license_verified"] = True
    db.touch(cust)
    return success(public(cust))
