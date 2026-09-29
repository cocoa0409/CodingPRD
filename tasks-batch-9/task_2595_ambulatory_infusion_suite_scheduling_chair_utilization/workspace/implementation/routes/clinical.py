"""Authorization, compounding, reactions, laboratory draws and outreach."""

from datetime import timedelta

from flask import Blueprint

import db
from db import apply_changes, get, must, new_row, rows
from errors import ApiError
from middleware import actor_id, authenticate, require_nurse_owner, require_patient_owner
from response import created, ok
from routes.appointments import check_state, check_terminal
from routes.common import paged
from services import derive, present
from services.derive import GRADE_EXTENSION, REMINDER_CAPS
from validators import (
    body,
    opt_int,
    opt_num,
    opt_str,
    q_enum,
    q_int,
    q_str,
    req_enum,
    req_instant,
    req_int,
    req_str,
)

bp = Blueprint("clinical", __name__)

AUTH_STATUSES = ("DRAFT", "SUBMITTED", "PENDED", "APPROVED", "DENIED", "EXPIRED")
DECISIONS = ("APPROVED", "PENDED", "DENIED")
PREP_STATUSES = ("REQUESTED", "PREPARED", "ADMINISTERED", "WASTED", "RETURNED")
EVENT_STATUSES = ("REPORTED", "UNDER_REVIEW", "CLOSED")
OUTCOMES = ("RESUME_SAME_DRUG", "SWITCH_BIOSIMILAR", "DISCONTINUE")
ACTIONS = ("SLOW_RATE", "HOLD", "ABORT")
LAB_STATUSES = ("PENDING", "RESULTED")
CHANNELS = ("SMS", "VOICE", "PORTAL")
REMINDER_OUTCOMES = ("NO_RESPONSE", "CONFIRM_ATTENDANCE", "CANCEL_REQUEST")


# ============================================================ authorizations
@bp.post("/appointments/<appointment_id>/authorization-requests")
def file_authorization(appointment_id):
    authenticate("AuthorizationSpecialist", "Scheduler")
    data = body()
    payer_name = req_str(data, "payer_name", 1, 120)
    appointment = must("appointments", appointment_id)
    check_terminal(appointment)
    auth = new_row(
        "auths",
        {
            "appointment_id": appointment_id,
            "treatment_plan_id": appointment["treatment_plan_id"],
            "payer_name": payer_name,
            "submission_count": 0,
            "approved_units": None,
            "decision_reason": None,
            "decided_at": None,
            "expires_at": None,
            "status": "DRAFT",
        },
    )
    auth["_expires_dt"] = None
    derive.sync_readiness(appointment)
    return created(present.plain(auth))


@bp.get("/authorization-requests/<auth_id>")
def read_authorization(auth_id):
    authenticate("AuthorizationSpecialist", "Scheduler", "MedicalDirector")
    return ok(present.plain(must("auths", auth_id)))


@bp.get("/authorization-requests")
def list_authorizations():
    authenticate("AuthorizationSpecialist", "Scheduler", "MedicalDirector")
    appointment_id = q_str("appointment_id")
    plan_id = q_str("treatment_plan_id")
    payer_name = q_str("payer_name")
    status = q_enum("status", AUTH_STATUSES)
    items = []
    for auth in rows("auths"):
        if appointment_id is not None and auth["appointment_id"] != appointment_id:
            continue
        if plan_id is not None and auth["treatment_plan_id"] != plan_id:
            continue
        if payer_name is not None and auth["payer_name"] != payer_name:
            continue
        if status is not None and auth["status"] != status:
            continue
        items.append(auth)
    return paged("auths", items)


@bp.post("/authorization-requests/<auth_id>/submit")
def submit_authorization(auth_id):
    authenticate("AuthorizationSpecialist")
    auth = must("auths", auth_id)
    if auth["status"] not in ("DRAFT", "PENDED"):
        raise ApiError("ERR_INVALID_AUTH_STATE")
    if int(auth["submission_count"]) >= 3:
        raise ApiError("ERR_AUTH_RESUBMIT_LIMIT")
    apply_changes(
        auth,
        {"status": "SUBMITTED", "submission_count": int(auth["submission_count"]) + 1},
    )
    appointment = get("appointments", auth["appointment_id"])
    if appointment is not None:
        derive.sync_readiness(appointment)
    return ok(present.plain(auth))


@bp.post("/authorization-requests/<auth_id>/decision")
def decide_authorization(auth_id):
    authenticate("AuthorizationSpecialist")
    data = body()
    decision = req_enum(data, "decision", DECISIONS)
    approved_units = opt_int(data, "approved_units", 1, None, None, allow_null=True)
    decision_reason = opt_str(data, "decision_reason", 1, None, None, allow_null=True)
    auth = must("auths", auth_id)
    if auth["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_AUTH_STATE")
    decided = db.now()
    changes = {"status": decision, "decided_at": db.iso_ms(decided)}
    if decision == "APPROVED":
        if approved_units is None:
            from validators import bad

            bad("Field 'approved_units' is required on an APPROVED decision.")
        expires = decided + timedelta(days=30)
        changes["approved_units"] = approved_units
        changes["expires_at"] = db.iso_ms(expires)
        auth["_expires_dt"] = expires
    else:
        changes["decision_reason"] = decision_reason
    apply_changes(auth, changes)
    appointment = get("appointments", auth["appointment_id"])
    if appointment is not None:
        derive.sync_readiness(appointment)
    return ok(present.plain(auth))


# ============================================================ preparations
def _fefo_lot(drug_id, units_requested):
    candidates = []
    for lot in rows("lots"):
        if lot["drug_id"] != drug_id:
            continue
        if lot["status"] != "AVAILABLE":
            continue
        if lot.get("_expires_dt") is None or lot["_expires_dt"] <= db.now():
            continue
        if int(lot["units_available"]) < units_requested:
            continue
        candidates.append(lot)
    if not candidates:
        return None
    candidates.sort(key=lambda lot: (lot["_expires_dt"], lot["_seq"]))
    return candidates[0]


@bp.post("/appointments/<appointment_id>/drug-preparations")
def request_preparation(appointment_id):
    authenticate("Pharmacist")
    data = body()
    units_requested = req_int(data, "units_requested", 1, 100)
    appointment = must("appointments", appointment_id)
    check_state(appointment, ("TENTATIVE", "CONFIRMED", "CHECKED_IN"))
    plan = derive.plan_of(appointment)
    lot = _fefo_lot((plan or {}).get("drug_id"), units_requested)
    if lot is None:
        raise ApiError("ERR_NO_ELIGIBLE_LOT")
    prep = new_row(
        "preps",
        {
            "appointment_id": appointment_id,
            "drug_lot_id": lot["id"],
            "units_requested": units_requested,
            "prepared_at": None,
            "usable_until": None,
            "waste_cost_cents": 0,
            "status": "REQUESTED",
        },
    )
    prep["_usable_dt"] = None
    derive.recompute_lot(lot)
    return created(present.plain(prep))


@bp.get("/drug-preparations/<prep_id>")
def read_preparation(prep_id):
    authenticate("Pharmacist", "InfusionNurse", "Scheduler", "MedicalDirector")
    return ok(present.plain(must("preps", prep_id)))


@bp.get("/drug-preparations")
def list_preparations():
    authenticate("Pharmacist", "InfusionNurse", "Scheduler", "MedicalDirector")
    appointment_id = q_str("appointment_id")
    lot_id = q_str("drug_lot_id")
    status = q_enum("status", PREP_STATUSES)
    items = []
    for prep in rows("preps"):
        if appointment_id is not None and prep["appointment_id"] != appointment_id:
            continue
        if lot_id is not None and prep["drug_lot_id"] != lot_id:
            continue
        if status is not None and prep["status"] != status:
            continue
        items.append(prep)
    return paged("preps", items)


@bp.post("/drug-preparations/<prep_id>/prepare")
def prepare_dose(prep_id):
    authenticate("Pharmacist")
    prep = must("preps", prep_id)
    if prep["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_PREPARATION_STATE")
    lot = derive.prep_lot(prep)
    if lot is None or lot["status"] != "AVAILABLE":
        raise ApiError("ERR_LOT_NOT_AVAILABLE")
    appointment = get("appointments", prep["appointment_id"])
    drug = get("drugs", lot["drug_id"])
    stability = int((drug or {}).get("prep_stability_minutes") or 0)
    now = db.now()
    if appointment is not None:
        start_instant = db.instant_of(
            appointment["service_date"], int(appointment.get("start_minute") or 0)
        )
        premed = int(appointment.get("premed_minutes") or 0)
        # Clinical safety (ladder step 11) precedes the temporal window (step 13).
        if now + timedelta(minutes=stability) < start_instant + timedelta(minutes=premed):
            raise ApiError("ERR_PREP_STABILITY_SHORT")
        if now < start_instant - timedelta(hours=1):
            raise ApiError("ERR_PREP_TOO_EARLY")
    usable = now + timedelta(minutes=stability)
    apply_changes(
        prep,
        {
            "status": "PREPARED",
            "prepared_at": db.iso_ms(now),
            "usable_until": db.iso_ms(usable),
        },
    )
    prep["_usable_dt"] = usable
    if appointment is not None:
        derive.sync_readiness(appointment)
    return ok(present.plain(prep))


@bp.post("/drug-preparations/<prep_id>/return")
def return_dose(prep_id):
    authenticate("Pharmacist")
    data = body()
    req_str(data, "reason", 1, None)
    prep = must("preps", prep_id)
    if prep["status"] not in ("REQUESTED", "PREPARED"):
        raise ApiError("ERR_INVALID_PREPARATION_STATE")
    if prep["status"] == "PREPARED":
        usable = prep.get("_usable_dt")
        if usable is None or db.now() >= usable:
            # A dose past its stability window can no longer go back to stock.
            raise ApiError("ERR_INVALID_PREPARATION_STATE")
    derive.prep_to_returned(prep)
    return ok(present.plain(prep))


# ============================================================ adverse events
def apply_observation_extension(appointment):
    """The visit's extension is the MAXIMUM across its reactions, not the sum."""
    events = derive.events_of(appointment["id"])
    new_max = 0
    for event in events:
        new_max = max(new_max, int(event.get("observation_extension_minutes") or 0))
    previous = int(appointment.get("observation_extension_minutes") or 0)
    delta = new_max - previous
    if delta == 0:
        return 0
    start = int(appointment.get("start_minute") or 0)
    chair_minutes = int(appointment.get("chair_minutes") or 0) + delta
    apply_changes(
        appointment,
        {
            "observation_extension_minutes": new_max,
            "observation_minutes": int(appointment.get("observation_minutes") or 0) + delta,
            "chair_minutes": chair_minutes,
            "end_minute": start + chair_minutes,
        },
    )
    return delta


@bp.post("/appointments/<appointment_id>/adverse-events")
def record_event(appointment_id):
    authenticate("InfusionNurse")
    appointment = get("appointments", appointment_id)
    require_nurse_owner(appointment)
    data = body()
    grade = req_int(data, "grade", 1, 4)
    action = req_enum(data, "action", ACTIONS)
    note = opt_str(data, "note", 1, None, None, allow_null=True)
    appointment = must("appointments", appointment_id)
    check_state(appointment, ("INFUSING", "OBSERVING"))
    extension = GRADE_EXTENSION[grade]
    if action == "ABORT":
        extension = max(extension, 60)
    event = new_row(
        "events",
        {
            "appointment_id": appointment_id,
            "reported_by_nurse_id": actor_id(),
            "grade": grade,
            "action": action,
            "note": note,
            "observation_extension_minutes": extension,
            "review_outcome": None,
            "status": "REPORTED",
        },
    )
    delta = apply_observation_extension(appointment)
    derive.sync_readiness(appointment)
    if delta != 0:
        # A chair's committed_minutes is the sum of the chair_minutes of the visits
        # holding it while committed, so a lengthened window raises the figure.
        derive.recompute_chair(appointment.get("chair_id"))
    if delta > 0:
        derive.bump_colliding_visits(appointment)
    return created(present.plain(event))


@bp.get("/adverse-events/<event_id>")
def read_event(event_id):
    authenticate("MedicalDirector", "InfusionNurse", "Scheduler")
    return ok(present.plain(must("events", event_id)))


@bp.get("/adverse-events")
def list_events():
    authenticate("MedicalDirector", "InfusionNurse", "Scheduler")
    appointment_id = q_str("appointment_id")
    nurse_id = q_str("reported_by_nurse_id")
    grade = q_int("grade")
    status = q_enum("status", EVENT_STATUSES)
    items = []
    for event in rows("events"):
        if appointment_id is not None and event["appointment_id"] != appointment_id:
            continue
        if nurse_id is not None and event["reported_by_nurse_id"] != nurse_id:
            continue
        if grade is not None and int(event["grade"]) != grade:
            continue
        if status is not None and event["status"] != status:
            continue
        items.append(event)
    return paged("events", items)


@bp.post("/adverse-events/<event_id>/start-review")
def start_review(event_id):
    authenticate("MedicalDirector")
    event = must("events", event_id)
    if event["status"] != "REPORTED":
        raise ApiError("ERR_INVALID_ADVERSE_EVENT_STATE")
    apply_changes(event, {"status": "UNDER_REVIEW"})
    return ok(present.plain(event))


@bp.post("/adverse-events/<event_id>/close")
def close_review(event_id):
    authenticate("MedicalDirector")
    data = body()
    review_outcome = req_enum(data, "review_outcome", OUTCOMES)
    note = opt_str(data, "note", 1, None, None, allow_null=True)
    event = must("events", event_id)
    if event["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_ADVERSE_EVENT_STATE")
    changes = {"status": "CLOSED", "review_outcome": review_outcome}
    if note is not None:
        changes["note"] = note
    apply_changes(event, changes)
    appointment = get("appointments", event["appointment_id"])
    if appointment is not None:
        if review_outcome == "RESUME_SAME_DRUG":
            derive.sync_readiness(appointment)
        else:
            plan = derive.plan_of(appointment)
            if plan is not None:
                derive.suspend_plan(plan)
    return ok(present.plain(event))


# ============================================================ lab results
@bp.post("/lab-results")
def create_lab_result():
    authenticate("Pharmacist", "InfusionNurse")
    data = body()
    patient_id = req_str(data, "patient_id", 1, None)
    collected_dt, collected_raw = req_instant(data, "collected_at")
    anc_value = opt_num(data, "anc_value", 0, 100, None, allow_null=True)
    platelet_value = opt_int(data, "platelet_value", 0, 2000, None, allow_null=True)
    must("patients", patient_id)
    resulted = anc_value is not None and platelet_value is not None
    row = new_row(
        "labs",
        {
            "patient_id": patient_id,
            "collected_at": collected_raw,
            "anc_value": float(anc_value) if anc_value is not None else None,
            "platelet_value": platelet_value,
            "status": "RESULTED" if resulted else "PENDING",
        },
        versioned=False,
    )
    row["_collected_dt"] = collected_dt
    derive.sync_readiness_for_patient(patient_id)
    return created(present.plain(row))


@bp.get("/lab-results/<lab_id>")
def read_lab_result(lab_id):
    authenticate("Pharmacist", "InfusionNurse", "Scheduler", "MedicalDirector")
    return ok(present.plain(must("labs", lab_id)))


@bp.get("/lab-results")
def list_lab_results():
    authenticate("Pharmacist", "InfusionNurse", "Scheduler", "MedicalDirector")
    patient_id = q_str("patient_id")
    status = q_enum("status", LAB_STATUSES)
    items = []
    for row in rows("labs"):
        if patient_id is not None and row["patient_id"] != patient_id:
            continue
        if status is not None and row["status"] != status:
            continue
        items.append(row)
    items.sort(key=lambda r: (r["_collected_dt"], r["_seq"]), reverse=True)
    return paged("labs", items)


# ============================================================ reminders
@bp.post("/appointments/<appointment_id>/reminders")
def record_reminder(appointment_id):
    authenticate("Scheduler")
    data = body()
    channel = req_enum(data, "channel", CHANNELS)
    appointment = must("appointments", appointment_id)
    check_terminal(appointment)
    patient = get("patients", appointment["patient_id"])
    tier = (patient or {}).get("reminder_tier") or "STANDARD"
    existing = derive.reminders_of(appointment_id)
    if len(existing) >= REMINDER_CAPS.get(tier, 1):
        raise ApiError("ERR_REMINDER_CADENCE_EXCEEDED")
    row = new_row(
        "reminders",
        {
            "appointment_id": appointment_id,
            "patient_id": appointment["patient_id"],
            "channel": channel,
            "sequence_number": len(existing) + 1,
            "sent_at": db.iso_ms(db.now()),
            "outcome": "NO_RESPONSE",
        },
    )
    return created(present.plain(row))


@bp.get("/reminder-contacts/<reminder_id>")
def read_reminder(reminder_id):
    authenticate("Scheduler", "Patient", "MedicalDirector")
    row = get("reminders", reminder_id)
    if row is not None:
        # Ladder step 4: a patient may only address their own reminder contact.
        require_patient_owner(row["patient_id"])
    return ok(present.plain(must("reminders", reminder_id)))


@bp.get("/reminder-contacts")
def list_reminders():
    authenticate("Scheduler", "Patient", "MedicalDirector")
    appointment_id = q_str("appointment_id")
    patient_id = q_str("patient_id")
    channel = q_enum("channel", CHANNELS)
    outcome = q_enum("outcome", REMINDER_OUTCOMES)
    items = []
    for row in rows("reminders"):
        if appointment_id is not None and row["appointment_id"] != appointment_id:
            continue
        if patient_id is not None and row["patient_id"] != patient_id:
            continue
        if channel is not None and row["channel"] != channel:
            continue
        if outcome is not None and row["outcome"] != outcome:
            continue
        items.append(row)
    items.sort(key=lambda r: (int(r["sequence_number"]), r["_seq"]))
    return paged("reminders", items)


@bp.post("/reminder-contacts/<reminder_id>/response")
def respond_to_reminder(reminder_id):
    authenticate("Patient", "Scheduler")
    row = get("reminders", reminder_id)
    if row is not None:
        require_patient_owner(row["patient_id"])
    data = body()
    outcome = req_enum(data, "outcome", REMINDER_OUTCOMES)
    row = must("reminders", reminder_id)
    if row["outcome"] != "NO_RESPONSE":
        raise ApiError("ERR_REMINDER_ALREADY_ANSWERED")
    apply_changes(row, {"outcome": outcome})
    if outcome == "CANCEL_REQUEST":
        appointment = get("appointments", row["appointment_id"])
        if appointment is not None and appointment["schedule_status"] in ("TENTATIVE", "CONFIRMED"):
            derive.cancel_appointment(appointment, system=False)
    return ok(present.plain(row))
