"""Toll event endpoints."""
from flask import Blueprint, request

from ..auth import require_roles
from ..errors import raise_api_error
from ..responses import paginate, parse_pagination, success_array, success_object
from ..serializers import serialize_toll_event
from ..services.toll_engine import ingest_toll_event, void_toll_event
from ..store import store
from ..validators import (
    AGENCIES,
    PLATE_STATES,
    normalize_plate,
    normalize_serial,
    optional_bool,
    optional_enum,
    optional_int,
    optional_str,
    require_enum,
    require_int,
    require_json,
    require_str,
)
from ..clock import parse_iso


toll_events_bp = Blueprint("toll_events", __name__)


@toll_events_bp.route("/toll-events", methods=["POST"])
@require_roles("GantryOperator")
def ingest():
    payload = require_json(request.get_json(silent=True))
    gantry_id = require_str(payload, "gantry_id", min_len=1, max_len=32)
    agency_code = require_enum(payload, "agency_code", AGENCIES)
    base_rate_cents = require_int(payload, "base_rate_cents", 0, 10_000_000)
    read_at_str = require_str(payload, "read_at", min_len=1, max_len=64)
    try:
        parse_iso(read_at_str)
    except ValueError:
        raise_api_error("ERR_VALIDATION", f"Invalid ISO 8601 read_at: {read_at_str}")
    raw_serial = optional_str(payload, "transponder_serial", default=None, min_len=1, max_len=64)
    transponder_serial = normalize_serial(raw_serial) if raw_serial else None
    raw_plate = optional_str(payload, "plate_number", default=None, min_len=1, max_len=20)
    plate_number = normalize_plate(raw_plate) if raw_plate else None
    plate_state = optional_enum(payload, "plate_state", PLATE_STATES, default=None)
    declared_occupants = optional_int(payload, "declared_occupants", 1, 9, default=1)
    hov_lane = optional_bool(payload, "hov_lane", default=False)

    cleaned = {
        "gantry_id": gantry_id,
        "agency_code": agency_code,
        "base_rate_cents": base_rate_cents,
        "read_at": read_at_str,
        "transponder_serial": transponder_serial,
        "plate_number": plate_number,
        "plate_state": plate_state,
        "declared_occupants": declared_occupants,
        "hov_lane": hov_lane,
    }
    event = ingest_toll_event(cleaned)
    return success_object(serialize_toll_event(event), status=201)


@toll_events_bp.route("/toll-events/<toll_event_id>", methods=["GET"])
@require_roles("AccountHolder", "AgencyAdmin", "GantryOperator")
def get_toll_event(toll_event_id: str):
    event = store.toll_events.get(toll_event_id)
    if event is None:
        raise_api_error("ERR_NOT_FOUND")
    role = getattr(request, "caller_role", None)
    caller_id = getattr(request, "caller_id", None)
    if role == "AccountHolder" and event.get("account_id") != caller_id:
        raise_api_error("ERR_FORBIDDEN")
    return success_object(serialize_toll_event(event))


@toll_events_bp.route("/toll-events", methods=["GET"])
@require_roles("AccountHolder", "AgencyAdmin")
def list_toll_events():
    limit, offset = parse_pagination(request.args)
    account_id = request.args.get("account_id")
    vehicle_id = request.args.get("vehicle_id")
    billing_status = request.args.get("billing_status")
    agency_code = request.args.get("agency_code")
    capture_method = request.args.get("capture_method")

    role = getattr(request, "caller_role", None)
    caller_id = getattr(request, "caller_id", None)
    if role == "AccountHolder":
        # Holders only see their own events
        if account_id is None:
            account_id = caller_id
        elif account_id != caller_id:
            raise_api_error("ERR_FORBIDDEN")

    rows = list(store.toll_events.values())
    if account_id:
        rows = [r for r in rows if r.get("account_id") == account_id]
    if vehicle_id:
        rows = [r for r in rows if r.get("vehicle_id") == vehicle_id]
    if billing_status:
        rows = [r for r in rows if r["billing_status"] == billing_status]
    if agency_code:
        rows = [r for r in rows if r["agency_code"] == agency_code]
    if capture_method:
        rows = [r for r in rows if r["capture_method"] == capture_method]
    rows.sort(key=lambda r: r["created_at"])
    page, total = paginate(rows, limit, offset)
    return success_array([serialize_toll_event(r) for r in page], limit, offset, total)


@toll_events_bp.route("/toll-events/<toll_event_id>/void", methods=["POST"])
@require_roles("AgencyAdmin")
def void_event(toll_event_id: str):
    event = store.toll_events.get(toll_event_id)
    if event is None:
        raise_api_error("ERR_NOT_FOUND")
    updated = void_toll_event(event)
    return success_object(serialize_toll_event(updated))
