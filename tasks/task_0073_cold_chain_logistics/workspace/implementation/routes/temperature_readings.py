"""Temperature reading ingestion / archival."""

from __future__ import annotations

from flask import Blueprint, request

from clock import clock, parse_iso8601
from db import db, new_id
from errors import err
from middleware import require_roles
from response import object_response, array_response
from serializers import reading as ser_reading
from services.alerts import maybe_open_alert
from services.precision import to_float_2, to_float_4
from validators import (
    get_pagination,
    paginate,
    require_dict,
    require_str,
    require_iso,
)


bp = Blueprint("readings", __name__)


SENSOR_KINDS = {"COMPARTMENT", "CARGO_BOX"}


def _compute_validity_and_violation(reading_body: dict, task: dict) -> tuple[str, str]:
    """Pin validity and threshold-violation verdict at ingest."""
    # Stage 1: window check
    captured = parse_iso8601(reading_body.get("captured_at"))
    planned_start = parse_iso8601(task["planned_start_at"])
    if captured is None:
        return "INVALID_SCHEMA", "WITHIN"
    if captured < planned_start or captured > clock.now():
        return "INVALID_OUT_OF_WINDOW", "WITHIN"

    # Stage 2: schema/range check
    sensor_kind = reading_body.get("sensor_kind")
    gps_lat = reading_body.get("gps_lat")
    gps_lng = reading_body.get("gps_lng")
    temp = reading_body.get("temperature_celsius")
    if sensor_kind not in SENSOR_KINDS:
        return "INVALID_SCHEMA", "WITHIN"
    if not isinstance(gps_lat, (int, float)) or isinstance(gps_lat, bool):
        return "INVALID_SCHEMA", "WITHIN"
    if not isinstance(gps_lng, (int, float)) or isinstance(gps_lng, bool):
        return "INVALID_SCHEMA", "WITHIN"
    if not isinstance(temp, (int, float)) or isinstance(temp, bool):
        return "INVALID_SCHEMA", "WITHIN"
    if not (-90.0 <= gps_lat <= 90.0):
        return "INVALID_SCHEMA", "WITHIN"
    if not (-180.0 <= gps_lng <= 180.0):
        return "INVALID_SCHEMA", "WITHIN"
    if not (-80.0 <= temp <= 80.0):
        return "INVALID_SCHEMA", "WITHIN"

    # VALID. Compute violation
    if temp < task["temp_min_celsius"]:
        return "VALID", "BELOW_MIN"
    if temp > task["temp_max_celsius"]:
        return "VALID", "ABOVE_MAX"
    return "VALID", "WITHIN"


@bp.post("/transport-tasks/<task_id>/temperature-readings")
@require_roles("SYSTEM", "DISPATCHER")
def ingest(task_id):
    with db.global_lock:
        task = db.tasks.get(task_id)
        if task is None:
            err("ERR_NOT_FOUND", "TransportTask not found.")

        body = require_dict(request.get_json(silent=True) or {})

        # Required fields (loose-typed; we'll let validity check classify schema)
        sensor_id = require_str(body.get("sensor_id"), field="sensor_id", min_len=1, max_len=64)
        idem_key = require_str(
            body.get("idempotency_key"), field="idempotency_key", min_len=1, max_len=128
        )
        require_iso(body.get("captured_at"), field="captured_at")

        strict_param = request.args.get("strict", "").lower()
        strict = strict_param == "true"

        # Idempotency check first (per (task_id, idempotency_key))
        idem_lookup = (task_id, idem_key)
        if idem_lookup in db.reading_idempotency:
            existing_id = db.reading_idempotency[idem_lookup]
            existing = db.readings.get(existing_id)
            return object_response(ser_reading(existing), status_code=200)

        # Task must be in DISPATCHED/IN_TRANSIT/AT_STOP for ingest
        if task["status"] not in {"DISPATCHED", "IN_TRANSIT", "AT_STOP"}:
            err("ERR_INVALID_STATE", "Task must be active to ingest readings.")

        # Determine validity + violation
        validity, violation = _compute_validity_and_violation(body, task)

        if validity == "INVALID_OUT_OF_WINDOW" and strict:
            err("ERR_READING_OUT_OF_WINDOW", "captured_at outside window.")

        # Construct reading row
        now_iso = clock.now_iso()
        temp_raw = body.get("temperature_celsius")
        gps_lat_raw = body.get("gps_lat")
        gps_lng_raw = body.get("gps_lng")

        def _safe_2(value):
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return to_float_2(value)
            return value

        def _safe_4(value):
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return to_float_4(value)
            return value

        reading_row = {
            "id": new_id(),
            "task_id": task_id,
            "sensor_id": sensor_id,
            "sensor_kind": body.get("sensor_kind"),
            "temperature_celsius": _safe_2(temp_raw),
            "gps_lat": _safe_4(gps_lat_raw),
            "gps_lng": _safe_4(gps_lng_raw),
            "captured_at": body.get("captured_at"),
            "idempotency_key": idem_key,
            "validity": validity,
            "violation": violation,
            "created_at": now_iso,
        }
        db.readings.put(reading_row)
        db.reading_idempotency[idem_lookup] = reading_row["id"]

        # Auto-open / recompute alerts on VALID violating readings
        if validity == "VALID" and violation != "WITHIN":
            maybe_open_alert(task, reading_row)

    return object_response(ser_reading(reading_row), status_code=201)


@bp.get("/transport-tasks/<task_id>/temperature-readings")
@require_roles(
    "SHIPPER", "CARRIER", "DRIVER", "DISPATCHER", "COMPLIANCE_OFFICER", "INSURANCE_ADJUSTER"
)
def list_readings(task_id):
    task = db.tasks.get(task_id)
    if task is None:
        err("ERR_NOT_FOUND", "TransportTask not found.")
    limit, offset = get_pagination(request.args)
    rows = db.readings_for_task(task_id)
    validity = request.args.get("validity")
    if validity:
        rows = [r for r in rows if r["validity"] == validity]
    violation = request.args.get("violation")
    if violation:
        rows = [r for r in rows if r["violation"] == violation]
    after = request.args.get("captured_after")
    if after:
        after_dt = parse_iso8601(after)
        if after_dt is None:
            err("ERR_VALIDATION", "captured_after must be ISO 8601.")
        rows = [r for r in rows if parse_iso8601(r["captured_at"]) >= after_dt]
    before = request.args.get("captured_before")
    if before:
        before_dt = parse_iso8601(before)
        if before_dt is None:
            err("ERR_VALIDATION", "captured_before must be ISO 8601.")
        rows = [r for r in rows if parse_iso8601(r["captured_at"]) < before_dt]
    rows.sort(key=lambda r: r["created_at"])
    page, total = paginate(rows, limit, offset)
    return array_response(
        [ser_reading(r) for r in page], limit=limit, offset=offset, total_count=total
    )


@bp.post("/transport-tasks/<task_id>/temperature-readings/archive")
@require_roles("COMPLIANCE_OFFICER")
def archive(task_id):
    task = db.tasks.get(task_id)
    if task is None:
        err("ERR_NOT_FOUND", "TransportTask not found.")
    if task["status"] != "CLOSED":
        err("ERR_INVALID_STATE", "Task must be CLOSED to archive readings.")
    closed_at = parse_iso8601(task.get("closed_at"))
    if closed_at is None:
        err("ERR_INVALID_STATE", "Task is missing closed_at.")
    count = 0
    for r in db.readings_for_task(task_id):
        if r["validity"] != "VALID":
            continue
        captured = parse_iso8601(r["captured_at"])
        if captured is None or captured >= closed_at:
            continue
        r["validity"] = "ARCHIVED"
        count += 1
    return object_response({"archived_count": count})
