"""Consumer and SkipTrace endpoints."""
from flask import Blueprint, request

from db import db, stamp_create, touch
from errors import ApiError, ERR_NOT_FOUND
from middleware import require_roles
from response import object_response, array_response
from serializers import serialize_consumer, serialize_skip_trace
from pagination import paginate
from validation import (
    get_body, require_str, optional_str, optional_int, require_enum, invalid,
)

bp = Blueprint("consumers", __name__)

SKIP_RESULTS = {"LOCATED", "NOT_FOUND"}


@bp.route("/consumers", methods=["POST"])
@require_roles("Creditor", "Collector")
def create_consumer():
    body = get_body()
    full_name = require_str(body, "full_name")
    tz = optional_int(body, "timezone_offset_minutes", default=0)
    phone = optional_str(body, "phone", default=None)
    address = optional_str(body, "address", default=None)
    c = stamp_create({
        "full_name": full_name,
        "timezone_offset_minutes": tz,
        "phone": phone,
        "address": address,
        "contactability": "UNKNOWN",
    })
    db.consumers[c["id"]] = c
    return object_response(serialize_consumer(c), status=201)


@bp.route("/consumers/<cid>", methods=["GET"])
@require_roles("Creditor", "Collector", "ComplianceOfficer", "BureauOperator", "System")
def get_consumer(cid):
    c = db.consumers.get(cid)
    if c is None:
        raise ApiError(*ERR_NOT_FOUND, message="Consumer not found")
    return object_response(serialize_consumer(c), status=200)


# ---- SkipTrace ----
@bp.route("/skip-traces", methods=["POST"])
@require_roles("Collector")
def create_skip_trace():
    body = get_body()
    consumer_id = require_str(body, "consumer_id")
    consumer = db.consumers.get(consumer_id)
    if consumer is None:
        raise ApiError(*ERR_NOT_FOUND, message="Consumer not found")
    result = require_enum(body, "result", SKIP_RESULTS)
    new_phone = optional_str(body, "new_phone", default=None)
    new_address = optional_str(body, "new_address", default=None)
    st = stamp_create({
        "consumer_id": consumer_id,
        "result": result,
        "new_phone": new_phone,
        "new_address": new_address,
    })
    db.skip_traces[st["id"]] = st
    # Side effects on the consumer.
    if result == "LOCATED":
        if new_phone is not None:
            consumer["phone"] = new_phone
        if new_address is not None:
            consumer["address"] = new_address
        consumer["contactability"] = "LOCATED"
        touch(consumer)
    else:  # NOT_FOUND
        consumer["contactability"] = "UNLOCATABLE"
        touch(consumer)
    return object_response(serialize_skip_trace(st), status=201)


@bp.route("/skip-traces/<sid>", methods=["GET"])
@require_roles("Collector", "ComplianceOfficer", "System")
def get_skip_trace(sid):
    st = db.skip_traces.get(sid)
    if st is None:
        raise ApiError(*ERR_NOT_FOUND, message="SkipTrace not found")
    return object_response(serialize_skip_trace(st), status=200)


@bp.route("/skip-traces", methods=["GET"])
@require_roles("Collector", "ComplianceOfficer", "System")
def list_skip_traces():
    consumer_id = request.args.get("consumer_id")
    items = list(db.skip_traces.values())
    if consumer_id:
        items = [s for s in items if s["consumer_id"] == consumer_id]
    page, limit, offset, total = paginate(items)
    return array_response([serialize_skip_trace(s) for s in page], limit, offset, total)
