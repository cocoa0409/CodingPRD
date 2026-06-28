"""Vehicle endpoints (PRD §3.1) + VIN history records (PRD §3.6).

Vehicle is an immutable lightweight record: id + created_at only.
"""
import re

from flask import Blueprint

from db import db, stamp_create
from errors import err
from helpers import (check_enum, get_json_body, iso_from_dt, paginate,
                     parse_iso8601, parse_pagination, require_fields, serialize,
                     sort_by_created)
from middleware import require_roles
from response import success
from services.lookups import get_vehicle, get_vin_history_record

bp = Blueprint("vehicles", __name__)

# VIN: exactly 17 uppercase alphanumeric chars, excludes I, O, Q.
VIN_RE = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")

RECORD_TYPES = {"TITLE", "ODOMETER", "BRANDING"}
BRANDING_CODES = {"NONE", "SALVAGE", "FLOOD", "LEMON", "REBUILT"}


def serialize_vehicle(v):
    return serialize(v)


def serialize_history_record(r):
    out = serialize(r)
    out.pop("event_date_dt", None)
    return out


@bp.route("/vehicles", methods=["POST"])
@require_roles("OpsAdmin", "AccountHolder")
def create_vehicle():
    body = get_json_body()
    require_fields(body, ["vin", "year", "make", "model"])
    vin = body["vin"]
    if not isinstance(vin, str) or not VIN_RE.match(vin):
        raise err("ERR_INVALID_REQUEST", "vin must be exactly 17 valid chars (no I,O,Q)")
    year = body["year"]
    if not isinstance(year, int) or isinstance(year, bool):
        raise err("ERR_INVALID_REQUEST", "year must be an integer")

    v = {
        "vin": vin,
        "year": year,
        "make": body["make"],
        "model": body["model"],
    }
    stamp_create(v, full=False)
    db.vehicles[v["id"]] = v
    return success(serialize_vehicle(v), status=201)


@bp.route("/vehicles/<vehicle_id>", methods=["GET"])
@require_roles("OpsAdmin", "AccountHolder")
def get_vehicle_ep(vehicle_id):
    v = get_vehicle(vehicle_id)
    return success(serialize_vehicle(v), status=200)


@bp.route("/vehicles/<vehicle_id>/history-records", methods=["POST"])
@require_roles("OpsAdmin")
def append_history_record(vehicle_id):
    get_vehicle(vehicle_id)
    body = get_json_body()
    require_fields(body, ["record_type", "event_date"])
    check_enum(body["record_type"], RECORD_TYPES, "record_type")
    event_dt = parse_iso8601(body["event_date"], "event_date")

    odometer_value = body.get("odometer_value", 0)
    if odometer_value is None:
        odometer_value = 0
    if not isinstance(odometer_value, int) or isinstance(odometer_value, bool):
        raise err("ERR_INVALID_REQUEST", "odometer_value must be an integer")

    branding_code = body.get("branding_code", "NONE")
    if branding_code is None:
        branding_code = "NONE"
    check_enum(branding_code, BRANDING_CODES, "branding_code")

    title_state = body.get("title_state", "")
    if title_state is None:
        title_state = ""

    rec = {
        "vehicle_id": vehicle_id,
        "record_type": body["record_type"],
        "event_date": iso_from_dt(event_dt),
        "event_date_dt": event_dt,
        "odometer_value": odometer_value,
        "branding_code": branding_code,
        "title_state": title_state,
    }
    stamp_create(rec, full=False)
    db.vin_history_records[rec["id"]] = rec
    return success(serialize_history_record(rec), status=201)


@bp.route("/vin-history-records/<record_id>", methods=["GET"])
@require_roles("OpsAdmin", "AccountHolder")
def get_history_record_ep(record_id):
    rec = get_vin_history_record(record_id)
    return success(serialize_history_record(rec), status=200)


@bp.route("/vin-history-records", methods=["GET"])
@require_roles("OpsAdmin", "AccountHolder")
def list_history_records():
    limit, offset = parse_pagination()
    vehicle_id = None
    from flask import request
    vehicle_id = request.args.get("vehicle_id")
    items = list(db.vin_history_records.values())
    if vehicle_id is not None:
        items = [r for r in items if r["vehicle_id"] == vehicle_id]
    items = sort_by_created(items)
    page, meta = paginate(items, limit, offset)
    return success([serialize_history_record(r) for r in page], status=200, pagination=meta)
