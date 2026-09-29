"""Into-plane fuelling orders and uplift tickets."""
from datetime import timedelta

from flask import Blueprint, request

import calc
import services as svc
from authz import (auth, body, enum, opt_num, out_of_range, req_dt, req_int,
                   req_num, req_str, resolve, resolve_ref, rng)
from core import (ApiError, D, base_row, created, db, f2, fmt_dt, listing, now,
                  now_iso, ok, parse_dt, public, touch)
from routes.commercial import own_account

bp = Blueprint("orders", __name__)

DELIVERY_MODES = ("HYDRANT", "TRUCK")
ABORT_REASONS = ("SPILL", "QUALITY_HOLD", "AIRCRAFT_RELEASE", "EQUIPMENT_FAILURE")


def order_view(order):
    svc.recompute_order_posted(order)
    return public(order)


def order_parts(order):
    tank = db.tanks.get(order["storage_tank_id"])
    farm = db.farms.get(tank["fuel_farm_id"]) if tank else None
    authz = db.authorizations.get(order["fuel_authorization_id"])
    flight = db.flights.get(order["flight_id"])
    account = db.accounts.get(flight["airline_account_id"]) if flight else None
    asset = db.assets.get(order.get("fueling_asset_id"))
    return tank, farm, authz, flight, account, asset


def tank_quality_guard(tank):
    if tank is None:
        return
    if tank["quality_status"] != "RELEASED":
        raise ApiError("ERR_TANK_QUARANTINED",
                       "Source tank quality_status is %s, not RELEASED" % tank["quality_status"])


# ------------------------------------------------------------------ creation
@bp.post("/fueling-orders")
def create_order():
    uid, role = auth("IntoPlaneAgent", "AirlineRep")
    data = body()

    flight_raw = data.get("flight_id")
    if role == "AirlineRep" and isinstance(flight_raw, str):
        f = db.flights.get(flight_raw)
        if f is not None:
            own_account(uid, role, f["airline_account_id"])

    flight = resolve_ref(db.flights, flight_raw, "Flight not found") \
        if isinstance(flight_raw, str) else None
    authz = resolve_ref(db.authorizations, data.get("fuel_authorization_id"),
                        "Fuel authorization not found") \
        if isinstance(data.get("fuel_authorization_id"), str) else None
    tank = resolve_ref(db.tanks, data.get("storage_tank_id"), "Storage tank not found") \
        if isinstance(data.get("storage_tank_id"), str) else None

    if flight is not None and authz is not None and authz["flight_id"] != flight["id"]:
        raise ApiError("ERR_CROSS_FARM_REFERENCE",
                       "The quoted authorization was not issued for this flight")

    flight_id = req_str(data, "flight_id")
    authz_id = req_str(data, "fuel_authorization_id")
    tank_id = req_str(data, "storage_tank_id")
    mode = req_str(data, "delivery_mode")
    requested = req_num(data, "requested_uplift_liters")
    win_start = req_dt(data, "window_start_utc")
    win_end = req_dt(data, "window_end_utc")
    quoted = req_str(data, "quoted_authorization_code")

    enum(mode, "delivery_mode", DELIVERY_MODES)
    rng(requested, "requested_uplift_liters", minimum=0, exclusive_min=True)
    if win_end <= win_start:
        out_of_range("window_end_utc must be later than window_start_utc")

    farm = db.farms.get(tank["fuel_farm_id"]) if tank else None
    svc.frozen_guard(farm)

    if quoted != authz["authorization_code"]:
        raise ApiError("ERR_AUTH_CODE_MISMATCH",
                       "The quoted authorization code does not match")

    if mode == "HYDRANT" and not farm["hydrant_system_available"]:
        raise ApiError("ERR_DELIVERY_MODE_MISMATCH",
                       "This farm cannot serve HYDRANT deliveries")
    if mode == "TRUCK" and data.get("hydrant_pit_id") is not None:
        raise ApiError("ERR_DELIVERY_MODE_MISMATCH",
                       "A TRUCK delivery may not name a hydrant pit")

    order = base_row()
    order.update({
        "flight_id": flight_id,
        "fuel_authorization_id": authz_id,
        "storage_tank_id": tank_id,
        "delivery_mode": mode,
        "requested_uplift_liters": f2(requested),
        "window_start_utc": fmt_dt(win_start),
        "window_end_utc": fmt_dt(win_end),
        "quoted_authorization_code": quoted,
        "fueling_asset_id": None,
        "hydrant_pit_id": None,
        "reserved_amount_cents": 0,
        "posted_net_liters": 0.0,
        "unassign_count": 0,
        "abort_reason": None,
        "status": "REQUESTED",
    })
    db.orders[order["id"]] = order
    return created(public(order))


@bp.get("/fueling-orders")
def list_orders():
    uid, role = auth("ConsortiumAdmin", "FarmOperator", "IntoPlaneAgent", "AirlineRep",
                     "BillingClerk")
    rows = list(db.orders.values())
    for o in rows:
        svc.recompute_order_posted(o)
    if role == "AirlineRep":
        rows = [o for o in rows if calc.order_account_id(o) == uid]
    for field in ("flight_id", "fuel_authorization_id", "storage_tank_id",
                  "fueling_asset_id", "hydrant_pit_id", "status"):
        val = request.args.get(field)
        if val:
            rows = [o for o in rows if o.get(field) == val]
    return listing(rows)


@bp.get("/fueling-orders/<oid>")
def get_order(oid):
    uid, role = auth("ConsortiumAdmin", "FarmOperator", "IntoPlaneAgent", "AirlineRep",
                     "BillingClerk")
    order = resolve(db.orders, oid, "Fueling order not found")
    if role == "AirlineRep":
        own_account(uid, role, calc.order_account_id(order))
    return ok(order_view(order))


# ------------------------------------------------------------------ authorize
@bp.post("/fueling-orders/<oid>/authorize")
def authorize_order(oid):
    auth("IntoPlaneAgent")
    order = resolve(db.orders, oid, "Fueling order not found")
    body()
    tank, farm, authz, flight, account, _asset = order_parts(order)

    svc.terminal_guard("order", order["status"])
    if order["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_ORDER_STATE",
                       "Order status %s cannot be authorized" % order["status"])

    svc.posture_and_permit_guard(farm)
    tank_quality_guard(tank)
    if tank["service_status"] != "IN_SERVICE":
        raise ApiError("ERR_TANK_QUARANTINED",
                       "Source tank service_status is %s, not IN_SERVICE" % tank["service_status"])

    svc.expire_authorization(authz)
    if order["quoted_authorization_code"] != authz["authorization_code"]:
        raise ApiError("ERR_AUTH_CODE_MISMATCH",
                       "The quoted authorization code does not match")
    if authz["status"] != "ISSUED" or now() >= parse_dt(authz["expires_at_utc"]):
        raise ApiError("ERR_AUTHORIZATION_NOT_REDEEMABLE",
                       "The quoted authorization is not redeemable")

    calc.recompute_tank(tank)
    requested = D(order["requested_uplift_liters"])
    if D(tank["available_volume_liters"]) < requested:
        raise ApiError("ERR_INSUFFICIENT_TANK_VOLUME",
                       "Source tank does not have enough available volume")

    reserved = calc.reservation_amount(account, requested)
    if account["status"] != "ACTIVE":
        raise ApiError("ERR_CREDIT_LIMIT_EXCEEDED",
                       "Airline account status is %s" % account["status"])
    order["reserved_amount_cents"] = int(reserved)
    order["status"] = "AUTHORIZED"
    calc.recompute_exposure(account)
    if int(account["accrual_exposure_cents"]) > int(account["credit_limit_cents"]):
        order["status"] = "REQUESTED"
        order["reserved_amount_cents"] = 0
        calc.recompute_exposure(account)
        raise ApiError("ERR_CREDIT_LIMIT_EXCEEDED",
                       "Accrual exposure would exceed the account credit limit")

    touch(order)
    calc.recompute_tank(tank)
    touch(tank)
    touch(account)
    svc.refresh_farm(farm)
    return ok(order_view(order))


# ------------------------------------------------------------------ assign
@bp.post("/fueling-orders/<oid>/assign")
def assign_order(oid):
    auth("IntoPlaneAgent")
    order = resolve(db.orders, oid, "Fueling order not found")
    data = body()
    tank, farm, authz, flight, account, _a = order_parts(order)

    asset = resolve_ref(db.assets, data.get("fueling_asset_id"), "Fueling asset not found") \
        if isinstance(data.get("fueling_asset_id"), str) else None
    pit = resolve_ref(db.pits, data.get("hydrant_pit_id"), "Hydrant pit not found") \
        if isinstance(data.get("hydrant_pit_id"), str) else None
    if pit is not None and tank is not None and pit["fuel_farm_id"] != tank["fuel_farm_id"]:
        raise ApiError("ERR_CROSS_FARM_REFERENCE",
                       "The hydrant pit and the storage tank belong to different farms")
    if asset is not None and tank is not None and asset["fuel_farm_id"] != tank["fuel_farm_id"]:
        raise ApiError("ERR_CROSS_FARM_REFERENCE",
                       "The fueling asset and the storage tank belong to different farms")

    asset_id = req_str(data, "fueling_asset_id")

    svc.terminal_guard("order", order["status"])
    if order["status"] != "AUTHORIZED":
        raise ApiError("ERR_INVALID_ORDER_STATE",
                       "Order status %s cannot be assigned" % order["status"])

    svc.frozen_guard(farm)
    # A RESTRICTED posture blocks assignment only for orders drawing on a
    # QUARANTINED tank; orders on clean tanks proceed normally (PRD 2.7).
    if tank is not None and tank["quality_status"] == "QUARANTINED":
        raise ApiError("ERR_TANK_QUARANTINED",
                       "The source tank is QUARANTINED, so no asset may be assigned")
    calc.recompute_asset(asset)
    if asset["status"] != "IN_SERVICE":
        raise ApiError("ERR_ASSET_NOT_SERVICEABLE",
                       "Asset status is %s, not IN_SERVICE" % asset["status"])

    mode = order["delivery_mode"]
    requested = D(order["requested_uplift_liters"])
    if mode == "TRUCK":
        if asset["asset_type"] != "TRUCK":
            raise ApiError("ERR_DELIVERY_MODE_MISMATCH",
                           "A TRUCK delivery requires a TRUCK asset")
        if pit is not None or data.get("hydrant_pit_id") is not None:
            raise ApiError("ERR_DELIVERY_MODE_MISMATCH",
                           "A TRUCK delivery may not name a hydrant pit")
    else:
        if asset["asset_type"] != "HYDRANT_CART":
            raise ApiError("ERR_DELIVERY_MODE_MISMATCH",
                           "A HYDRANT delivery requires a HYDRANT_CART asset")
        if pit is None:
            raise ApiError("ERR_DELIVERY_MODE_MISMATCH",
                           "A HYDRANT delivery requires a hydrant_pit_id")
        if pit["stand_code"] != (flight["stand_code"] if flight else None):
            raise ApiError("ERR_DELIVERY_MODE_MISMATCH",
                           "The hydrant pit does not serve the flight's stand")

    win_start = parse_dt(order["window_start_utc"])
    win_end = parse_dt(order["window_end_utc"])
    if mode == "HYDRANT":
        if pit["status"] != "AVAILABLE":
            raise ApiError("ERR_PIT_WINDOW_CONFLICT",
                           "Hydrant pit status is %s" % pit["status"])
        for other in svc.pit_occupied_windows(pit["id"], exclude_order_id=order["id"]):
            os_ = parse_dt(other["window_start_utc"])
            oe = parse_dt(other["window_end_utc"])
            if win_start < oe and os_ < win_end:
                raise ApiError("ERR_PIT_WINDOW_CONFLICT",
                               "The booked window overlaps another order on this pit")

    buffer_minutes = int(asset["turnaround_buffer_minutes"])
    my_end = win_end + timedelta(minutes=buffer_minutes)
    for other in db.orders.values():
        if other["id"] == order["id"] or other.get("fueling_asset_id") != asset["id"]:
            continue
        if other["status"] not in ("ASSIGNED", "FUELING"):
            continue
        other_asset = db.assets.get(other["fueling_asset_id"])
        ob = int(other_asset["turnaround_buffer_minutes"]) if other_asset else 0
        os_ = parse_dt(other["window_start_utc"])
        oe = parse_dt(other["window_end_utc"]) + timedelta(minutes=ob)
        if win_start <= oe and os_ <= my_end:
            raise ApiError("ERR_ASSET_WINDOW_CONFLICT",
                           "The booked window overlaps another order on this asset")

    if mode == "TRUCK":
        calc.recompute_asset(asset)
        calc.recompute_tank(tank)
        if (D(asset["onboard_volume_liters"]) < requested
                and D(tank["available_volume_liters"]) < requested):
            raise ApiError("ERR_INSUFFICIENT_TANK_VOLUME",
                           "Neither the truck nor its source tank can supply the volume")

    order["fueling_asset_id"] = asset["id"]
    order["hydrant_pit_id"] = pit["id"] if mode == "HYDRANT" else None
    order["status"] = "ASSIGNED"
    touch(order)
    touch(asset)
    if mode == "HYDRANT":
        touch(pit)
    svc.refresh_farm(farm)
    return ok(order_view(order))


@bp.post("/fueling-orders/<oid>/unassign")
def unassign(oid):
    auth("IntoPlaneAgent")
    order = resolve(db.orders, oid, "Fueling order not found")
    body()
    svc.terminal_guard("order", order["status"])
    if order["status"] != "ASSIGNED":
        raise ApiError("ERR_INVALID_ORDER_STATE",
                       "Order status %s cannot be unassigned" % order["status"])
    svc.unassign_order(order)
    return ok(order_view(order))


# ------------------------------------------------------------------ start
@bp.post("/fueling-orders/<oid>/start")
def start_fueling(oid):
    auth("IntoPlaneAgent")
    order = resolve(db.orders, oid, "Fueling order not found")
    body()
    tank, farm, authz, flight, account, asset = order_parts(order)

    svc.terminal_guard("order", order["status"])
    if order["status"] != "ASSIGNED":
        raise ApiError("ERR_INVALID_ORDER_STATE",
                       "Order status %s cannot start fuelling" % order["status"])

    svc.frozen_guard(farm)
    tank_quality_guard(tank)
    calc.recompute_asset(asset)
    if asset["status"] != "IN_SERVICE":
        raise ApiError("ERR_ASSET_NOT_SERVICEABLE",
                       "Asset status is %s, not IN_SERVICE" % asset["status"])
    if D(asset["element_life_pct"]) >= D("100.0"):
        raise ApiError("ERR_ASSET_NOT_SERVICEABLE",
                       "Asset element_life_pct has reached 100.0")
    if flight is not None and flight["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_ORDER_STATE",
                       "Flight status is %s, not SCHEDULED" % flight["status"])

    clock = now()
    if not (parse_dt(order["window_start_utc"]) <= clock < parse_dt(order["window_end_utc"])):
        raise ApiError("ERR_OUTSIDE_FUELING_WINDOW",
                       "The logical clock is outside the booked fuelling window")

    order["status"] = "FUELING"
    touch(order)
    svc.refresh_farm(farm)
    return ok(order_view(order))


# ------------------------------------------------------------------ uplifts
@bp.post("/fueling-orders/<oid>/uplift-records")
def post_uplift(oid):
    auth("IntoPlaneAgent")
    order = resolve(db.orders, oid, "Fueling order not found")
    data = body()
    tank, farm, authz, flight, account, asset = order_parts(order)

    ticket = req_str(data, "ticket_number")
    meter_start = req_num(data, "meter_start_liters")
    meter_end = req_num(data, "meter_end_liters")
    temperature = req_num(data, "temperature_c")
    expected = req_int(data, "expected_fueling_order_version")

    rng(meter_start, "meter_start_liters", minimum=0)
    if D(meter_end) <= D(meter_start):
        out_of_range("meter_end_liters must exceed meter_start_liters")
    rng(temperature, "temperature_c", minimum=-20, maximum=60)

    for u in db.uplifts.values():
        if u["ticket_number"] == ticket:
            raise ApiError("ERR_DUPLICATE_KEY", "ticket_number %s already exists" % ticket)

    if int(expected) != int(order["version"]):
        raise ApiError("ERR_STALE_ORDER_VERSION",
                       "expected_fueling_order_version %s does not match %s"
                       % (expected, order["version"]))
    svc.terminal_guard("order", order["status"])
    if order["status"] != "FUELING":
        raise ApiError("ERR_INVALID_ORDER_STATE",
                       "Order status %s cannot accept an uplift ticket" % order["status"])

    permit = svc.posture_and_permit_guard(farm)
    tank_quality_guard(tank)
    calc.recompute_asset(asset)
    if asset is not None and asset["status"] != "IN_SERVICE":
        raise ApiError("ERR_ASSET_NOT_SERVICEABLE",
                       "Asset status is %s, not IN_SERVICE" % asset["status"])

    clock = now()
    if not (parse_dt(order["window_start_utc"]) <= clock < parse_dt(order["window_end_utc"])):
        raise ApiError("ERR_OUTSIDE_FUELING_WINDOW",
                       "The logical clock is outside the booked fuelling window")

    gross = calc.q2(D(meter_end) - D(meter_start))
    vcf = calc.vcf_for(tank["density_kg_per_m3"], temperature)
    net = calc.q2(gross * vcf)

    used = calc.permit_day_throughput(farm["id"])
    if used + net > D(permit["max_daily_throughput_liters"]):
        raise ApiError("ERR_PERMIT_THROUGHPUT_EXCEEDED",
                       "Posting would exceed the permitted daily throughput")
    calc.recompute_tank(tank)
    unpumpable = D(farm["unpumpable_bottom_liters"])
    if D(tank["book_volume_liters"]) - unpumpable < net:
        raise ApiError("ERR_INSUFFICIENT_TANK_VOLUME",
                       "Source tank does not hold enough pumpable volume")
    svc.recompute_order_posted(order)
    if D(order["posted_net_liters"]) + net > calc.q2(
            D(authz["max_authorized_liters"]) * D("1.05")):
        raise ApiError("ERR_UPLIFT_EXCEEDS_AUTHORIZATION",
                       "Posting would exceed 105 percent of the authorized volume")

    uplift = base_row()
    uplift.update({
        "fueling_order_id": order["id"],
        "storage_tank_id": order["storage_tank_id"],
        "ticket_number": ticket,
        "meter_start_liters": f2(meter_start),
        "meter_end_liters": f2(meter_end),
        "temperature_c": float(D(temperature)),
        "gross_liters": f2(gross),
        "net_liters": f2(net),
        "volume_tier_diff_cents_per_liter": 0.0,
        "fuel_component_cents": 0,
        "billed_line_cents": 0,
        "status": "POSTED",
        "voided_reason": None,
        "invoice_id": None,
        "_filter_epoch": asset.get("_filter_epoch", 0) if asset else 0,
    })
    db.uplifts[uplift["id"]] = uplift
    calc.price_uplift(uplift, account)

    svc.recompute_order_posted(order)
    touch(order)
    calc.recompute_tank(tank)
    if asset is not None:
        asset["liters_since_filter_change"] = float(
            calc.q2(D(asset["liters_since_filter_change"]) + net))
        calc.recompute_asset(asset)
    calc.recompute_exposure(account)
    svc.apply_posture_change(farm)
    return created(public(uplift))


@bp.get("/uplift-records")
def list_uplifts():
    uid, role = auth("ConsortiumAdmin", "FarmOperator", "IntoPlaneAgent", "AirlineRep",
                     "BillingClerk")
    rows = list(db.uplifts.values())
    if role == "AirlineRep":
        rows = [u for u in rows
                if calc.order_account_id(db.orders.get(u["fueling_order_id"])) == uid]
    for field in ("fueling_order_id", "storage_tank_id", "invoice_id", "status"):
        val = request.args.get(field)
        if val:
            rows = [u for u in rows if u.get(field) == val]
    return listing(rows)


@bp.get("/uplift-records/<uid_>")
def get_uplift(uid_):
    uid, role = auth("ConsortiumAdmin", "FarmOperator", "IntoPlaneAgent", "AirlineRep",
                     "BillingClerk")
    uplift = resolve(db.uplifts, uid_, "Uplift record not found")
    if role == "AirlineRep":
        own_account(uid, role,
                    calc.order_account_id(db.orders.get(uplift["fueling_order_id"])))
    return ok(public(uplift))


# ------------------------------------------------------------------ closures
@bp.post("/fueling-orders/<oid>/complete")
def complete_order(oid):
    auth("IntoPlaneAgent")
    order = resolve(db.orders, oid, "Fueling order not found")
    body()
    tank, farm, authz, flight, account, asset = order_parts(order)

    svc.terminal_guard("order", order["status"])
    if order["status"] != "FUELING":
        raise ApiError("ERR_INVALID_ORDER_STATE",
                       "Order status %s cannot be completed" % order["status"])

    posted = [u for u in calc.order_uplifts(order["id"]) if u["status"] == "POSTED"]
    if not posted:
        raise ApiError("ERR_NO_UPLIFT_RECORDED",
                       "The order has no POSTED uplift ticket")
    svc.recompute_order_posted(order)
    if D(order["posted_net_liters"]) > D(authz["max_authorized_liters"]):
        raise ApiError("ERR_UPLIFT_EXCEEDS_AUTHORIZATION",
                       "Posted volume exceeds the authorized volume")

    order["status"] = "COMPLETED"
    svc.end_pit_occupancy(order)
    touch(order)
    svc.expire_authorization(authz)
    if authz["status"] == "ISSUED":
        authz["status"] = "REDEEMED"
    touch(authz)
    if tank is not None:
        calc.recompute_tank(tank)
        touch(tank)
    if asset is not None:
        calc.recompute_asset(asset)
        if asset["status"] == "IN_SERVICE" and D(asset["element_life_pct"]) >= D("100.0"):
            asset["status"] = "FILTER_DUE"
        touch(asset)
    if account is not None:
        calc.recompute_exposure(account)
        touch(account)
    svc.refresh_farm(farm)
    return ok(order_view(order))


@bp.post("/fueling-orders/<oid>/abort")
def abort(oid):
    auth("IntoPlaneAgent")
    order = resolve(db.orders, oid, "Fueling order not found")
    data = body()
    reason = req_str(data, "abort_reason")
    enum(reason, "abort_reason", ABORT_REASONS)

    svc.terminal_guard("order", order["status"])
    if order["status"] != "FUELING":
        raise ApiError("ERR_INVALID_ORDER_STATE",
                       "Order status %s cannot be aborted" % order["status"])
    svc.abort_order(order, reason, "ORDER_CANCELLED")
    return ok(order_view(order))


@bp.post("/fueling-orders/<oid>/cancel")
def cancel(oid):
    uid, role = auth("AirlineRep", "IntoPlaneAgent")
    order = resolve(db.orders, oid, "Fueling order not found")
    if role == "AirlineRep":
        own_account(uid, role, calc.order_account_id(order))
    body()
    svc.terminal_guard("order", order["status"])
    if order["status"] not in ("REQUESTED", "AUTHORIZED", "ASSIGNED"):
        raise ApiError("ERR_INVALID_ORDER_STATE",
                       "Order status %s cannot be cancelled" % order["status"])
    svc.cancel_order(order, "ORDER_CANCELLED")
    return ok(order_view(order))
