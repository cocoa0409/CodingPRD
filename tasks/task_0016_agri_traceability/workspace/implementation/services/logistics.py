"""LogisticsLeg + SensorReading services."""

from flask import g

from common import (
    get_json_body,
    paginate,
    parse_iso_datetime,
    parse_pagination,
    require_field,
    sort_by_created_at,
    stamp_create,
    stamp_create_immutable,
    stamp_update,
)
from db import db
from errors import (
    ERR_FORBIDDEN,
    ERR_INVALID_STATE,
    ERR_LEG_INTERVAL_OVERLAP,
    ERR_NOT_FOUND,
    ERR_READING_OUT_OF_LEG_WINDOW,
    ERR_VALIDATION,
    ERR_VERSION_CONFLICT,
    raise_error,
)
from services.audit import record_audit
from services.planting_batch import get_batch_or_404


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------

def _serialize(leg: dict) -> dict:
    return {
        "id": leg["id"],
        "created_at": leg["created_at"],
        "updated_at": leg["updated_at"],
        "version": leg["version"],
        "planting_batch_id": leg["planting_batch_id"],
        "leg_index": leg["leg_index"],
        "from_party_id": leg["from_party_id"],
        "to_party_id": leg["to_party_id"],
        "depart_at": leg["depart_at"],
        "arrive_at": leg["arrive_at"],
        "temperature_min_c": leg["temperature_min_c"],
        "temperature_max_c": leg["temperature_max_c"],
        "status": leg["status"],
        "abnormal_segment_count": leg["abnormal_segment_count"],
        "handover_acknowledged": leg["handover_acknowledged"],
    }


def _serialize_reading(r: dict) -> dict:
    return {
        "id": r["id"],
        "created_at": r["created_at"],
        "logistics_leg_id": r["logistics_leg_id"],
        "device_id": r["device_id"],
        "idempotency_key": r["idempotency_key"],
        "reading_at": r["reading_at"],
        "temperature_c": r["temperature_c"],
        "out_of_range": r["out_of_range"],
    }


def get_leg_or_404(leg_id):
    leg = db.logistics_legs.get(leg_id)
    if leg is None:
        raise_error(ERR_NOT_FOUND, f"logistics leg {leg_id} not found")
    return leg


# ---------------------------------------------------------------------------
# Leg create
# ---------------------------------------------------------------------------

def create_leg(batch_id):
    body = get_json_body()
    leg_index = body.get("leg_index")
    if leg_index is None:
        raise_error(ERR_VALIDATION, "missing required field leg_index")
    try:
        leg_index = int(leg_index)
    except Exception:
        raise_error(ERR_VALIDATION, "leg_index must be integer")
    if leg_index < 1:
        raise_error(ERR_VALIDATION, "leg_index must be >= 1")
    from_party_id = require_field(body, "from_party_id", str)
    to_party_id = require_field(body, "to_party_id", str)
    depart_at = require_field(body, "depart_at", str)
    arrive_at = require_field(body, "arrive_at", str)
    tmin = body.get("temperature_min_c")
    tmax = body.get("temperature_max_c")
    if tmin is None or tmax is None:
        raise_error(ERR_VALIDATION, "temperature_min_c and temperature_max_c required")
    try:
        tmin_f = float(tmin)
        tmax_f = float(tmax)
    except Exception:
        raise_error(ERR_VALIDATION, "temperature bounds must be numeric")
    if tmax_f < tmin_f:
        raise_error(ERR_VALIDATION, "temperature_max_c must be >= temperature_min_c")

    dep = parse_iso_datetime(depart_at, "depart_at")
    arr = parse_iso_datetime(arrive_at, "arrive_at")
    if arr <= dep:
        raise_error(ERR_LEG_INTERVAL_OVERLAP, "arrive_at must be > depart_at")

    with db.lock:
        batch = get_batch_or_404(batch_id)

        # Uniqueness on (planting_batch_id, leg_index) — not separately specified
        # error; treat as ERR_LEG_INTERVAL_OVERLAP per scaffold's validation cluster.
        for l in db.logistics_legs.values():
            if l["planting_batch_id"] == batch_id and l["leg_index"] == leg_index:
                raise_error(ERR_LEG_INTERVAL_OVERLAP, "leg_index already used for this batch")
            if l["planting_batch_id"] == batch_id:
                # closed-open overlap detection on intervals [d, a)
                ld = parse_iso_datetime(l["depart_at"])
                la = parse_iso_datetime(l["arrive_at"])
                # overlap if max(deps) < min(arrs)
                if max(dep, ld) < min(arr, la):
                    raise_error(ERR_LEG_INTERVAL_OVERLAP,
                                "leg interval overlaps another leg of the same batch")

        leg = {
            "id": db.new_id(),
            "planting_batch_id": batch_id,
            "leg_index": leg_index,
            "from_party_id": from_party_id,
            "to_party_id": to_party_id,
            "depart_at": depart_at,
            "arrive_at": arrive_at,
            "temperature_min_c": tmin_f,
            "temperature_max_c": tmax_f,
            "status": "PLANNED",
            "abnormal_segment_count": 0,
            "handover_acknowledged": False,
        }
        stamp_create(leg)
        db.logistics_legs[leg["id"]] = leg
        record_audit(
            "LogisticsLeg", leg["id"], "CREATE", "PLANNED",
            before_state=None,
            change_summary={"batch_id": batch_id, "leg_index": leg_index},
        )
    return _serialize(leg)


def depart_leg(leg_id):
    body = get_json_body()
    with db.lock:
        leg = get_leg_or_404(leg_id)
        if "version" in body and body["version"] is not None:
            if body["version"] != leg["version"]:
                raise_error(ERR_VERSION_CONFLICT, "version mismatch")
        if leg["status"] != "PLANNED":
            raise_error(ERR_INVALID_STATE, f"cannot depart leg in {leg['status']}")
        batch = db.planting_batches.get(leg["planting_batch_id"])
        if batch is None:
            raise_error(ERR_NOT_FOUND, "parent batch missing")
        if batch["posture"] == "BLOCKED":
            raise_error(ERR_INVALID_STATE, "batch posture BLOCKED")
        if batch["status"] not in {"INSPECTED_PASS", "IN_TRANSIT"}:
            raise_error(ERR_INVALID_STATE, f"batch status {batch['status']} not eligible")

        # First leg of the batch must have at least one minted QR among harvest records
        is_first_leg = not any(
            l["planting_batch_id"] == batch["id"] and l["status"] != "PLANNED"
            for l in db.logistics_legs.values()
            if l["id"] != leg["id"]
        )
        # If batch.status is INSPECTED_PASS, this is the very first dispatch; require QR.
        if batch["status"] == "INSPECTED_PASS":
            has_qr = False
            for hr in db.harvest_records.values():
                if hr["planting_batch_id"] == batch["id"] and hr["id"] in db.qr_by_harvest:
                    has_qr = True
                    break
            if not has_qr:
                raise_error(ERR_INVALID_STATE, "no QR code minted for any harvest of the batch")

        before = leg["status"]
        leg["status"] = "IN_TRANSIT"
        stamp_update(leg)
        record_audit(
            "LogisticsLeg", leg["id"], "STATE_TRANSITION", "IN_TRANSIT",
            before_state=before,
            change_summary={"trigger": "depart"},
        )
        if batch["status"] == "INSPECTED_PASS":
            before_b = batch["status"]
            batch["status"] = "IN_TRANSIT"
            stamp_update(batch)
            record_audit(
                "PlantingBatch", batch["id"], "STATE_TRANSITION", "IN_TRANSIT",
                before_state=before_b,
                change_summary={"trigger": "first_leg_depart"},
            )
    return _serialize(leg)


def acknowledge_leg(leg_id):
    body = get_json_body()
    with db.lock:
        leg = get_leg_or_404(leg_id)
        if "version" in body and body["version"] is not None:
            if body["version"] != leg["version"]:
                raise_error(ERR_VERSION_CONFLICT, "version mismatch")
        # State validation
        if leg["status"] not in {"IN_TRANSIT", "ABNORMAL"}:
            raise_error(ERR_INVALID_STATE, f"cannot acknowledge leg in {leg['status']}")

        role = g.user_role
        # ABNORMAL legs: only RegulatoryOfficer may acknowledge
        if leg["status"] == "ABNORMAL":
            if role != "RegulatoryOfficer":
                raise_error(ERR_FORBIDDEN, "only RegulatoryOfficer may acknowledge ABNORMAL leg")
        else:
            # IN_TRANSIT: Distributor must equal to_party_id; LogisticsOperator and
            # RegulatoryOfficer also permitted by RBAC matrix but we do not require
            # ownership for those. Distributor ownership check is mechanical.
            if role == "Distributor" and g.user_id != leg["to_party_id"]:
                raise_error(ERR_FORBIDDEN, "distributor X-User-ID must equal leg.to_party_id")

        # If leg was ABNORMAL, ensure recall (if any) has been COMPLETED/CLOSED/CANCELLED.
        if leg["status"] == "ABNORMAL":
            batch = db.planting_batches.get(leg["planting_batch_id"])
            if batch is not None:
                # Find any active recall for this batch
                for ro in db.recall_orders.values():
                    if ro["planting_batch_id"] == batch["id"] and ro["status"] in {
                        "INITIATED", "NOTIFIED", "IN_PROGRESS",
                    }:
                        raise_error(ERR_INVALID_STATE,
                                    "cannot acknowledge ABNORMAL leg while recall is active")

        # Final-leg guard for IN_TRANSIT path: if abnormal_segment_count > 0
        # the leg should be in ABNORMAL state already (set by detector). The check
        # for IN_TRANSIT path with non-zero abnormals: deny unless recall closed.
        if leg["status"] == "IN_TRANSIT" and leg["abnormal_segment_count"] > 0:
            batch = db.planting_batches.get(leg["planting_batch_id"])
            for ro in db.recall_orders.values():
                if ro["planting_batch_id"] == batch["id"] and ro["status"] in {
                    "INITIATED", "NOTIFIED", "IN_PROGRESS",
                }:
                    raise_error(ERR_INVALID_STATE,
                                "leg has abnormal segments; recall pending")

        before = leg["status"]
        leg["status"] = "HANDED_OVER"
        leg["handover_acknowledged"] = True
        stamp_update(leg)
        record_audit(
            "LogisticsLeg", leg["id"], "STATE_TRANSITION", "HANDED_OVER",
            before_state=before,
            change_summary={"trigger": "acknowledge"},
        )

        # If last leg → batch DELIVERED
        batch = db.planting_batches.get(leg["planting_batch_id"])
        if batch is not None:
            max_idx = 0
            for l in db.logistics_legs.values():
                if l["planting_batch_id"] == batch["id"]:
                    if l["leg_index"] > max_idx:
                        max_idx = l["leg_index"]
            if leg["leg_index"] == max_idx and batch["status"] == "IN_TRANSIT":
                before_b = batch["status"]
                batch["status"] = "DELIVERED"
                stamp_update(batch)
                record_audit(
                    "PlantingBatch", batch["id"], "STATE_TRANSITION", "DELIVERED",
                    before_state=before_b,
                    change_summary={"trigger": "final_leg_acknowledged"},
                )
    return _serialize(leg)


def list_legs(batch_id, args):
    get_batch_or_404(batch_id)
    limit, offset = parse_pagination()
    items = [l for l in db.logistics_legs.values() if l["planting_batch_id"] == batch_id]
    items.sort(key=lambda l: l["leg_index"])
    page, total = paginate(items, limit, offset)
    return [_serialize(l) for l in page], limit, offset, total


# ---------------------------------------------------------------------------
# Sensor readings
# ---------------------------------------------------------------------------

def create_sensor_reading(leg_id):
    body = get_json_body()
    device_id = require_field(body, "device_id", str)
    idempotency_key = require_field(body, "idempotency_key", str)
    reading_at = require_field(body, "reading_at", str)
    temperature_c = body.get("temperature_c")
    if temperature_c is None:
        raise_error(ERR_VALIDATION, "missing required field temperature_c")
    try:
        temp_f = float(temperature_c)
    except Exception:
        raise_error(ERR_VALIDATION, "temperature_c must be numeric")
    rd_at = parse_iso_datetime(reading_at, "reading_at")

    with db.lock:
        leg = get_leg_or_404(leg_id)

        # Idempotency check (priority high — return original on duplicate)
        key = (leg_id, idempotency_key)
        existing_id = db.sensor_idempotency.get(key)
        if existing_id is not None:
            existing = db.sensor_readings[existing_id]
            return _serialize_reading(existing), True  # replay flag

        # Window check: (depart_at, arrive_at]
        dep = parse_iso_datetime(leg["depart_at"])
        arr = parse_iso_datetime(leg["arrive_at"])
        if rd_at <= dep or rd_at > arr:
            raise_error(ERR_READING_OUT_OF_LEG_WINDOW,
                        "reading_at not in (depart_at, arrive_at]")

        out_of_range = (temp_f < float(leg["temperature_min_c"])
                        or temp_f > float(leg["temperature_max_c"]))
        sr = {
            "id": db.new_id(),
            "logistics_leg_id": leg_id,
            "device_id": device_id,
            "idempotency_key": idempotency_key,
            "reading_at": reading_at,
            "temperature_c": temp_f,
            "out_of_range": out_of_range,
        }
        stamp_create_immutable(sr)
        db.sensor_readings[sr["id"]] = sr
        db.sensor_idempotency[key] = sr["id"]

        # Run breach detector
        _recompute_breach_count(leg)

    return _serialize_reading(sr), False


def _recompute_breach_count(leg):
    """Recompute abnormal_segment_count from scratch via chronological replay.

    Auto-transition leg → ABNORMAL and emit auto-recall when count >= 1 and
    leg is currently IN_TRANSIT and parent batch.recall_status == NONE.
    """
    readings = [r for r in db.sensor_readings.values()
                if r["logistics_leg_id"] == leg["id"]]
    readings.sort(key=lambda r: (r["reading_at"], r["created_at"]))
    runs = 0
    current = 0
    for r in readings:
        if r["out_of_range"]:
            current += 1
            if current == 3:
                runs += 1
        else:
            current = 0
    leg["abnormal_segment_count"] = runs
    stamp_update(leg)

    if runs >= 1 and leg["status"] == "IN_TRANSIT":
        batch = db.planting_batches.get(leg["planting_batch_id"])
        before = leg["status"]
        leg["status"] = "ABNORMAL"
        stamp_update(leg)
        record_audit(
            "LogisticsLeg", leg["id"], "STATE_TRANSITION", "ABNORMAL",
            before_state=before,
            change_summary={"trigger": "cold_chain_breach", "runs": runs},
        )
        if batch is not None and batch.get("recall_status") == "NONE":
            from services.recall import _auto_initiate_recall
            _auto_initiate_recall(batch, reason_code="COLD_CHAIN_BREACH")


def list_readings(leg_id, args):
    get_leg_or_404(leg_id)
    limit, offset = parse_pagination()
    items = [r for r in db.sensor_readings.values() if r["logistics_leg_id"] == leg_id]
    items.sort(key=lambda r: (r["reading_at"], r["created_at"]))
    page, total = paginate(items, limit, offset)
    return [_serialize_reading(r) for r in page], limit, offset, total
