from flask import Blueprint, g, request

import constants as C
import fees
import serializers
import validation as V
from envelope import object_response, paginate
from errors import ApiError
from lookups import (agency_of_appointment, agency_of_ori, body_row, check_billing_freeze,
                     freeze_for_site, ori_of_service_type, path_row, require_appointment_state,
                     require_record_state)
from store import db
from timeutil import add_hours, add_minutes, date_of

bp = Blueprint("appointments", __name__)


def _check_capacity(site, start, end, channel, exclude_id=None):
    """Rung 18 -- interval overlap counted over BOOKED, CHECKED_IN and IN_CAPTURE
    appointments at the same site; intervals are half-open so adjacency is free."""
    load = 0
    for other in db.appointments.values():
        if other["site_id"] != site["id"]:
            continue
        if exclude_id is not None and other["id"] == exclude_id:
            continue
        if other["status"] not in ("BOOKED", "CHECKED_IN", "IN_CAPTURE"):
            continue
        if other["scheduled_start"] < end and other["scheduled_end"] > start:
            load += 1
    ceiling = site["concurrent_capacity"] if channel == "BOOKED" else site["walkin_usable_capacity"]
    if load + 1 > ceiling:
        raise ApiError("ERR_SLOT_CAPACITY_EXCEEDED", "the site is at capacity for that interval")


@bp.post("/livescan/appointments")
def create_appointment():
    data = V.body()
    applicant = body_row("applicants", data["applicant_id"]) if data.get("applicant_id") else None
    site = body_row("sites", data["site_id"]) if data.get("site_id") else None
    service_type = (
        body_row("service_types", data["service_type_id"]) if data.get("service_type_id") else None
    )

    scheduled_start = V.req_instant(data, "scheduled_start")
    channel = V.opt_string(data, "booking_channel", default="BOOKED")
    if applicant is None:
        V.bad_request("applicant_id is required")
    if site is None:
        V.bad_request("site_id is required")
    if service_type is None:
        V.bad_request("service_type_id is required")

    V.enum_value("booking_channel", channel, C.BOOKING_CHANNELS)

    ori = ori_of_service_type(service_type)
    check_billing_freeze(agency_of_ori(ori), freeze_for_site(site))
    require_record_state(service_type["status"] == "ACTIVE", "service type is RETIRED")

    scheduled_end = add_minutes(scheduled_start, service_type["slot_duration_minutes"])
    _check_capacity(site, scheduled_start, scheduled_end, channel)

    row = db.create(
        "appointments",
        {
            "applicant_id": applicant["id"],
            "site_id": site["id"],
            "service_type_id": service_type["id"],
            "booking_channel": channel,
            "scheduled_start": scheduled_start,
            "scheduled_end": scheduled_end,
            "status": "BOOKED",
            "reschedule_count": 0,
            "presented_document_type": None,
            "presented_documents": None,
            "checked_in_at": None,
            "no_show_fee_assessed": False,
        },
    )
    return object_response(serializers.appointment(row), 201)


@bp.get("/livescan/appointments/<id>")
def read_appointment(id):
    return object_response(serializers.appointment(path_row("appointments", id)))


@bp.get("/livescan/appointments")
def list_appointments():
    rows = list(db.appointments.values())
    for field in ("applicant_id", "site_id", "service_type_id", "status"):
        value = request.args.get(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    return paginate(rows, serializers.appointment)


@bp.post("/livescan/appointments/<id>/reschedule")
def reschedule(id):
    appointment = path_row("appointments", id)
    data = V.body()
    new_start = V.req_instant(data, "scheduled_start")

    require_appointment_state(appointment, ("BOOKED",))

    if db.now() > add_hours(
        appointment["scheduled_start"], -C.APPOINTMENT_RESCHEDULE_WINDOW_HOURS
    ):
        raise ApiError("ERR_RESCHEDULE_WINDOW_CLOSED", "inside the final 24 hours")
    if appointment["reschedule_count"] >= C.APPOINTMENT_MAX_RESCHEDULES:
        raise ApiError("ERR_APPOINTMENT_STATE_INVALID", "reschedule budget exhausted")

    service_type = db.service_types[appointment["service_type_id"]]
    site = db.sites[appointment["site_id"]]
    new_end = add_minutes(new_start, service_type["slot_duration_minutes"])
    _check_capacity(
        site, new_start, new_end, appointment["booking_channel"], exclude_id=appointment["id"]
    )

    appointment["scheduled_start"] = new_start
    appointment["scheduled_end"] = new_end
    appointment["reschedule_count"] += 1
    db.touch(appointment)
    return object_response(serializers.appointment(appointment))


@bp.post("/livescan/appointments/<id>/cancel")
def cancel(id):
    appointment = path_row("appointments", id)
    status = appointment["status"]
    if status == "BOOKED":
        pass
    elif status == "CHECKED_IN":
        if g.role != "LivescanTechnician":
            raise ApiError(
                "ERR_APPOINTMENT_STATE_INVALID",
                "only a technician may cancel a checked-in appointment",
            )
        has_card = any(c["appointment_id"] == appointment["id"] for c in db.cards.values())
        if has_card:
            raise ApiError(
                "ERR_APPOINTMENT_STATE_INVALID", "a fingerprint card was already opened"
            )
    else:
        raise ApiError("ERR_APPOINTMENT_STATE_INVALID", "appointment is %s" % status)

    appointment["status"] = "CANCELLED"
    db.touch(appointment)
    return object_response(serializers.appointment(appointment))


@bp.post("/livescan/appointments/<id>/check-in")
def check_in(id):
    appointment = path_row("appointments", id)
    data = V.body()
    document_type = V.req_string(data, "presented_document_type")
    documents = V.req_array(data, "presented_documents", allow_empty=True)
    V.enum_value("presented_document_type", document_type, C.ID_DOCUMENT_TYPES)

    require_appointment_state(appointment, ("BOOKED",))

    now = db.now()
    start = appointment["scheduled_start"]
    if now < add_minutes(start, -C.CHECKIN_EARLY_WINDOW_MINUTES) or now > add_minutes(
        start, C.CHECKIN_LATE_GRACE_MINUTES
    ):
        raise ApiError("ERR_CHECKIN_WINDOW_CLOSED", "outside the check-in window")

    service_type = db.service_types[appointment["service_type_id"]]
    if document_type not in service_type["accepted_id_document_types"]:
        raise ApiError(
            "ERR_REQUIRED_DOCUMENT_MISSING", "the presented identity document is not accepted"
        )

    applicant = db.applicants[appointment["applicant_id"]]
    if applicant["id_document_expires_on"] < date_of(now):
        raise ApiError("ERR_IDENTITY_DOCUMENT_EXPIRED", "the identity document has expired")

    missing = [c for c in service_type["required_document_codes"] if c not in documents]
    if missing:
        raise ApiError(
            "ERR_REQUIRED_DOCUMENT_MISSING", "missing document codes: %s" % ", ".join(missing)
        )

    appointment["status"] = "CHECKED_IN"
    appointment["checked_in_at"] = now
    appointment["presented_document_type"] = document_type
    appointment["presented_documents"] = list(documents)
    db.touch(appointment)
    return object_response(serializers.appointment(appointment))


@bp.post("/livescan/appointments/<id>/no-show")
def no_show(id):
    appointment = path_row("appointments", id)
    require_appointment_state(appointment, ("BOOKED",))
    if db.now() <= add_minutes(appointment["scheduled_start"], C.CHECKIN_LATE_GRACE_MINUTES):
        raise ApiError(
            "ERR_APPOINTMENT_STATE_INVALID", "the grace period has not yet elapsed"
        )

    appointment["status"] = "NO_SHOW"
    appointment["no_show_fee_assessed"] = True
    db.touch(appointment)

    fees.create_no_show_assessment(agency_of_appointment(appointment), appointment)
    return object_response(serializers.appointment(appointment))
