"""Synchronization, auto-ship posture, dose events and the adherence review."""

from datetime import date, timedelta

from flask import Blueprint

import calc
import clock
import db
import engine
import enums
import middleware
import response
import store
import validators
from errors import ApiError

bp = Blueprint("patients", __name__)


def _next_anchor_date(anchor_fill_day):
    """Earliest calendar date on or after the clock date with that day-of-month."""
    today = clock.today()
    if today.day <= anchor_fill_day:
        return date(today.year, today.month, anchor_fill_day)
    year = today.year + (1 if today.month == 12 else 0)
    month = 1 if today.month == 12 else today.month + 1
    return date(year, month, anchor_fill_day)


@bp.post("/patients/<patient_id>/synchronize")
def synchronize(patient_id):
    middleware.authenticate(("PharmacyOperations",))
    body = validators.json_body()
    anchor_fill_day = validators.integer(body, "anchor_fill_day", minimum=1, maximum=31)
    sync_mode = validators.enum(body, "sync_mode", enums.SYNC_MODES)

    patient = middleware.lookup("patient", patient_id)

    if patient["autoship_status"] not in ("ACTIVE", "PAUSED_PATIENT"):
        raise ApiError("ERR_AUTOSHIP_PAUSED")
    if anchor_fill_day > enums.ANCHOR_DAY_BUSINESS_MAX:
        raise ApiError("ERR_INVALID_ANCHOR_DAY")

    today = clock.today()
    prescriptions = engine.prescriptions_of_patient(patient_id)
    expiring = [
        rx
        for rx in prescriptions
        if rx["status"] == "ACTIVE" and store.d(rx["expiration_date"]) < today
    ]
    expiring_ids = {rx["id"] for rx in expiring}
    surviving = [
        rx
        for rx in prescriptions
        if rx["status"] == "ACTIVE" and rx["id"] not in expiring_ids
    ]
    if not surviving:
        raise ApiError("ERR_NO_ACTIVE_PRESCRIPTIONS")

    # First: the expiry sweep.
    for rx in expiring:
        rx["status"] = "EXPIRED"
        store.touch(rx)

    # Second: pin the schedule.
    next_start = _next_anchor_date(anchor_fill_day)
    patient["anchor_fill_day"] = anchor_fill_day
    patient["sync_mode"] = sync_mode
    patient["sync_status"] = "SYNCED"
    patient["next_cycle_start_date"] = store.fmt_date(next_start)
    store.touch(patient)

    # Third: project the alignment against next_cycle_start_date.
    for rx in surviving:
        bridge, trim, _ = calc.alignment(
            sync_mode,
            next_start,
            0,
            store.d(rx["last_dispensed_date"]),
            rx["last_dispensed_days_supply"],
        )
        rx["sync_bridge_days"] = bridge
        rx["sync_trim_days"] = trim
        store.touch(rx)

    store.commit()
    return response.object_response(store.serialize(patient))


@bp.post("/patients/<patient_id>/autoship")
def change_autoship(patient_id):
    user_id, role = middleware.authenticate(("PharmacyOperations", "Patient"))
    body = validators.json_body()
    action = validators.enum(body, "action", enums.AUTOSHIP_ACTIONS)

    patient = middleware.lookup("patient", patient_id)
    middleware.enforce_scope(role, user_id, "patient", patient)

    if action == "PAUSE":
        if patient["autoship_status"] != "ACTIVE":
            raise ApiError("ERR_AUTOSHIP_PAUSED")
        patient["autoship_status"] = "PAUSED_PATIENT"
        patient["pause_reason"] = "PATIENT_REQUEST"
        store.touch(patient)
        engine.cancel_draft_cycles(patient)
    elif action == "RESUME":
        if patient["autoship_status"] in ("PAUSED_ADHERENCE", "PAUSED_PATIENT"):
            patient["autoship_status"] = "ACTIVE"
        patient["pause_reason"] = None
        patient["consecutive_missed_pickups"] = 0
        store.touch(patient)
    else:  # CANCEL
        patient["autoship_status"] = "CANCELLED"
        patient["pause_reason"] = "PATIENT_REQUEST"
        store.touch(patient)
        engine.cancel_draft_cycles(patient)
        engine.void_issued_memos(patient)

    store.commit()
    return response.object_response(store.serialize(patient))


@bp.post("/patients/<patient_id>/dose-events")
def report_dose_events(patient_id):
    user_id, role = middleware.authenticate(("Patient", "PharmacyOperations"))
    body = validators.json_body()
    cycle_id = validators.string(body, "cycle_id")
    raw_events = validators.object_array(body, "events", non_empty=True)

    parsed = []
    for element in raw_events:
        event_type = validators.enum(element, "event_type", enums.DOSE_EVENT_TYPES)
        occurred_at = validators.instant_field(element, "occurred_at")
        if occurred_at > clock.now():
            raise validators.bad("Field 'occurred_at' must not be after the clock.")
        dose_slot = validators.enum(
            element, "dose_slot", enums.DOSE_SLOTS, required=False, default=None
        )
        pouch_index = validators.integer(
            element, "pouch_index", required=False, default=None, minimum=1
        )
        parsed.append((event_type, occurred_at, dose_slot, pouch_index))

    patient = middleware.lookup("patient", patient_id)
    cycle = middleware.lookup("fill_cycle", cycle_id)
    middleware.enforce_scope(role, user_id, "patient", patient)
    middleware.enforce_scope(role, user_id, "fill_cycle", cycle)

    source = "PATIENT_REPORTED" if role == "Patient" else "SYSTEM_SCAN"
    created = []
    for event_type, occurred_at, dose_slot, pouch_index in parsed:
        created.append(
            engine.append_event(
                cycle_id,
                event_type,
                clock.fmt_instant(occurred_at),
                source,
                dose_slot=dose_slot,
                pouch_index=pouch_index,
            )
        )

    engine.recompute_adherence_score(patient)
    engine.evaluate_pause_gate(patient)

    store.commit()
    return response.array_response(store.serialize_many(created), status=201)


@bp.post("/patients/<patient_id>/adherence-review")
def adherence_review(patient_id):
    middleware.authenticate(("PharmacyOperations",))
    patient = middleware.lookup("patient", patient_id)

    swept = 0
    for shipment in engine.shipments_of_patient(patient_id):
        if shipment["status"] != "DELIVERED":
            continue
        delivered_at = store.ts(shipment["delivered_at"])
        if delivered_at is None:
            continue
        if delivered_at + timedelta(days=enums.PICKUP_GRACE_DAYS) <= clock.now():
            shipment["status"] = "PICKUP_MISSED"
            store.touch(shipment)
            engine.append_event(
                shipment["cycle_id"], "PICKUP_MISSED", clock.now_iso(), "SYSTEM_SCAN"
            )
            swept += 1

    if swept:
        patient["consecutive_missed_pickups"] += swept
    store.touch(patient)

    engine.recompute_adherence_score(patient)
    engine.evaluate_pause_gate(patient)

    store.commit()
    return response.object_response(store.serialize(patient))
