"""Buildings, psychologists, instruments, licence seats and protocol orders."""

from decimal import Decimal

from flask import Blueprint, request

import calc
import lookups
import serializers
import services
import validators as v
from auth import ALL_ROLES, authorize, current_user_id
from envelope import paginate, pagination, respond_array, respond_object
from errors import ApiError
from store import base_record, db, iso, now, sort_key, touch

bp = Blueprint("reference", __name__)

GRADE_BANDS = ("ELEMENTARY", "MIDDLE", "HIGH")
CREDENTIALS = ("SSP", "PHD", "INTERN")


# ---------------------------------------------------------------- schools

@bp.post("/psych-services/schools")
@authorize("DistrictAdmin")
def create_school():
    body = v.body()
    name = v.req_str(body, "name")
    code = v.building_code(body, "building_code")
    grade_band = v.req_enum(body, "grade_band", GRADE_BANDS)
    capacity = v.opt_int(body, "concurrent_meeting_capacity", 1, minimum=1)
    enrollment = v.opt_int(body, "enrollment_count", 0, minimum=0)

    for existing in db.schools.values():
        if existing["building_code"] == code:
            raise ApiError("ERR_DUPLICATE_BUILDING_CODE",
                           "building_code %s is already registered." % code)

    record = base_record()
    record.update({
        "name": name,
        "building_code": code,
        "grade_band": grade_band,
        "concurrent_meeting_capacity": capacity,
        "enrollment_count": enrollment,
    })
    db.schools[record["id"]] = record
    return respond_object(serializers.school(record), 201)


@bp.get("/psych-services/schools/<school_id>")
@authorize(*ALL_ROLES)
def get_school(school_id):
    record = lookups.school(school_id)
    return respond_object(serializers.school(record))


# ---------------------------------------------------------------- psychologists

@bp.post("/psych-services/psychologists")
@authorize("DistrictAdmin")
def create_psychologist():
    body = v.body()
    full_name = v.req_str(body, "full_name")
    employee_number = v.req_str(body, "employee_number")
    credential_type = v.req_enum(body, "credential_type", CREDENTIALS)
    languages = v.language_list(body, "languages_certified", ["en"])
    school_ids = v.req_str_list(body, "assigned_school_ids")
    capacity = v.opt_int(body, "weekly_capacity_points", 20, minimum=1)

    for school_id in school_ids:
        lookups.school(school_id)

    record = base_record()
    record.update({
        "full_name": full_name,
        "employee_number": employee_number,
        "credential_type": credential_type,
        "languages_certified": languages,
        "assigned_school_ids": school_ids,
        "weekly_capacity_points": capacity,
        "status": "ACTIVE",
        "open_case_points": 0,
        "caseload_status": "BALANCED",
        "pressure_index_assigned_basis": calc.round_half_up(Decimal(0), 2),
        "pressure_index_clock_weighted": calc.round_half_up(Decimal(0), 2),
    })
    db.psychologists[record["id"]] = record
    return respond_object(serializers.psychologist(record), 201)


@bp.get("/psych-services/psychologists/<psychologist_id>")
@authorize(*ALL_ROLES)
def get_psychologist(psychologist_id):
    record = lookups.psychologist(psychologist_id)
    return respond_object(serializers.psychologist(record))


@bp.post("/psych-services/psychologists/<psychologist_id>/leave")
@authorize("DistrictAdmin")
def psychologist_leave(psychologist_id):
    record = lookups.psychologist(psychologist_id)
    if record["status"] != "ACTIVE":
        raise ApiError("ERR_PSYCHOLOGIST_STATE_INVALID", "Psychologist is already ON_LEAVE.")
    services.leave_cascade(record)
    return respond_object(serializers.psychologist(record))


@bp.get("/psych-services/psychologists/<psychologist_id>/license-seats")
@authorize("PsychServicesSupervisor", "ComplianceOfficer", "DistrictAdmin")
def list_psychologist_seats(psychologist_id):
    record = lookups.psychologist(psychologist_id)
    limit, offset = pagination(request.args)
    status = request.args.get("status")
    rows = [s for s in db.seats.values() if s["psychologist_id"] == record["id"]]
    if status:
        rows = [s for s in rows if s["status"] == status]
    rows.sort(key=sort_key)
    page, total = paginate(rows, limit, offset)
    return respond_array([serializers.scoring_license_seat(r) for r in page], limit, offset, total)


# ---------------------------------------------------------------- instruments

@bp.post("/psych-services/assessment-instruments")
@authorize("DistrictAdmin")
def create_instrument():
    body = v.body()
    name = v.req_str(body, "name")
    instrument_code = v.req_str(body, "instrument_code")
    stock = v.opt_int(body, "protocol_stock_count", 0, minimum=0)
    per_admin = v.opt_int(body, "protocol_units_per_administration", 1, minimum=1)
    unit_cost = v.req_int(body, "protocol_unit_cost_cents", minimum=1)
    seat_total = v.opt_int(body, "license_seat_total", 0, minimum=0)
    expires_on = v.req_date(body, "license_expires_on")
    editions = v.language_list(body, "supported_language_editions", ["en"])

    record = base_record()
    record.update({
        "name": name,
        "instrument_code": instrument_code,
        "protocol_stock_count": stock,
        "protocol_units_per_administration": per_admin,
        "protocol_unit_cost_cents": unit_cost,
        "license_seat_total": seat_total,
        "license_expires_on": expires_on.isoformat(),
        "supported_language_editions": editions,
    })
    db.instruments[record["id"]] = record
    return respond_object(serializers.assessment_instrument(record), 201)


@bp.get("/psych-services/assessment-instruments/<instrument_id>")
@authorize("SchoolPsychologist", "PsychServicesSupervisor", "ComplianceOfficer", "DistrictAdmin")
def get_instrument(instrument_id):
    record = lookups.instrument(instrument_id)
    return respond_object(serializers.assessment_instrument(record))


@bp.get("/psych-services/assessment-instruments/<instrument_id>/license-seats")
@authorize("PsychServicesSupervisor", "ComplianceOfficer", "DistrictAdmin")
def list_instrument_seats(instrument_id):
    record = lookups.instrument(instrument_id)
    limit, offset = pagination(request.args)
    status = request.args.get("status")
    rows = [s for s in db.seats.values() if s["instrument_id"] == record["id"]]
    if status:
        rows = [s for s in rows if s["status"] == status]
    rows.sort(key=sort_key)
    page, total = paginate(rows, limit, offset)
    return respond_array([serializers.scoring_license_seat(r) for r in page], limit, offset, total)


@bp.get("/psych-services/assessment-instruments/<instrument_id>/protocol-orders")
@authorize("PsychServicesSupervisor", "ComplianceOfficer", "DistrictAdmin")
def list_instrument_orders(instrument_id):
    record = lookups.instrument(instrument_id)
    limit, offset = pagination(request.args)
    status = request.args.get("status")
    rows = [o for o in db.orders.values() if o["instrument_id"] == record["id"]]
    if status:
        rows = [o for o in rows if o["status"] == status]
    rows.sort(key=sort_key)
    page, total = paginate(rows, limit, offset)
    return respond_array([serializers.protocol_order(r) for r in page], limit, offset, total)


# ---------------------------------------------------------------- licence seats

@bp.post("/psych-services/assessment-instruments/<instrument_id>/license-seats")
@authorize("DistrictAdmin", "PsychServicesSupervisor")
def create_license_seat(instrument_id):
    body = v.body()
    psychologist_id = v.req_str(body, "psychologist_id")
    instrument = lookups.instrument(instrument_id)
    psychologist = lookups.psychologist(psychologist_id)

    if services.license_seats_free(instrument) < 1:
        raise ApiError("ERR_LICENSE_SEATS_EXHAUSTED",
                       "No free scoring licence seat remains on this instrument.")
    for seat in db.seats.values():
        if seat["instrument_id"] == instrument["id"] \
                and seat["psychologist_id"] == psychologist["id"] \
                and seat["status"] == "ASSIGNED":
            raise ApiError("ERR_LICENSE_SEATS_EXHAUSTED",
                           "Psychologist already holds an ASSIGNED seat for this instrument.")

    record = base_record()
    record.update({
        "instrument_id": instrument["id"],
        "psychologist_id": psychologist["id"],
        "status": "ASSIGNED",
        "assigned_at": iso(now()),
        "released_at": None,
    })
    db.seats[record["id"]] = record
    touch(instrument)  # license_seats_free is a derived field of the instrument
    return respond_object(serializers.scoring_license_seat(record), 201)


@bp.post("/psych-services/assessment-instruments/<instrument_id>/license-seats/<seat_id>/release")
@authorize("PsychServicesSupervisor", "DistrictAdmin")
def release_license_seat(instrument_id, seat_id):
    instrument = lookups.instrument(instrument_id)
    seat = lookups.seat_of_instrument(instrument, seat_id)
    if seat["status"] != "ASSIGNED":
        raise ApiError("ERR_SEAT_STATE_INVALID", "Seat is already RELEASED.")
    seat["status"] = "RELEASED"
    seat["released_at"] = iso(now())
    touch(seat)
    touch(instrument)
    return respond_object(serializers.scoring_license_seat(seat))


# ---------------------------------------------------------------- protocol orders

@bp.post("/psych-services/protocol-orders")
@authorize("PsychServicesSupervisor", "DistrictAdmin")
def create_protocol_order():
    body = v.body()
    instrument_id = v.req_str(body, "instrument_id")
    quantity = v.req_int(body, "quantity_requested", minimum=1)
    rush_flag = v.opt_bool(body, "rush_flag", False)
    instrument = lookups.instrument(instrument_id)

    pricing = calc.protocol_order_pricing(
        instrument["protocol_unit_cost_cents"], quantity, rush_flag
    )
    record = base_record()
    record.update({
        "instrument_id": instrument["id"],
        "quantity_requested": quantity,
        "rush_flag": rush_flag,
        "status": "APPROVED" if pricing["auto_approved"] else "SUBMITTED",
        "received_quantity": 0,
        "decided_by_user_id": None,
    })
    record.update(pricing)
    db.orders[record["id"]] = record
    return respond_object(serializers.protocol_order(record), 201)


@bp.post("/psych-services/protocol-orders/<order_id>/decision")
@authorize("DistrictAdmin")
def decide_protocol_order(order_id):
    body = v.body()
    decision = v.req_enum(body, "decision", ("APPROVE", "CANCEL"))
    order = lookups.order(order_id)
    if order["status"] != "SUBMITTED":
        raise ApiError("ERR_ORDER_STATE_INVALID", "Order is not SUBMITTED.")
    order["status"] = "APPROVED" if decision == "APPROVE" else "CANCELLED"
    order["decided_by_user_id"] = current_user_id()
    touch(order)
    return respond_object(serializers.protocol_order(order))


@bp.post("/psych-services/protocol-orders/<order_id>/receive")
@authorize("PsychServicesSupervisor", "DistrictAdmin")
def receive_protocol_order(order_id):
    body = v.body()
    received = v.req_int(body, "received_quantity")
    order = lookups.order(order_id)
    if order["status"] != "APPROVED":
        raise ApiError("ERR_ORDER_STATE_INVALID", "Order is not APPROVED.")
    if received < 1 or received > order["quantity_requested"]:
        raise ApiError("ERR_RECEIPT_QUANTITY_EXCEEDS_ORDER",
                       "received_quantity must be between 1 and quantity_requested.")
    order["status"] = "RECEIVED"
    order["received_quantity"] = received
    touch(order)
    instrument = db.instruments.get(order["instrument_id"])
    if instrument is not None:
        instrument["protocol_stock_count"] += received
        touch(instrument)
    return respond_object(serializers.protocol_order(order))
