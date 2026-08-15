"""Configuration-surface routes: locations, travel edges, transporters,
equipment assets, staffing shifts, demand curves, and staffing adequacy."""

from flask import Blueprint, request

from db import store, now
from errors import ApiError
from middleware import require_roles, forbidden
from response import ok, ok_list, public, public_list, sort_created, paginate
from services import (
    LOCATION_TYPES, EQUIPMENT_TYPES, PRIORITIES, DAY_TYPES,
    stamp_new, touch, find_edge, has_active_assignment, has_pending_offer_for,
    auto_dispatch_eval, staffing_adequacy,
)
from util import (
    get_body, req_string, req_enum, req_int, req_number, opt_bool, req_datetime,
    parse_datetime, fmt,
)

bp = Blueprint("config", __name__)


def _not_found(what):
    raise ApiError("ERR_NOT_FOUND", 404, "{} not found".format(what))


def _filters(recs, params):
    out = list(recs)
    for param in params:
        v = request.args.get(param)
        if v is not None:
            out = [r for r in out if r.get(param) is not None and str(r.get(param)) == v]
    return out


# ---------------------------------------------------------------------------
# Locations
# ---------------------------------------------------------------------------

@bp.post("/transport/locations")
def create_location():
    require_roles("TransportSupervisor")
    data = get_body()
    code = req_string(data, "code")
    name = req_string(data, "name")
    location_type = req_enum(data, "location_type", LOCATION_TYPES)
    zone_code = req_string(data, "zone_code")
    rec = stamp_new({
        "code": code,
        "name": name,
        "location_type": location_type,
        "zone_code": zone_code,
    })
    store.locations[rec["id"]] = rec
    return ok(public(rec), 201)


# ---------------------------------------------------------------------------
# Travel edges
# ---------------------------------------------------------------------------

@bp.post("/transport/travel-edges")
def create_travel_edge():
    require_roles("TransportSupervisor")
    data = get_body()
    frm = req_string(data, "from_location_id")
    to = req_string(data, "to_location_id")
    base = req_int(data, "base_minutes", min_value=1)
    air = req_int(data, "airborne_minutes", min_value=1)
    if frm not in store.locations:
        _not_found("location")
    if to not in store.locations:
        _not_found("location")
    if find_edge(frm, to) is not None:
        raise ApiError("ERR_TRAVEL_EDGE_DUPLICATE", 409, "a travel edge already exists for this directed pair")
    rec = stamp_new({
        "from_location_id": frm,
        "to_location_id": to,
        "base_minutes": base,
        "airborne_minutes": air,
    })
    store.travel_edges[rec["id"]] = rec
    return ok(public(rec), 201)


@bp.get("/transport/travel-edges")
def list_travel_edges():
    require_roles("TransportDispatcher", "TransportSupervisor")
    recs = _filters(sort_created(store.travel_edges.values()), ["from_location_id", "to_location_id"])
    page, meta = paginate(recs)
    return ok_list(public_list(page), meta)


@bp.get("/transport/travel-edges/<edge_id>")
def get_travel_edge(edge_id):
    require_roles("TransportDispatcher", "TransportSupervisor")
    rec = store.travel_edges.get(edge_id)
    if rec is None:
        _not_found("travel edge")
    return ok(public(rec))


# ---------------------------------------------------------------------------
# Transporters
# ---------------------------------------------------------------------------

@bp.post("/transport/transporters")
def create_transporter():
    require_roles("TransportSupervisor")
    data = get_body()
    name = req_string(data, "name")
    home = req_string(data, "home_location_id")
    cert = data.get("certified_equipment", [])
    if not isinstance(cert, list) or any(not isinstance(c, str) or c not in EQUIPMENT_TYPES for c in cert):
        raise ApiError("ERR_VALIDATION", 400, "certified_equipment must be a list of equipment types")
    oxygen = opt_bool(data, "oxygen_certified", False)
    isolation = opt_bool(data, "isolation_certified", False)
    if home not in store.locations:
        _not_found("location")
    rec = stamp_new({
        "name": name,
        "home_location_id": home,
        "certified_equipment": list(cert),
        "oxygen_certified": oxygen,
        "isolation_certified": isolation,
        "status": "OFF_SHIFT",
        "current_location_id": home,
    })
    store.transporters[rec["id"]] = rec
    return ok(public(rec), 201)


@bp.get("/transport/transporters")
def list_transporters():
    require_roles("TransportDispatcher", "TransportSupervisor")
    recs = _filters(sort_created(store.transporters.values()),
                    ["status", "home_location_id", "current_location_id"])
    page, meta = paginate(recs)
    return ok_list(public_list(page), meta)


def _get_transporter_checked(transporter_id, uid, role):
    t = store.transporters.get(transporter_id)
    if t is None:
        _not_found("transporter")
    if role == "Transporter" and t["id"] != uid:
        forbidden("transporters may only access their own record")
    return t


@bp.get("/transport/transporters/<transporter_id>")
def get_transporter(transporter_id):
    uid, role = require_roles("TransportDispatcher", "TransportSupervisor", "Transporter")
    t = _get_transporter_checked(transporter_id, uid, role)
    return ok(public(t))


@bp.post("/transport/transporters/<transporter_id>/set-status")
def set_transporter_status(transporter_id):
    uid, role = require_roles("Transporter", "TransportSupervisor")
    data = get_body()
    target = req_enum(data, "status", {"ON_SHIFT", "OFF_SHIFT", "SUSPENDED"})
    t = store.transporters.get(transporter_id)
    if t is None:
        _not_found("transporter")
    # Role-payload restrictions (tier 2).
    if role == "Transporter":
        if t["id"] != uid:
            forbidden("transporters may only set their own status")
        if target == "SUSPENDED":
            forbidden("suspension is supervisor-only")
    cur = t["status"]
    if target == "ON_SHIFT":
        if cur != "OFF_SHIFT":
            raise ApiError("ERR_INVALID_TRANSPORTER_STATE", 409,
                           "clock-in is only possible from OFF_SHIFT")
        covered = any(
            s["transporter_id"] == t["id"] and s["status"] == "PLANNED"
            and parse_datetime(s["shift_start"], "shift_start") <= now() < parse_datetime(s["shift_end"], "shift_end")
            for s in store.shifts.values()
        )
        if not covered:
            raise ApiError("ERR_NO_SHIFT_COVERAGE", 422, "no PLANNED shift covers the current instant")
    elif target == "OFF_SHIFT":
        if cur == "ON_SHIFT":
            if has_active_assignment(t["id"]) or has_pending_offer_for(t["id"]):
                raise ApiError("ERR_INVALID_TRANSPORTER_STATE", 409,
                               "cannot clock out with an active assignment or pending offer")
        elif cur == "SUSPENDED":
            if role != "TransportSupervisor":
                forbidden("reinstatement from SUSPENDED is supervisor-only")
        else:
            raise ApiError("ERR_INVALID_TRANSPORTER_STATE", 409,
                           "transporter is already OFF_SHIFT")
    else:  # SUSPENDED (supervisor-only; transporter rejected above)
        if cur != "ON_SHIFT":
            raise ApiError("ERR_INVALID_TRANSPORTER_STATE", 409,
                           "suspension is only possible from ON_SHIFT")
        if has_active_assignment(t["id"]) or has_pending_offer_for(t["id"]):
            raise ApiError("ERR_INVALID_TRANSPORTER_STATE", 409,
                           "cannot suspend with an active assignment or pending offer")
    t["status"] = target
    touch(t)
    return ok(public(t))


@bp.get("/transport/transporters/<transporter_id>/shifts")
def list_transporter_shifts(transporter_id):
    uid, role = require_roles("TransportDispatcher", "TransportSupervisor", "Transporter")
    t = _get_transporter_checked(transporter_id, uid, role)
    recs = [s for s in store.shifts.values() if s["transporter_id"] == t["id"]]
    recs = _filters(sort_created(recs), ["status"])
    page, meta = paginate(recs)
    return ok_list(public_list(page), meta)


@bp.get("/transport/transporters/<transporter_id>/offers")
def list_transporter_offers(transporter_id):
    uid, role = require_roles("TransportDispatcher", "TransportSupervisor", "Transporter")
    t = _get_transporter_checked(transporter_id, uid, role)
    recs = [o for o in store.offers.values() if o["transporter_id"] == t["id"]]
    recs = _filters(sort_created(recs), ["status"])
    page, meta = paginate(recs)
    return ok_list(public_list(page), meta)


# ---------------------------------------------------------------------------
# Equipment assets
# ---------------------------------------------------------------------------

@bp.post("/transport/equipment-assets")
def create_equipment_asset():
    require_roles("TransportSupervisor")
    data = get_body()
    tag = req_string(data, "asset_tag")
    etype = req_enum(data, "equipment_type", EQUIPMENT_TYPES)
    loc = req_string(data, "current_location_id")
    if loc not in store.locations:
        _not_found("location")
    rec = stamp_new({
        "asset_tag": tag,
        "equipment_type": etype,
        "status": "AVAILABLE",
        "current_location_id": loc,
        "isolation_contaminated": False,
    })
    store.equipment_assets[rec["id"]] = rec
    return ok(public(rec), 201)


@bp.get("/transport/equipment-assets")
def list_equipment_assets():
    require_roles("TransportDispatcher", "TransportSupervisor")
    recs = _filters(sort_created(store.equipment_assets.values()),
                    ["status", "equipment_type", "current_location_id"])
    page, meta = paginate(recs)
    return ok_list(public_list(page), meta)


@bp.get("/transport/equipment-assets/<asset_id>")
def get_equipment_asset(asset_id):
    require_roles("TransportDispatcher", "TransportSupervisor")
    rec = store.equipment_assets.get(asset_id)
    if rec is None:
        _not_found("equipment asset")
    return ok(public(rec))


@bp.post("/transport/equipment-assets/<asset_id>/set-service-status")
def set_asset_service_status(asset_id):
    require_roles("TransportSupervisor")
    data = get_body()
    target = req_enum(data, "service_status", {"OUT_OF_SERVICE", "AVAILABLE"})
    a = store.equipment_assets.get(asset_id)
    if a is None:
        _not_found("equipment asset")
    if target == "OUT_OF_SERVICE":
        if a["status"] not in ("AVAILABLE", "RESERVED"):
            raise ApiError("ERR_INVALID_ASSET_STATE", 409,
                           "only AVAILABLE or RESERVED assets can be pulled from service")
        a["status"] = "OUT_OF_SERVICE"
        touch(a)
    else:
        if a["status"] != "OUT_OF_SERVICE":
            raise ApiError("ERR_INVALID_ASSET_STATE", 409,
                           "only OUT_OF_SERVICE assets can be returned to service")
        a["status"] = "AVAILABLE"
        touch(a)
        auto_dispatch_eval(a)
    return ok(public(a))


# ---------------------------------------------------------------------------
# Staffing shifts
# ---------------------------------------------------------------------------

@bp.post("/transport/staffing-shifts")
def create_staffing_shift():
    require_roles("TransportSupervisor")
    data = get_body()
    tid = req_string(data, "transporter_id")
    start = req_datetime(data, "shift_start")
    end = req_datetime(data, "shift_end")
    if not end > start:
        raise ApiError("ERR_VALIDATION", 400, "shift_end must be later than shift_start")
    t = store.transporters.get(tid)
    if t is None:
        _not_found("transporter")
    if t["status"] == "SUSPENDED":
        raise ApiError("ERR_TRANSPORTER_SUSPENDED", 422, "cannot plan a shift for a SUSPENDED transporter")
    for s in store.shifts.values():
        if s["transporter_id"] != tid or s["status"] != "PLANNED":
            continue
        s_start = parse_datetime(s["shift_start"], "shift_start")
        s_end = parse_datetime(s["shift_end"], "shift_end")
        # Half-open intervals: touching endpoints do not overlap.
        if start < s_end and s_start < end:
            raise ApiError("ERR_SHIFT_OVERLAP", 409, "shift overlaps an existing PLANNED shift")
    rec = stamp_new({
        "transporter_id": tid,
        "shift_start": fmt(start),
        "shift_end": fmt(end),
        "status": "PLANNED",
    })
    store.shifts[rec["id"]] = rec
    return ok(public(rec), 201)


@bp.post("/transport/staffing-shifts/<shift_id>/set-status")
def set_shift_status(shift_id):
    require_roles("TransportSupervisor")
    data = get_body()
    target = req_enum(data, "status", {"CANCELLED"})
    s = store.shifts.get(shift_id)
    if s is None:
        _not_found("staffing shift")
    if s["status"] != "PLANNED":
        raise ApiError("ERR_INVALID_SHIFT_STATE", 409, "only a PLANNED shift can be cancelled")
    s["status"] = "CANCELLED"
    touch(s)
    return ok(public(s))


# ---------------------------------------------------------------------------
# Demand curves
# ---------------------------------------------------------------------------

@bp.post("/transport/demand-curves")
def create_demand_curve():
    require_roles("TransportSupervisor")
    data = get_body()
    day_type = req_enum(data, "day_type", DAY_TYPES)
    hour_block = req_int(data, "hour_block", min_value=0, max_value=23)
    priority = req_enum(data, "priority", PRIORITIES)
    expected = req_number(data, "expected_requests", min_value=0)
    mean_service = req_int(data, "mean_service_minutes", min_value=1)
    for dc in store.demand_curves.values():
        if (dc["day_type"] == day_type and dc["hour_block"] == hour_block
                and dc["priority"] == priority):
            raise ApiError("ERR_DEMAND_CURVE_CONFLICT", 409,
                           "a demand-curve row already exists for this day_type/hour_block/priority")
    rec = stamp_new({
        "day_type": day_type,
        "hour_block": hour_block,
        "priority": priority,
        "expected_requests": expected,
        "mean_service_minutes": mean_service,
    })
    store.demand_curves[rec["id"]] = rec
    return ok(public(rec), 201)


# ---------------------------------------------------------------------------
# Staffing adequacy (computed read)
# ---------------------------------------------------------------------------

@bp.get("/transport/staffing/adequacy")
def get_staffing_adequacy():
    require_roles("TransportDispatcher", "TransportSupervisor")
    q = request.args
    date_s = q.get("date")
    hour_s = q.get("hour_block")
    win_s = q.get("window_hours")
    variant = q.get("variant")
    if date_s is None or hour_s is None or win_s is None or variant is None:
        raise ApiError("ERR_VALIDATION", 400, "date, hour_block, window_hours and variant are required")
    try:
        from datetime import datetime as _dt, timezone as _tz
        date_dt = _dt.strptime(date_s, "%Y-%m-%d").replace(tzinfo=_tz.utc)
    except (ValueError, TypeError):
        date_dt = parse_datetime(date_s, "date")
    try:
        hour_block = int(hour_s)
    except (TypeError, ValueError):
        raise ApiError("ERR_VALIDATION", 400, "hour_block must be an integer")
    try:
        window_hours = int(win_s)
    except (TypeError, ValueError):
        raise ApiError("ERR_VALIDATION", 400, "window_hours must be an integer")
    if hour_block < 0 or hour_block > 23:
        raise ApiError("ERR_VALIDATION", 400, "hour_block must be in 0..23")
    if window_hours < 1 or hour_block + window_hours > 24:
        raise ApiError("ERR_VALIDATION", 400, "invalid window: window_hours >= 1 and hour_block + window_hours <= 24")
    if variant not in ("FORECAST", "REPLAY"):
        raise ApiError("ERR_VALIDATION", 400, "variant must be FORECAST or REPLAY")
    result = staffing_adequacy(date_dt, hour_block, window_hours, variant)
    return ok(result)
