"""Flat top-level cross-aggregate search and get-by-id endpoints (PRD §4)."""
from flask import Blueprint, request

import db
from middleware import authenticate, authorize, paginate
from models import serialize, serialize_list
from lookups import leaf_or_404
from response import ok

bp = Blueprint("search", __name__)

ALL4 = ["FrontDesk", "Provider", "PracticeAdmin", "BillingClerk"]
NO_BILLING = ["Provider", "FrontDesk", "PracticeAdmin"]


def _filter_eq(items, args, fields):
    for f in fields:
        v = args.get(f)
        if v is not None:
            items = [a for a in items if a.get(f) == v]
    return items


# ---- Appointments ----
@bp.route("/appointments", methods=["GET"])
def search_appointments():
    _, role = authenticate()
    authorize(role, ALL4)
    items = list(db.appointments.values())
    items = _filter_eq(items, request.args, [
        "patient_id", "provider_id", "treatment_room_id", "insurance_policy_id",
        "appointment_series_id", "plan_phase_id", "replaces_appointment_id",
        "attendance_status", "billing_status",
    ])
    window, pg = paginate(items)
    return ok(serialize_list(window), pagination=pg)


@bp.route("/appointments/<appt_id>", methods=["GET"])
def get_appointment(appt_id):
    _, role = authenticate()
    authorize(role, ALL4)
    rec = leaf_or_404(db.appointments, appt_id)
    return ok(serialize(rec))


# ---- Appointment series ----
@bp.route("/appointment-series", methods=["GET"])
def search_series():
    _, role = authenticate()
    authorize(role, NO_BILLING)
    items = list(db.appointment_series.values())
    items = _filter_eq(items, request.args, [
        "treatment_plan_id", "plan_phase_id", "provider_id", "treatment_room_id", "status",
    ])
    window, pg = paginate(items)
    return ok(serialize_list(window), pagination=pg)


@bp.route("/appointment-series/<series_id>", methods=["GET"])
def get_series(series_id):
    _, role = authenticate()
    authorize(role, NO_BILLING)
    rec = leaf_or_404(db.appointment_series, series_id)
    return ok(serialize(rec))


# ---- Plan phases ----
@bp.route("/plan-phases", methods=["GET"])
def search_phases():
    _, role = authenticate()
    authorize(role, NO_BILLING)
    items = list(db.plan_phases.values())
    items = _filter_eq(items, request.args, ["treatment_plan_id", "status"])
    window, pg = paginate(items)
    return ok(serialize_list(window), pagination=pg)


@bp.route("/plan-phases/<phase_id>", methods=["GET"])
def get_phase(phase_id):
    _, role = authenticate()
    authorize(role, NO_BILLING)
    rec = leaf_or_404(db.plan_phases, phase_id)
    return ok(serialize(rec))


# ---- Treatment plans ----
@bp.route("/treatment-plans", methods=["GET"])
def search_plans():
    _, role = authenticate()
    authorize(role, ALL4)
    items = list(db.treatment_plans.values())
    items = _filter_eq(items, request.args, ["patient_id", "exam_record_id", "status"])
    window, pg = paginate(items)
    return ok(serialize_list(window), pagination=pg)


@bp.route("/treatment-plans/<plan_id>", methods=["GET"])
def get_plan(plan_id):
    _, role = authenticate()
    authorize(role, ALL4)
    rec = leaf_or_404(db.treatment_plans, plan_id)
    return ok(serialize(rec))


# ---- Exams ----
@bp.route("/exams", methods=["GET"])
def search_exams():
    _, role = authenticate()
    authorize(role, NO_BILLING)
    items = list(db.exam_records.values())
    items = _filter_eq(items, request.args, ["patient_id", "provider_id", "status", "exam_type"])
    window, pg = paginate(items)
    return ok(serialize_list(window), pagination=pg)


@bp.route("/exams/<exam_id>", methods=["GET"])
def get_exam(exam_id):
    _, role = authenticate()
    authorize(role, NO_BILLING)
    rec = leaf_or_404(db.exam_records, exam_id)
    return ok(serialize(rec))


# ---- Insurance policies ----
@bp.route("/insurance-policies", methods=["GET"])
def search_policies():
    _, role = authenticate()
    authorize(role, ["FrontDesk", "BillingClerk", "PracticeAdmin", "Provider"])
    items = list(db.insurance_policies.values())
    items = _filter_eq(items, request.args, ["patient_id", "status"])
    window, pg = paginate(items)
    return ok(serialize_list(window), pagination=pg)


@bp.route("/insurance-policies/<policy_id>", methods=["GET"])
def get_policy(policy_id):
    _, role = authenticate()
    authorize(role, ["FrontDesk", "BillingClerk", "PracticeAdmin", "Provider"])
    rec = leaf_or_404(db.insurance_policies, policy_id)
    return ok(serialize(rec))


# ---- SOAP notes ----
@bp.route("/soap-notes", methods=["GET"])
def search_soap():
    _, role = authenticate()
    authorize(role, ALL4)
    items = list(db.soap_notes.values())
    items = _filter_eq(items, request.args, ["appointment_id", "provider_id", "status"])
    window, pg = paginate(items)
    return ok(serialize_list(window), pagination=pg)


@bp.route("/soap-notes/<note_id>", methods=["GET"])
def get_soap(note_id):
    _, role = authenticate()
    authorize(role, ALL4)
    rec = leaf_or_404(db.soap_notes, note_id)
    return ok(serialize(rec))


# ---- Ledger entries ----
@bp.route("/ledger-entries", methods=["GET"])
def search_ledger():
    _, role = authenticate()
    authorize(role, ["FrontDesk", "PracticeAdmin", "BillingClerk"])
    items = list(db.ledger_entries.values())
    items = _filter_eq(items, request.args, ["patient_id", "appointment_id", "entry_type"])
    window, pg = paginate(items)
    return ok(serialize_list(window), pagination=pg)


@bp.route("/ledger-entries/<entry_id>", methods=["GET"])
def get_ledger(entry_id):
    _, role = authenticate()
    authorize(role, ["FrontDesk", "PracticeAdmin", "BillingClerk"])
    rec = leaf_or_404(db.ledger_entries, entry_id)
    return ok(serialize(rec))
