"""Sensor and SensorReading routes."""

from flask import Blueprint, g, request

from clock import CLOCK
from db import DB, LOCK, new_id
from errors import forbidden, not_found, poll_interval_out_of_range, validation_error
from middleware import require_roles
from response import success_array, success_object
from services.alerts import emit_alert
from services.common import (
    bump_version,
    check_occ,
    fetch_or_404,
    get_json_body,
    paginate,
    parse_pagination,
    require_str,
    stamp_create,
    stamp_create_appendonly,
)
from clock import parse_iso
from services.serializers import sensor_reading_view, sensor_view


bp = Blueprint("sensors", __name__)

VALID_SENSOR_TYPES = {"SOIL_MOISTURE", "SOIL_TEMPERATURE", "SOIL_EC", "WEATHER_STATION"}
VALID_SENSOR_STATUSES = {"ONLINE", "OFFLINE", "FAULTY"}


def _validate_poll_interval(val):
    if isinstance(val, bool) or not isinstance(val, int):
        raise poll_interval_out_of_range("poll_interval_seconds must be an integer")
    if val < 30 or val > 3600:
        raise poll_interval_out_of_range()
    return val


@bp.route("/sensors", methods=["POST"])
@require_roles("WaterAdmin")
def create_sensor():
    body = get_json_body()
    plot_id = require_str(body, "plot_id")
    sensor_type = require_str(body, "sensor_type")
    if sensor_type not in VALID_SENSOR_TYPES:
        raise validation_error("sensor_type invalid")
    if "min_valid_value" not in body or body["min_valid_value"] is None:
        raise validation_error("min_valid_value is required")
    if "max_valid_value" not in body or body["max_valid_value"] is None:
        raise validation_error("max_valid_value is required")
    min_v = body["min_valid_value"]
    max_v = body["max_valid_value"]
    if isinstance(min_v, bool) or not isinstance(min_v, (int, float)):
        raise validation_error("min_valid_value must be a number")
    if isinstance(max_v, bool) or not isinstance(max_v, (int, float)):
        raise validation_error("max_valid_value must be a number")

    poll_interval = body.get("poll_interval_seconds", 300)
    _validate_poll_interval(poll_interval)

    with LOCK:
        if plot_id not in DB.plots:
            raise validation_error("plot_id does not exist")
        rec = stamp_create({
            "id": new_id(),
            "plot_id": plot_id,
            "sensor_type": sensor_type,
            "poll_interval_seconds": poll_interval,
            "min_valid_value": float(min_v),
            "max_valid_value": float(max_v),
            "status": "ONLINE",
            "last_reading_at": None,
        })
        DB.sensors[rec["id"]] = rec
        DB.readings_by_sensor.setdefault(rec["id"], [])
    return success_object(sensor_view(rec), status=201)


@bp.route("/sensors/<sensor_id>", methods=["GET"])
def read_sensor(sensor_id):
    if g.role not in {"PlatformAdmin", "WaterAdmin", "Operator"}:
        raise forbidden()
    with LOCK:
        rec = fetch_or_404(DB.sensors, sensor_id)
    return success_object(sensor_view(rec))


@bp.route("/sensors/<sensor_id>", methods=["PATCH"])
@require_roles("WaterAdmin")
def update_sensor(sensor_id):
    body = get_json_body()
    with LOCK:
        rec = fetch_or_404(DB.sensors, sensor_id)
        check_occ(rec, body)

        if "poll_interval_seconds" in body and body["poll_interval_seconds"] is not None:
            _validate_poll_interval(body["poll_interval_seconds"])
            rec["poll_interval_seconds"] = body["poll_interval_seconds"]
        if "min_valid_value" in body and body["min_valid_value"] is not None:
            v = body["min_valid_value"]
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                raise validation_error("min_valid_value must be a number")
            rec["min_valid_value"] = float(v)
        if "max_valid_value" in body and body["max_valid_value"] is not None:
            v = body["max_valid_value"]
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                raise validation_error("max_valid_value must be a number")
            rec["max_valid_value"] = float(v)

        prev_status = rec["status"]
        if "status" in body and body["status"] is not None:
            st = body["status"]
            if st not in VALID_SENSOR_STATUSES:
                raise validation_error("status invalid")
            rec["status"] = st

        bump_version(rec)

        # ONLINE -> OFFLINE flip emits SENSOR_OFFLINE alert
        if prev_status == "ONLINE" and rec["status"] == "OFFLINE":
            plot = DB.plots.get(rec["plot_id"])
            tenant_id = plot.get("tenant_id") if plot else None
            emit_alert(
                rule_code="SENSOR_OFFLINE",
                subject_type="SENSOR",
                subject_id=rec["id"],
                tenant_id=tenant_id,
            )
    return success_object(sensor_view(rec))


# ----- SensorReading -----------------------------------------------------------------------------

@bp.route("/sensors/<sensor_id>/readings", methods=["POST"])
@require_roles("DeviceAgent", "WaterAdmin")
def ingest_reading(sensor_id):
    body = get_json_body()
    if "value" not in body or body["value"] is None:
        raise validation_error("value is required")
    val = body["value"]
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise validation_error("value must be a number")
    if "reading_timestamp" not in body or body["reading_timestamp"] is None:
        raise validation_error("reading_timestamp is required")
    ts_raw = body["reading_timestamp"]
    if not isinstance(ts_raw, str):
        raise validation_error("reading_timestamp must be a string")
    try:
        ts = parse_iso(ts_raw)
    except Exception:
        raise validation_error("reading_timestamp must be ISO 8601")

    with LOCK:
        sensor = fetch_or_404(DB.sensors, sensor_id)
        # Validity classification
        validity = "VALID"
        if val < sensor["min_valid_value"] or val > sensor["max_valid_value"]:
            validity = "OUT_OF_RANGE"

        # Check for three consecutive OUT_OF_RANGE on this sensor.
        recent_ids = DB.readings_by_sensor.get(sensor_id, [])
        prev_two_oor = False
        if validity == "OUT_OF_RANGE" and len(recent_ids) >= 2:
            tail = [DB.sensor_readings[rid] for rid in recent_ids[-2:]]
            if all(r.get("validity") in ("OUT_OF_RANGE", "ABNORMAL_FILTERED") for r in tail):
                # at least two prior OOR readings already → this third (or later) becomes ABNORMAL_FILTERED
                # but only if the immediate prior two are both OUT_OF_RANGE (not already filtered)
                if all(r.get("validity") == "OUT_OF_RANGE" for r in tail):
                    prev_two_oor = True

        emit_filter_alert = False
        if prev_two_oor:
            validity = "ABNORMAL_FILTERED"
            emit_filter_alert = True

        rec = stamp_create_appendonly({
            "id": new_id(),
            "sensor_id": sensor_id,
            "value": float(val),
            "reading_timestamp": ts,
            "validity": validity,
            "archived": False,
        })
        DB.sensor_readings[rec["id"]] = rec
        DB.readings_by_sensor.setdefault(sensor_id, []).append(rec["id"])

        sensor["last_reading_at"] = CLOCK.now()
        bump_version(sensor)

        if emit_filter_alert:
            plot = DB.plots.get(sensor["plot_id"])
            tenant_id = plot.get("tenant_id") if plot else None
            emit_alert(
                rule_code="ABNORMAL_FLOW",
                subject_type="SENSOR",
                subject_id=sensor_id,
                tenant_id=tenant_id,
            )

    return success_object(sensor_reading_view(rec), status=201)


@bp.route("/sensors/<sensor_id>/readings", methods=["GET"])
def list_readings(sensor_id):
    if g.role not in {"PlatformAdmin", "WaterAdmin", "Operator"}:
        raise forbidden()
    limit, offset = parse_pagination()
    include_archived_raw = request.args.get("include_archived")
    include_archived = False
    if include_archived_raw is not None:
        include_archived = include_archived_raw.lower() in ("true", "1", "yes")

    with LOCK:
        # Existence: sensor must exist
        fetch_or_404(DB.sensors, sensor_id)

        rids = DB.readings_by_sensor.get(sensor_id, [])
        items = [DB.sensor_readings[rid] for rid in rids]
        if not include_archived:
            items = [r for r in items if not r.get("archived")]
        items.sort(key=lambda r: r.get("created_at"))
        page, total, has_more = paginate(items, limit, offset)
        data = [sensor_reading_view(r) for r in page]
    return success_array(data, limit, offset, total, has_more)
