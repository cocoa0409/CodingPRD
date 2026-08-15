"""CruiseInstance: scheduling, lifecycle transitions, weather hold/cancel."""
from flask import Blueprint, request

import clock
import db
from errors import ApiError, err_invalid_request, err_invalid_state
from response import ok
from serializers import serialize as _sz, serialize_list as _szl
from services import core as svc
from util import require_auth, get_json, paginate, get_or_404, touch

bp = Blueprint("cruises", __name__)

ALL_ROLES = ["OperationsManager", "Captain", "CharterSalesAgent", "Customer", "GalleyManager", "DockAttendant"]
OM = ["OperationsManager"]
CAPTAIN = ["Captain"]

CRUISE_STATUSES = ["SCHEDULED", "BOARDING", "UNDERWAY", "COMPLETED", "WEATHER_HOLD", "CANCELLED"]


@bp.post("/cruises")
def create_cruise():
    require_auth(OM)
    body = get_json(required_fields=["vessel_id", "menu_tier_id", "depart_at", "return_at"])
    vessel_id = body["vessel_id"]
    menu_tier_id = body["menu_tier_id"]
    if not isinstance(vessel_id, str) or not isinstance(menu_tier_id, str):
        raise err_invalid_request("vessel_id and menu_tier_id must be strings")
    depart_at = clock.parse_dt(body["depart_at"])
    return_at = clock.parse_dt(body["return_at"])
    if depart_at is None or return_at is None:
        raise err_invalid_request("depart_at and return_at must be ISO-8601 datetimes")
    if return_at <= depart_at:
        raise err_invalid_request("return_at must be later than depart_at")
    # Existence of body FK references
    vessel = db.vessels.get(vessel_id)
    if vessel is None:
        from errors import NOT_FOUND_IDS, err_not_found
        raise err_not_found(NOT_FOUND_IDS["vessel"], "Vessel not found")
    menu_tier = db.menu_tiers.get(menu_tier_id)
    if menu_tier is None:
        from errors import NOT_FOUND_IDS, err_not_found
        raise err_not_found(NOT_FOUND_IDS["menu_tier"], "Menu tier not found")
    # Rung 17: vessel must be in service
    if vessel["status"] != "ACTIVE":
        raise ApiError("ERR_VESSEL_OUT_OF_SERVICE", 409, "Vessel is OUT_OF_SERVICE")

    now_z = clock.to_z(clock.now())
    cruise = {
        "id": db.new_id(), "created_at": now_z, "updated_at": now_z, "version": 1,
        "vessel_id": vessel["id"], "menu_tier_id": menu_tier["id"],
        "depart_at": clock.to_z(depart_at), "return_at": clock.to_z(return_at),
        "season": svc.season_of(depart_at),
        "is_holiday": svc.is_holiday_date(depart_at),
        "reserved_covers": 0, "boarded_count": 0,
        "bar_service_enabled": False, "charter_booking_id": None,
        "status": "SCHEDULED", "cancelled_by_event_id": None,
    }
    db.insert(db.cruises, cruise)
    # Auto-create the boarding manifest in DRAFT with the capacity snapshot
    manifest = {
        "id": db.new_id(), "created_at": now_z, "updated_at": now_z, "version": 1,
        "cruise_id": cruise["id"], "passenger_count": 0,
        "coast_guard_capacity": vessel["coast_guard_capacity"],
        "status": "DRAFT",
    }
    db.insert(db.manifests, manifest)
    return ok(_sz("cruise", cruise), status=201)


@bp.get("/cruises")
def list_cruises():
    require_auth(ALL_ROLES)
    status_filter = request.args.get("status")
    if status_filter is not None and status_filter not in CRUISE_STATUSES:
        raise err_invalid_request("Invalid value for status")
    vessel_filter = request.args.get("vessel_id")
    items = list(db.cruises.values())
    if status_filter is not None:
        items = [c for c in items if c["status"] == status_filter]
    if vessel_filter is not None:
        items = [c for c in items if c["vessel_id"] == vessel_filter]
    items.sort(key=lambda c: c["created_at"])
    page, meta = paginate(items)
    return ok(_szl("cruise", page), pagination=meta)


@bp.get("/cruises/<cid>")
def get_cruise(cid):
    require_auth(ALL_ROLES)
    cruise = get_or_404(db.cruises, cid, "cruise", "Cruise not found")
    return ok(_sz("cruise", cruise))


def _load_cruise(cid):
    return get_or_404(db.cruises, cid, "cruise", "Cruise not found")


@bp.post("/cruises/<cid>/open-boarding")
def open_boarding(cid):
    require_auth(OM)
    cruise = _load_cruise(cid)
    if cruise["status"] != "SCHEDULED":
        raise err_invalid_state("Cruise is not SCHEDULED")
    # Rung 6 (capacity) before rung 15 (manifest frozen)
    vessel = db.vessels[cruise["vessel_id"]]
    if cruise["reserved_covers"] > vessel["coast_guard_capacity"]:
        raise ApiError("ERR_CAPACITY_EXCEEDED", 409, "reserved_covers exceeds coast_guard_capacity")
    manifest = svc.manifest_for_cruise(cruise["id"])
    if manifest is None or manifest["status"] != "FROZEN":
        raise ApiError("ERR_MANIFEST_NOT_FROZEN", 409, "Boarding manifest is not FROZEN")
    cruise["status"] = "BOARDING"
    touch(cruise)
    # Side effect: passenger_count snapshot recomputed one final time
    count = 0
    for p in db.passengers.values():
        b = db.bookings.get(p["booking_id"])
        if b is not None and b["cruise_id"] == cruise["id"] and p["boarded_at"] is not None:
            count += 1
    manifest["passenger_count"] = count
    touch(manifest)
    return ok(_sz("cruise", cruise))


@bp.post("/cruises/<cid>/depart")
def depart(cid):
    require_auth(CAPTAIN)
    cruise = _load_cruise(cid)
    if cruise["status"] != "BOARDING":
        raise err_invalid_state("Cruise is not BOARDING")
    vessel = db.vessels[cruise["vessel_id"]]
    if cruise["boarded_count"] > vessel["coast_guard_capacity"]:
        raise ApiError("ERR_CAPACITY_EXCEEDED", 409, "boarded_count exceeds coast_guard_capacity")
    manifest = svc.manifest_for_cruise(cruise["id"])
    if manifest is None or manifest["status"] != "FROZEN":
        raise ApiError("ERR_MANIFEST_NOT_FROZEN", 409, "Boarding manifest is not FROZEN")
    svc.depart_cascade(cruise)
    return ok(_sz("cruise", cruise))


@bp.post("/cruises/<cid>/complete")
def complete(cid):
    require_auth(CAPTAIN)
    cruise = _load_cruise(cid)
    if cruise["status"] != "UNDERWAY":
        raise err_invalid_state("Cruise is not UNDERWAY")
    svc.complete_cascade(cruise)
    return ok(_sz("cruise", cruise))


@bp.post("/cruises/<cid>/clear-weather-hold")
def clear_weather_hold(cid):
    require_auth(OM)
    cruise = _load_cruise(cid)
    if cruise["status"] != "WEATHER_HOLD":
        raise err_invalid_state("Cruise is not WEATHER_HOLD")
    covering = svc.weather_events_covering(cruise)
    for e in covering:
        if e["status"] not in ("DECLARED", "CLOSED"):
            raise ApiError("ERR_WEATHER_EVENT_ACTIVE", 409,
                           "Covering weather event is not in DECLARED or CLOSED")
    cruise["status"] = "SCHEDULED"
    touch(cruise)
    return ok(_sz("cruise", cruise))


@bp.post("/cruises/<cid>/weather-cancel")
def weather_cancel(cid):
    require_auth(OM)
    cruise = _load_cruise(cid)
    if cruise["status"] not in ("SCHEDULED", "WEATHER_HOLD"):
        raise err_invalid_state("Cruise is not SCHEDULED or WEATHER_HOLD")
    event = svc.covering_cancellation_event(cruise)
    if event is None:
        raise ApiError("ERR_NO_ACTIVE_WEATHER_EVENT", 409,
                       "No covering CANCELLATION_REQUIRED event in DECLARED or CANCELLATION_ISSUED")
    svc.weather_cancel_cascade(cruise)
    return ok(_sz("cruise", cruise))
