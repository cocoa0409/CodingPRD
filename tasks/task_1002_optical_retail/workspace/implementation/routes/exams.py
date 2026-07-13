"""Eye exams and the prescription they produce (PRD 3.3, interval rules PRD 2.10)."""
from datetime import timedelta

from flask import Blueprint, request

import schema
import store
from auth import authenticate, require_owner
from envelope import array_response, object_response, paginate
from errors import err
from serializers import dump, dump_all

bp = Blueprint("exams", __name__)


@bp.post("/exam-appointments")
def book_appointment():
    actor = authenticate("Customer")
    b = schema.body()
    customer_id = schema.string_field(b, "customer_id")
    store_id = schema.string_field(b, "store_id")
    start_raw, start_dt = schema.datetime_field(b, "start_at")
    end_raw, end_dt = schema.datetime_field(b, "end_at")
    schema.strictly_after("end_at", end_dt, "start_at", start_dt)

    schema.get_customer(customer_id)
    shop = schema.get_store(store_id)
    require_owner(actor, customer_id)

    # Priority 25 -- HALF-OPEN [start_at, end_at) with a TRAILING buffer.
    buffer_delta = timedelta(minutes=shop["buffer_minutes"])
    new_end = end_dt + buffer_delta
    colliding = 0
    for appt in store.ordered(store.appointments):
        if appt["store_id"] != store_id or appt["status"] not in ("BOOKED", "COMPLETED"):
            continue
        other_end = appt["_end_at_dt"] + buffer_delta
        if start_dt < other_end and appt["_start_at_dt"] < new_end:
            colliding += 1
    if colliding >= shop["exam_chairs"]:
        raise err("ERR_EXAM_SLOT_CONFLICT")

    rec = store.new_record(
        customer_id=customer_id,
        store_id=store_id,
        start_at=start_raw,
        end_at=end_raw,
        status="BOOKED",
        resulting_prescription_id=None,
    )
    rec["_start_at_dt"] = start_dt
    rec["_end_at_dt"] = end_dt
    store.appointments[rec["id"]] = rec
    return object_response(dump("appointment", rec), 201)


@bp.get("/exam-appointments/<appt_id>")
def read_appointment(appt_id):
    actor = authenticate("Customer", "StoreAssociate", "PlatformAdmin")
    rec = schema.get_appointment(appt_id)
    require_owner(actor, rec["customer_id"])
    return object_response(dump("appointment", rec))


@bp.get("/exam-appointments")
def list_appointments():
    authenticate("StoreAssociate", "PlatformAdmin")
    items = store.ordered(store.appointments)
    for field in ("customer_id", "store_id", "resulting_prescription_id", "status"):
        value = request.args.get(field)
        if value:
            items = [a for a in items if a[field] == value]
    window, meta = paginate(items)
    return array_response(dump_all("appointment", window), meta)


@bp.post("/exam-appointments/<appt_id>/complete")
def complete_appointment(appt_id):
    authenticate("StoreAssociate")
    b = schema.body()
    rx_id = schema.string_field(b, "prescription_id")

    appt = schema.get_appointment(appt_id)
    rx = schema.get_prescription(rx_id)

    if appt["status"] != "BOOKED":
        raise err("ERR_INVALID_STATE")
    if rx["customer_id"] != appt["customer_id"]:
        raise err("ERR_PRESCRIPTION_OWNER_MISMATCH")

    appt["status"] = "COMPLETED"
    appt["resulting_prescription_id"] = rx_id
    store.touch(appt)
    return object_response(dump("appointment", appt))
