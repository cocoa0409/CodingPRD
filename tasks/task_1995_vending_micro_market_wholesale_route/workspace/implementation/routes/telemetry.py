"""TelemetryEvent ingestion (append-only; cascades per scaffold §1.5 CASCADE B)."""
from flask import Blueprint
import db
from middleware import get_auth, require_role
from response import success_object
from util import get_json_body, req_string, req_int, req_array, stamp_new
from errors import ApiError, ERR_LOCATION_NOT_FOUND, ERR_PRODUCT_NOT_FOUND, ERR_INVALID_REQUEST
from services import pricing
import clock

bp = Blueprint("telemetry", __name__)


def view(e):
    return {k: v for k, v in e.items() if k != "recorded_at_dt"}


@bp.post("/wholesale/telemetry-events")
def ingest_telemetry():
    user_id, role = get_auth()
    body = get_json_body()
    require_role(role, ["TelemetryGateway"])
    location_id = req_string(body, "location_id")
    recorded_raw = req_string(body, "recorded_at")
    cash_collected_cents = req_int(body, "cash_collected_cents")
    if cash_collected_cents < 0:
        raise ApiError(ERR_INVALID_REQUEST, 400, "cash_collected_cents must be >= 0")
    cashless_sales_cents = req_int(body, "cashless_sales_cents")
    if cashless_sales_cents < 0:
        raise ApiError(ERR_INVALID_REQUEST, 400, "cashless_sales_cents must be >= 0")
    items = req_array(body, "items")
    try:
        recorded_dt = clock.parse_iso(recorded_raw)
    except ValueError:
        raise ApiError(ERR_INVALID_REQUEST, 400, "recorded_at must be an ISO 8601 datetime")
    location = db.locations.get(location_id)
    if location is None:
        raise ApiError(ERR_LOCATION_NOT_FOUND, 404, "Location id does not exist")
    new_items = []
    for item in items:
        if not isinstance(item, dict):
            raise ApiError(ERR_INVALID_REQUEST, 400, "items rows must be objects")
        pid = item.get("product_id")
        if not isinstance(pid, str) or not pid:
            raise ApiError(ERR_INVALID_REQUEST, 400, "items[].product_id required")
        units_vended = item.get("units_vended")
        if isinstance(units_vended, bool) or not isinstance(units_vended, int) or units_vended < 0:
            raise ApiError(ERR_INVALID_REQUEST, 400, "items[].units_vended must be a non-negative integer")
        on_hand_units = item.get("on_hand_units")
        if isinstance(on_hand_units, bool) or not isinstance(on_hand_units, int) or on_hand_units < 0:
            raise ApiError(ERR_INVALID_REQUEST, 400, "items[].on_hand_units must be a non-negative integer")
        if pid not in db.products:
            raise ApiError(ERR_PRODUCT_NOT_FOUND, 404, "Product id does not exist")
        new_items.append({
            "product_id": pid,
            "units_vended": units_vended,
            "on_hand_units": on_hand_units,
        })
    # Append-only: id + created_at only, no updated_at / version (PRD §2.4)
    ev = stamp_new({
        "location_id": location_id,
        "recorded_at": recorded_raw,
        "recorded_at_dt": recorded_dt,
        "cash_collected_cents": cash_collected_cents,
        "cashless_sales_cents": cashless_sales_cents,
        "items": new_items,
    }, with_common=False)
    db.telemetry_events[ev["id"]] = ev
    # CASCADE B link 1: rebuild location projection (bumps Location.version)
    pricing.rebuild_projection(location)
    # CASCADE B link 2: refresh DRAFT TELEMETRY_SUGGESTED order lines (bumps its version)
    pricing.refresh_suggested_draft(location)
    return success_object(view(ev), 201)
