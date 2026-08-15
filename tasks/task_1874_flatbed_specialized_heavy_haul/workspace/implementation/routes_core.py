"""Clock, Customer, and Load lifecycle endpoints."""
from flask import Blueprint, request

from store import store, new_entity, bump
from helpers import (
    api_error, ok, ok_list, require_roles, json_body, pub, paginate,
    pagination_params, v_str, v_int, v_bool, v_enum, v_state_list,
    ERR_NOT_FOUND, ERR_NOT_OWN, ERR_INVALID_REQUEST, ERR_CUSTOMER_SUSPENDED,
    ERR_LOAD_INVALID_STATE, ERR_INVALID_STATE, ERR_LOAD_NOT_CANCELLABLE,
    ERR_PERMIT_REQ_UNMET, ERR_REINSTATE_NOT_ALLOWED, ERR_TRAILER_CAPACITY,
    ERR_AXLE_COUNT, ERR_DRIVER_NOT_ENDORSED, ERR_ESCORT_UNMET,
    ERR_OUTSIDE_WINDOW, ERR_CURFEW, ERR_CREDIT,
)
from logic import (
    TRAILER_CATALOG, STATES, compute_flags, required_axles, escort_positions,
    survey_pass, compute_cost_estimate, required_permit_pairs,
    permits_of, escorts_of, cranes_of, readiness_gate, load_cancel_cascade,
)

bp = Blueprint("core", __name__)

ALL_ROLES = ("PlatformAdmin", "Shipper", "Dispatcher", "PermitClerk",
             "StateAuthority", "SafetyManager", "Driver", "BillingClerk")


def load_or_404(load_id):
    load = store.loads.get(load_id)
    if load is None:
        api_error(ERR_NOT_FOUND, 404, "Load not found")
    return load


def check_shipper_owns_load(uid, role, load):
    if role == "Shipper" and load["customer_id"] != uid:
        api_error(ERR_NOT_OWN, 403, "Shipper does not own this resource")


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------

@bp.post("/_clock/set_current_utc")
def set_clock():
    require_roles("PlatformAdmin")
    data = json_body()
    raw = v_str(data, "to_iso8601")
    from helpers import parse_dt
    dt = parse_dt(raw)
    if dt is None:
        api_error(ERR_INVALID_REQUEST, 400,
                  "to_iso8601 must be a valid ISO 8601 datetime")
    store.clock_dt = dt
    store.clock_str = raw
    return ok({"current_utc": raw})


# ---------------------------------------------------------------------------
# Customers
# ---------------------------------------------------------------------------

@bp.post("/heavy-haul/customers")
def create_customer():
    require_roles("PlatformAdmin")
    data = json_body()
    company_name = v_str(data, "company_name")
    credit_limit = v_int(data, "credit_limit_cents", min_value=1)
    if any(c["company_name"] == company_name for c in store.customers.values()):
        api_error(ERR_INVALID_REQUEST, 400, "company_name must be unique")
    cust = new_entity()
    cust.update({
        "company_name": company_name,
        "credit_limit_cents": credit_limit,
        "outstanding_balance_cents": 0,
        "status": "ACTIVE",
    })
    store.customers[cust["id"]] = cust
    return ok(pub(cust), 201)


@bp.get("/heavy-haul/customers/<cid>")
def get_customer(cid):
    uid, role = require_roles("PlatformAdmin", "BillingClerk", "Dispatcher",
                              "SafetyManager", "Shipper")
    cust = store.customers.get(cid)
    if cust is None:
        api_error(ERR_NOT_FOUND, 404, "Customer not found")
    if role == "Shipper" and cid != uid:
        api_error(ERR_NOT_OWN, 403, "Shipper may only read their own customer record")
    return ok(pub(cust))


@bp.post("/heavy-haul/customers/<cid>/reinstate")
def reinstate_customer(cid):
    require_roles("BillingClerk")
    cust = store.customers.get(cid)
    if cust is None:
        api_error(ERR_NOT_FOUND, 404, "Customer not found")
    if cust["status"] != "SUSPENDED":
        api_error(ERR_INVALID_STATE, 409, "Customer is not SUSPENDED")
    if cust["outstanding_balance_cents"] > cust["credit_limit_cents"]:
        api_error(ERR_REINSTATE_NOT_ALLOWED, 409,
                  "Outstanding balance still exceeds the credit limit")
    cust["status"] = "ACTIVE"
    bump(cust)
    return ok(pub(cust))


# ---------------------------------------------------------------------------
# Loads
# ---------------------------------------------------------------------------

@bp.post("/heavy-haul/loads")
def create_load():
    uid, role = require_roles("Shipper")
    cust = store.customers.get(uid)
    if cust is None:
        api_error(ERR_NOT_FOUND, 404, "Shipper customer not found")
    # Customer suspension is checked before any other load-creation rule (PRD 3.2).
    if cust["status"] == "SUSPENDED":
        api_error(ERR_CUSTOMER_SUSPENDED, 409, "Customer is SUSPENDED")
    data = json_body()
    cargo_description = v_str(data, "cargo_description")
    gross = v_int(data, "gross_weight_lbs", min_value=1)
    width = v_int(data, "width_in", min_value=1)
    height = v_int(data, "height_in", min_value=1)
    length = v_int(data, "length_in", min_value=1)
    origin = v_str(data, "origin")
    destination = v_str(data, "destination")
    tarp = v_bool(data, "cargo_requires_tarp", required=False, default=False)
    declared = v_int(data, "declared_value_cents", required=False, min_value=0, default=0)
    is_os, is_ow, is_sl = compute_flags(gross, width, height, length)
    load = new_entity()
    load.update({
        "customer_id": uid,
        "cargo_description": cargo_description,
        "cargo_requires_tarp": tarp,
        "gross_weight_lbs": gross,
        "width_in": width,
        "height_in": height,
        "length_in": length,
        "origin": origin,
        "destination": destination,
        "declared_value_cents": declared,
        "trailer_type": None,
        "trailer_axle_count": None,
        "driver_name": None,
        "driver_oversize_endorsed": None,
        "overall_height_in": None,
        "is_oversize": is_os,
        "is_overweight": is_ow,
        "is_superload": is_sl,
        "required_axles": required_axles(gross),
        "required_escort_positions": None,
        "route_miles": None,
        "states_crossed": None,
        "min_bridge_clearance_in": None,
        "max_bridge_weight_lbs": None,
        "survey_result": None,
        "status": "DRAFT",
        "hold_reason": None,
    })
    store.loads[load["id"]] = load
    return ok(pub(load), 201)


@bp.get("/heavy-haul/loads")
def list_loads():
    uid, role = require_roles(*ALL_ROLES)
    limit, offset = pagination_params()
    records = list(store.loads.values())
    if role == "Shipper":
        records = [l for l in records if l["customer_id"] == uid]
    else:
        customer_id = request.args.get("customer_id")
        if customer_id is not None:
            records = [l for l in records if l["customer_id"] == customer_id]
    status = request.args.get("status")
    if status is not None:
        records = [l for l in records if l["status"] == status]
    page, total = paginate(records, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.get("/heavy-haul/loads/<lid>")
def get_load(lid):
    uid, role = require_roles(*ALL_ROLES)
    load = load_or_404(lid)
    check_shipper_owns_load(uid, role, load)
    return ok(pub(load))


@bp.post("/heavy-haul/loads/<lid>/plan")
def plan_load(lid):
    require_roles("Dispatcher")
    load = load_or_404(lid)
    data = json_body()
    trailer_type = v_enum(data, "trailer_type", TRAILER_CATALOG.keys())
    axles = v_int(data, "trailer_axle_count", min_value=2)
    driver_name = v_str(data, "driver_name")
    endorsed = v_bool(data, "driver_oversize_endorsed")
    if load["status"] not in ("DRAFT", "PLANNED", "SURVEYED"):
        api_error(ERR_LOAD_INVALID_STATE, 409,
                  "Load must be DRAFT, PLANNED, or SURVEYED to plan")
    # Adequacy checks in pinned order: capacity, axles, endorsement.
    cat = TRAILER_CATALOG[trailer_type]
    if cat["max_payload_lbs"] < load["gross_weight_lbs"]:
        api_error(ERR_TRAILER_CAPACITY, 422,
                  "Trailer payload limit is below the gross weight")
    req_axles = required_axles(load["gross_weight_lbs"])
    if axles < req_axles:
        api_error(ERR_AXLE_COUNT, 422,
                  f"trailer_axle_count below required {req_axles}")
    if (load["is_oversize"] or load["is_overweight"]) and not endorsed:
        api_error(ERR_DRIVER_NOT_ENDORSED, 422,
                  "Oversize/overweight load requires an endorsed driver")
    load["trailer_type"] = trailer_type
    load["trailer_axle_count"] = axles
    load["driver_name"] = driver_name
    load["driver_oversize_endorsed"] = endorsed
    load["overall_height_in"] = load["height_in"] + cat["deck_height_in"]
    is_os, is_ow, is_sl = compute_flags(load["gross_weight_lbs"], load["width_in"],
                                        load["height_in"], load["length_in"])
    load["is_oversize"], load["is_overweight"], load["is_superload"] = is_os, is_ow, is_sl
    load["required_axles"] = req_axles
    load["required_escort_positions"] = escort_positions(
        load["width_in"], load["overall_height_in"])
    if load["status"] == "SURVEYED":
        load["survey_result"] = None
    load["status"] = "PLANNED"
    bump(load)
    return ok(pub(load))


@bp.post("/heavy-haul/loads/<lid>/survey")
def survey_load(lid):
    require_roles("Dispatcher")
    load = load_or_404(lid)
    data = json_body()
    route_miles = v_int(data, "route_miles", min_value=1)
    states = v_state_list(data, "states_crossed", STATES)
    clearance = v_int(data, "min_bridge_clearance_in", min_value=1)
    bridge_weight = v_int(data, "max_bridge_weight_lbs", min_value=1)
    if load["status"] not in ("PLANNED", "SURVEYED"):
        api_error(ERR_LOAD_INVALID_STATE, 409,
                  "Load must be PLANNED or SURVEYED to survey")
    passed = survey_pass(load["overall_height_in"], load["gross_weight_lbs"],
                         clearance, bridge_weight)
    load["route_miles"] = route_miles
    load["states_crossed"] = states
    load["min_bridge_clearance_in"] = clearance
    load["max_bridge_weight_lbs"] = bridge_weight
    load["survey_result"] = "PASSED" if passed else "FAILED"
    load["status"] = "SURVEYED" if passed else "PLANNED"
    bump(load)
    return ok(pub(load))


@bp.post("/heavy-haul/loads/<lid>/cancel")
def cancel_load(lid):
    uid, role = require_roles("Shipper", "Dispatcher")
    load = load_or_404(lid)
    check_shipper_owns_load(uid, role, load)
    if load["status"] in ("IN_TRANSIT", "DELIVERED", "CANCELLED"):
        api_error(ERR_LOAD_NOT_CANCELLABLE, 409,
                  "Load cannot be cancelled in its current state")
    load_cancel_cascade(load)
    return ok(pub(load))


@bp.post("/heavy-haul/loads/<lid>/depart")
def depart_load(lid):
    require_roles("Driver")
    load = load_or_404(lid)
    if load["status"] != "CLEARED":
        api_error(ERR_LOAD_INVALID_STATE, 409, "Load must be CLEARED to depart")
    for pos in (load["required_escort_positions"] or []):
        if not any(b["position"] == pos and b["status"] == "CONFIRMED"
                   for b in escorts_of(load["id"])):
            api_error(ERR_ESCORT_UNMET, 409,
                      f"No CONFIRMED escort booking for required position {pos}")
    now = store.clock_dt
    window_ok = True
    for p in permits_of(load["id"]):
        if p["status"] != "GRANTED":
            continue
        if p.get("_twe_dt") is not None and now > p["_twe_dt"]:
            p["status"] = "EXPIRED"
            bump(p)
            window_ok = False
        elif p.get("_tws_dt") is not None and now < p["_tws_dt"]:
            window_ok = False
    if not window_ok:
        api_error(ERR_OUTSIDE_WINDOW, 409,
                  "Logical clock is outside a granted permit's travel window")
    if not (5 <= now.hour < 21):
        api_error(ERR_CURFEW, 409, "Departure curfew: UTC hour must be in [5, 21)")
    estimate = compute_cost_estimate(load)
    cust = store.customers.get(load["customer_id"])
    headroom = cust["credit_limit_cents"] - cust["outstanding_balance_cents"]
    if estimate["total_cents"] > headroom:
        api_error(ERR_CREDIT, 402,
                  "Provisional estimate exceeds remaining credit")
    load["status"] = "IN_TRANSIT"
    bump(load)
    return ok(pub(load))


@bp.post("/heavy-haul/loads/<lid>/arrive")
def arrive_load(lid):
    require_roles("Driver")
    load = load_or_404(lid)
    if load["status"] != "IN_TRANSIT":
        api_error(ERR_LOAD_INVALID_STATE, 409, "Load must be IN_TRANSIT to arrive")
    load["status"] = "DELIVERED"
    bump(load)
    for b in escorts_of(load["id"]):
        if b["status"] == "CONFIRMED":
            b["status"] = "COMPLETED"
            bump(b)
    for c in cranes_of(load["id"]):
        if c["status"] == "SCHEDULED":
            c["status"] = "COMPLETED"
            bump(c)
    return ok(pub(load))


@bp.post("/heavy-haul/loads/<lid>/release-hold")
def release_hold(lid):
    require_roles("SafetyManager")
    load = load_or_404(lid)
    if load["status"] != "ON_HOLD":
        api_error(ERR_LOAD_INVALID_STATE, 409, "Load must be ON_HOLD to release")
    granted = {(p["state_code"], p["permit_type"])
               for p in permits_of(load["id"]) if p["status"] == "GRANTED"}
    for pair in required_permit_pairs(load):
        if pair not in granted:
            api_error(ERR_PERMIT_REQ_UNMET, 409,
                      f"Required permit {pair[1]} for {pair[0]} is not GRANTED")
    load["hold_reason"] = None
    load["status"] = "SURVEYED"
    bump(load)
    readiness_gate(load)
    return ok(pub(load))


@bp.get("/heavy-haul/loads/<lid>/cost-estimate")
def cost_estimate(lid):
    uid, role = require_roles("Dispatcher", "BillingClerk", "Shipper", "PlatformAdmin")
    load = load_or_404(lid)
    check_shipper_owns_load(uid, role, load)
    if load["status"] not in ("SURVEYED", "CLEARED", "ON_HOLD", "IN_TRANSIT", "DELIVERED"):
        api_error(ERR_LOAD_INVALID_STATE, 409,
                  "Cost estimate requires the load to be at least SURVEYED")
    return ok(compute_cost_estimate(load))
