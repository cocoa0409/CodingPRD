"""Symptom protocols — the clinical rule sets the acuity score is built from."""
from flask import Blueprint

import lookups
from auth import ALL_ROLES, PLATFORM_ADMIN, authorize
from envelope import list_response, object_response, pagination_params
from errors import ApiError
from serializers import protocol_json
from store import base_record, ordered, store, touch
from util import DISPOSITION_LEVELS, PROTOCOL_CODE_RE
from validators import (body, get_bool, get_enum, get_int, get_string,
                        query_enum, query_string)

bp = Blueprint("protocols", __name__)

PROTOCOL_STATUSES = ("ACTIVE", "RETIRED")
DEFAULT_INFANT_MODIFIER_POINTS = 20


@bp.route("/symptom-protocols", methods=["POST"])
@authorize([PLATFORM_ADMIN])
def create_protocol():
    data = body()
    code = get_string(data, "code", pattern=PROTOCOL_CODE_RE)
    title = get_string(data, "title", min_len=1, max_len=120)
    base_severity = get_int(data, "base_severity", minimum=0, maximum=100)
    min_age = get_int(data, "min_age_years", minimum=0, maximum=120)
    max_age = get_int(data, "max_age_years", minimum=0, maximum=120)
    if max_age < min_age:
        raise ApiError("ERR_INVALID_REQUEST",
                       "max_age_years may not be below min_age_years.")
    pregnancy_sensitive = get_bool(data, "pregnancy_sensitive", required=False, default=False)
    emergency_override = get_bool(data, "emergency_override", required=False, default=False)
    floor = get_enum(data, "min_disposition_level", DISPOSITION_LEVELS, required=False)
    infant_points = get_int(data, "infant_modifier_points", required=False,
                            minimum=0, maximum=40)

    record = base_record()
    record.update({
        "code": code,
        "title": title,
        "base_severity": base_severity,
        "min_age_years": min_age,
        "max_age_years": max_age,
        "pregnancy_sensitive": pregnancy_sensitive,
        "emergency_override": emergency_override,
        "min_disposition_level": floor if floor is not None else "HOME_CARE",
        "infant_modifier_points": (infant_points if infant_points is not None
                                   else DEFAULT_INFANT_MODIFIER_POINTS),
        "status": "ACTIVE",
    })
    store.protocols[record["id"]] = record
    return object_response(protocol_json(record), 201)


@bp.route("/symptom-protocols/<protocol_id>", methods=["GET"])
@authorize(ALL_ROLES)
def read_protocol(protocol_id):
    return object_response(protocol_json(lookups.protocol(protocol_id)))


@bp.route("/symptom-protocols", methods=["GET"])
@authorize(ALL_ROLES)
def list_protocols():
    limit, offset = pagination_params()
    status = query_enum("status", PROTOCOL_STATUSES)
    code = query_string("code")
    rows = ordered(store.protocols)
    if status is not None:
        rows = [p for p in rows if p["status"] == status]
    if code is not None:
        rows = [p for p in rows if p["code"] == code]
    return list_response(rows, protocol_json, limit, offset)


@bp.route("/symptom-protocols/<protocol_id>/retire", methods=["POST"])
@authorize([PLATFORM_ADMIN])
def retire_protocol(protocol_id):
    protocol = lookups.protocol(protocol_id)
    protocol["status"] = "RETIRED"
    touch(protocol)
    return object_response(protocol_json(protocol))
