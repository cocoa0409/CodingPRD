"""Detention authority: holds, extension petitions, court hearings (PRD §3.3, §3.4)."""

from datetime import timedelta

from flask import Blueprint

import calc
import cascades
import serializers
from auth import (
    ANY_ROLE,
    ATTENDING_PSYCHIATRIST,
    COMPLIANCE_OFFICER,
    INTAKE_CLINICIAN,
    RIGHTS_ADVOCATE_ROLE,
    context,
)
from envelope import list_response, object_response
from errors import fail
from store import base_row, db, ordered, touch
from timeutil import COURT_CLOSE, COURT_OPEN, at_time, is_judicial_day
from validation import apply_filters, body, filters, pagination, venum, vdt, vint, vstr

bp = Blueprint("holds", __name__)

HOLD_TYPES = ("EMERGENCY_72H", "EXTENSION_14D")
OPEN_PETITION_STATES = ("FILED", "HEARING_SCHEDULED", "CONTINUED")
HEARING_OUTCOMES = ("GRANTED", "DENIED", "CONTINUED")
HEARING_DURATIONS = (30, 60)
CONTINUANCE_LIMIT = 2


# --------------------------------------------------------------------------- #
# Holds
# --------------------------------------------------------------------------- #
def _build_hold(patient_id, evaluation_id, hold_type, clock_started_at):
    row = base_row()
    statutory_hours = calc.statutory_hours_for(hold_type)
    cert_deadline, release_deadline, filing_deadline = calc.hold_deadlines(
        clock_started_at, statutory_hours
    )
    row.update(
        {
            "patient_id": patient_id,
            "evaluation_id": evaluation_id,
            "predecessor_hold_id": None,
            "initiated_by_clinician_id": None,
            "certifying_clinician_id": None,
            "hold_type": hold_type,
            "statutory_hours": statutory_hours,
            "clock_started_at": clock_started_at,
            "certification_deadline_at": cert_deadline,
            "release_deadline_at": release_deadline,
            "petition_filing_deadline_at": filing_deadline,
            "certified_at": None,
            "status": "PENDING_CERTIFICATION",
            "closure_reason": None,
        }
    )
    return row


@bp.post("/behavioral-health/holds")
def create_hold():
    user_id, _role = context((INTAKE_CLINICIAN, ATTENDING_PSYCHIATRIST))
    data = body()
    patient_id = vstr(data, "patient_id")
    evaluation_id = vstr(data, "evaluation_id")
    hold_type = venum(data, "hold_type", HOLD_TYPES)
    if hold_type != "EMERGENCY_72H":
        # EXTENSION_14D is never client-created; it exists only as a system successor.
        fail("ERR_INVALID_REQUEST", "hold_type must be EMERGENCY_72H on initiation")

    patient = db.patients.get(patient_id)
    if patient is None:
        fail("ERR_PATIENT_NOT_FOUND", "patient not found")
    evaluation = db.evaluations.get(evaluation_id)
    if evaluation is None:
        fail("ERR_EVALUATION_NOT_FOUND", "evaluation not found")
    if evaluation["status"] != "SIGNED":
        fail("ERR_EVALUATION_NOT_SIGNED", "the anchoring evaluation is not signed")
    if evaluation["recommended_status"] != "INVOLUNTARY_HOLD":
        fail("ERR_CLINICAL_CRITERIA_NOT_MET", "the evaluation does not recommend an involuntary hold")

    row = _build_hold(patient_id, evaluation_id, hold_type, evaluation["signed_at"])
    row["initiated_by_clinician_id"] = user_id
    db.holds[row["id"]] = row
    return object_response(serializers.hold(row), 201)


@bp.post("/behavioral-health/holds/<hold_id>/certify")
def certify_hold(hold_id):
    user_id, _role = context((ATTENDING_PSYCHIATRIST,))
    body()
    hold = db.holds.get(hold_id)
    if hold is None:
        fail("ERR_HOLD_NOT_FOUND", "hold not found")
    if hold["status"] != "PENDING_CERTIFICATION":
        fail("ERR_HOLD_NOT_PENDING_CERTIFICATION", "hold is not pending certification")
    if hold["initiated_by_clinician_id"] == user_id:
        fail("ERR_SEGREGATION_OF_DUTIES", "the initiating clinician may not certify this hold")
    if db.now() > hold["certification_deadline_at"]:
        fail("ERR_CERTIFICATION_WINDOW_CLOSED", "the certification window has closed")

    hold["status"] = "ACTIVE"
    hold["certified_at"] = db.now()
    hold["certifying_clinician_id"] = user_id
    touch(hold)

    patient = db.patients.get(hold["patient_id"])
    if patient is not None:
        cascades.recompute_patient_hold_count(patient)
        for admission in cascades._patient_admissions_in_scope(patient["id"]):
            if admission["legal_status"] != "INVOLUNTARY":
                admission["legal_status"] = "INVOLUNTARY"
                touch(admission)
    return object_response(serializers.hold(hold))


@bp.post("/behavioral-health/holds/<hold_id>/rescind")
def rescind_hold(hold_id):
    user_id, _role = context((ATTENDING_PSYCHIATRIST,))
    data = body()
    rescind_reason = vstr(data, "rescind_reason")
    hold = db.holds.get(hold_id)
    if hold is None:
        fail("ERR_HOLD_NOT_FOUND", "hold not found")
    if hold["status"] not in ("PENDING_CERTIFICATION", "ACTIVE"):
        fail("ERR_HOLD_NOT_ACTIVE", "hold may not be rescinded from its current status")

    was_active = hold["status"] == "ACTIVE"
    hold["status"] = "RESCINDED"
    hold["closure_reason"] = rescind_reason
    touch(hold)
    if was_active:
        cascades.close_hold_cascade(hold, "RESCIND", responding_clinician_id=user_id)
    return object_response(serializers.hold(hold))


@bp.get("/behavioral-health/holds/<hold_id>")
def get_hold(hold_id):
    context(ANY_ROLE)
    hold = db.holds.get(hold_id)
    if hold is None:
        fail("ERR_HOLD_NOT_FOUND", "hold not found")
    return object_response(serializers.hold(hold))


@bp.get("/behavioral-health/holds")
def list_holds():
    context(ANY_ROLE)
    limit, offset = pagination()
    rows = apply_filters(
        list(db.holds.values()),
        filters(
            "patient_id",
            "evaluation_id",
            "predecessor_hold_id",
            "initiated_by_clinician_id",
            "certifying_clinician_id",
            "status",
        ),
    )
    rows = ordered(rows)
    total = len(rows)
    page = rows[offset : offset + limit]
    return list_response([serializers.hold(r) for r in page], limit, offset, total)


# --------------------------------------------------------------------------- #
# Petitions
# --------------------------------------------------------------------------- #
def _open_petition_for(hold_id):
    for petition in ordered(list(db.petitions.values())):
        if petition["hold_id"] == hold_id and petition["status"] in OPEN_PETITION_STATES:
            return petition
    return None


@bp.post("/behavioral-health/petitions")
def create_petition():
    user_id, _role = context((ATTENDING_PSYCHIATRIST,))
    data = body()
    hold_id = vstr(data, "hold_id")
    requested_hold_type = venum(data, "requested_hold_type", HOLD_TYPES)
    petition_grounds = vstr(data, "petition_grounds")
    if requested_hold_type != "EXTENSION_14D":
        fail("ERR_INVALID_REQUEST", "requested_hold_type must be EXTENSION_14D")

    hold = db.holds.get(hold_id)
    if hold is None:
        fail("ERR_HOLD_NOT_FOUND", "hold not found")
    if hold["status"] != "ACTIVE":
        fail("ERR_HOLD_NOT_ACTIVE", "petitions may only be filed against an ACTIVE hold")
    if db.now() > hold["petition_filing_deadline_at"]:
        fail("ERR_PETITION_WINDOW_CLOSED", "the petition filing window has closed")
    if _open_petition_for(hold_id) is not None:
        fail("ERR_PETITION_PENDING", "a petition for this hold is already open")

    row = base_row()
    row.update(
        {
            "hold_id": hold_id,
            "petitioning_clinician_id": user_id,
            "requested_hold_type": requested_hold_type,
            "petition_grounds": petition_grounds,
            "filed_at": db.now(),
            "continuance_count": 0,
            "status": "FILED",
        }
    )
    db.petitions[row["id"]] = row
    return object_response(serializers.petition(row), 201)


@bp.post("/behavioral-health/petitions/<petition_id>/withdraw")
def withdraw_petition(petition_id):
    context((ATTENDING_PSYCHIATRIST, RIGHTS_ADVOCATE_ROLE))
    body()
    petition = db.petitions.get(petition_id)
    if petition is None:
        fail("ERR_REFERENCED_RESOURCE_NOT_FOUND", "petition not found")
    if petition["status"] not in OPEN_PETITION_STATES:
        fail("ERR_PETITION_NOT_OPEN", "petition may not be withdrawn from its current status")

    petition["status"] = "WITHDRAWN"
    touch(petition)
    advocate_ids = []
    for hearing in ordered(list(db.hearings.values())):
        if hearing["petition_id"] != petition_id or hearing["status"] != "SCHEDULED":
            continue
        hearing["status"] = "VACATED"
        touch(hearing)
        if hearing["advocate_clinician_id"] not in advocate_ids:
            advocate_ids.append(hearing["advocate_clinician_id"])
    for advocate_id in advocate_ids:
        cascades.recompute_clinician_docket_by_id(advocate_id)
    return object_response(serializers.petition(petition))


@bp.get("/behavioral-health/petitions/<petition_id>")
def get_petition(petition_id):
    context(ANY_ROLE)
    petition = db.petitions.get(petition_id)
    if petition is None:
        fail("ERR_REFERENCED_RESOURCE_NOT_FOUND", "petition not found")
    return object_response(serializers.petition(petition))


@bp.get("/behavioral-health/petitions")
def list_petitions():
    context(ANY_ROLE)
    limit, offset = pagination()
    rows = apply_filters(
        list(db.petitions.values()),
        filters("hold_id", "petitioning_clinician_id", "status"),
    )
    rows = ordered(rows)
    total = len(rows)
    page = rows[offset : offset + limit]
    return list_response([serializers.petition(r) for r in page], limit, offset, total)


# --------------------------------------------------------------------------- #
# Hearings
# --------------------------------------------------------------------------- #
def _slot_is_valid(start, end, now):
    if not is_judicial_day(start.date()):
        return False
    if start < at_time(start.date(), COURT_OPEN):
        return False
    if end > at_time(start.date(), COURT_CLOSE):
        return False
    if start <= now:
        return False
    return True


@bp.post("/behavioral-health/hearings")
def create_hearing():
    context((RIGHTS_ADVOCATE_ROLE, COMPLIANCE_OFFICER))
    data = body()
    petition_id = vstr(data, "petition_id")
    advocate_clinician_id = vstr(data, "advocate_clinician_id")
    scheduled_start_at = vdt(data, "scheduled_start_at")
    duration_minutes = vint(data, "duration_minutes")
    if duration_minutes not in HEARING_DURATIONS:
        fail("ERR_INVALID_REQUEST", "duration_minutes must be exactly 30 or 60")

    petition = db.petitions.get(petition_id)
    if petition is None:
        fail("ERR_REFERENCED_RESOURCE_NOT_FOUND", "petition not found")
    advocate = db.clinicians.get(advocate_clinician_id)
    if advocate is None:
        fail("ERR_REFERENCED_RESOURCE_NOT_FOUND", "advocate clinician not found")
    if petition["status"] not in ("FILED", "CONTINUED"):
        fail("ERR_PETITION_NOT_OPEN", "petition is not open for hearing scheduling")

    scheduled_end_at = scheduled_start_at + timedelta(minutes=duration_minutes)
    if not _slot_is_valid(scheduled_start_at, scheduled_end_at, db.now()):
        fail("ERR_HEARING_SLOT_INVALID", "the requested docket slot is not a valid court slot")

    hold = db.holds.get(petition["hold_id"])
    release_deadline = hold["release_deadline_at"] if hold is not None else None
    if release_deadline is not None and scheduled_end_at > release_deadline:
        fail("ERR_HEARING_BEYOND_HOLD_EXPIRY", "the hearing ends after detention authority lapses")
    if calc.docket_conflict(advocate_clinician_id, scheduled_start_at, scheduled_end_at):
        fail("ERR_ADVOCATE_DOCKET_CONFLICT", "the advocate's buffered docket collides")
    if advocate["staff_role"] != "RIGHTS_ADVOCATE":
        fail("ERR_ADVOCATE_NOT_QUALIFIED", "the nominated advocate is not a RIGHTS_ADVOCATE")

    row = base_row()
    row.update(
        {
            "petition_id": petition_id,
            "advocate_clinician_id": advocate_clinician_id,
            "scheduled_start_at": scheduled_start_at,
            "duration_minutes": duration_minutes,
            "scheduled_end_at": scheduled_end_at,
            "status": "SCHEDULED",
            "outcome": "PENDING",
            "findings_note": None,
        }
    )
    db.hearings[row["id"]] = row

    petition["status"] = "HEARING_SCHEDULED"
    touch(petition)
    cascades.recompute_clinician_docket(advocate)
    return object_response(serializers.hearing(row), 201)


def _record_granted(hearing, petition, hold):
    hearing["status"] = "HELD"
    hearing["outcome"] = "GRANTED"
    petition["status"] = "GRANTED"
    touch(petition)

    hold["status"] = "SUPERSEDED"
    touch(hold)
    successor = _build_hold(
        hold["patient_id"], hold["evaluation_id"], "EXTENSION_14D", hold["release_deadline_at"]
    )
    successor["predecessor_hold_id"] = hold["id"]
    successor["status"] = "ACTIVE"
    successor["certifying_clinician_id"] = petition["petitioning_clinician_id"]
    db.holds[successor["id"]] = successor

    patient = db.patients.get(hold["patient_id"])
    if patient is not None:
        cascades.recompute_patient_hold_count(patient)


def _record_denied(hearing, petition, hold):
    hearing["status"] = "HELD"
    hearing["outcome"] = "DENIED"
    petition["status"] = "DENIED"
    touch(petition)

    hold["status"] = "DISCHARGED_BY_COURT"
    hold["closure_reason"] = "COURT_DENIED_EXTENSION"
    touch(hold)
    cascades.close_hold_cascade(hold, "COURT_DENIED")


def _record_continued(hearing, petition):
    # hearing.outcome stays PENDING: the stored enum is PENDING | GRANTED | DENIED.
    hearing["status"] = "CONTINUED"
    petition["status"] = "CONTINUED"
    cascades.recompute_petition_continuances(petition)
    touch(petition)


@bp.post("/behavioral-health/hearings/<hearing_id>/record-outcome")
def record_hearing_outcome(hearing_id):
    context((COMPLIANCE_OFFICER,))
    data = body()
    outcome = venum(data, "outcome", HEARING_OUTCOMES)
    findings_note = vstr(data, "findings_note")

    hearing = db.hearings.get(hearing_id)
    if hearing is None:
        fail("ERR_REFERENCED_RESOURCE_NOT_FOUND", "hearing not found")
    petition = db.petitions.get(hearing["petition_id"])
    if petition is None or petition["status"] != "HEARING_SCHEDULED":
        fail("ERR_PETITION_NOT_OPEN", "the petition is not awaiting a hearing outcome")
    if hearing["status"] != "SCHEDULED":
        fail("ERR_HEARING_NOT_SCHEDULED", "hearing is not scheduled")

    hold = db.holds.get(petition["hold_id"])
    if outcome in ("GRANTED", "DENIED"):
        if hold is None or hold["status"] != "ACTIVE":
            fail("ERR_HOLD_NOT_ACTIVE", "the petition's hold is no longer ACTIVE")
    if outcome == "CONTINUED" and petition["continuance_count"] >= CONTINUANCE_LIMIT:
        fail("ERR_CONTINUANCE_LIMIT_REACHED", "the continuance limit for this petition is reached")

    hearing["findings_note"] = findings_note
    if outcome == "GRANTED":
        _record_granted(hearing, petition, hold)
    elif outcome == "DENIED":
        _record_denied(hearing, petition, hold)
    else:
        _record_continued(hearing, petition)
    touch(hearing)
    cascades.recompute_clinician_docket_by_id(hearing["advocate_clinician_id"])
    return object_response(serializers.hearing(hearing))


@bp.get("/behavioral-health/hearings/<hearing_id>")
def get_hearing(hearing_id):
    context(ANY_ROLE)
    hearing = db.hearings.get(hearing_id)
    if hearing is None:
        fail("ERR_REFERENCED_RESOURCE_NOT_FOUND", "hearing not found")
    return object_response(serializers.hearing(hearing))


@bp.get("/behavioral-health/hearings")
def list_hearings():
    context(ANY_ROLE)
    limit, offset = pagination()
    rows = apply_filters(
        list(db.hearings.values()),
        filters("petition_id", "advocate_clinician_id", "status"),
    )
    rows = ordered(rows)
    total = len(rows)
    page = rows[offset : offset + limit]
    return list_response([serializers.hearing(r) for r in page], limit, offset, total)
