"""Consulate interview bookings: booking, rescheduling and the interview outcome."""
import datetime as _dt

from flask import Blueprint

import clock
import serializers
import store
import validation
from calendar_util import is_business_day
from constants import (
    API_PREFIX,
    APPOINTMENT_LEAD_TIME_HOURS,
    APPOINTMENT_OUTCOMES,
    APPOINTMENT_RESCHEDULE_CAP,
    NO_SHOW_REBOOK_CAP,
)
from errors import fail
from routes.common import READ_ROLES, created, endpoint, listing, ok
from services import lookup, readiness, slots
from validation import Body

bp = Blueprint("appointments", __name__)
P = API_PREFIX


def _slot_checks(applicant, order, slot):
    """Rungs 16, 17, 18, 19 against the target slot, in ladder order."""
    consulate = store.get("consulates", slot["consulate_id"])
    day = slot["starts_at"].date()
    if not is_business_day(day, consulate):
        fail("ERR_EMBASSY_CLOSED")
    regions = consulate["jurisdiction_region_codes"] if consulate else []
    if (applicant["residence_region_code"] not in regions
            or slot["consulate_id"] != order["consulate_id"]):
        fail("ERR_OUT_OF_JURISDICTION")
    lead = clock.now() + _dt.timedelta(hours=APPOINTMENT_LEAD_TIME_HOURS)
    if slot["starts_at"] < lead:
        fail("ERR_LEAD_TIME_VIOLATION")
    if slot["booked_count"] >= slot["capacity"]:
        fail("ERR_SLOT_CAPACITY_EXCEEDED")


@bp.route(P + "/appointments", methods=["POST"])
@endpoint("appointments.create", ["CaseManager"])
def book_appointment(ctx):
    raw_applicant = ctx.body.get("applicant_id")
    applicant = validation.need("applicants", raw_applicant) if isinstance(
        raw_applicant, str) else None
    raw_slot = ctx.body.get("slot_id")
    slot = validation.need("slots", raw_slot) if isinstance(raw_slot, str) else None

    body = Body(ctx.body)
    body.string("applicant_id")
    body.string("slot_id")
    expected = body.integer("expected_slot_version")
    body.check()

    order = lookup.order_of_applicant(applicant)
    validation.guard_order(ctx, order)
    validation.check_occ(expected, slot)
    _slot_checks(applicant, order, slot)

    row = store.insert("appointments", {
        "applicant_id": applicant["id"],
        "slot_id": slot["id"],
        "booking_status": "BOOKED",
        "reschedule_count": 0,
        "no_show_count": 0,
        "booked_at": clock.now(),
    })
    slots.take_seat(slot)
    return created(serializers.appointment(row))


@bp.route(P + "/appointments", methods=["GET"])
@endpoint("appointments.list", READ_ROLES)
def list_appointments(ctx):
    rows = store.all_rows("appointments")
    rows = validation.apply_filter(rows, "applicant_id")
    rows = validation.apply_filter(rows, "slot_id")
    rows = validation.apply_filter(rows, "booking_status")
    return listing(store.sort_default(rows), serializers.appointment)


@bp.route(P + "/appointments/<appointment_id>", methods=["GET"])
@endpoint("appointments.read", READ_ROLES)
def read_appointment(ctx, appointment_id):
    row = validation.need("appointments", appointment_id)
    validation.check_membership(ctx, lookup.order_of_appointment(row))
    return ok(serializers.appointment(row))


@bp.route(P + "/appointments/<appointment_id>/reschedule", methods=["POST"])
@endpoint("appointments.reschedule", ["CaseManager"])
def reschedule_appointment(ctx, appointment_id):
    appointment = validation.need("appointments", appointment_id)
    raw_slot = ctx.body.get("slot_id")
    target = validation.need("slots", raw_slot) if isinstance(raw_slot, str) else None

    body = Body(ctx.body)
    body.string("slot_id")
    body.check()

    applicant = store.get("applicants", appointment["applicant_id"])
    order = lookup.order_of_applicant(applicant)
    validation.guard_order(ctx, order)
    validation.require_state(appointment["booking_status"], ("BOOKED", "NO_SHOW"))
    _slot_checks(applicant, order, target)

    was_booked = appointment["booking_status"] == "BOOKED"
    if was_booked:
        if appointment["reschedule_count"] >= APPOINTMENT_RESCHEDULE_CAP:
            fail("ERR_RESCHEDULE_CAP_EXCEEDED")
    else:
        if appointment["no_show_count"] >= NO_SHOW_REBOOK_CAP:
            fail("ERR_RESCHEDULE_CAP_EXCEEDED")

    if was_booked:
        released = store.get("slots", appointment["slot_id"])
        if released is not None:
            slots.release_seat(released)
        appointment["reschedule_count"] += 1
    else:
        appointment["booking_status"] = "BOOKED"

    appointment["slot_id"] = target["id"]
    appointment["booked_at"] = clock.now()
    store.touch(appointment)
    slots.take_seat(target)
    return ok(serializers.appointment(appointment))


@bp.route(P + "/appointments/<appointment_id>/outcome", methods=["POST"])
@endpoint("appointments.outcome", ["AgencyLiaison"])
def record_outcome(ctx, appointment_id):
    appointment = validation.need("appointments", appointment_id)
    body = Body(ctx.body)
    outcome = body.enum("outcome", APPOINTMENT_OUTCOMES)
    body.check()

    applicant = store.get("applicants", appointment["applicant_id"])
    order = lookup.order_of_applicant(applicant)
    validation.guard_order(ctx, order)
    slot = store.get("slots", appointment["slot_id"])
    if appointment["booking_status"] != "BOOKED" or clock.now() < slot["starts_at"]:
        fail("ERR_INVALID_STATE", "The interview window has not opened for this booking.")

    if outcome == "ATTENDED":
        appointment["booking_status"] = "ATTENDED"
    else:
        appointment["booking_status"] = "NO_SHOW"
        appointment["no_show_count"] += 1
        slots.release_seat(slot)
    store.touch(appointment)

    readiness.recompute_readiness(applicant)
    readiness.reevaluate_gate(order)
    return ok(serializers.appointment(appointment))
