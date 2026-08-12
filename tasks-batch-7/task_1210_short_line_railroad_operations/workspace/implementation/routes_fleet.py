"""CarOrders (with demurrage) and Railcars (PRD 3.1, 3.2, 3.3)."""

from flask import Blueprint, request

from auth import authenticate, require_role, require_owner
from db import store
from envelope import success_object, success_list
from errors import (ApiError, ERR_INVALID_REQUEST, ERR_STALE_VERSION,
                    ERR_SIDING_AGREEMENT_INACTIVE, ERR_SIDING_CAPACITY_EXCEEDED,
                    ERR_CUSTOMER_CREDIT_SUSPENDED, ERR_QUANTITY_BELOW_FURNISHED,
                    ERR_INSUFFICIENT_AVAILABLE_CARS, ERR_ORDER_NOT_AMENDABLE,
                    ERR_DUPLICATE_REPORTING_MARK, not_found, invalid_state)
from util import (json_body, req_str, opt_str, req_int, req_dt, opt_dt, opt_int,
                  req_enum, paginate)
from domain import (new_record, touch, car_order_view, railcar_view,
                    cars_furnished_count, CAR_TYPES, OWNERSHIPS,
                    DEMURRAGE_PER_CAR_PER_DAY_CENTS)

bp = Blueprint("fleet", __name__)


# ---------------------------------------------------------------------------
# Car orders
# ---------------------------------------------------------------------------

@bp.post("/rail/car-orders")
def create_car_order():
    uid, role = authenticate()
    body = json_body(required=True)
    customer_id = req_str(body, "customer_id")
    siding_id = req_str(body, "siding_id")
    car_type = req_enum(body, "car_type", CAR_TYPES)
    quantity = req_int(body, "quantity")
    if quantity < 1:
        raise ApiError(400, ERR_INVALID_REQUEST, "quantity must be at least 1")
    needed_by = req_dt(body, "needed_by_date")
    require_role(role, ["CustomerRep"])
    # Entity-backed identity: a CustomerRep places orders only for its own customer.
    require_owner(customer_id, uid)
    if customer_id not in store.customers:
        raise not_found("customer not found")
    siding = store.sidings.get(siding_id)
    if siding is None:
        raise not_found("siding not found")
    if siding["customer_id"] != customer_id:
        raise ApiError(400, ERR_INVALID_REQUEST,
                       "siding_id must belong to customer_id")
    rec = new_record({
        "customer_id": customer_id,
        "siding_id": siding_id,
        "car_type": car_type,
        "quantity": quantity,
        "needed_by_date": needed_by,
        "status": "PLACED",
        "furnished_at": None,
        "released_at": None,
    })
    store.car_orders[rec["id"]] = rec
    return success_object(car_order_view(rec), status=201)


@bp.get("/rail/car-orders")
def list_car_orders():
    uid, role = authenticate()
    f_customer = request.args.get("customer_id")
    f_siding = request.args.get("siding_id")
    f_status = request.args.get("status")
    records = list(store.car_orders.values())
    if f_customer is not None:
        records = [o for o in records if o["customer_id"] == f_customer]
    if f_siding is not None:
        records = [o for o in records if o["siding_id"] == f_siding]
    if f_status is not None:
        records = [o for o in records if o["status"] == f_status]
    limit, offset, total, page = paginate(records)
    return success_list([car_order_view(o) for o in page], limit, offset, total)


def _get_order(oid):
    rec = store.car_orders.get(oid)
    if rec is None:
        raise not_found("car order not found")
    return rec


@bp.get("/rail/car-orders/<oid>")
def get_car_order(oid):
    uid, role = authenticate()
    return success_object(car_order_view(_get_order(oid)))


@bp.patch("/rail/car-orders/<oid>")
def patch_car_order(oid):
    uid, role = authenticate()
    body = json_body(required=True)
    # Syntactic band: the OCC guard field is always required.
    expected = req_int(body, "expected_car_order_version")
    quantity = opt_int(body, "quantity")
    needed_by = opt_dt(body, "needed_by_date")
    require_role(role, ["CustomerRep"])
    order = _get_order(oid)
    require_owner(order["customer_id"], uid)
    # State band: amendable only from PLACED / ACCEPTED / PARTIALLY_FURNISHED.
    if order["status"] not in ("PLACED", "ACCEPTED", "PARTIALLY_FURNISHED"):
        raise ApiError(409, ERR_ORDER_NOT_AMENDABLE,
                       "order in status %s cannot be amended" % order["status"])
    # OCC guard (PRD 2.8): stale version rejected before any field is applied.
    if expected != order["version"]:
        raise ApiError(412, ERR_STALE_VERSION,
                       "expected_car_order_version does not match the current version")
    if quantity is not None:
        if quantity < 1:
            raise ApiError(400, ERR_INVALID_REQUEST, "quantity must be at least 1")
        if quantity < cars_furnished_count(oid):
            raise ApiError(422, ERR_QUANTITY_BELOW_FURNISHED,
                           "quantity is below cars already furnished")
        order["quantity"] = quantity
    if needed_by is not None:
        order["needed_by_date"] = needed_by
    touch(order)
    return success_object(car_order_view(order))


@bp.post("/rail/car-orders/<oid>/accept")
def accept_car_order(oid):
    uid, role = authenticate()
    json_body()
    require_role(role, ["Dispatcher"])
    order = _get_order(oid)
    if order["status"] != "PLACED":
        raise invalid_state("only a PLACED order can be accepted")
    # Business gates in pinned order (PRD 3.2): agreement -> capacity -> credit.
    siding = store.sidings.get(order["siding_id"])
    if siding is None or siding["maintenance_agreement_status"] != "ACTIVE":
        raise ApiError(422, ERR_SIDING_AGREEMENT_INACTIVE,
                       "siding maintenance agreement is not ACTIVE")
    if order["quantity"] > siding["capacity_cars"]:
        raise ApiError(422, ERR_SIDING_CAPACITY_EXCEEDED,
                       "order quantity exceeds siding capacity_cars")
    customer = store.customers.get(order["customer_id"])
    if customer is None or customer["credit_status"] != "GOOD":
        raise ApiError(422, ERR_CUSTOMER_CREDIT_SUSPENDED,
                       "customer credit_status is not GOOD")
    order["status"] = "ACCEPTED"
    touch(order)
    return success_object(car_order_view(order))


@bp.post("/rail/car-orders/<oid>/furnish")
def furnish_car_order(oid):
    uid, role = authenticate()
    body = json_body(required=True)
    count = req_int(body, "count")
    if count < 1:
        raise ApiError(400, ERR_INVALID_REQUEST, "count must be at least 1")
    require_role(role, ["Dispatcher"])
    order = _get_order(oid)
    if order["status"] not in ("ACCEPTED", "PARTIALLY_FURNISHED"):
        raise invalid_state("furnish is defined only from ACCEPTED or PARTIALLY_FURNISHED")
    remaining = order["quantity"] - cars_furnished_count(oid)
    if count > remaining:
        raise ApiError(400, ERR_INVALID_REQUEST,
                       "count exceeds the unfilled remainder of the order")
    eligible = [c for c in store.railcars.values()
                if c["status"] == "AVAILABLE" and c["car_type"] == order["car_type"]]
    if len(eligible) < count:
        raise ApiError(409, ERR_INSUFFICIENT_AVAILABLE_CARS,
                       "fewer eligible railcars than the requested count")
    # Roster seniority: earliest created_at first, ties broken by reporting_mark.
    eligible.sort(key=lambda c: (c["created_at"], c["reporting_mark"]))
    selected = eligible[:count]
    first_furnish = order["furnished_at"] is None
    for car in selected:
        car["status"] = "ASSIGNED"
        car["assigned_order_id"] = oid
        touch(car)
    if first_furnish:
        order["furnished_at"] = store.now
    order["status"] = "FURNISHED" if count == remaining else "PARTIALLY_FURNISHED"
    touch(order)
    return success_object(car_order_view(order))


@bp.post("/rail/car-orders/<oid>/release")
def release_car_order(oid):
    uid, role = authenticate()
    json_body()
    require_role(role, ["CustomerRep"])
    order = _get_order(oid)
    require_owner(order["customer_id"], uid)
    if order["status"] not in ("FURNISHED", "PARTIALLY_FURNISHED"):
        raise invalid_state("release is defined only from FURNISHED or PARTIALLY_FURNISHED")
    order["released_at"] = store.now
    for car in store.railcars.values():
        if car["assigned_order_id"] == oid:
            car["status"] = "LOADED"
            car["assigned_order_id"] = None
            touch(car)
    order["status"] = "RELEASED"
    touch(order)
    return success_object(car_order_view(order))


@bp.post("/rail/car-orders/<oid>/cancel")
def cancel_car_order(oid):
    uid, role = authenticate()
    json_body()
    require_role(role, ["CustomerRep"])
    order = _get_order(oid)
    require_owner(order["customer_id"], uid)
    if order["status"] not in ("PLACED", "ACCEPTED", "PARTIALLY_FURNISHED", "FURNISHED"):
        raise invalid_state("order in status %s cannot be cancelled" % order["status"])
    if order["status"] in ("PARTIALLY_FURNISHED", "FURNISHED"):
        for car in store.railcars.values():
            if car["assigned_order_id"] == oid:
                car["status"] = "AVAILABLE"
                car["assigned_order_id"] = None
                touch(car)
    order["status"] = "CANCELLED"
    touch(order)
    return success_object(car_order_view(order))


@bp.get("/rail/car-orders/<oid>/demurrage")
def car_order_demurrage(oid):
    uid, role = authenticate()
    require_role(role, ["CustomerRep", "Dispatcher", "SettlementClerk"])
    order = _get_order(oid)
    if role == "CustomerRep":
        require_owner(order["customer_id"], uid)
    # calculations.demurrage_charge
    if order["status"] in ("FURNISHED", "PARTIALLY_FURNISHED") and order["furnished_at"] is not None:
        days_loading = int((store.now - order["furnished_at"]).total_seconds() // 86400)
    else:
        days_loading = 0
    customer = store.customers.get(order["customer_id"])
    free_days = customer["demurrage_free_days"] if customer else 0
    billable_days = max(0, days_loading - free_days)
    cars_held = cars_furnished_count(oid)
    charge_cents = billable_days * cars_held * DEMURRAGE_PER_CAR_PER_DAY_CENTS
    return success_object({
        "billable_days": billable_days,
        "cars_held": cars_held,
        "free_days": free_days,
        "charge_cents": charge_cents,
    })


# ---------------------------------------------------------------------------
# Railcars
# ---------------------------------------------------------------------------

@bp.post("/rail/railcars")
def create_railcar():
    uid, role = authenticate()
    body = json_body(required=True)
    reporting_mark = req_str(body, "reporting_mark")
    car_type = req_enum(body, "car_type", CAR_TYPES)
    ownership = req_enum(body, "ownership", OWNERSHIPS)
    hour_rate = req_int(body, "hire_rate_per_hour_cents")
    mile_rate = req_int(body, "hire_rate_per_mile_cents")
    home_road_mark = opt_str(body, "home_road_mark")
    location = opt_str(body, "current_location_segment_id")
    require_role(role, ["SystemAdmin"])
    if location is not None and location not in store.track_segments:
        raise not_found("track segment not found")
    if any(c["reporting_mark"] == reporting_mark for c in store.railcars.values()):
        raise ApiError(409, ERR_DUPLICATE_REPORTING_MARK,
                       "reporting_mark already registered")
    rec = new_record({
        "reporting_mark": reporting_mark,
        "car_type": car_type,
        "ownership": ownership,
        "home_road_mark": home_road_mark,
        "status": "AVAILABLE",
        "current_location_segment_id": location,
        "assigned_order_id": None,
        "hire_rate_per_hour_cents": hour_rate,
        "hire_rate_per_mile_cents": mile_rate,
    })
    store.railcars[rec["id"]] = rec
    return success_object(railcar_view(rec), status=201)


@bp.get("/rail/railcars")
def list_railcars():
    uid, role = authenticate()
    records = list(store.railcars.values())
    for param, field in (("ownership", "ownership"), ("status", "status"),
                         ("car_type", "car_type"),
                         ("current_location_segment_id", "current_location_segment_id"),
                         ("assigned_order_id", "assigned_order_id")):
        v = request.args.get(param)
        if v is not None:
            records = [c for c in records if c[field] == v]
    limit, offset, total, page = paginate(records)
    return success_list([railcar_view(c) for c in page], limit, offset, total)


def _get_railcar(rid):
    rec = store.railcars.get(rid)
    if rec is None:
        raise not_found("railcar not found")
    return rec


@bp.get("/rail/railcars/<rid>")
def get_railcar(rid):
    uid, role = authenticate()
    return success_object(railcar_view(_get_railcar(rid)))


@bp.post("/rail/railcars/<rid>/bad-order")
def bad_order_railcar(rid):
    uid, role = authenticate()
    json_body()
    require_role(role, ["Dispatcher"])
    car = _get_railcar(rid)
    if car["status"] not in ("AVAILABLE", "ASSIGNED"):
        raise invalid_state("bad-order is defined only from AVAILABLE or ASSIGNED")
    if car["status"] == "ASSIGNED":
        # Withdrawn from its order; cars_furnished_count recomputes (computed field).
        car["assigned_order_id"] = None
    car["status"] = "BAD_ORDER"
    touch(car)
    return success_object(railcar_view(car))


@bp.post("/rail/railcars/<rid>/return-to-service")
def return_railcar(rid):
    uid, role = authenticate()
    json_body()
    require_role(role, ["Dispatcher"])
    car = _get_railcar(rid)
    if car["status"] not in ("BAD_ORDER", "HELD"):
        raise invalid_state("return-to-service is defined only from BAD_ORDER or HELD")
    car["status"] = "AVAILABLE"
    touch(car)
    return success_object(railcar_view(car))
