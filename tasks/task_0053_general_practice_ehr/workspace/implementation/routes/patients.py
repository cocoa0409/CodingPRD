"""Patient endpoints (PRD §3.2) and patient sub-collections."""
from __future__ import annotations

import datetime as _dt

from flask import Blueprint, request, g

import db
from db import stamp_create, touch
from errors import (
    APIError,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_NOT_RESOURCE_OWNER,
    ERR_PATIENT_HAS_OPEN_VISITS,
)
from middleware import require
from response import ok_array, ok_object
from routes.common import lookup_or_404, paginate, parse_pagination, sort_by_created
from services import derive
from validation import get_body, require_date, require_enum, require_int, require_str

bp = Blueprint("patients", __name__)

SEXES = {"M", "F"}
OPEN_VISIT_STATES = {"SCHEDULED", "CHECKED_IN", "IN_PROGRESS", "CODED"}


def _ensure_patient_self(patient_id: str) -> None:
    """For Patient role, X-User-ID must equal the patient id (PRD §2.1)."""
    if g.user_role == "Patient" and g.user_id != patient_id:
        raise APIError(ERR_NOT_RESOURCE_OWNER, 403, "Patient may only read own records")


@bp.route("/patients", methods=["POST"])
def create_patient():
    require(["FrontDesk"])
    body = get_body()
    first_name = require_str(body, "first_name")
    last_name = require_str(body, "last_name")
    date_of_birth = require_date(body, "date_of_birth")
    sex = require_enum(body, "sex", SEXES)

    # date_of_birth must be on or before the current clock date (PRD §3.2).
    dob = _dt.date.fromisoformat(date_of_birth)
    if dob > db.clock.now().date():
        raise APIError(ERR_INVALID_REQUEST, 422, "date_of_birth must be on or before current date")

    rec = stamp_create({
        "first_name": first_name,
        "last_name": last_name,
        "date_of_birth": date_of_birth,
        "sex": sex,
        "pcp_id": None,
        "status": "ACTIVE",
        "lifetime_charges_cents": 0,
        "outstanding_balance_cents": 0,
        "active_medication_count": 0,
        "open_care_gaps": 0,
    })
    db.patients[rec["id"]] = rec
    return ok_object(derive.serialize_patient(rec), 201)


@bp.route("/patients/<pid>", methods=["GET"])
def get_patient(pid):
    require(["FrontDesk", "Provider", "Biller", "QualityAnalyst", "Patient"])
    rec = lookup_or_404(db.patients, pid, "Patient")
    _ensure_patient_self(pid)
    return ok_object(derive.serialize_patient(rec), 200)


@bp.route("/patients", methods=["GET"])
def list_patients():
    require(["FrontDesk", "Provider", "Biller", "QualityAnalyst"])
    limit, offset = parse_pagination()
    items = list(db.patients.values())
    pcp_id = request.args.get("pcp_id")
    status = request.args.get("status")
    if pcp_id is not None:
        items = [p for p in items if p.get("pcp_id") == pcp_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    items = sort_by_created(items)
    window, total = paginate(items, limit, offset)
    return ok_array([derive.serialize_patient(p) for p in window], limit, offset, total)


@bp.route("/patients/<pid>/deactivate", methods=["POST"])
def deactivate_patient(pid):
    require(["FrontDesk"])
    rec = lookup_or_404(db.patients, pid, "Patient")
    if rec["status"] != "ACTIVE":
        raise APIError(ERR_INVALID_STATE, 409, "Patient is not ACTIVE")

    # Priority 14: reject if any non-terminal visit exists.
    for v in db.visits.values():
        if v.get("patient_id") == pid and v.get("status") in OPEN_VISIT_STATES:
            raise APIError(ERR_PATIENT_HAS_OPEN_VISITS, 409, "Patient has open visits")

    former_pcp = rec.get("pcp_id")
    rec["status"] = "INACTIVE"
    rec["pcp_id"] = None
    touch(rec)
    # Former PCP panel_size recomputed (decremented).
    if former_pcp and former_pcp in db.providers:
        prov = db.providers[former_pcp]
        prov["panel_size"] = derive.compute_provider_panel_size(former_pcp)
    return ok_object(derive.serialize_patient(rec), 200)


@bp.route("/patients/<pid>/payments", methods=["POST"])
def record_payment(pid):
    require(["Biller"])
    rec = lookup_or_404(db.patients, pid, "Patient")
    body = get_body()
    amount_cents = require_int(body, "amount_cents")

    db.patient_payments[pid] = db.patient_payments.get(pid, 0) + amount_cents
    # Recompute ledger and mutate the patient (derived-field change -> version bump).
    derive.recompute_patient_ledger(rec)
    touch(rec)
    # PRD §6: payment recording modifies an existing resource -> 200 OK.
    return ok_object(derive.serialize_patient(rec), 200)


@bp.route("/patients/<pid>/visits", methods=["GET"])
def list_patient_visits(pid):
    require(["FrontDesk", "Provider", "Biller", "Patient"])
    lookup_or_404(db.patients, pid, "Patient")
    _ensure_patient_self(pid)
    limit, offset = parse_pagination()
    items = [v for v in db.visits.values() if v.get("patient_id") == pid]
    status = request.args.get("status")
    if status is not None:
        items = [v for v in items if v["status"] == status]
    items = sort_by_created(items)
    window, total = paginate(items, limit, offset)
    return ok_array([derive.serialize_visit(v) for v in window], limit, offset, total)


@bp.route("/patients/<pid>/prescriptions", methods=["GET"])
def list_patient_prescriptions(pid):
    require(["FrontDesk", "Provider", "Patient"])
    lookup_or_404(db.patients, pid, "Patient")
    _ensure_patient_self(pid)
    limit, offset = parse_pagination()
    items = [rx for rx in db.prescriptions.values() if rx.get("patient_id") == pid]
    status = request.args.get("status")
    if status is not None:
        items = [rx for rx in items if rx["status"] == status]
    items = sort_by_created(items)
    window, total = paginate(items, limit, offset)
    return ok_array([derive.serialize_prescription(rx) for rx in window], limit, offset, total)


@bp.route("/patients/<pid>/referrals", methods=["GET"])
def list_patient_referrals(pid):
    require(["FrontDesk", "Provider", "Patient"])
    lookup_or_404(db.patients, pid, "Patient")
    _ensure_patient_self(pid)
    limit, offset = parse_pagination()
    items = [r for r in db.referrals.values() if r.get("patient_id") == pid]
    status = request.args.get("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    items = sort_by_created(items)
    window, total = paginate(items, limit, offset)
    return ok_array([derive.serialize_referral(r) for r in window], limit, offset, total)


@bp.route("/patients/<pid>/hedis-measures", methods=["GET"])
def list_patient_hedis(pid):
    require(["QualityAnalyst", "Provider", "FrontDesk"])
    lookup_or_404(db.patients, pid, "Patient")
    limit, offset = parse_pagination()
    items = [m for m in db.hedis_measures.values() if m.get("patient_id") == pid]
    measure_type = request.args.get("measure_type")
    measurement_year = request.args.get("measurement_year")
    status = request.args.get("status")
    if measure_type is not None:
        items = [m for m in items if m["measure_type"] == measure_type]
    if measurement_year is not None:
        try:
            my = int(measurement_year)
        except ValueError:
            raise APIError(ERR_INVALID_REQUEST, 422, "measurement_year must be an integer")
        items = [m for m in items if m["measurement_year"] == my]
    if status is not None:
        items = [m for m in items if m["status"] == status]
    items = sort_by_created(items)
    window, total = paginate(items, limit, offset)
    return ok_array([derive.serialize_hedis_measure(m) for m in window], limit, offset, total)


@bp.route("/patients/<pid>/portal-account", methods=["GET"])
def get_patient_portal(pid):
    require(["FrontDesk", "Patient"])
    lookup_or_404(db.patients, pid, "Patient")
    _ensure_patient_self(pid)
    limit, offset = parse_pagination()
    items = [pa for pa in db.portal_accounts.values() if pa.get("patient_id") == pid]
    items = sort_by_created(items)
    window, total = paginate(items, limit, offset)
    return ok_array([derive.serialize_portal_account(pa) for pa in window], limit, offset, total)
