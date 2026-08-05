from datetime import timedelta

from flask import Blueprint, request

import store
from store import DB
from core import (ApiError, get_auth, require_role, get_body, require_fields,
                  check_enum, as_number, as_bool, parse_dt, ok, ok_list,
                  paginate, sorted_records, base_record, touch, deny,
                  select_fuel_price, money_mul, g1)
from serializers import ser_order, ser_addon
from domain import (get_customer, get_membership, get_fleet_account, get_vehicle,
                    get_route, get_order, NON_TERMINAL_ORDER,
                    compute_service_fee, membership_discount, recompute_estimate,
                    commit_budget, release_commit, release_reservation)
from routes.vehicles import suspend_vehicle_effects

bp = Blueprint("orders", __name__)

BUFFER = timedelta(minutes=store.SERVICE_BUFFER_MINUTES)


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------
@bp.post("/orders")
def create_order():
    uid, role = get_auth()
    require_role(role, {"Member", "FleetManager"})
    body = get_body()
    require_fields(body, ["customer_id", "vehicle_id", "zone", "delivery_address",
                          "requested_gallons", "delivery_window_start", "delivery_window_end"])
    check_enum(body["zone"], store.ZONES, "zone")
    as_number(body["requested_gallons"], "requested_gallons", gt=0)
    ws = parse_dt(body["delivery_window_start"])
    we = parse_dt(body["delivery_window_end"])
    is_priority = False
    if "is_priority" in body and body["is_priority"] is not None:
        is_priority = as_bool(body["is_priority"], "is_priority")
    membership_id = body.get("membership_id")
    fleet_account_id = body.get("fleet_account_id")
    requested = body["requested_gallons"]

    # ownership (header vs body identity)
    if body["customer_id"] != uid:
        deny()

    # existence (left-to-right)
    get_customer(body["customer_id"])
    vehicle = get_vehicle(body["vehicle_id"])
    membership = get_membership(membership_id) if membership_id is not None else None
    fleet = get_fleet_account(fleet_account_id) if fleet_account_id is not None else None

    # state validity
    if vehicle["status"] != "ACTIVE":
        raise ApiError("ERR_VEHICLE_SUSPENDED", "Vehicle is suspended")
    if membership is not None and membership["status"] != "ACTIVE":
        raise ApiError("ERR_MEMBERSHIP_NOT_ACTIVE", "Membership is not ACTIVE")
    if fleet is not None and fleet["status"] != "ACTIVE":
        raise ApiError("ERR_FLEET_ACCOUNT_SUSPENDED", "Fleet account is not ACTIVE")

    fuel_type = vehicle["fuel_type"]

    # referential
    if fleet is not None and fuel_type not in fleet["allowed_fuel_types"]:
        raise ApiError("ERR_FUEL_TYPE_NOT_ALLOWED", "Fuel type not allowed for fleet")
    price = select_fuel_price(fuel_type, body["zone"])
    if price is None:
        raise ApiError("ERR_NO_FUEL_PRICE_AVAILABLE", "No fuel price available")

    # safety: tank headroom
    headroom = vehicle["tank_capacity_gallons"] - vehicle["current_fuel_level_gallons"]
    if requested > headroom + 1e-9:
        raise ApiError("ERR_EXCEEDS_TANK_CAPACITY", "Requested gallons exceed tank headroom")

    # temporal: vehicle window conflict
    for o in DB.orders.values():
        if o["vehicle_id"] == body["vehicle_id"] and o["status"] in NON_TERMINAL_ORDER:
            if _window_conflict(ws, we, o["delivery_window_start"], o["delivery_window_end"]):
                raise ApiError("ERR_VEHICLE_WINDOW_CONFLICT", "Delivery window conflict")

    # build order and compute provisional figures
    rec = base_record()
    rec.update({
        "customer_id": body["customer_id"],
        "vehicle_id": body["vehicle_id"],
        "membership_id": membership_id,
        "fleet_account_id": fleet_account_id,
        "route_id": None,
        "fuel_type": fuel_type,
        "zone": body["zone"],
        "delivery_address": body["delivery_address"],
        "requested_gallons": requested,
        "is_priority": is_priority,
        "delivery_window_start": ws,
        "delivery_window_end": we,
        "dispensed_gallons": None,
        "locked_price_per_gallon_cents": price,
        "estimated_fuel_cost_cents": money_mul(requested, price),
        "final_fuel_cost_cents": None,
        "service_fee_cents": 0,
        "addon_total_cents": 0,
        "membership_discount_cents": 0,
        "estimated_total_cents": 0,
        "total_cost_cents": None,
        "payment_status": "UNCHARGED",
        "status": "SCHEDULED",
        "_compartment_id": None,
    })
    rec["service_fee_cents"] = compute_service_fee(rec, membership)
    estimated_total = recompute_estimate(rec, membership)

    # fiscal gate (evaluated on would-be committed amounts)
    if vehicle["monthly_spend_cap_cents"] > 0:
        projected = vehicle["settled_spend_cents"] + vehicle["committed_spend_cents"] + estimated_total
        if projected > vehicle["monthly_spend_cap_cents"]:
            raise ApiError("ERR_VEHICLE_BUDGET_EXCEEDED", "Vehicle budget exceeded")
    if fleet is not None:
        projected = fleet["settled_budget_cents"] + fleet["committed_budget_cents"] + estimated_total
        if projected > fleet["monthly_budget_cap_cents"]:
            raise ApiError("ERR_FLEET_BUDGET_EXCEEDED", "Fleet budget exceeded")

    DB.orders[rec["id"]] = rec
    commit_budget(rec, estimated_total)
    return ok(ser_order(rec), status=201)


def _window_conflict(s1, e1, s2, e2):
    # overlap or gap < SERVICE_BUFFER_MINUTES => conflict
    if s1 < e2 and s2 < e1:
        return True  # overlap
    if e1 <= s2:
        gap = s2 - e1
    else:  # e2 <= s1
        gap = s1 - e2
    return gap < BUFFER


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------
@bp.get("/orders")
def list_orders():
    uid, role = get_auth()
    require_role(role, {"Member", "FleetManager", "Dispatcher", "Driver",
                        "BillingOfficer", "PlatformAdmin"})
    items = sorted_records(DB.orders)
    if role in ("Member", "FleetManager"):
        items = [o for o in items if o["customer_id"] == uid]
    for key in ("customer_id", "vehicle_id", "membership_id", "fleet_account_id", "route_id", "status"):
        val = request.args.get(key)
        if val:
            items = [o for o in items if o[key] == val]
    page, total, limit, offset = paginate(items)
    return ok_list([ser_order(o) for o in page], total, limit, offset)


@bp.get("/orders/<oid>")
def get_order_ep(oid):
    uid, role = get_auth()
    require_role(role, {"Member", "FleetManager", "Dispatcher", "Driver",
                        "BillingOfficer", "PlatformAdmin"})
    o = get_order(oid)
    if role in ("Member", "FleetManager") and o["customer_id"] != uid:
        deny()
    return ok(ser_order(o))


# ---------------------------------------------------------------------------
# Dispatch-side: assign to a route
# ---------------------------------------------------------------------------
@bp.post("/orders/<oid>/assign-route")
def assign_route(oid):
    uid, role = get_auth()
    require_role(role, {"Dispatcher"})
    o = get_order(oid)
    body = get_body()
    require_fields(body, ["route_id"])
    route = get_route(body["route_id"])
    if o["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_ORDER_STATE", "Order not SCHEDULED")
    if route["status"] != "PLANNING":
        raise ApiError("ERR_INVALID_ROUTE_STATE", "Route not PLANNING")
    if route["zone"] != o["zone"]:
        raise ApiError("ERR_ROUTE_ZONE_MISMATCH", "Route zone does not match order zone")
    if route["stop_count"] >= route["max_stops"]:
        raise ApiError("ERR_ROUTE_AT_CAPACITY", "Route at capacity")
    comp = _find_compartment(route["truck_id"], o["fuel_type"], o["requested_gallons"])
    if comp is None:
        raise ApiError("ERR_INSUFFICIENT_COMPARTMENT_FUEL", "Insufficient compartment fuel")

    o["status"] = "ROUTED"
    o["route_id"] = route["id"]
    o["_compartment_id"] = comp["id"]
    route["stop_count"] += 1
    touch(route)
    comp["gallons_reserved"] = g1(comp["gallons_reserved"] + o["requested_gallons"])
    touch(comp)
    touch(o)
    return ok(ser_order(o))


def _find_compartment(truck_id, fuel_type, requested):
    matches = [c for c in sorted_records(DB.compartments)
               if c["truck_id"] == truck_id and c["fuel_type"] == fuel_type]
    for c in matches:
        available = c["gallons_onboard"] - c["gallons_reserved"]
        if available + 1e-9 >= requested:
            return c
    return None


# ---------------------------------------------------------------------------
# Driver-side: arrive / deliver / report-unable-access
# ---------------------------------------------------------------------------
def _driver_owns(o, uid):
    route = DB.routes.get(o["route_id"]) if o["route_id"] else None
    if route is None or route["assigned_driver_id"] != uid:
        deny()


@bp.post("/orders/<oid>/arrive")
def arrive(oid):
    uid, role = get_auth()
    require_role(role, {"Driver"})
    o = get_order(oid)
    _driver_owns(o, uid)
    if o["status"] != "EN_ROUTE":
        raise ApiError("ERR_INVALID_ORDER_STATE", "Order not EN_ROUTE")
    o["status"] = "ARRIVED"
    touch(o)
    return ok(ser_order(o))


@bp.post("/orders/<oid>/deliver")
def deliver(oid):
    uid, role = get_auth()
    require_role(role, {"Driver"})
    o = get_order(oid)
    _driver_owns(o, uid)
    body = get_body()
    require_fields(body, ["dispensed_gallons"])
    as_number(body["dispensed_gallons"], "dispensed_gallons", gt=0)
    dispensed = body["dispensed_gallons"]
    if o["status"] != "ARRIVED":
        raise ApiError("ERR_INVALID_ORDER_STATE", "Order not ARRIVED")
    if dispensed > o["requested_gallons"] + 1e-9:
        raise ApiError("ERR_DISPENSE_EXCEEDS_REQUESTED", "Dispensed exceeds requested")
    vehicle = DB.vehicles[o["vehicle_id"]]
    headroom = vehicle["tank_capacity_gallons"] - vehicle["current_fuel_level_gallons"]
    if dispensed > headroom + 1e-9:
        raise ApiError("ERR_EXCEEDS_TANK_CAPACITY", "Dispensed exceeds tank headroom")

    membership = DB.memberships.get(o["membership_id"]) if o["membership_id"] else None
    # effective price (price-lock aware)
    if membership is not None and membership["price_lock_enabled"]:
        effective_price = o["locked_price_per_gallon_cents"]
    else:
        sel = select_fuel_price(o["fuel_type"], o["zone"])
        effective_price = sel if sel is not None else o["locked_price_per_gallon_cents"]

    estimate = o["estimated_total_cents"]
    final_fuel = money_mul(dispensed, effective_price)
    service_fee = compute_service_fee(o, membership)   # reads used BEFORE increment
    disc_final = membership_discount(dispensed, membership)
    total = final_fuel + service_fee + o["addon_total_cents"] - disc_final
    if total < 0:
        total = 0

    o["dispensed_gallons"] = dispensed
    o["final_fuel_cost_cents"] = final_fuel
    o["service_fee_cents"] = service_fee
    o["membership_discount_cents"] = disc_final
    o["total_cost_cents"] = total
    o["payment_status"] = "CHARGED"
    o["status"] = "DELIVERED"

    # physical side effects
    vehicle["current_fuel_level_gallons"] = g1(vehicle["current_fuel_level_gallons"] + dispensed)
    comp = DB.compartments.get(o.get("_compartment_id"))
    if comp:
        comp["gallons_onboard"] = g1(comp["gallons_onboard"] - dispensed)
        comp["gallons_reserved"] = g1(comp["gallons_reserved"] - o["requested_gallons"])
        touch(comp)
    o["_compartment_id"] = None

    if membership is not None:
        membership["deliveries_used_this_period"] += 1
        touch(membership)

    # budget settlement
    vehicle["committed_spend_cents"] -= estimate
    vehicle["settled_spend_cents"] += total
    if o["fleet_account_id"]:
        f = DB.fleet_accounts[o["fleet_account_id"]]
        f["committed_budget_cents"] -= estimate
        f["settled_budget_cents"] += total
        touch(f)

    # auto-suspend vehicle at cap
    if vehicle["monthly_spend_cap_cents"] > 0 and \
            vehicle["settled_spend_cents"] >= vehicle["monthly_spend_cap_cents"] and \
            vehicle["status"] == "ACTIVE":
        suspend_vehicle_effects(vehicle)
    else:
        touch(vehicle)

    touch(o)
    return ok(ser_order(o))


@bp.post("/orders/<oid>/report-unable-access")
def report_unable_access(oid):
    uid, role = get_auth()
    require_role(role, {"Driver"})
    o = get_order(oid)
    _driver_owns(o, uid)
    if o["status"] != "ARRIVED":
        raise ApiError("ERR_INVALID_ORDER_STATE", "Order not ARRIVED")
    route = DB.routes.get(o["route_id"]) if o["route_id"] else None
    if route:
        route["stop_count"] -= 1
        touch(route)
    release_reservation(o)
    o["route_id"] = None
    o["status"] = "UNABLE_TO_ACCESS"
    touch(o)
    return ok(ser_order(o))


# ---------------------------------------------------------------------------
# Reschedule / cancel
# ---------------------------------------------------------------------------
@bp.post("/orders/<oid>/reschedule")
def reschedule(oid):
    uid, role = get_auth()
    require_role(role, {"Member", "FleetManager"})
    o = get_order(oid)
    if o["customer_id"] != uid:
        deny()
    body = get_body()
    require_fields(body, ["delivery_window_start", "delivery_window_end"])
    ws = parse_dt(body["delivery_window_start"])
    we = parse_dt(body["delivery_window_end"])
    if o["status"] != "UNABLE_TO_ACCESS":
        raise ApiError("ERR_INVALID_ORDER_STATE", "Order not UNABLE_TO_ACCESS")
    price = select_fuel_price(o["fuel_type"], o["zone"])
    if price is None:
        raise ApiError("ERR_NO_FUEL_PRICE_AVAILABLE", "No fuel price available")

    membership = DB.memberships.get(o["membership_id"]) if o["membership_id"] else None
    old_estimate = o["estimated_total_cents"]
    o["delivery_window_start"] = ws
    o["delivery_window_end"] = we
    o["locked_price_per_gallon_cents"] = price
    o["estimated_fuel_cost_cents"] = money_mul(o["requested_gallons"], price)
    new_estimate = recompute_estimate(o, membership)
    delta = new_estimate - old_estimate
    if delta != 0:
        commit_budget(o, delta)
    o["status"] = "SCHEDULED"
    touch(o)
    return ok(ser_order(o))


@bp.post("/orders/<oid>/cancel")
def cancel_order(oid):
    uid, role = get_auth()
    require_role(role, {"Member", "FleetManager", "Dispatcher"})
    o = get_order(oid)
    if role in ("Member", "FleetManager") and o["customer_id"] != uid:
        deny()
    if o["status"] not in ("SCHEDULED", "ROUTED", "UNABLE_TO_ACCESS"):
        raise ApiError("ERR_INVALID_ORDER_STATE", "Order cannot be cancelled from %s" % o["status"])
    cancel_order_effects(o)
    return ok(ser_order(o))


def cancel_order_effects(o):
    """Shared cancel side effects (also used by membership cancellation cascade)."""
    if o["status"] == "ROUTED":
        route = DB.routes.get(o["route_id"]) if o["route_id"] else None
        if route:
            route["stop_count"] -= 1
            touch(route)
        release_reservation(o)
        o["route_id"] = None
    release_commit(o, o["estimated_total_cents"])
    o["status"] = "CANCELLED"
    touch(o)


# ---------------------------------------------------------------------------
# Add-ons
# ---------------------------------------------------------------------------
@bp.post("/orders/<oid>/addons")
def add_addon(oid):
    uid, role = get_auth()
    require_role(role, {"Member", "FleetManager"})
    o = get_order(oid)
    if o["customer_id"] != uid:
        deny()
    body = get_body()
    require_fields(body, ["addon_type"])
    check_enum(body["addon_type"], store.ADDON_TYPES, "addon_type")
    addon_type = body["addon_type"]

    if o["fleet_account_id"]:
        f = DB.fleet_accounts.get(o["fleet_account_id"])
        if f and addon_type not in f["allowed_addons"]:
            raise ApiError("ERR_ADDON_NOT_ALLOWED", "Add-on not allowed for fleet")

    list_price = store.CAR_WASH_PRICE_CENTS if addon_type == "CAR_WASH" else store.OIL_CHANGE_PRICE_CENTS
    if o["membership_id"]:
        from core import round_half_up
        from decimal import Decimal
        charged = round_half_up(Decimal(str(list_price)) * (Decimal("1") - Decimal(store.MEMBER_ADDON_DISCOUNT_PCT)))
    else:
        charged = list_price

    rec = base_record(with_version=False)
    rec.update({
        "order_id": oid,
        "addon_type": addon_type,
        "list_price_cents": list_price,
        "charged_price_cents": charged,
    })
    DB.addons[rec["id"]] = rec

    # recompute addon_total and re-commit estimated_total delta
    o["addon_total_cents"] = sum(a["charged_price_cents"] for a in DB.addons.values()
                                 if a["order_id"] == oid)
    membership = DB.memberships.get(o["membership_id"]) if o["membership_id"] else None
    old_estimate = o["estimated_total_cents"]
    new_estimate = recompute_estimate(o, membership)
    if o["status"] in NON_TERMINAL_ORDER:
        delta = new_estimate - old_estimate
        if delta != 0:
            commit_budget(o, delta)
    touch(o)
    return ok(ser_addon(rec), status=201)


@bp.get("/orders/<oid>/addons")
def list_addons(oid):
    uid, role = get_auth()
    require_role(role, {"Member", "FleetManager", "Dispatcher", "Driver",
                        "BillingOfficer", "PlatformAdmin"})
    o = get_order(oid)
    if role in ("Member", "FleetManager") and o["customer_id"] != uid:
        deny()
    items = [a for a in sorted_records(DB.addons) if a["order_id"] == oid]
    page, total, limit, offset = paginate(items)
    return ok_list([ser_addon(a) for a in page], total, limit, offset)
