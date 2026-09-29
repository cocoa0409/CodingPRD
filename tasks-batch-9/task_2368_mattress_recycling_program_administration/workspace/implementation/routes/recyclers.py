"""Recycler certification and commodity output records."""

from decimal import Decimal

from flask import Blueprint, g

import calc
import response
import services
from db import clock, db
from errors import ApiError
from middleware import (ADMIN, AUDITOR, RECYCLER, SITE_OPERATOR, auth,
                        get_commodity_record, get_program, get_recycler, own)
from util import (F, apply_filters, base_record, dec, pagination, paginate,
                  public, sort_records, touch, validate_body)

bp = Blueprint("recyclers", __name__)

READ_ROLES = [ADMIN, AUDITOR, RECYCLER, SITE_OPERATOR]


@bp.post("/recyclers")
def create_recycler():
    auth([ADMIN])
    body = validate_body([
        F("state_program_id", "string"),
        F("facility_name", "string"),
        F("accepted_unit_classes", "array", min_items=1,
          item_enum=["MATTRESS", "FOUNDATION"]),
    ])
    program = get_program(body["state_program_id"])
    rec = base_record()
    rec.update({
        "state_program_id": program["id"],
        "facility_name": body["facility_name"],
        "accepted_unit_classes": list(body["accepted_unit_classes"]),
        "certification_status": "PROVISIONAL",
        "certified_at": None,
        "units_received_count": 0,
        "units_processed_count": 0,
        "units_rejected_count": 0,
        "verified_output_weight_kg": 0.0,
        "diversion_rate_pct": 0.0,
    })
    db.recyclers[rec["id"]] = rec
    return response.obj(public(rec), 201)


@bp.get("/recyclers/<recycler_id>")
def read_recycler(recycler_id):
    auth(READ_ROLES)
    recycler = get_recycler(recycler_id)
    if g.role == RECYCLER:
        own(recycler["id"])
    return response.obj(public(recycler))


@bp.get("/recyclers")
def list_recyclers():
    auth(READ_ROLES)
    limit, offset = pagination()
    records = sort_records(list(db.recyclers.values()))
    records = apply_filters(records, [
        ("state_program_id", "state_program_id"),
        ("certification_status", "certification_status"),
    ])
    window, total = paginate(records, limit, offset)
    return response.arr([public(r) for r in window], limit, offset, total)


@bp.post("/recyclers/<recycler_id>/certify")
def certify(recycler_id):
    auth([ADMIN])
    recycler = get_recycler(recycler_id)
    if recycler["certification_status"] != "PROVISIONAL":
        raise ApiError("ERR_RECYCLER_CERT_STATE_INVALID")
    recycler["certification_status"] = "CERTIFIED"
    recycler["certified_at"] = clock.stamp()
    touch(recycler)
    return response.obj(public(recycler))


@bp.post("/recyclers/<recycler_id>/suspend-certification")
def suspend_certification(recycler_id):
    auth([ADMIN])
    body = validate_body([F("reason", "string")])
    recycler = get_recycler(recycler_id)
    if recycler["certification_status"] != "CERTIFIED":
        raise ApiError("ERR_RECYCLER_CERT_STATE_INVALID")
    del body
    recycler["certification_status"] = "SUSPENDED"
    recycler["certified_at"] = None
    touch(recycler)
    return response.obj(public(recycler))


@bp.post("/recyclers/<recycler_id>/recertify")
def recertify(recycler_id):
    auth([ADMIN])
    recycler = get_recycler(recycler_id)
    if recycler["certification_status"] != "SUSPENDED":
        raise ApiError("ERR_RECYCLER_CERT_STATE_INVALID")
    if dec(recycler["diversion_rate_pct"]) < calc.MIN_RECERTIFICATION_DIVERSION_PCT:
        raise ApiError("ERR_DIVERSION_RATE_BELOW_MINIMUM")
    recycler["certification_status"] = "CERTIFIED"
    recycler["certified_at"] = clock.stamp()
    touch(recycler)
    return response.obj(public(recycler))


# --------------------------------------------------------------------------
# Commodity output records
# --------------------------------------------------------------------------
@bp.post("/recyclers/<recycler_id>/commodity-output-records")
def create_record(recycler_id):
    auth([RECYCLER])
    body = validate_body([
        F("commodity", "enum", enum=["STEEL", "FOAM", "FIBER", "WOOD"]),
        F("output_weight_kg", "number", exclusive_min=0),
        F("source_period_month", "string", pattern=r"^[0-9]{4}-(0[1-9]|1[0-2])$"),
    ])
    recycler = get_recycler(recycler_id)
    own(recycler["id"])

    rec = base_record()
    rec.update({
        "recycler_id": recycler["id"],
        "commodity": body["commodity"],
        "output_weight_kg": body["output_weight_kg"],
        "source_period_month": body["source_period_month"],
        "record_status": "SUBMITTED",
        "verified_by_user_id": None,
    })
    db.commodity_output_records[rec["id"]] = rec
    return response.obj(public(rec), 201)


@bp.get("/recyclers/<recycler_id>/commodity-output-records")
def list_records(recycler_id):
    auth([ADMIN, AUDITOR, RECYCLER])
    limit, offset = pagination()
    recycler = get_recycler(recycler_id)
    if g.role == RECYCLER:
        own(recycler["id"])
    records = sort_records([r for r in db.commodity_output_records.values()
                            if r["recycler_id"] == recycler["id"]])
    records = apply_filters(records, [
        ("record_status", "record_status"),
        ("commodity", "commodity"),
    ])
    window, total = paginate(records, limit, offset)
    return response.arr([public(r) for r in window], limit, offset, total)


@bp.post("/commodity-output-records/<record_id>/verify")
def verify_record(record_id):
    auth([AUDITOR])
    record = get_commodity_record(record_id)
    if record["record_status"] != "SUBMITTED":
        raise ApiError("ERR_COMMODITY_RECORD_NOT_SUBMITTED")
    record["record_status"] = "VERIFIED"
    record["verified_by_user_id"] = g.user_id
    touch(record)
    recycler = db.recyclers[record["recycler_id"]]
    services.refresh_recycler(recycler)
    touch(recycler)
    return response.obj(public(record))
