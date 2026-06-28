"""Appointment endpoints (PRD §3.9): scheduling with cross-entity + temporal
overlap checks, and the visit lifecycle."""

from flask import Blueprint, request

import errors
from db import db, lock
from helpers import (
    get_json_body, require_str, require_enum, require_fields, stamp_new,
    parse_pagination, sort_and_paginate, touch,
)
from lookups import get_or_404, fk_or_404
from middleware import require_roles
from response import success, list_success
from serializers import public, public_list
from clock import clock, parse_iso8601
from datetime import timedelta

bp = Blueprint("appointments", __name__)

VISIT_TYPES = {"BONDING", "ADJUSTMENT", "EMERGENCY", "DEBOND"}
NON_TERMINAL_APPT = {"SCHEDULED", "CHECKED_IN"}
PLAN_REQUIRED_VISITS = {"ADJUSTMENT", "BONDING", "DEBOND"}


@bp.post("/appointments")
@require_roles("FrontDesk", "ClinicAdmin")
def create_appointment():
    body = get_json_body()
    patient_id = require_str(body, "patient_id")
    provider_id = require_str(body, "provider_id")
    chair_id = require_str(body, "chair_id")
    visit_type = require_enum(body, "visit_type", VISIT_TYPES)
    require_fields(body, ["starts_at", "ends_at"])
    starts_raw = body["starts_at"]
    ends_raw = body["ends_at"]
    if not isinstance(starts_raw, str) or not isinstance(ends_raw, str):
        raise errors.invalid_request("starts_at and ends_at must be strings")
    try:
        starts_at = parse_iso8601(starts_raw)
        ends_at = parse_iso8601(ends_raw)
    except ValueError:
        raise errors.invalid_request("starts_at/ends_at must be ISO 8601 timestamps")
    # ends_at must be strictly after starts_at.
    if ends_at <= starts_at:
        raise errors.invalid_request("ends_at must be strictly after starts_at")

    plan_id = body.get("plan_id")
    if plan_id is not None and not isinstance(plan_id, str):
        raise errors.invalid_request("plan_id must be a string")
    if visit_type in PLAN_REQUIRED_VISITS and plan_id is None:
        raise errors.invalid_request(f"plan_id is required for {visit_type} visits")

    with lock:
        # Priority 3: existence (left-to-right).
        fk_or_404(db.patients, patient_id)
        provider = fk_or_404(db.providers, provider_id)
        chair = fk_or_404(db.chairs, chair_id)
        plan = None
        if plan_id is not None:
            plan = fk_or_404(db.treatment_plans, plan_id)

        # Priority 7: cross-entity state — plan must be ACTIVE for treatment visits.
        if visit_type in PLAN_REQUIRED_VISITS:
            if plan is None or plan["status"] != "ACTIVE":
                raise errors.cross_entity_state()

        # Priority 9: chair temporal overlap (closed interval with turnover buffer).
        buffer_min = chair.get("turnover_buffer_minutes", 0)
        for appt in db.appointments.values():
            if appt["chair_id"] != chair_id or appt["status"] not in NON_TERMINAL_APPT:
                continue
            ex_start = parse_iso8601(appt["starts_at"])
            ex_end = parse_iso8601(appt["ends_at"]) + timedelta(minutes=buffer_min)
            new_end = ends_at + timedelta(minutes=buffer_min)
            # Overlap of half-open [start, end+buffer) intervals.
            if starts_at < ex_end and ex_start < new_end:
                raise errors.chair_conflict()

        # Priority 10: provider temporal overlap (half-open, no buffer; adjacency OK).
        for appt in db.appointments.values():
            if appt["provider_id"] != provider_id or appt["status"] not in NON_TERMINAL_APPT:
                continue
            ex_start = parse_iso8601(appt["starts_at"])
            ex_end = parse_iso8601(appt["ends_at"])
            if starts_at < ex_end and ex_start < ends_at:
                raise errors.provider_conflict()

        rec = {
            "patient_id": patient_id,
            "provider_id": provider_id,
            "chair_id": chair_id,
            "plan_id": plan_id,
            "visit_type": visit_type,
            "starts_at": starts_raw,
            "ends_at": ends_raw,
            "status": "SCHEDULED",
        }
        stamp_new(rec)
        db.appointments[rec["id"]] = rec
        return success(public(rec), 201)


@bp.get("/appointments/<appointment_id>")
@require_roles("FrontDesk", "ClinicAdmin", "Orthodontist", "Guardian")
def get_appointment(appointment_id):
    with lock:
        rec = get_or_404(db.appointments, appointment_id)
        _guardian_owns_appt(rec)
        return success(public(rec), 200)


@bp.get("/appointments")
@require_roles("FrontDesk", "ClinicAdmin", "Orthodontist", "Guardian")
def list_appointments():
    from flask import g
    with lock:
        limit, offset = parse_pagination()
        records = list(db.appointments.values())
        for field in ("patient_id", "provider_id", "chair_id", "plan_id", "status"):
            val = request.args.get(field)
            if val is not None:
                records = [r for r in records if r.get(field) == val]
        if g.user_role == "Guardian":
            records = [r for r in records if _appt_owned_by_guardian(r)]
        page, total = sort_and_paginate(records, limit, offset)
        return list_success(public_list(page), limit, offset, total, 200)


@bp.post("/appointments/<appointment_id>/check-in")
@require_roles("FrontDesk")
def checkin_appointment(appointment_id):
    with lock:
        appt = get_or_404(db.appointments, appointment_id)
        if appt["status"] != "SCHEDULED":
            raise errors.invalid_state()
        # Window opens 60 minutes before starts_at.
        starts_at = parse_iso8601(appt["starts_at"])
        if clock.now() < starts_at - timedelta(minutes=60):
            raise errors.too_early_checkin()
        appt["status"] = "CHECKED_IN"
        touch(appt)
        return success(public(appt), 200)


@bp.post("/appointments/<appointment_id>/complete")
@require_roles("Orthodontist")
def complete_appointment(appointment_id):
    with lock:
        appt = get_or_404(db.appointments, appointment_id)
        if appt["status"] != "CHECKED_IN":
            raise errors.invalid_state()
        appt["status"] = "COMPLETED"
        touch(appt)
        return success(public(appt), 200)


@bp.post("/appointments/<appointment_id>/cancel")
@require_roles("FrontDesk")
def cancel_appointment(appointment_id):
    with lock:
        appt = get_or_404(db.appointments, appointment_id)
        if appt["status"] != "SCHEDULED":
            raise errors.invalid_state()
        appt["status"] = "CANCELLED"
        touch(appt)
        return success(public(appt), 200)


@bp.post("/appointments/<appointment_id>/no-show")
@require_roles("FrontDesk")
def noshow_appointment(appointment_id):
    with lock:
        appt = get_or_404(db.appointments, appointment_id)
        if appt["status"] not in ("SCHEDULED", "CHECKED_IN"):
            raise errors.invalid_state()
        starts_at = parse_iso8601(appt["starts_at"])
        if clock.now() < starts_at:
            raise errors.too_early_noshow()
        appt["status"] = "NO_SHOW"
        touch(appt)
        return success(public(appt), 200)


# -----------------------------------------------------------------------------
# Ownership helpers
# -----------------------------------------------------------------------------

def _appt_owned_by_guardian(appt):
    from lookups import family_of_patient, guardian_owns_family
    pat = db.patients.get(appt["patient_id"])
    return pat is not None and guardian_owns_family(family_of_patient(pat))


def _guardian_owns_appt(appt):
    from flask import g
    if g.user_role == "Guardian" and not _appt_owned_by_guardian(appt):
        raise errors.forbidden()
