"""In-person conversions: create under consult, complete, cancel, list, get."""

from datetime import timedelta

from flask import Blueprint, request

import db
import services
import util
from errors import (
    ApiError,
    ERR_APPOINTMENT_WINDOW_OVERLAP,
    ERR_CONSULT_NOT_ANSWERED,
    ERR_CONVERSION_ALREADY_EXISTS,
    ERR_CONVERSION_NOT_SCHEDULED,
    ERR_DISPOSITION_NOT_CONVERSION,
    ERR_NOT_ASSIGNED_SPECIALIST,
    ERR_NOT_CONSULT_OWNER,
    ERR_WINDOW_INVALID_RANGE,
)
from middleware import require_roles, ANY_ROLE
from response import ok, ok_list
from util import serialize, serialize_list

bp = Blueprint("conversions", __name__)


@bp.route("/econsult/consult-requests/<rid>/conversions", methods=["POST"])
def create_conversion(rid):
    uid, _role = require_roles("Specialist")
    data = util.json_body()
    appointment_start = util.req_datetime(data, "appointment_start")
    appointment_end = util.req_datetime(data, "appointment_end")

    consult = services.get_consult(rid)
    if consult["assigned_specialist_id"] != uid:
        raise ApiError(
            ERR_NOT_ASSIGNED_SPECIALIST, 403,
            "Caller is not the responding specialist",
        )
    if consult["status"] != "ANSWERED":
        raise ApiError(ERR_CONSULT_NOT_ANSWERED, 409, "Consult is not ANSWERED")
    resp = services.response_for_consult(consult["id"])
    if resp is None or resp["disposition"] != "CONVERT_TO_VISIT":
        raise ApiError(
            ERR_DISPOSITION_NOT_CONVERSION, 409,
            "Conversion requires response disposition CONVERT_TO_VISIT",
        )
    for existing in db.store["in_person_conversions"].values():
        if existing["consult_id"] == consult["id"]:
            raise ApiError(
                ERR_CONVERSION_ALREADY_EXISTS, 409,
                "Consult already has an in-person conversion",
            )
    if appointment_end <= appointment_start:
        raise ApiError(
            ERR_WINDOW_INVALID_RANGE, 422,
            "appointment_end must be strictly later than appointment_start",
        )

    buffer = timedelta(minutes=services.CONVERSION_BUFFER_MINUTES)
    for existing in db.store["in_person_conversions"].values():
        if existing["specialist_id"] != uid:
            continue
        if existing["status"] != "SCHEDULED":
            continue
        # Buffered overlap: a gap of exactly 30 minutes does not conflict.
        if (appointment_start < existing["appointment_end"] + buffer
                and existing["appointment_start"] < appointment_end + buffer):
            raise ApiError(
                ERR_APPOINTMENT_WINDOW_OVERLAP, 409,
                "Appointment overlaps a SCHEDULED conversion of the same specialist",
            )

    rec = services.base_record()
    rec.update({
        "consult_id": consult["id"],
        "specialist_id": uid,
        "appointment_start": appointment_start,
        "appointment_end": appointment_end,
        "status": "SCHEDULED",
    })
    db.store["in_person_conversions"][rec["id"]] = rec
    return ok(serialize("in_person_conversion", rec), 201)


@bp.route("/econsult/in-person-conversions/<rid>/complete", methods=["POST"])
def complete_conversion(rid):
    uid, _role = require_roles("Specialist")
    conversion = services.get_conversion(rid)
    if conversion["specialist_id"] != uid:
        raise ApiError(
            ERR_NOT_ASSIGNED_SPECIALIST, 403,
            "Caller is not the converting specialist",
        )
    if conversion["status"] != "SCHEDULED":
        raise ApiError(ERR_CONVERSION_NOT_SCHEDULED, 409, "Conversion is not SCHEDULED")
    conversion["status"] = "COMPLETED"
    services.touch(conversion)
    return ok(serialize("in_person_conversion", conversion), 200)


@bp.route("/econsult/in-person-conversions/<rid>/cancel", methods=["POST"])
def cancel_conversion(rid):
    uid, role = require_roles("Specialist", "ReferringProvider")
    conversion = services.get_conversion(rid)
    consult = db.store["consult_requests"][conversion["consult_id"]]
    if role == "Specialist":
        if conversion["specialist_id"] != uid:
            raise ApiError(
                ERR_NOT_ASSIGNED_SPECIALIST, 403,
                "Caller is not the converting specialist",
            )
    else:
        if consult["referring_provider_id"] != uid:
            raise ApiError(ERR_NOT_CONSULT_OWNER, 403, "Caller does not own this consult")
    if conversion["status"] != "SCHEDULED":
        raise ApiError(ERR_CONVERSION_NOT_SCHEDULED, 409, "Conversion is not SCHEDULED")
    conversion["status"] = "CANCELLED"
    services.touch(conversion)
    return ok(serialize("in_person_conversion", conversion), 200)


@bp.route("/econsult/in-person-conversions", methods=["GET"])
def list_conversions():
    require_roles(*ANY_ROLE)
    records = list(db.store["in_person_conversions"].values())
    for param, field in (
        ("consult_id", "consult_id"),
        ("specialist_id", "specialist_id"),
        ("status", "status"),
    ):
        value = request.args.get(param)
        if value is not None:
            records = [c for c in records if c[field] == value]
    page, total, limit, offset = util.paginate(records)
    return ok_list(serialize_list("in_person_conversion", page), total, limit, offset)


@bp.route("/econsult/in-person-conversions/<rid>", methods=["GET"])
def get_conversion(rid):
    require_roles(*ANY_ROLE)
    return ok(serialize("in_person_conversion", services.get_conversion(rid)), 200)
