import os
from flask import Flask, jsonify, request

from errors import (
    ApiError, err,
    ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_DUPLICATE_RESOURCE, ERR_VALIDATION_RANGE,
    ERR_INVALID_STATE, ERR_PROPERTY_MISMATCH, ERR_CONTRACT_NOT_ACTIVE,
    ERR_NO_EQUIPMENT_AVAILABLE, ERR_EQUIPMENT_NOT_READY, ERR_READING_ALREADY_PROCESSED,
    ERR_SNOW_THRESHOLD_NOT_MET, ERR_OPEN_DISPATCH_EXISTS, ERR_STALE_VERSION,
    ERR_NO_SKIPPABLE_VISIT,
)
from response import success_object, success_array, error_body
from db import db, new_common, touch
from middleware import get_auth, require_roles
from serialize import serialize
from helpers import get_or_404, ensure_owner, paginate, sorted_by_seq
import validate as V
import calculations as C

app = Flask(__name__)


# =========================================================================
# Error handling
# =========================================================================
@app.errorhandler(ApiError)
def handle_api_error(e):
    return jsonify(error_body(e.error_id, e.message)), e.http_status


@app.errorhandler(404)
def handle_404(e):
    return jsonify(error_body("ERR_NOT_FOUND", "Resource not found")), 404


@app.errorhandler(405)
def handle_405(e):
    return jsonify(error_body("ERR_NOT_FOUND", "Method not allowed")), 404


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return handle_api_error(e)
    return jsonify(error_body("ERR_INVALID_REQUEST", str(e))), 422


def respond_obj(kind, rec, status=200):
    body, code = success_object(serialize(kind, rec), status)
    return jsonify(body), code


def respond_list(kind, records, limit, offset):
    records = sorted_by_seq(records)
    page, total = paginate(records, limit, offset)
    data = [serialize(kind, r) for r in page]
    body, code = success_array(data, limit, offset, total)
    return jsonify(body), code


# =========================================================================
# Customers
# =========================================================================
@app.post("/customers")
def create_customer():
    _, role = get_auth()
    require_roles(role, {"PlatformAdmin"})
    body = V.get_json()
    email = V.req_str(body, "email")
    full_name = V.req_str(body, "full_name")
    service_zip = V.zip5(body, "service_zip")
    for c in db.customers.values():
        if c["email"] == email:
            raise err(ERR_DUPLICATE_RESOURCE, "Email already registered")
    rec = new_common({
        "email": email, "full_name": full_name, "service_zip": service_zip,
        "wallet_credit_cents": 0,
    })
    db.customers[rec["id"]] = rec
    return respond_obj("customer", rec, 201)


@app.get("/customers/<rid>")
def get_customer(rid):
    uid, role = get_auth()
    require_roles(role, {"PlatformAdmin", "Customer", "DispatchManager"})
    rec = get_or_404(db.customers, rid)
    ensure_owner(role, uid, rec["id"])
    return respond_obj("customer", rec)


# =========================================================================
# Properties
# =========================================================================
@app.post("/properties")
def create_property():
    uid, role = get_auth()
    require_roles(role, {"PlatformAdmin", "Customer"})
    body = V.get_json()
    customer_id = V.req_str(body, "customer_id")
    customer = get_or_404(db.customers, customer_id)
    ensure_owner(role, uid, customer_id)
    address = V.req_str(body, "address")
    lawn_area = V.req_int(body, "lawn_area_sqft")
    if lawn_area <= 0:
        raise err(ERR_INVALID_REQUEST, "lawn_area_sqft must be > 0")
    zip_ = V.zip5(body, "zip")
    rec = new_common({
        "customer_id": customer_id, "address": address,
        "lawn_area_sqft": lawn_area, "zip": zip_,
    })
    db.properties[rec["id"]] = rec
    return respond_obj("property", rec, 201)


@app.get("/properties/<rid>")
def get_property(rid):
    uid, role = get_auth()
    require_roles(role, {"PlatformAdmin", "Customer", "DispatchManager"})
    rec = get_or_404(db.properties, rid)
    ensure_owner(role, uid, rec["customer_id"])
    return respond_obj("property", rec)


@app.get("/properties")
def list_properties():
    uid, role = get_auth()
    require_roles(role, {"PlatformAdmin", "Customer", "DispatchManager"})
    limit, offset = V.pagination()
    customer_id = request.args.get("customer_id")
    items = list(db.properties.values())
    if customer_id is not None:
        items = [p for p in items if p["customer_id"] == customer_id]
    if role == "Customer":
        items = [p for p in items if p["customer_id"] == uid]
    return respond_list("property", items, limit, offset)


# =========================================================================
# Preferences
# =========================================================================
@app.post("/preferences")
def create_preference():
    uid, role = get_auth()
    require_roles(role, {"PlatformAdmin", "Customer"})
    body = V.get_json()
    property_id = V.req_str(body, "property_id")
    prop = get_or_404(db.properties, property_id)
    ensure_owner(role, uid, prop["customer_id"])
    grass = V.req_int(body, "grass_height_mm")
    if grass < 20 or grass > 120:
        raise err(ERR_INVALID_REQUEST, "grass_height_mm must be between 20 and 120")
    fert = V.opt_bool(body, "fertilization_enabled", False)
    opt_out = V.opt_bool(body, "snow_opt_out", False)
    rec = new_common({
        "property_id": property_id, "grass_height_mm": grass,
        "fertilization_enabled": fert, "snow_opt_out": opt_out,
    })
    db.preferences[rec["id"]] = rec
    return respond_obj("preference", rec, 201)


@app.get("/preferences/<rid>")
def get_preference(rid):
    uid, role = get_auth()
    require_roles(role, {"PlatformAdmin", "Customer", "DispatchManager"})
    rec = get_or_404(db.preferences, rid)
    prop = db.properties.get(rec["property_id"])
    if role == "Customer" and prop is not None:
        ensure_owner(role, uid, prop["customer_id"])
    return respond_obj("preference", rec)


@app.get("/preferences")
def list_preferences():
    uid, role = get_auth()
    require_roles(role, {"PlatformAdmin", "Customer", "DispatchManager"})
    limit, offset = V.pagination()
    property_id = request.args.get("property_id")
    items = list(db.preferences.values())
    if property_id is not None:
        items = [p for p in items if p["property_id"] == property_id]
    if role == "Customer":
        owned = {p["id"] for p in db.properties.values() if p["customer_id"] == uid}
        items = [p for p in items if p["property_id"] in owned]
    return respond_list("preference", items, limit, offset)


# =========================================================================
# Contracts
# =========================================================================
@app.post("/contracts")
def create_contract():
    uid, role = get_auth()
    require_roles(role, {"PlatformAdmin", "Customer"})
    body = V.get_json()
    customer_id = V.req_str(body, "customer_id")
    customer = get_or_404(db.customers, customer_id)
    ensure_owner(role, uid, customer_id)
    property_id = V.req_str(body, "property_id")
    prop = get_or_404(db.properties, property_id)
    season = V.req_enum(body, "season", {"WINTER", "SUMMER"})
    price = V.req_int(body, "contract_price_cents")
    if price < 0:
        raise err(ERR_INVALID_REQUEST, "contract_price_cents must be >= 0")
    term = V.req_int(body, "term_months")
    if term < 1:
        raise err(ERR_INVALID_REQUEST, "term_months must be >= 1")
    deposit = V.opt_int(body, "prepaid_deposit_cents", 0)
    if deposit < 0:
        raise err(ERR_INVALID_REQUEST, "prepaid_deposit_cents must be >= 0")
    rec = new_common({
        "customer_id": customer_id, "property_id": property_id, "season": season,
        "contract_price_cents": price, "term_months": term,
        "prepaid_deposit_cents": deposit, "status": "DRAFT", "accrued_balance_cents": 0,
    })
    db.contracts[rec["id"]] = rec
    return respond_obj("contract", rec, 201)


@app.get("/contracts/<rid>")
def get_contract(rid):
    uid, role = get_auth()
    require_roles(role, {"PlatformAdmin", "Customer", "DispatchManager"})
    rec = get_or_404(db.contracts, rid)
    ensure_owner(role, uid, rec["customer_id"])
    return respond_obj("contract", rec)


@app.get("/contracts")
def list_contracts():
    uid, role = get_auth()
    require_roles(role, {"PlatformAdmin", "Customer", "DispatchManager"})
    limit, offset = V.pagination()
    customer_id = request.args.get("customer_id")
    property_id = request.args.get("property_id")
    items = list(db.contracts.values())
    if customer_id is not None:
        items = [c for c in items if c["customer_id"] == customer_id]
    if property_id is not None:
        items = [c for c in items if c["property_id"] == property_id]
    if role == "Customer":
        items = [c for c in items if c["customer_id"] == uid]
    return respond_list("contract", items, limit, offset)


@app.post("/contracts/<rid>/activate")
def activate_contract(rid):
    uid, role = get_auth()
    require_roles(role, {"Customer", "PlatformAdmin"})
    contract = get_or_404(db.contracts, rid)
    ensure_owner(role, uid, contract["customer_id"])
    status = contract["status"]
    if status == "DRAFT":
        prop = db.properties.get(contract["property_id"])
        if prop is None:
            raise err(ERR_NOT_FOUND, "Referenced property not found")
        if prop["customer_id"] != contract["customer_id"]:
            raise err(ERR_PROPERTY_MISMATCH, "Property not owned by contract customer")
        contract["status"] = "ACTIVE"
        contract["accrued_balance_cents"] = contract["contract_price_cents"]
        touch(contract)
    elif status == "SUSPENDED":
        contract["status"] = "ACTIVE"
        for stop in db.route_stops.values():
            if stop["property_id"] == contract["property_id"]:
                stop["active"] = True
                touch(stop)
        touch(contract)
    else:
        raise err(ERR_INVALID_STATE, "Contract cannot be activated from %s" % status)
    return respond_obj("contract", contract)


@app.post("/contracts/<rid>/suspend")
def suspend_contract(rid):
    _, role = get_auth()
    require_roles(role, {"DispatchManager", "PlatformAdmin"})
    contract = get_or_404(db.contracts, rid)
    if contract["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "Contract cannot be suspended from %s" % contract["status"])
    contract["status"] = "SUSPENDED"
    for stop in db.route_stops.values():
        if stop["property_id"] == contract["property_id"]:
            stop["active"] = False
            touch(stop)
    touch(contract)
    return respond_obj("contract", contract)


@app.post("/contracts/<rid>/close-season")
def close_season(rid):
    _, role = get_auth()
    require_roles(role, {"DispatchManager", "PlatformAdmin"})
    contract = get_or_404(db.contracts, rid)
    if contract["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "Contract cannot be closed from %s" % contract["status"])
    # no visit on contract in DISPATCHED state
    for v in db.visits.values():
        if v["contract_id"] == rid and v["status"] == "DISPATCHED":
            raise err(ERR_OPEN_DISPATCH_EXISTS, "An open dispatch exists for this contract")
    customer = db.customers.get(contract["customer_id"])
    # finalized chronological replay
    completed = [v for v in db.visits.values()
                 if v["contract_id"] == rid and v["status"] == "COMPLETED"]
    completed = sorted_by_seq(completed)
    approved_skips = []
    for s in db.skip_requests.values():
        if s["status"] != "APPROVED":
            continue
        vis = db.visits.get(s["visit_id"])
        if vis is not None and vis["contract_id"] == rid:
            approved_skips.append(s)
    subtotal, tax, total_due, wallet_applied = C.final_season_invoice(
        contract, completed, approved_skips, customer)
    invoice = new_common({
        "contract_id": rid, "subtotal_cents": subtotal, "tax_cents": tax,
        "total_due_cents": total_due, "status": "ISSUED",
    })
    db.invoices[invoice["id"]] = invoice
    # debit wallet
    if customer is not None and wallet_applied:
        customer["wallet_credit_cents"] -= wallet_applied
        touch(customer)
    contract["status"] = "CLOSED"
    touch(contract)
    return respond_obj("contract", contract)


@app.get("/contracts/<rid>/invoices")
def list_contract_invoices(rid):
    uid, role = get_auth()
    require_roles(role, {"PlatformAdmin", "Customer", "DispatchManager"})
    contract = get_or_404(db.contracts, rid)
    ensure_owner(role, uid, contract["customer_id"])
    limit, offset = V.pagination()
    items = [i for i in db.invoices.values() if i["contract_id"] == rid]
    return respond_list("invoice", items, limit, offset)


@app.get("/contracts/<rid>/visits")
def list_contract_visits(rid):
    uid, role = get_auth()
    require_roles(role, {"PlatformAdmin", "Customer", "DispatchManager", "CrewLead"})
    contract = get_or_404(db.contracts, rid)
    if role == "Customer":
        ensure_owner(role, uid, contract["customer_id"])
    limit, offset = V.pagination()
    items = [v for v in db.visits.values() if v["contract_id"] == rid]
    return respond_list("visit", items, limit, offset)


# =========================================================================
# Routes
# =========================================================================
@app.post("/routes")
def create_route():
    _, role = get_auth()
    require_roles(role, {"PlatformAdmin", "DispatchManager"})
    body = V.get_json()
    region_zip = V.zip5(body, "region_zip")
    cap = V.req_int(body, "daily_capacity_minutes")
    if cap <= 0:
        raise err(ERR_INVALID_REQUEST, "daily_capacity_minutes must be > 0")
    rec = new_common({
        "region_zip": region_zip, "daily_capacity_minutes": cap,
        "status": "OPEN", "last_dispatch_load_minutes": 0,
    })
    db.routes[rec["id"]] = rec
    return respond_obj("route", rec, 201)


@app.get("/routes/<rid>")
def get_route(rid):
    _, role = get_auth()
    require_roles(role, {"PlatformAdmin", "DispatchManager", "CrewLead"})
    rec = get_or_404(db.routes, rid)
    return respond_obj("route", rec)


@app.post("/routes/<rid>/reopen")
def reopen_route(rid):
    _, role = get_auth()
    require_roles(role, {"DispatchManager", "PlatformAdmin"})
    route = get_or_404(db.routes, rid)
    if route["status"] != "DISPATCHED":
        raise err(ERR_INVALID_STATE, "Route cannot be reopened from %s" % route["status"])
    for v in db.visits.values():
        stop = db.route_stops.get(v["route_stop_id"])
        if stop is not None and stop["route_id"] == rid and v["status"] == "DISPATCHED":
            raise err(ERR_INVALID_STATE, "A visit on this route is still DISPATCHED")
    route["status"] = "OPEN"
    touch(route)
    return respond_obj("route", route)


@app.post("/routes/<rid>/close")
def close_route(rid):
    _, role = get_auth()
    require_roles(role, {"DispatchManager", "PlatformAdmin"})
    route = get_or_404(db.routes, rid)
    if route["status"] != "OPEN":
        raise err(ERR_INVALID_STATE, "Route cannot be closed from %s" % route["status"])
    route["status"] = "CLOSED"
    touch(route)
    return respond_obj("route", route)


@app.get("/routes/<rid>/stops")
def list_route_stops(rid):
    _, role = get_auth()
    require_roles(role, {"PlatformAdmin", "DispatchManager", "CrewLead"})
    get_or_404(db.routes, rid)
    limit, offset = V.pagination()
    items = [s for s in db.route_stops.values() if s["route_id"] == rid]
    return respond_list("route_stop", items, limit, offset)


@app.get("/routes/<rid>/crews")
def list_route_crews(rid):
    _, role = get_auth()
    require_roles(role, {"PlatformAdmin", "DispatchManager", "CrewLead"})
    get_or_404(db.routes, rid)
    limit, offset = V.pagination()
    items = [c for c in db.crews.values() if c["home_route_id"] == rid]
    return respond_list("crew", items, limit, offset)


@app.get("/routes/<rid>/equipment")
def list_route_equipment(rid):
    _, role = get_auth()
    require_roles(role, {"PlatformAdmin", "DispatchManager", "CrewLead"})
    get_or_404(db.routes, rid)
    limit, offset = V.pagination()
    items = [e for e in db.equipment.values() if e["assigned_route_id"] == rid]
    return respond_list("equipment", items, limit, offset)


# =========================================================================
# RouteStops
# =========================================================================
@app.post("/route-stops")
def create_route_stop():
    _, role = get_auth()
    require_roles(role, {"PlatformAdmin", "DispatchManager"})
    body = V.get_json()
    route_id = V.req_str(body, "route_id")
    route = get_or_404(db.routes, route_id)
    property_id = V.req_str(body, "property_id")
    prop = get_or_404(db.properties, property_id)
    sequence = V.req_int(body, "sequence")
    if sequence < 1:
        raise err(ERR_INVALID_REQUEST, "sequence must be >= 1")
    base = V.req_int(body, "base_service_minutes")
    if base <= 0:
        raise err(ERR_INVALID_REQUEST, "base_service_minutes must be > 0")
    travel = V.opt_int(body, "travel_minutes", 0)
    if travel < 0:
        raise err(ERR_INVALID_REQUEST, "travel_minutes must be >= 0")
    # referential coherence: property must be owned by same customer as the route's contracts
    contract_customers = {c["customer_id"] for c in db.contracts.values()
                          if c["property_id"] in
                          {st["property_id"] for st in db.route_stops.values()
                           if st["route_id"] == route_id}}
    # property must match a customer that owns a contract on this route, if any exist
    route_contracts = [c for c in db.contracts.values()
                       if any(st["route_id"] == route_id and st["property_id"] == c["property_id"]
                              for st in db.route_stops.values())]
    if route_contracts:
        owners = {c["customer_id"] for c in route_contracts}
        if prop["customer_id"] not in owners:
            raise err(ERR_PROPERTY_MISMATCH, "Property owner inconsistent with route's contracts")
    rec = new_common({
        "route_id": route_id, "property_id": property_id, "sequence": sequence,
        "base_service_minutes": base, "travel_minutes": travel, "active": True,
    })
    db.route_stops[rec["id"]] = rec
    return respond_obj("route_stop", rec, 201)


@app.get("/route-stops/<rid>")
def get_route_stop(rid):
    _, role = get_auth()
    require_roles(role, {"PlatformAdmin", "DispatchManager", "CrewLead"})
    rec = get_or_404(db.route_stops, rid)
    return respond_obj("route_stop", rec)


@app.get("/route-stops")
def list_route_stops_top():
    _, role = get_auth()
    require_roles(role, {"PlatformAdmin", "DispatchManager", "CrewLead"})
    limit, offset = V.pagination()
    property_id = request.args.get("property_id")
    items = list(db.route_stops.values())
    if property_id is not None:
        items = [s for s in items if s["property_id"] == property_id]
    return respond_list("route_stop", items, limit, offset)


# =========================================================================
# Crews
# =========================================================================
@app.post("/crews")
def create_crew():
    _, role = get_auth()
    require_roles(role, {"PlatformAdmin", "DispatchManager"})
    body = V.get_json()
    name = V.req_str(body, "name")
    home_route_id = V.req_str(body, "home_route_id")
    get_or_404(db.routes, home_route_id)
    rec = new_common({
        "name": name, "home_route_id": home_route_id, "status": "AVAILABLE",
    })
    db.crews[rec["id"]] = rec
    return respond_obj("crew", rec, 201)


@app.get("/crews/<rid>")
def get_crew(rid):
    _, role = get_auth()
    require_roles(role, {"PlatformAdmin", "DispatchManager", "CrewLead"})
    rec = get_or_404(db.crews, rid)
    return respond_obj("crew", rec)


# =========================================================================
# Equipment
# =========================================================================
@app.post("/equipment")
def create_equipment():
    _, role = get_auth()
    require_roles(role, {"PlatformAdmin", "DispatchManager"})
    body = V.get_json()
    asset_tag = V.req_str(body, "asset_tag")
    equipment_type = V.req_enum(body, "equipment_type", {"PLOW", "MOWER", "SPREADER"})
    age = V.req_int(body, "age_months")
    if age < 0:
        raise err(ERR_INVALID_REQUEST, "age_months must be >= 0")
    assigned_route_id = body.get("assigned_route_id")
    if assigned_route_id is not None:
        if not isinstance(assigned_route_id, str):
            raise err(ERR_INVALID_REQUEST, "assigned_route_id must be a string")
        get_or_404(db.routes, assigned_route_id)
    for e in db.equipment.values():
        if e["asset_tag"] == asset_tag:
            raise err(ERR_DUPLICATE_RESOURCE, "asset_tag already exists")
    rec = new_common({
        "asset_tag": asset_tag, "equipment_type": equipment_type,
        "assigned_route_id": assigned_route_id,
        "cumulative_runtime_hours": 0, "runtime_at_last_service_hours": 0,
        "dispatch_count_since_service": 0, "age_months": age,
        "wear_score": 0, "status": "IDLE",
    })
    db.equipment[rec["id"]] = rec
    return respond_obj("equipment", rec, 201)


@app.get("/equipment/<rid>")
def get_equipment(rid):
    _, role = get_auth()
    require_roles(role, {"PlatformAdmin", "DispatchManager", "CrewLead"})
    rec = get_or_404(db.equipment, rid)
    return respond_obj("equipment", rec)


@app.get("/equipment")
def list_equipment():
    _, role = get_auth()
    require_roles(role, {"PlatformAdmin", "DispatchManager", "CrewLead"})
    limit, offset = V.pagination()
    assigned_route_id = request.args.get("assigned_route_id")
    items = list(db.equipment.values())
    if assigned_route_id is not None:
        items = [e for e in items if e["assigned_route_id"] == assigned_route_id]
    return respond_list("equipment", items, limit, offset)


@app.post("/equipment/<rid>/rotate")
def rotate_equipment(rid):
    _, role = get_auth()
    require_roles(role, {"DispatchManager", "PlatformAdmin"})
    equip = get_or_404(db.equipment, rid)
    body = V.get_json()
    assigned_route_id = V.req_str(body, "assigned_route_id")
    expected_version = V.req_int(body, "expected_equipment_version")
    route = get_or_404(db.routes, assigned_route_id)
    if expected_version != equip["version"]:
        raise err(ERR_STALE_VERSION, "expected_equipment_version does not match current version")
    equip["assigned_route_id"] = assigned_route_id
    equip["wear_score"] = C.equipment_wear_score(equip)
    touch(equip)
    return respond_obj("equipment", equip)


@app.post("/equipment/<rid>/start-maintenance")
def start_maintenance(rid):
    _, role = get_auth()
    require_roles(role, {"DispatchManager", "PlatformAdmin"})
    equip = get_or_404(db.equipment, rid)
    if equip["status"] != "MAINTENANCE_DUE":
        raise err(ERR_INVALID_STATE, "Cannot start maintenance from %s" % equip["status"])
    equip["status"] = "UNDER_MAINTENANCE"
    touch(equip)
    return respond_obj("equipment", equip)


@app.post("/equipment/<rid>/complete-maintenance")
def complete_maintenance(rid):
    _, role = get_auth()
    require_roles(role, {"DispatchManager", "PlatformAdmin"})
    equip = get_or_404(db.equipment, rid)
    if equip["status"] != "UNDER_MAINTENANCE":
        raise err(ERR_INVALID_STATE, "Cannot complete maintenance from %s" % equip["status"])
    equip["runtime_at_last_service_hours"] = equip["cumulative_runtime_hours"]
    equip["dispatch_count_since_service"] = 0
    equip["wear_score"] = C.equipment_wear_score(equip)
    equip["status"] = "IDLE"
    touch(equip)
    return respond_obj("equipment", equip)


@app.get("/equipment/<rid>/wear-estimate")
def wear_estimate(rid):
    _, role = get_auth()
    require_roles(role, {"PlatformAdmin", "DispatchManager", "CrewLead"})
    equip = get_or_404(db.equipment, rid)
    # find in-flight DISPATCHED visit using this equipment
    in_flight = None
    for v in sorted_by_seq(list(db.visits.values())):
        if v["equipment_id"] == rid and v["status"] == "DISPATCHED":
            in_flight = v
            break
    projected_runtime = in_flight["runtime_hours"] if in_flight is not None else 0
    estimated = C.estimated_wear_score(equip, projected_runtime)
    actual = equip["wear_score"]
    body, code = success_object({
        "equipment_id": rid,
        "estimated_wear_score": estimated,
        "actual_wear_score": actual,
    })
    return jsonify(body), code


# =========================================================================
# Weather Readings
# =========================================================================
@app.post("/weather-readings")
def create_weather_reading():
    _, role = get_auth()
    require_roles(role, {"PlatformAdmin", "DispatchManager"})
    body = V.get_json()
    region_zip = V.zip5(body, "region_zip")
    snow_depth = V.req_number(body, "snow_depth_in")
    if snow_depth < 0:
        raise err(ERR_VALIDATION_RANGE, "snow_depth_in must be >= 0")
    observed_at = V.req_str(body, "observed_at")
    rec = new_common({
        "region_zip": region_zip, "snow_depth_in": snow_depth,
        "observed_at": observed_at, "processed": False,
    })
    db.weather_readings[rec["id"]] = rec
    return respond_obj("weather_reading", rec, 201)


@app.get("/weather-readings/<rid>")
def get_weather_reading(rid):
    _, role = get_auth()
    require_roles(role, {"PlatformAdmin", "DispatchManager"})
    rec = get_or_404(db.weather_readings, rid)
    return respond_obj("weather_reading", rec)


def _select_equipment(route_id):
    """Lowest wear_score among IDLE/IN_SERVICE on the route; tie-break created_at ASC."""
    candidates = [e for e in db.equipment.values()
                  if e["assigned_route_id"] == route_id
                  and e["status"] in ("IDLE", "IN_SERVICE")]
    if not candidates:
        return None
    candidates.sort(key=lambda e: (e["wear_score"], e["_seq"]))
    return candidates[0]


def _pref_for_property(property_id):
    prefs = [p for p in db.preferences.values() if p["property_id"] == property_id]
    prefs = sorted_by_seq(prefs)
    return prefs[-1] if prefs else None


@app.post("/weather-readings/<rid>/process")
def process_weather_reading(rid):
    _, role = get_auth()
    require_roles(role, {"DispatchManager", "PlatformAdmin"})
    reading = get_or_404(db.weather_readings, rid)
    body = V.get_json()
    route_id = V.req_str(body, "route_id")
    route = get_or_404(db.routes, route_id)
    # already processed
    if reading["processed"]:
        raise err(ERR_READING_ALREADY_PROCESSED, "Reading already processed")
    # threshold
    if not (reading["snow_depth_in"] > 2.0):
        raise err(ERR_SNOW_THRESHOLD_NOT_MET, "snow_depth_in must exceed 2.0")
    # route must be OPEN
    if route["status"] != "OPEN":
        raise err(ERR_INVALID_STATE, "Route is not OPEN")
    # active stops on route, not snow-opted-out
    stops = [s for s in db.route_stops.values() if s["route_id"] == route_id and s["active"]]
    stops = sorted(stops, key=lambda s: (s["sequence"], s["_seq"]))
    eligible = []
    for s in stops:
        pref = _pref_for_property(s["property_id"])
        if pref is not None and pref["snow_opt_out"]:
            continue
        eligible.append(s)
    # contracts owning these stops' properties must be ACTIVE
    for s in eligible:
        contract = _active_contract_for_property(s["property_id"])
        if contract is None:
            raise err(ERR_CONTRACT_NOT_ACTIVE, "Owning contract is not ACTIVE")
    # equipment availability check (must have a usable asset for fan-out)
    if eligible and _select_equipment(route_id) is None:
        raise err(ERR_NO_EQUIPMENT_AVAILABLE, "No equipment available on route")
    # compute dispatch load over eligible stops
    load = C.route_dispatch_load(
        [(s["base_service_minutes"], s["travel_minutes"]) for s in eligible],
        reading["snow_depth_in"], route["daily_capacity_minutes"])
    route["last_dispatch_load_minutes"] = load
    # fan-out: create SNOW visit per eligible stop, dispatch it
    for s in eligible:
        contract = _active_contract_for_property(s["property_id"])
        equip = _select_equipment(route_id)
        visit = new_common({
            "contract_id": contract["id"], "route_stop_id": s["id"],
            "equipment_id": equip["id"], "service_type": "SNOW",
            "snow_depth_in": reading["snow_depth_in"], "runtime_hours": 0,
            "surcharge_cents": 0, "status": "DISPATCHED",
        })
        db.visits[visit["id"]] = visit
        equip["status"] = "IN_SERVICE"
        touch(equip)
        _set_crew_on_dispatch(route_id)
    reading["processed"] = True
    route["status"] = "DISPATCHED"
    touch(route)
    return respond_obj("route", route)


def _active_contract_for_property(property_id):
    contracts = [c for c in db.contracts.values()
                 if c["property_id"] == property_id and c["status"] == "ACTIVE"]
    contracts = sorted_by_seq(contracts)
    return contracts[0] if contracts else None


def _set_crew_on_dispatch(route_id):
    for c in db.crews.values():
        if c["home_route_id"] == route_id:
            c["status"] = "ON_DISPATCH"
            touch(c)


# =========================================================================
# Visits
# =========================================================================
@app.post("/visits")
def create_visit():
    _, role = get_auth()
    require_roles(role, {"PlatformAdmin", "DispatchManager"})
    body = V.get_json()
    contract_id = V.req_str(body, "contract_id")
    contract = get_or_404(db.contracts, contract_id)
    route_stop_id = V.req_str(body, "route_stop_id")
    stop = get_or_404(db.route_stops, route_stop_id)
    service_type = V.req_enum(body, "service_type", {"LAWN", "SNOW", "FERTILIZATION"})
    snow_depth = V.opt_number(body, "snow_depth_in", 0)
    if snow_depth < 0:
        raise err(ERR_VALIDATION_RANGE, "snow_depth_in must be >= 0")
    runtime = V.opt_number(body, "runtime_hours", 0)
    if runtime < 0:
        raise err(ERR_VALIDATION_RANGE, "runtime_hours must be >= 0")
    # property coherence: contract and route_stop must reference same property
    if contract["property_id"] != stop["property_id"]:
        raise err(ERR_PROPERTY_MISMATCH, "Contract and route stop reference different properties")
    rec = new_common({
        "contract_id": contract_id, "route_stop_id": route_stop_id, "equipment_id": None,
        "service_type": service_type, "snow_depth_in": snow_depth, "runtime_hours": runtime,
        "surcharge_cents": 0, "status": "SCHEDULED",
    })
    db.visits[rec["id"]] = rec
    return respond_obj("visit", rec, 201)


@app.get("/visits/<rid>")
def get_visit(rid):
    uid, role = get_auth()
    require_roles(role, {"PlatformAdmin", "DispatchManager", "CrewLead", "Customer"})
    rec = get_or_404(db.visits, rid)
    if role == "Customer":
        contract = db.contracts.get(rec["contract_id"])
        if contract is not None:
            ensure_owner(role, uid, contract["customer_id"])
    return respond_obj("visit", rec)


@app.get("/visits")
def list_visits():
    _, role = get_auth()
    require_roles(role, {"PlatformAdmin", "DispatchManager", "CrewLead"})
    limit, offset = V.pagination()
    route_stop_id = request.args.get("route_stop_id")
    equipment_id = request.args.get("equipment_id")
    contract_id = request.args.get("contract_id")
    items = list(db.visits.values())
    if route_stop_id is not None:
        items = [v for v in items if v["route_stop_id"] == route_stop_id]
    if equipment_id is not None:
        items = [v for v in items if v["equipment_id"] == equipment_id]
    if contract_id is not None:
        items = [v for v in items if v["contract_id"] == contract_id]
    return respond_list("visit", items, limit, offset)


@app.post("/visits/<rid>/dispatch")
def dispatch_visit(rid):
    _, role = get_auth()
    require_roles(role, {"DispatchManager", "PlatformAdmin"})
    visit = get_or_404(db.visits, rid)
    if visit["status"] != "SCHEDULED":
        raise err(ERR_INVALID_STATE, "Visit cannot be dispatched from %s" % visit["status"])
    stop = db.route_stops.get(visit["route_stop_id"])
    if stop is None:
        raise err(ERR_NOT_FOUND, "Route stop not found")
    contract = db.contracts.get(visit["contract_id"])
    if contract is None or contract["status"] != "ACTIVE":
        raise err(ERR_CONTRACT_NOT_ACTIVE, "Owning contract is not ACTIVE")
    equip = _select_equipment(stop["route_id"])
    if equip is None:
        raise err(ERR_NO_EQUIPMENT_AVAILABLE, "No equipment available on route")
    visit["status"] = "DISPATCHED"
    visit["equipment_id"] = equip["id"]
    touch(visit)
    equip["status"] = "IN_SERVICE"
    touch(equip)
    _set_crew_on_dispatch(stop["route_id"])
    return respond_obj("visit", visit)


@app.post("/visits/<rid>/complete")
def complete_visit(rid):
    _, role = get_auth()
    require_roles(role, {"CrewLead", "PlatformAdmin"})
    visit = get_or_404(db.visits, rid)
    if visit["status"] != "DISPATCHED":
        raise err(ERR_INVALID_STATE, "Visit cannot be completed from %s" % visit["status"])
    equip = db.equipment.get(visit["equipment_id"]) if visit["equipment_id"] else None
    if equip is None or equip["status"] != "IN_SERVICE":
        raise err(ERR_EQUIPMENT_NOT_READY, "Selected equipment is not IN_SERVICE")
    body = V.get_json()
    if "runtime_hours" in body and body["runtime_hours"] is not None:
        rh = V.opt_number(body, "runtime_hours", 0)
        if rh < 0:
            raise err(ERR_VALIDATION_RANGE, "runtime_hours must be >= 0")
        visit["runtime_hours"] = rh
    # surcharge
    stop = db.route_stops.get(visit["route_stop_id"])
    pref = _pref_for_property(stop["property_id"]) if stop is not None else None
    fert_enabled = pref["fertilization_enabled"] if pref is not None else False
    surcharge = C.visit_surcharge(visit, fert_enabled)
    visit["surcharge_cents"] = surcharge
    visit["status"] = "COMPLETED"
    touch(visit)
    # age equipment
    equip["cumulative_runtime_hours"] = equip["cumulative_runtime_hours"] + visit["runtime_hours"]
    equip["dispatch_count_since_service"] = equip["dispatch_count_since_service"] + 1
    equip["wear_score"] = C.equipment_wear_score(equip)
    if equip["wear_score"] >= 100:
        equip["status"] = "MAINTENANCE_DUE"
    else:
        equip["status"] = "IDLE"
    touch(equip)
    # provisional balance
    contract = db.contracts.get(visit["contract_id"])
    if contract is not None:
        contract["accrued_balance_cents"] = contract["accrued_balance_cents"] + surcharge
        touch(contract)
    return respond_obj("visit", visit)


@app.post("/visits/<rid>/cancel")
def cancel_visit(rid):
    _, role = get_auth()
    require_roles(role, {"DispatchManager", "PlatformAdmin"})
    visit = get_or_404(db.visits, rid)
    if visit["status"] != "SCHEDULED":
        raise err(ERR_INVALID_STATE, "Visit cannot be cancelled from %s" % visit["status"])
    visit["status"] = "CANCELLED"
    touch(visit)
    return respond_obj("visit", visit)


# =========================================================================
# Skip Requests
# =========================================================================
@app.post("/skip-requests")
def create_skip_request():
    uid, role = get_auth()
    require_roles(role, {"Customer", "PlatformAdmin"})
    body = V.get_json()
    visit_id = V.req_str(body, "visit_id")
    visit = get_or_404(db.visits, visit_id)
    reason = V.req_str(body, "reason", allow_empty=True)
    if role == "Customer":
        contract = db.contracts.get(visit["contract_id"])
        if contract is not None:
            ensure_owner(role, uid, contract["customer_id"])
    if visit["status"] != "SCHEDULED":
        raise err(ERR_NO_SKIPPABLE_VISIT, "Visit is not in SCHEDULED state")
    rec = new_common({
        "visit_id": visit_id, "reason": reason, "credit_cents": 0, "status": "PENDING",
    })
    db.skip_requests[rec["id"]] = rec
    return respond_obj("skip_request", rec, 201)


@app.get("/skip-requests/<rid>")
def get_skip_request(rid):
    uid, role = get_auth()
    require_roles(role, {"PlatformAdmin", "DispatchManager", "Customer"})
    rec = get_or_404(db.skip_requests, rid)
    if role == "Customer":
        visit = db.visits.get(rec["visit_id"])
        if visit is not None:
            contract = db.contracts.get(visit["contract_id"])
            if contract is not None:
                ensure_owner(role, uid, contract["customer_id"])
    return respond_obj("skip_request", rec)


@app.get("/skip-requests")
def list_skip_requests():
    uid, role = get_auth()
    require_roles(role, {"PlatformAdmin", "DispatchManager", "Customer"})
    limit, offset = V.pagination()
    visit_id = request.args.get("visit_id")
    items = list(db.skip_requests.values())
    if visit_id is not None:
        items = [s for s in items if s["visit_id"] == visit_id]
    if role == "Customer":
        owned = set()
        for s in items:
            visit = db.visits.get(s["visit_id"])
            if visit is None:
                continue
            contract = db.contracts.get(visit["contract_id"])
            if contract is not None and contract["customer_id"] == uid:
                owned.add(s["id"])
        items = [s for s in items if s["id"] in owned]
    return respond_list("skip_request", items, limit, offset)


@app.post("/skip-requests/<rid>/approve")
def approve_skip_request(rid):
    _, role = get_auth()
    require_roles(role, {"DispatchManager", "PlatformAdmin"})
    skip = get_or_404(db.skip_requests, rid)
    if skip["status"] != "PENDING":
        raise err(ERR_INVALID_STATE, "Skip request is not PENDING")
    visit = db.visits.get(skip["visit_id"])
    if visit is None:
        raise err(ERR_NOT_FOUND, "Referenced visit not found")
    if visit["status"] != "SCHEDULED":
        raise err(ERR_INVALID_STATE, "Referenced visit is not SCHEDULED")
    contract = db.contracts.get(visit["contract_id"])
    credit = C.skip_credit(visit, contract)
    visit["status"] = "SKIPPED"
    touch(visit)
    skip["credit_cents"] = credit
    skip["status"] = "APPROVED"
    touch(skip)
    if contract is not None:
        customer = db.customers.get(contract["customer_id"])
        if customer is not None:
            customer["wallet_credit_cents"] = customer["wallet_credit_cents"] + credit
            touch(customer)
        contract["accrued_balance_cents"] = contract["accrued_balance_cents"] - credit
        touch(contract)
    return respond_obj("skip_request", skip)


@app.post("/skip-requests/<rid>/reject")
def reject_skip_request(rid):
    _, role = get_auth()
    require_roles(role, {"DispatchManager", "PlatformAdmin"})
    skip = get_or_404(db.skip_requests, rid)
    if skip["status"] != "PENDING":
        raise err(ERR_INVALID_STATE, "Skip request is not PENDING")
    skip["status"] = "REJECTED"
    touch(skip)
    return respond_obj("skip_request", skip)


# =========================================================================
# Invoices
# =========================================================================
@app.get("/invoices/<rid>")
def get_invoice(rid):
    uid, role = get_auth()
    require_roles(role, {"PlatformAdmin", "Customer", "DispatchManager"})
    rec = get_or_404(db.invoices, rid)
    if role == "Customer":
        contract = db.contracts.get(rec["contract_id"])
        if contract is not None:
            ensure_owner(role, uid, contract["customer_id"])
    return respond_obj("invoice", rec)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
