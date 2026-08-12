"""TrainMovements, Waybills, RevenueDivisions (PRD 3.4, 3.5)."""

from flask import Blueprint, request

from auth import authenticate, require_role
from db import store
from envelope import success_object, success_list
from errors import (ApiError, ERR_INVALID_REQUEST, ERR_SEGMENT_NOT_IN_SERVICE,
                    ERR_MOVEMENT_NO_CREW, ERR_WAYBILL_NOT_RATED,
                    ERR_CAR_NOT_ON_LINE, ERR_DIVISION_BASIS_INVALID,
                    ERR_DIVISION_EXISTS, not_found, invalid_state)
from util import (json_body, req_str, opt_str, req_int, opt_int, req_bool,
                  req_enum, opt_num, paginate)
from domain import (new_record, touch, movement_view, waybill_view,
                    division_view, create_division, division_exists_for,
                    waybill_rate_cents, COMMODITIES, DIVISION_BASES,
                    CAR_NOT_ON_LINE_STATUSES)

bp = Blueprint("movement", __name__)

DIVISION_READ_ROLES = ["SettlementClerk", "SystemAdmin"]


# ---------------------------------------------------------------------------
# Train movements
# ---------------------------------------------------------------------------

@bp.post("/rail/train-movements")
def create_movement():
    uid, role = authenticate()
    body = json_body(required=True)
    symbol = req_str(body, "symbol")
    route = body.get("route_segment_ids")
    if (not isinstance(route, list) or not route
            or any(not isinstance(s, str) for s in route)):
        raise ApiError(400, ERR_INVALID_REQUEST,
                       "route_segment_ids must be a non-empty array of segment ids")
    origin_interchange_id = opt_str(body, "origin_interchange_id")
    require_role(role, ["Dispatcher"])
    for seg_id in route:
        if seg_id not in store.track_segments:
            raise not_found("track segment not found")
    if origin_interchange_id is not None and origin_interchange_id not in store.interchange_events:
        raise not_found("interchange event not found")
    rec = new_record({
        "symbol": symbol,
        "route_segment_ids": list(route),
        "origin_interchange_id": origin_interchange_id,
        "status": "PLANNED",
        "max_speed_mph": _route_max_speed(route),
        "departed_at": None,
        "arrived_at": None,
    })
    store.movements[rec["id"]] = rec
    return success_object(movement_view(rec), status=201)


def _route_max_speed(route):
    return min(store.track_segments[s]["effective_speed_mph"] for s in route)


@bp.get("/rail/train-movements")
def list_movements():
    uid, role = authenticate()
    records = list(store.movements.values())
    f_status = request.args.get("status")
    f_origin = request.args.get("origin_interchange_id")
    if f_status is not None:
        records = [m for m in records if m["status"] == f_status]
    if f_origin is not None:
        records = [m for m in records if m["origin_interchange_id"] == f_origin]
    limit, offset, total, page = paginate(records)
    return success_list([movement_view(m) for m in page], limit, offset, total)


def _get_movement(mid):
    rec = store.movements.get(mid)
    if rec is None:
        raise not_found("train movement not found")
    return rec


@bp.get("/rail/train-movements/<mid>")
def get_movement(mid):
    uid, role = authenticate()
    return success_object(movement_view(_get_movement(mid)))


def _movement_waybills(mid):
    return [w for w in store.waybills.values() if w["movement_id"] == mid]


def _segments_in_service(mv, require_no_defect=False):
    for seg_id in mv["route_segment_ids"]:
        seg = store.track_segments.get(seg_id)
        if seg is None or seg["status"] != "IN_SERVICE":
            return False
        if require_no_defect and seg["defect_open"]:
            return False
    return True


@bp.post("/rail/train-movements/<mid>/ready")
def ready_movement(mid):
    uid, role = authenticate()
    json_body()
    require_role(role, ["Dispatcher"])
    mv = _get_movement(mid)
    if mv["status"] != "PLANNED":
        raise invalid_state("only a PLANNED movement can be readied")
    if not _segments_in_service(mv):
        raise ApiError(409, ERR_SEGMENT_NOT_IN_SERVICE,
                       "every route segment must be IN_SERVICE")
    has_crew = any(c["movement_id"] == mid and c["status"] in ("ACCEPTED", "ON_DUTY")
                   for c in store.crew_calls.values())
    if not has_crew:
        raise ApiError(422, ERR_MOVEMENT_NO_CREW,
                       "no crew call in ACCEPTED or ON_DUTY for this movement")
    mv["max_speed_mph"] = _route_max_speed(mv["route_segment_ids"])
    mv["status"] = "READY"
    touch(mv)
    return success_object(movement_view(mv))


@bp.post("/rail/train-movements/<mid>/depart")
def depart_movement(mid):
    uid, role = authenticate()
    json_body()
    require_role(role, ["Dispatcher"])
    mv = _get_movement(mid)
    if mv["status"] != "READY":
        raise invalid_state("only a READY movement can depart")
    if not _segments_in_service(mv, require_no_defect=True):
        raise ApiError(409, ERR_SEGMENT_NOT_IN_SERVICE,
                       "every route segment must be IN_SERVICE with no open defect")
    mv["departed_at"] = store.now
    for wb in _movement_waybills(mid):
        car = store.railcars.get(wb["railcar_id"])
        if car is not None and car["status"] == "LOADED":
            car["status"] = "IN_TRANSIT"
            touch(car)
    mv["status"] = "DEPARTED"
    touch(mv)
    return success_object(movement_view(mv))


@bp.post("/rail/train-movements/<mid>/hold")
def hold_movement(mid):
    uid, role = authenticate()
    json_body()
    require_role(role, ["Dispatcher"])
    mv = _get_movement(mid)
    if mv["status"] != "DEPARTED":
        raise invalid_state("only a DEPARTED movement can be held")
    mv["status"] = "HELD"
    touch(mv)
    return success_object(movement_view(mv))


@bp.post("/rail/train-movements/<mid>/resume")
def resume_movement(mid):
    uid, role = authenticate()
    json_body()
    require_role(role, ["Dispatcher"])
    mv = _get_movement(mid)
    if mv["status"] != "HELD":
        raise invalid_state("only a HELD movement can be resumed")
    if not _segments_in_service(mv):
        raise ApiError(409, ERR_SEGMENT_NOT_IN_SERVICE,
                       "every route segment must be IN_SERVICE")
    mv["status"] = "DEPARTED"
    touch(mv)
    return success_object(movement_view(mv))


@bp.post("/rail/train-movements/<mid>/arrive")
def arrive_movement(mid):
    uid, role = authenticate()
    json_body()
    require_role(role, ["Dispatcher"])
    mv = _get_movement(mid)
    if mv["status"] != "DEPARTED":
        raise invalid_state("only a DEPARTED movement can arrive")
    mv["arrived_at"] = store.now
    for wb in _movement_waybills(mid):
        if wb["through_route"]:
            continue  # through cars stay in transit until interchanged
        car = store.railcars.get(wb["railcar_id"])
        if car is not None and car["status"] == "IN_TRANSIT":
            car["status"] = "AVAILABLE"
            touch(car)
    mv["status"] = "ARRIVED"
    touch(mv)
    return success_object(movement_view(mv))


@bp.post("/rail/train-movements/<mid>/settle")
def settle_movement(mid):
    uid, role = authenticate()
    json_body()
    require_role(role, ["SettlementClerk"])
    mv = _get_movement(mid)
    if mv["status"] != "ARRIVED":
        raise invalid_state("only an ARRIVED movement can be settled")
    waybills = _movement_waybills(mid)
    if any(w["status"] not in ("RATED", "BILLED") for w in waybills):
        raise ApiError(409, ERR_WAYBILL_NOT_RATED,
                       "every waybill on the movement must be RATED or BILLED")
    for wb in waybills:
        if wb["status"] == "RATED":
            wb["status"] = "BILLED"
            touch(wb)
        if wb["through_route"]:
            # Auto-create a DRAFT MILEAGE_PRORATE division (snapshot fields copied).
            if not division_exists_for(wb["id"]):
                create_division(wb, "MILEAGE_PRORATE", None)
        else:
            if wb["status"] == "BILLED":
                wb["status"] = "SETTLED"
                touch(wb)
        # The order that supplied the car completes when its waybill is billed.
        if wb["car_order_id"]:
            order = store.car_orders.get(wb["car_order_id"])
            if order is not None and order["status"] == "RELEASED":
                order["status"] = "COMPLETED"
                touch(order)
    mv["status"] = "SETTLED"
    touch(mv)
    return success_object(movement_view(mv))


# ---------------------------------------------------------------------------
# Waybills
# ---------------------------------------------------------------------------

@bp.post("/rail/waybills")
def create_waybill():
    uid, role = authenticate()
    body = json_body(required=True)
    railcar_id = req_str(body, "railcar_id")
    origin_customer_id = req_str(body, "origin_customer_id")
    destination = req_str(body, "destination")
    commodity = req_enum(body, "commodity", COMMODITIES)
    weight_tons = req_int(body, "weight_tons")
    if weight_tons < 0:
        raise ApiError(400, ERR_INVALID_REQUEST, "weight_tons must be >= 0")
    through_route = req_bool(body, "through_route")
    our_miles = opt_int(body, "our_miles")
    total_miles = opt_int(body, "total_miles")
    car_order_id = opt_str(body, "car_order_id")
    movement_id = opt_str(body, "movement_id")
    # Through waybill without both mileages (or with inverted miles) is a
    # malformed body per the error catalog's ERR_INVALID_REQUEST example.
    if through_route:
        if our_miles is None or total_miles is None:
            raise ApiError(400, ERR_INVALID_REQUEST,
                           "through_route requires our_miles and total_miles")
        if not (total_miles >= our_miles >= 0):
            raise ApiError(400, ERR_INVALID_REQUEST,
                           "total_miles must be >= our_miles >= 0")
    require_role(role, ["Dispatcher"])
    car = store.railcars.get(railcar_id)
    if car is None:
        raise not_found("railcar not found")
    if origin_customer_id not in store.customers:
        raise not_found("customer not found")
    if car_order_id is not None and car_order_id not in store.car_orders:
        raise not_found("car order not found")
    if movement_id is not None and movement_id not in store.movements:
        raise not_found("train movement not found")
    if car["status"] in CAR_NOT_ON_LINE_STATUSES:
        raise ApiError(409, ERR_CAR_NOT_ON_LINE,
                       "railcar status %s is not on line" % car["status"])
    rec = new_record({
        "railcar_id": railcar_id,
        "origin_customer_id": origin_customer_id,
        "car_order_id": car_order_id,
        "movement_id": movement_id,
        "destination": destination,
        "commodity": commodity,
        "weight_tons": weight_tons,
        "through_route": through_route,
        "our_miles": our_miles,
        "total_miles": total_miles,
        "total_freight_charge_cents": None,
        "status": "CREATED",
    })
    store.waybills[rec["id"]] = rec
    return success_object(waybill_view(rec), status=201)


@bp.get("/rail/waybills")
def list_waybills():
    uid, role = authenticate()
    records = list(store.waybills.values())
    for param, field in (("railcar_id", "railcar_id"),
                         ("origin_customer_id", "origin_customer_id"),
                         ("car_order_id", "car_order_id"),
                         ("movement_id", "movement_id"),
                         ("status", "status")):
        v = request.args.get(param)
        if v is not None:
            records = [w for w in records if w[field] == v]
    limit, offset, total, page = paginate(records)
    return success_list([waybill_view(w) for w in page], limit, offset, total)


def _get_waybill(wid):
    rec = store.waybills.get(wid)
    if rec is None:
        raise not_found("waybill not found")
    return rec


@bp.get("/rail/waybills/<wid>")
def get_waybill(wid):
    uid, role = authenticate()
    return success_object(waybill_view(_get_waybill(wid)))


@bp.post("/rail/waybills/<wid>/rate")
def rate_waybill(wid):
    uid, role = authenticate()
    json_body()
    require_role(role, ["SettlementClerk"])
    wb = _get_waybill(wid)
    if wb["status"] != "CREATED":
        raise invalid_state("only a CREATED waybill can be rated")
    car = store.railcars.get(wb["railcar_id"])
    if car is None or car["status"] in CAR_NOT_ON_LINE_STATUSES:
        raise ApiError(409, ERR_CAR_NOT_ON_LINE,
                       "railcar is not on line")
    wb["total_freight_charge_cents"] = waybill_rate_cents(wb["commodity"], wb["weight_tons"])
    wb["status"] = "RATED"
    touch(wb)
    return success_object(waybill_view(wb))


# ---------------------------------------------------------------------------
# Revenue divisions
# ---------------------------------------------------------------------------

@bp.post("/rail/revenue-divisions")
def create_revenue_division():
    uid, role = authenticate()
    body = json_body(required=True)
    waybill_id = req_str(body, "waybill_id")
    basis = req_enum(body, "basis", DIVISION_BASES)
    agreed_pct = opt_num(body, "agreed_pct")
    require_role(role, ["SettlementClerk"])
    wb = store.waybills.get(waybill_id)
    if wb is None:
        raise not_found("waybill not found")
    # At most one division per waybill (band 7) precedes basis shape (band 8).
    if division_exists_for(waybill_id):
        raise ApiError(409, ERR_DIVISION_EXISTS,
                       "a division already exists for this waybill")
    if wb["status"] not in ("RATED", "BILLED") or not wb["through_route"]:
        raise ApiError(400, ERR_DIVISION_BASIS_INVALID,
                       "waybill must be a RATED or BILLED through waybill")
    if basis == "AGREED_PERCENTAGE":
        if agreed_pct is None or not (0 < agreed_pct < 1):
            raise ApiError(400, ERR_DIVISION_BASIS_INVALID,
                           "agreed_pct must be strictly between 0 and 1")
    else:  # MILEAGE_PRORATE forbids agreed_pct
        if agreed_pct is not None:
            raise ApiError(400, ERR_DIVISION_BASIS_INVALID,
                           "agreed_pct is forbidden for MILEAGE_PRORATE")
    div = create_division(wb, basis, agreed_pct)
    return success_object(division_view(div), status=201)


@bp.get("/rail/revenue-divisions")
def list_divisions():
    uid, role = authenticate()
    require_role(role, DIVISION_READ_ROLES)
    records = list(store.revenue_divisions.values())
    f_wb = request.args.get("waybill_id")
    f_status = request.args.get("status")
    if f_wb is not None:
        records = [d for d in records if d["waybill_id"] == f_wb]
    if f_status is not None:
        records = [d for d in records if d["status"] == f_status]
    limit, offset, total, page = paginate(records)
    return success_list([division_view(d) for d in page], limit, offset, total)


def _get_division(did):
    rec = store.revenue_divisions.get(did)
    if rec is None:
        raise not_found("revenue division not found")
    return rec


@bp.get("/rail/revenue-divisions/<did>")
def get_division(did):
    uid, role = authenticate()
    require_role(role, DIVISION_READ_ROLES)
    return success_object(division_view(_get_division(did)))


@bp.post("/rail/revenue-divisions/<did>/agree")
def agree_division(did):
    uid, role = authenticate()
    json_body()
    require_role(role, ["SettlementClerk"])
    div = _get_division(did)
    if div["status"] not in ("DRAFT", "DISPUTED"):
        raise invalid_state("only a DRAFT or DISPUTED division can be agreed")
    div["status"] = "AGREED"
    touch(div)
    return success_object(division_view(div))


@bp.post("/rail/revenue-divisions/<did>/dispute")
def dispute_division(did):
    uid, role = authenticate()
    json_body()
    require_role(role, ["SettlementClerk"])
    div = _get_division(did)
    if div["status"] != "AGREED":
        raise invalid_state("only an AGREED division can be disputed")
    div["status"] = "DISPUTED"
    touch(div)
    return success_object(division_view(div))


@bp.post("/rail/revenue-divisions/<did>/settle")
def settle_division(did):
    uid, role = authenticate()
    json_body()
    require_role(role, ["SettlementClerk"])
    div = _get_division(did)
    if div["status"] != "AGREED":
        raise invalid_state("only an AGREED division can be settled")
    div["status"] = "SETTLED"
    touch(div)
    wb = store.waybills.get(div["waybill_id"])
    if wb is not None and wb["status"] == "BILLED":
        wb["status"] = "SETTLED"
        touch(wb)
    return success_object(division_view(div))
