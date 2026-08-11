"""ProcessingFacility + FacilityDelivery endpoints (PRD §3.8)."""

from datetime import timedelta

from flask import Blueprint, request

from db import STORE, _parse_dt
from errors import (ApiError, ERR_DELIVERY_WINDOW_OVERLAP, ERR_FACILITY_CAPACITY_EXCEEDED,
                    ERR_FACILITY_NOT_FOUND, ERR_FACILITY_NOT_OPEN,
                    ERR_LOAD_SAFETY_LIMIT_EXCEEDED, ERR_ROUTE_NOT_PUBLISHED,
                    err_invalid_request, err_invalid_state, err_not_found)
from middleware import require_roles
from response import success_list, success_object, parse_pagination
from services.core import (base_record, touch, facility_out, delivery_out,
                           parse_date, DELIVERY_BUFFER_MINUTES)
from services.validate import (require_body, check_unknown_fields, req_str, req_int,
                               req_date, opt_int, req_enum)

bp = Blueprint("facilities", __name__)

FACILITY_ROLES = ("ProgramAdmin", "RouteSupervisor")
DELIVERY_READ_ROLES = ("RouteSupervisor", "ProgramAdmin")


# ---- ProcessingFacility ----

@bp.post("/facilities")
def create_facility():
    require_roles("ProgramAdmin")
    data = require_body(request.get_json(silent=True))
    check_unknown_fields(data, {"name", "daily_receiving_capacity_lbs",
                                "safety_contamination_item_limit"})
    name = req_str(data, "name")
    cap = req_int(data, "daily_receiving_capacity_lbs")
    limit = req_int(data, "safety_contamination_item_limit")

    f = base_record()
    f.update({
        "name": name,
        "daily_receiving_capacity_lbs": cap,
        "safety_contamination_item_limit": limit,
        "status": "OPEN",
        "season_accepted_lbs": 0,
    })
    STORE.facilities[f["id"]] = f
    return success_object(facility_out(f), 201)


@bp.get("/facilities")
def list_facilities():
    require_roles(*FACILITY_ROLES)
    limit, offset = parse_pagination(request.args)
    items = list(STORE.facilities.values())
    st = request.args.get("status")
    if st is not None:
        items = [f for f in items if f["status"] == st]
    items.sort(key=lambda f: (f["created_at"], f["id"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([facility_out(f) for f in page], limit, offset, total)


@bp.get("/facilities/<fid>")
def get_facility(fid):
    require_roles(*FACILITY_ROLES)
    f = STORE.facilities.get(fid)
    if not f:
        raise err_not_found(ERR_FACILITY_NOT_FOUND, "Facility not found")
    return success_object(facility_out(f))


@bp.patch("/facilities/<fid>")
def patch_facility(fid):
    require_roles("ProgramAdmin")
    f = STORE.facilities.get(fid)
    if not f:
        raise err_not_found(ERR_FACILITY_NOT_FOUND, "Facility not found")
    data = require_body(request.get_json(silent=True))
    check_unknown_fields(data, {"status", "daily_receiving_capacity_lbs",
                                "safety_contamination_item_limit"})

    if "status" in data and data["status"] is not None:
        new_status = req_enum(data, "status", {"OPEN", "CLOSED"})
        if new_status == "CLOSED" and f["status"] != "OPEN":
            raise err_invalid_state("Facility is not OPEN")
        if new_status == "OPEN" and f["status"] != "CLOSED":
            raise err_invalid_state("Facility is not CLOSED")
        f["status"] = new_status
    if "daily_receiving_capacity_lbs" in data:
        f["daily_receiving_capacity_lbs"] = req_int(data, "daily_receiving_capacity_lbs")
    if "safety_contamination_item_limit" in data:
        f["safety_contamination_item_limit"] = req_int(data, "safety_contamination_item_limit")

    touch(f)
    return success_object(facility_out(f))


# ---- FacilityDelivery ----

@bp.post("/facility-deliveries")
def create_delivery():
    require_roles("RouteSupervisor")
    data = require_body(request.get_json(silent=True))
    check_unknown_fields(data, {"facility_id", "route_id", "delivery_date",
                                "window_start", "window_end"})
    facility_id = req_str(data, "facility_id")
    route_id = req_str(data, "route_id")
    delivery_date = req_date(data, "delivery_date")
    ws = req_str(data, "window_start")
    we = req_str(data, "window_end")
    try:
        ws_dt = _parse_dt(ws)
        we_dt = _parse_dt(we)
    except Exception:
        raise err_invalid_request("window_start/window_end must be ISO 8601 datetimes")

    # shape: both on delivery_date, window_end > window_start
    if we_dt <= ws_dt:
        raise err_invalid_request("window_end must be after window_start")
    if ws_dt.date() != parse_date(delivery_date) or we_dt.date() != parse_date(delivery_date):
        raise err_invalid_request("window_start/window_end must fall on delivery_date")

    # body FK existence
    facility = STORE.facilities.get(facility_id)
    if not facility:
        raise err_not_found(ERR_FACILITY_NOT_FOUND, "Facility not found")
    route = STORE.routes.get(route_id)
    if not route:
        raise err_not_found()

    # referential: facility OPEN, route PUBLISHED
    if facility["status"] != "OPEN":
        raise ApiError(ERR_FACILITY_NOT_OPEN, "Facility is not OPEN", 409)
    if route["status"] != "PUBLISHED":
        raise ApiError(ERR_ROUTE_NOT_PUBLISHED, "Route must be PUBLISHED", 409)

    # buffered bay-window overlap at same facility+date
    buf = timedelta(minutes=DELIVERY_BUFFER_MINUTES)
    nws = ws_dt - buf
    nwe = we_dt + buf
    for d in STORE.deliveries.values():
        if d["facility_id"] != facility_id or d["delivery_date"] != delivery_date:
            continue
        if d["status"] == "REJECTED":
            continue
        dws = _parse_dt(d["window_start"]) - buf
        dwe = _parse_dt(d["window_end"]) + buf
        # overlap: nws < dwe and dws < nwe (buffer-edge touch allowed)
        if nws < dwe and dws < nwe:
            raise ApiError(ERR_DELIVERY_WINDOW_OVERLAP,
                           "Buffered bay window overlaps an existing delivery", 409)

    d = base_record()
    d.update({
        "facility_id": facility_id, "route_id": route_id,
        "delivery_date": delivery_date, "window_start": ws, "window_end": we,
        "status": "SCHEDULED",
        "gross_weight_lbs": None, "contaminated_item_count": None,
        "accepted_weight_lbs": 0,
    })
    STORE.deliveries[d["id"]] = d
    return success_object(delivery_out(d), 201)


@bp.get("/facility-deliveries")
def list_deliveries():
    require_roles(*DELIVERY_READ_ROLES)
    limit, offset = parse_pagination(request.args)
    items = list(STORE.deliveries.values())
    fid = request.args.get("facility_id")
    rid = request.args.get("route_id")
    dd = request.args.get("delivery_date")
    st = request.args.get("status")
    if fid is not None:
        items = [d for d in items if d["facility_id"] == fid]
    if rid is not None:
        items = [d for d in items if d["route_id"] == rid]
    if dd is not None:
        items = [d for d in items if d["delivery_date"] == dd]
    if st is not None:
        items = [d for d in items if d["status"] == st]
    items.sort(key=lambda d: (d["created_at"], d["id"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([delivery_out(d) for d in page], limit, offset, total)


@bp.get("/facility-deliveries/<did>")
def get_delivery(did):
    require_roles(*DELIVERY_READ_ROLES)
    d = STORE.deliveries.get(did)
    if not d:
        raise err_not_found()
    return success_object(delivery_out(d))


@bp.post("/facility-deliveries/<did>/receive")
def receive_delivery(did):
    require_roles("RouteSupervisor")
    d = STORE.deliveries.get(did)
    if not d:
        raise err_not_found()
    data = require_body(request.get_json(silent=True))
    check_unknown_fields(data, {"outcome", "gross_weight_lbs", "contaminated_item_count"})
    outcome = req_enum(data, "outcome", {"ACCEPT", "REJECT"})
    gross = req_int(data, "gross_weight_lbs")
    contaminated = req_int(data, "contaminated_item_count")
    if gross < 0 or contaminated < 0:
        raise err_invalid_request("gross_weight_lbs and contaminated_item_count must be >= 0")

    if d["status"] != "SCHEDULED":
        raise err_invalid_state("Delivery is not SCHEDULED")

    facility = STORE.facilities.get(d["facility_id"])
    route = STORE.routes.get(d["route_id"])

    if outcome == "ACCEPT":
        # safety gate (priority 8)
        if contaminated > facility["safety_contamination_item_limit"]:
            raise ApiError(ERR_LOAD_SAFETY_LIMIT_EXCEEDED,
                           "Contaminated item count exceeds facility safety limit", 422)
        # capacity gate (priority 9)
        day_accepted = sum(x["gross_weight_lbs"] for x in STORE.deliveries.values()
                           if x["facility_id"] == facility["id"]
                           and x["delivery_date"] == d["delivery_date"]
                           and x["status"] == "ACCEPTED")
        if day_accepted + gross > facility["daily_receiving_capacity_lbs"]:
            raise ApiError(ERR_FACILITY_CAPACITY_EXCEEDED,
                           "Facility daily capacity would be exceeded", 409)
        # referential gate (priority 11)
        if not route or route["status"] != "PUBLISHED":
            raise ApiError(ERR_ROUTE_NOT_PUBLISHED, "Route must be PUBLISHED at receive time", 409)
        d["status"] = "ACCEPTED"
        d["accepted_weight_lbs"] = gross
        facility["season_accepted_lbs"] += gross
        touch(facility)
    else:
        # REJECT bypasses all gates
        d["status"] = "REJECTED"
        d["accepted_weight_lbs"] = 0

    d["gross_weight_lbs"] = gross
    d["contaminated_item_count"] = contaminated
    touch(d)
    return success_object(delivery_out(d))
