"""MeterRead lifecycle (PRD §3.5)."""

from flask import Blueprint, request

import db
from errors import ApiError
from middleware import require_roles
from response import success, list_success
from services.common import (
    get_json_body, require_fields, serialize,
    pagination_params, paginate, sort_by_creation,
)
from services.calculations import HIGH_READING_MULTIPLE
from services.lookups import matching_cycle_for_read

meter_reads_bp = Blueprint("meter_reads", __name__)


def _is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


@meter_reads_bp.route("/meter-reads", methods=["POST"])
@require_roles("MeterTech", "PropertyManager")
def create_meter_read():
    body = get_json_body()
    require_fields(body, "meter_id", "property_id", "period_label", "reading_value")

    meter_id = body["meter_id"]
    if meter_id not in db.meters:
        raise ApiError("ERR_NOT_FOUND", "Meter not found")
    property_id = body["property_id"]
    if property_id not in db.properties:
        raise ApiError("ERR_NOT_FOUND", "Property not found")

    period_label = body["period_label"]
    if not isinstance(period_label, str) or not period_label.strip():
        raise ApiError("ERR_INVALID_REQUEST", "period_label must be a non-empty string")

    reading_value = body["reading_value"]
    if not _is_number(reading_value) or reading_value < 0:
        raise ApiError("ERR_INVALID_REQUEST", "reading_value must be >= 0")

    record = {
        "meter_id": meter_id,
        "property_id": property_id,
        "period_label": period_label,
        "reading_value": reading_value,
        "consumption": 0,
        "re_read_count": 0,
        "flag_reason": None,
        "status": "PENDING",
    }
    db.stamp_create(record)
    db.meter_reads[record["id"]] = record
    return success(serialize(record), status=201)


@meter_reads_bp.route("/meter-reads/<read_id>", methods=["GET"])
@require_roles("PropertyManager", "MeterTech", "Auditor")
def get_meter_read(read_id):
    record = db.meter_reads.get(read_id)
    if record is None:
        raise ApiError("ERR_NOT_FOUND", "MeterRead not found")
    return success(serialize(record), status=200)


@meter_reads_bp.route("/meter-reads", methods=["GET"])
@require_roles("PropertyManager", "MeterTech", "Auditor")
def list_meter_reads():
    meter_id = request.args.get("meter_id")
    property_id = request.args.get("property_id")
    period_label = request.args.get("period_label")
    status = request.args.get("status")
    items = list(db.meter_reads.values())
    if meter_id is not None:
        items = [r for r in items if r["meter_id"] == meter_id]
    if property_id is not None:
        items = [r for r in items if r["property_id"] == property_id]
    if period_label is not None:
        items = [r for r in items if r["period_label"] == period_label]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    items = sort_by_creation(items)
    limit, offset = pagination_params()
    page, total = paginate(items, limit, offset)
    return list_success([serialize(r) for r in page], limit, offset, total)


@meter_reads_bp.route("/meter-reads/<read_id>/submit", methods=["POST"])
@require_roles("MeterTech")
def submit_read(read_id):
    read = db.meter_reads.get(read_id)
    if read is None:
        raise ApiError("ERR_NOT_FOUND", "MeterRead not found")

    body = get_json_body()
    # Optional re-read value validation if provided.
    if "reading_value" in body and body["reading_value"] is not None:
        if not _is_number(body["reading_value"]) or body["reading_value"] < 0:
            raise ApiError("ERR_INVALID_REQUEST", "reading_value must be >= 0")

    if read["status"] not in ("PENDING", "RE_READ_REQUESTED"):
        raise ApiError("ERR_INVALID_STATE", "MeterRead cannot be submitted from its current state")

    # Matching cycle must be OPEN.
    cycle = matching_cycle_for_read(read)
    if cycle is None or cycle["status"] != "OPEN":
        raise ApiError("ERR_CYCLE_NOT_OPEN", "Matching billing cycle is not OPEN")

    # On a re-read submission, overwrite reading_value if a new one is supplied.
    if read["status"] == "RE_READ_REQUESTED":
        if "reading_value" in body and body["reading_value"] is not None:
            read["reading_value"] = body["reading_value"]
    else:
        # First submission from PENDING may also accept an override reading_value.
        if "reading_value" in body and body["reading_value"] is not None:
            read["reading_value"] = body["reading_value"]

    meter = db.meters[read["meter_id"]]
    read["consumption"] = max(0, read["reading_value"] - meter["last_validated_reading"])
    read["status"] = "SUBMITTED"
    db.touch(read)
    return success(serialize(read), status=200)


@meter_reads_bp.route("/meter-reads/<read_id>/validate", methods=["POST"])
@require_roles("PropertyManager")
def validate_read(read_id):
    read = db.meter_reads.get(read_id)
    if read is None:
        raise ApiError("ERR_NOT_FOUND", "MeterRead not found")
    if read["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", "MeterRead is not SUBMITTED")

    meter = db.meters[read["meter_id"]]
    baseline = meter["last_validated_reading"]
    if baseline != 0:
        if read["consumption"] > baseline * HIGH_READING_MULTIPLE:
            raise ApiError("ERR_READING_OUT_OF_RANGE", "Read consumption exceeds high-reading band")

    # Supersede any other SUBMITTED/VALIDATED read for same meter+period.
    for other in db.meter_reads.values():
        if other["id"] == read_id:
            continue
        if other["meter_id"] != read["meter_id"]:
            continue
        if other["period_label"] != read["period_label"]:
            continue
        if other["status"] in ("SUBMITTED", "VALIDATED"):
            other["status"] = "SUPERSEDED"
            db.touch(other)

    read["status"] = "VALIDATED"
    db.touch(read)
    meter["last_validated_reading"] = read["reading_value"]
    db.touch(meter)
    return success(serialize(read), status=200)


@meter_reads_bp.route("/meter-reads/<read_id>/flag", methods=["POST"])
@require_roles("PropertyManager")
def flag_read(read_id):
    read = db.meter_reads.get(read_id)
    if read is None:
        raise ApiError("ERR_NOT_FOUND", "MeterRead not found")

    body = get_json_body()
    require_fields(body, "flag_reason")
    flag_reason = body["flag_reason"]
    if not isinstance(flag_reason, str) or not flag_reason.strip():
        raise ApiError("ERR_INVALID_REQUEST", "flag_reason must be a non-empty string")

    if read["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", "MeterRead is not SUBMITTED")

    read["flag_reason"] = flag_reason
    read["status"] = "FLAGGED"
    db.touch(read)
    return success(serialize(read), status=200)


@meter_reads_bp.route("/meter-reads/<read_id>/request-re-read", methods=["POST"])
@require_roles("PropertyManager")
def request_re_read(read_id):
    read = db.meter_reads.get(read_id)
    if read is None:
        raise ApiError("ERR_NOT_FOUND", "MeterRead not found")
    if read["status"] != "FLAGGED":
        raise ApiError("ERR_INVALID_STATE", "MeterRead is not FLAGGED")

    read["re_read_count"] += 1
    read["status"] = "RE_READ_REQUESTED"
    db.touch(read)
    return success(serialize(read), status=200)
