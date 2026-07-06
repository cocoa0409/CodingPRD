import math
import os

from flask import Flask, request

import db
import errors
import helpers
import ledger_service
import response
import serialize
import util
from middleware import require_role

app = Flask(__name__)
app.url_map.strict_slashes = False

AGREEMENT_VALIDITY_DAYS = 365
PDMP_FRESHNESS_DAYS = 30
SECONDS_PER_DAY = 86400

ALL_ROLES = ["ClinicAdmin", "IntakeCoordinator", "Prescriber", "ComplianceOfficer", "PriorAuthClerk"]


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------
@app.errorhandler(errors.ApiError)
def handle_api_error(exc):
    return response.error(exc.error_id, exc.http_status, exc.message)


@app.errorhandler(404)
def handle_404(_exc):
    return response.error(errors.ERR_INVALID_REQUEST, 400, "unknown route")


@app.errorhandler(405)
def handle_405(_exc):
    return response.error(errors.ERR_INVALID_REQUEST, 400, "method not allowed")


@app.errorhandler(Exception)
def handle_uncaught(exc):
    if isinstance(exc, errors.ApiError):
        return handle_api_error(exc)
    return response.error(errors.ERR_INVALID_REQUEST, 400, str(exc))


def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise errors.ApiError(errors.ERR_INVALID_REQUEST, 400, "body must be an object")
    return data


def clinic_utc(clinic):
    return util.parse_iso(clinic["current_utc"])


# ===========================================================================
# Clinics
# ===========================================================================
@app.route("/clinics", methods=["POST"])
def create_clinic():
    require_role(["ClinicAdmin"])
    b = body()
    name = util.require(b, "name")
    state_code = util.require(b, "state_code")
    med_threshold = b.get("med_review_threshold_mg", 90)
    tolerance = b.get("pill_count_tolerance", 2)
    if med_threshold is None:
        med_threshold = 90
    if tolerance is None:
        tolerance = 2
    rec = db.base_fields()
    rec.update({
        "name": name,
        "state_code": state_code,
        "med_review_threshold_mg": med_threshold,
        "pill_count_tolerance": tolerance,
        "current_utc": db.DEFAULT_CLOCK,
    })
    db.clinics[rec["id"]] = rec
    return response.created(serialize.clinic(rec))


@app.route("/clinics/<clinic_id>", methods=["GET"])
def get_clinic(clinic_id):
    require_role(ALL_ROLES)
    c = helpers.get_clinic(clinic_id)
    return response.ok(serialize.clinic(c))


@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_role(["ClinicAdmin"])
    b = body()
    clinic_id = util.require(b, "clinic_id")
    to_iso = util.require(b, "to_iso8601")
    c = helpers.get_clinic(clinic_id)
    util.parse_iso(to_iso)  # validate format
    c["current_utc"] = to_iso
    db.touch(c)
    return response.ok(serialize.clinic(c))


# ===========================================================================
# Providers
# ===========================================================================
@app.route("/clinics/<clinic_id>/providers", methods=["POST"])
def create_provider(clinic_id):
    require_role(["ClinicAdmin"])
    helpers.get_clinic(clinic_id)
    b = body()
    full_name = util.require(b, "full_name")
    dea_number = util.require(b, "dea_number")
    role_kind = util.require(b, "role_kind")
    if role_kind not in ("PRESCRIBER", "COMPLIANCE_OFFICER"):
        raise errors.ApiError(errors.ERR_INVALID_ENUM_VALUE, 422, "invalid role_kind")
    rec = db.base_fields()
    rec.update({
        "clinic_id": clinic_id,
        "full_name": full_name,
        "dea_number": dea_number,
        "role_kind": role_kind,
    })
    db.providers[rec["id"]] = rec
    return response.created(serialize.provider(rec))


@app.route("/clinics/<clinic_id>/providers", methods=["GET"])
def list_clinic_providers(clinic_id):
    require_role(ALL_ROLES)
    helpers.get_clinic(clinic_id)
    items = [p for p in db.providers.values() if p["clinic_id"] == clinic_id]
    items = helpers.sort_created(items)
    page, limit, offset, total = helpers.paginate(items)
    return response.list_ok([serialize.provider(p) for p in page], limit, offset, total)


# ===========================================================================
# Patients (referral & intake)
# ===========================================================================
@app.route("/clinics/<clinic_id>/patients", methods=["POST"])
def create_patient(clinic_id):
    require_role(["IntakeCoordinator"])
    helpers.get_clinic(clinic_id)
    b = body()
    full_name = util.require(b, "full_name")
    referral_source = util.require(b, "referral_source")
    rec = db.base_fields()
    rec.update({
        "clinic_id": clinic_id,
        "full_name": full_name,
        "referral_source": referral_source,
        "status": "REFERRED",
        "intake_utc": None,
        "compliance_flag": "NONE",
        "current_daily_med_mg": 0,
        "open_uds_count": 0,
    })
    db.patients[rec["id"]] = rec
    # Create the ControlledSubstanceLedger row for the patient.
    ledger = db.base_fields()
    ledger.update({
        "patient_id": rec["id"],
        "total_active_med_mg": 0,
        "discontinued_med_mg": 0,
        "suspended_med_mg": 0,
    })
    db.ledgers[ledger["id"]] = ledger
    db.ledger_by_patient[rec["id"]] = ledger["id"]
    return response.created(serialize.patient(rec))


@app.route("/clinics/<clinic_id>/patients", methods=["GET"])
def list_clinic_patients(clinic_id):
    require_role(ALL_ROLES)
    helpers.get_clinic(clinic_id)
    status = request.args.get("status")
    items = [p for p in db.patients.values() if p["clinic_id"] == clinic_id]
    if status:
        items = [p for p in items if p["status"] == status]
    items = helpers.sort_created(items)
    page, limit, offset, total = helpers.paginate(items)
    return response.list_ok([serialize.patient(p) for p in page], limit, offset, total)


@app.route("/clinics/<clinic_id>/patients/<patient_id>", methods=["GET"])
def get_patient(clinic_id, patient_id):
    require_role(ALL_ROLES)
    helpers.get_clinic(clinic_id)
    p = helpers.get_patient(clinic_id, patient_id)
    return response.ok(serialize.patient(p))


@app.route("/clinics/<clinic_id>/patients/<patient_id>/schedule-intake", methods=["POST"])
def schedule_intake(clinic_id, patient_id):
    require_role(["IntakeCoordinator"])
    c = helpers.get_clinic(clinic_id)
    p = helpers.get_patient(clinic_id, patient_id)
    b = body()
    intake_utc = util.require(b, "intake_utc")
    intake_dt = util.parse_iso(intake_utc)
    if p["status"] != "REFERRED":
        raise errors.ApiError(errors.ERR_PATIENT_STATE_INVALID, 409, "patient not REFERRED")
    if intake_dt < clinic_utc(c):
        raise errors.ApiError(errors.ERR_INTAKE_IN_PAST, 422, "intake_utc is in the past")
    p["status"] = "INTAKE_SCHEDULED"
    p["intake_utc"] = intake_utc
    db.touch(p)
    return response.ok(serialize.patient(p))


@app.route("/clinics/<clinic_id>/patients/<patient_id>/complete-intake", methods=["POST"])
def complete_intake(clinic_id, patient_id):
    require_role(["IntakeCoordinator"])
    c = helpers.get_clinic(clinic_id)
    p = helpers.get_patient(clinic_id, patient_id)
    if p["status"] != "INTAKE_SCHEDULED":
        raise errors.ApiError(errors.ERR_PATIENT_STATE_INVALID, 409, "patient not INTAKE_SCHEDULED")
    if clinic_utc(c) < util.parse_iso(p["intake_utc"]):
        raise errors.ApiError(errors.ERR_INTAKE_NOT_DUE, 409, "intake not due yet")
    p["status"] = "INTAKE_COMPLETE"
    db.touch(p)
    return response.ok(serialize.patient(p))


@app.route("/clinics/<clinic_id>/patients/<patient_id>/activate", methods=["POST"])
def activate_patient(clinic_id, patient_id):
    require_role(["IntakeCoordinator"])
    helpers.get_clinic(clinic_id)
    p = helpers.get_patient(clinic_id, patient_id)
    if p["status"] != "INTAKE_COMPLETE":
        raise errors.ApiError(errors.ERR_PATIENT_STATE_INVALID, 409, "patient not INTAKE_COMPLETE")
    has_live_plan = any(
        tp["patient_id"] == patient_id and tp["status"] in ("ACTIVE", "PROCEDURE_PATH", "MEDICATION_PATH")
        for tp in db.treatment_plans.values()
    )
    if not has_live_plan:
        raise errors.ApiError(errors.ERR_NO_ACTIVE_PLAN, 409, "no active treatment plan")
    p["status"] = "ACTIVE"
    db.touch(p)
    return response.ok(serialize.patient(p))


@app.route("/clinics/<clinic_id>/patients/<patient_id>/discharge", methods=["POST"])
def discharge_patient(clinic_id, patient_id):
    require_role(["Prescriber"])
    helpers.get_clinic(clinic_id)
    p = helpers.get_patient(clinic_id, patient_id)
    if p["status"] != "ACTIVE":
        raise errors.ApiError(errors.ERR_PATIENT_STATE_INVALID, 409, "patient not ACTIVE")
    blocking = any(
        rx["patient_id"] == patient_id and rx["status"] in ("ACTIVE", "SUSPENDED")
        for rx in db.prescriptions.values()
    )
    if blocking:
        raise errors.ApiError(errors.ERR_ACTIVE_PRESCRIPTIONS_EXIST, 409, "active/suspended prescriptions exist")
    p["status"] = "DISCHARGED"
    db.touch(p)
    # CASCADE: cancel REQUESTED/SCHEDULED procedures (SCHEDULED debit suite).
    for proc in db.procedures.values():
        if proc["patient_id"] == patient_id and proc["status"] in ("REQUESTED", "SCHEDULED"):
            was_scheduled = proc["status"] == "SCHEDULED"
            proc["status"] = "CANCELLED"
            db.touch(proc)
            if was_scheduled:
                suite = db.fluoroscopy_suites.get(proc["suite_id"])
                if suite is not None:
                    suite["booked_minutes"] -= proc["duration_minutes"]
                    db.touch(suite)
    # CASCADE: cancel non-terminal treatment plans.
    for tp in db.treatment_plans.values():
        if tp["patient_id"] == patient_id and tp["status"] not in ("COMPLETED", "CANCELLED"):
            tp["status"] = "CANCELLED"
            db.touch(tp)
    return response.ok(serialize.patient(p))


@app.route("/clinics/<clinic_id>/patients/<patient_id>/clear-flag", methods=["POST"])
def clear_flag(clinic_id, patient_id):
    require_role(["ComplianceOfficer"])
    helpers.get_clinic(clinic_id)
    p = helpers.get_patient(clinic_id, patient_id)
    p["compliance_flag"] = "CLEARED"
    db.touch(p)
    return response.ok(serialize.patient(p))


@app.route("/clinics/<clinic_id>/patients/<patient_id>/controlled-substance-ledger", methods=["GET"])
def patient_ledger(clinic_id, patient_id):
    require_role(["ClinicAdmin", "Prescriber", "ComplianceOfficer"])
    helpers.get_clinic(clinic_id)
    helpers.get_patient(clinic_id, patient_id)
    items = [l for l in db.ledgers.values() if l["patient_id"] == patient_id]
    items = helpers.sort_created(items)
    page, limit, offset, total = helpers.paginate(items)
    return response.list_ok([serialize.ledger(l) for l in page], limit, offset, total)


# ===========================================================================
# Opioid agreements
# ===========================================================================
@app.route("/clinics/<clinic_id>/opioid-agreements", methods=["POST"])
def create_agreement(clinic_id):
    require_role(["Prescriber"])
    helpers.get_clinic(clinic_id)
    b = body()
    patient_id = util.require(b, "patient_id")
    prescriber_id = util.require(b, "prescriber_id")
    patient = db.patients.get(patient_id)
    if patient is None or patient["clinic_id"] != clinic_id:
        raise errors.ApiError(errors.ERR_PATIENT_NOT_FOUND, 404, "patient not found")
    prescriber = db.providers.get(prescriber_id)
    if prescriber is None or prescriber["clinic_id"] != clinic_id:
        raise errors.ApiError(errors.ERR_PROVIDER_NOT_FOUND, 404, "prescriber not found")
    rec = db.base_fields()
    rec.update({
        "clinic_id": clinic_id,
        "patient_id": patient_id,
        "prescriber_id": prescriber_id,
        "signed_utc": None,
        "expires_utc": None,
        "status": "DRAFT",
    })
    db.opioid_agreements[rec["id"]] = rec
    return response.created(serialize.opioid_agreement(rec))


@app.route("/clinics/<clinic_id>/opioid-agreements", methods=["GET"])
def list_clinic_agreements(clinic_id):
    require_role(["ClinicAdmin", "Prescriber", "ComplianceOfficer"])
    helpers.get_clinic(clinic_id)
    patient_id = request.args.get("patient_id")
    items = [a for a in db.opioid_agreements.values() if a["clinic_id"] == clinic_id]
    if patient_id:
        items = [a for a in items if a["patient_id"] == patient_id]
    items = helpers.sort_created(items)
    page, limit, offset, total = helpers.paginate(items)
    return response.list_ok([serialize.opioid_agreement(a) for a in page], limit, offset, total)


def _get_agreement(clinic_id, agreement_id):
    a = db.opioid_agreements.get(agreement_id)
    if a is None or a["clinic_id"] != clinic_id:
        raise errors.ApiError(errors.ERR_AGREEMENT_NOT_FOUND, 404, "agreement not found")
    return a


@app.route("/clinics/<clinic_id>/opioid-agreements/<agreement_id>/counter-sign", methods=["POST"])
def counter_sign(clinic_id, agreement_id):
    user_id, _ = require_role(["Prescriber"])
    c = helpers.get_clinic(clinic_id)
    a = _get_agreement(clinic_id, agreement_id)
    if a["status"] != "DRAFT":
        raise errors.ApiError(errors.ERR_AGREEMENT_STATE_INVALID, 409, "agreement not DRAFT")
    if user_id != a["prescriber_id"]:
        raise errors.ApiError(errors.ERR_NOT_AGREEMENT_PRESCRIBER, 403, "not the agreement prescriber")
    signed = clinic_utc(c)
    expires = signed + _timedelta_days(AGREEMENT_VALIDITY_DAYS)
    a["status"] = "ACTIVE"
    a["signed_utc"] = _to_iso(signed)
    a["expires_utc"] = _to_iso(expires)
    db.touch(a)
    return response.ok(serialize.opioid_agreement(a))


@app.route("/clinics/<clinic_id>/opioid-agreements/<agreement_id>/revoke", methods=["POST"])
def revoke_agreement(clinic_id, agreement_id):
    require_role(["ComplianceOfficer"])
    helpers.get_clinic(clinic_id)
    a = _get_agreement(clinic_id, agreement_id)
    if a["status"] != "ACTIVE":
        raise errors.ApiError(errors.ERR_AGREEMENT_STATE_INVALID, 409, "agreement not ACTIVE")
    a["status"] = "REVOKED"
    db.touch(a)
    # CASCADE: suspend ACTIVE/TAPERING opioid prescriptions for the patient.
    patient_id = a["patient_id"]
    for rx in db.prescriptions.values():
        if rx["patient_id"] == patient_id and rx["status"] in ("ACTIVE", "TAPERING"):
            rx["status"] = "SUSPENDED"
            db.touch(rx)
    ledger_service.reconcile(patient_id)
    return response.ok(serialize.opioid_agreement(a))


# ===========================================================================
# PDMP checks
# ===========================================================================
@app.route("/clinics/<clinic_id>/pdmp-checks", methods=["POST"])
def create_pdmp(clinic_id):
    require_role(["Prescriber"])
    c = helpers.get_clinic(clinic_id)
    b = body()
    patient_id = util.require(b, "patient_id")
    queried_by = util.require(b, "queried_by_provider_id")
    outcome = util.require(b, "outcome")
    outside_med = b.get("outside_med_mg", 0)
    if outside_med is None:
        outside_med = 0
    patient = db.patients.get(patient_id)
    if patient is None or patient["clinic_id"] != clinic_id:
        raise errors.ApiError(errors.ERR_PATIENT_NOT_FOUND, 404, "patient not found")
    prov = db.providers.get(queried_by)
    if prov is None or prov["clinic_id"] != clinic_id:
        raise errors.ApiError(errors.ERR_PROVIDER_NOT_FOUND, 404, "provider not found")
    if outcome not in ("CLEAR", "CONCERN"):
        raise errors.ApiError(errors.ERR_INVALID_ENUM_VALUE, 422, "invalid outcome")
    # Immutable audit record: only id + created_at (no updated_at/version).
    rec = db.base_fields(with_version=False)
    rec.update({
        "clinic_id": clinic_id,
        "patient_id": patient_id,
        "queried_by_provider_id": queried_by,
        "outside_med_mg": outside_med,
        "outcome": outcome,
        "queried_utc": c["current_utc"],
    })
    db.pdmp_checks[rec["id"]] = rec
    return response.created(serialize.pdmp_check(rec))


@app.route("/clinics/<clinic_id>/pdmp-checks", methods=["GET"])
def list_clinic_pdmp(clinic_id):
    require_role(["ClinicAdmin", "Prescriber", "ComplianceOfficer"])
    helpers.get_clinic(clinic_id)
    patient_id = request.args.get("patient_id")
    items = [x for x in db.pdmp_checks.values() if x["clinic_id"] == clinic_id]
    if patient_id:
        items = [x for x in items if x["patient_id"] == patient_id]
    items = helpers.sort_created(items)
    page, limit, offset, total = helpers.paginate(items)
    return response.list_ok([serialize.pdmp_check(x) for x in page], limit, offset, total)


# ===========================================================================
# Treatment plans
# ===========================================================================
@app.route("/clinics/<clinic_id>/patients/<patient_id>/treatment-plans", methods=["POST"])
def create_plan(clinic_id, patient_id):
    require_role(["Prescriber"])
    helpers.get_clinic(clinic_id)
    helpers.get_patient(clinic_id, patient_id)
    b = body()
    modality = util.require(b, "modality")
    if modality not in ("INJECTION", "RFA", "MEDICATION"):
        raise errors.ApiError(errors.ERR_INVALID_ENUM_VALUE, 422, "invalid modality")
    rec = db.base_fields()
    rec.update({
        "patient_id": patient_id,
        "modality": modality,
        "requires_procedure": modality in ("INJECTION", "RFA"),
        "requires_medication": modality == "MEDICATION",
        "status": "PROPOSED",
    })
    db.treatment_plans[rec["id"]] = rec
    return response.created(serialize.treatment_plan(rec))


@app.route("/clinics/<clinic_id>/patients/<patient_id>/treatment-plans", methods=["GET"])
def list_plans(clinic_id, patient_id):
    require_role(ALL_ROLES)
    helpers.get_clinic(clinic_id)
    helpers.get_patient(clinic_id, patient_id)
    items = [tp for tp in db.treatment_plans.values() if tp["patient_id"] == patient_id]
    items = helpers.sort_created(items)
    page, limit, offset, total = helpers.paginate(items)
    return response.list_ok([serialize.treatment_plan(tp) for tp in page], limit, offset, total)


def _get_plan(clinic_id, patient_id, plan_id):
    tp = db.treatment_plans.get(plan_id)
    if tp is None or tp["patient_id"] != patient_id:
        raise errors.ApiError(errors.ERR_TREATMENT_PLAN_NOT_FOUND, 404, "treatment plan not found")
    return tp


@app.route("/clinics/<clinic_id>/patients/<patient_id>/treatment-plans/<plan_id>/approve", methods=["POST"])
def approve_plan(clinic_id, patient_id, plan_id):
    require_role(["Prescriber"])
    helpers.get_clinic(clinic_id)
    helpers.get_patient(clinic_id, patient_id)
    tp = _get_plan(clinic_id, patient_id, plan_id)
    if tp["status"] != "PROPOSED":
        raise errors.ApiError(errors.ERR_PLAN_STATE_INVALID, 409, "plan not PROPOSED")
    tp["status"] = "ACTIVE"
    db.touch(tp)
    return response.ok(serialize.treatment_plan(tp))


@app.route("/clinics/<clinic_id>/patients/<patient_id>/treatment-plans/<plan_id>/route", methods=["POST"])
def route_plan(clinic_id, patient_id, plan_id):
    require_role(["Prescriber"])
    helpers.get_clinic(clinic_id)
    helpers.get_patient(clinic_id, patient_id)
    tp = _get_plan(clinic_id, patient_id, plan_id)
    if tp["status"] != "ACTIVE":
        raise errors.ApiError(errors.ERR_PLAN_STATE_INVALID, 409, "plan not ACTIVE")
    if tp["requires_procedure"]:
        tp["status"] = "PROCEDURE_PATH"
    elif tp["requires_medication"]:
        tp["status"] = "MEDICATION_PATH"
    else:
        raise errors.ApiError(errors.ERR_PLAN_MODALITY_MISMATCH, 409, "plan modality mismatch")
    db.touch(tp)
    return response.ok(serialize.treatment_plan(tp))


@app.route("/clinics/<clinic_id>/patients/<patient_id>/treatment-plans/<plan_id>/complete", methods=["POST"])
def complete_plan(clinic_id, patient_id, plan_id):
    require_role(["Prescriber"])
    helpers.get_clinic(clinic_id)
    helpers.get_patient(clinic_id, patient_id)
    tp = _get_plan(clinic_id, patient_id, plan_id)
    if tp["status"] == "PROCEDURE_PATH":
        open_procs = any(
            proc["treatment_plan_id"] == plan_id and proc["status"] not in ("COMPLETED", "CANCELLED")
            for proc in db.procedures.values()
        )
        if open_procs:
            raise errors.ApiError(errors.ERR_OPEN_PROCEDURES_EXIST, 409, "open procedures exist")
    elif tp["status"] == "MEDICATION_PATH":
        open_rx = any(
            rx.get("treatment_plan_id") == plan_id and rx["status"] != "DISCONTINUED"
            for rx in db.prescriptions.values()
        )
        if open_rx:
            raise errors.ApiError(errors.ERR_OPEN_PRESCRIPTIONS_EXIST, 409, "open prescriptions exist")
    else:
        raise errors.ApiError(errors.ERR_PLAN_STATE_INVALID, 409, "plan not on a completable path")
    tp["status"] = "COMPLETED"
    db.touch(tp)
    return response.ok(serialize.treatment_plan(tp))


# ===========================================================================
# Fluoroscopy suites
# ===========================================================================
@app.route("/clinics/<clinic_id>/fluoroscopy-suites", methods=["POST"])
def create_suite(clinic_id):
    require_role(["ClinicAdmin"])
    helpers.get_clinic(clinic_id)
    b = body()
    name = util.require(b, "name")
    buffer_min = b.get("cleanup_buffer_minutes", 15)
    if buffer_min is None:
        buffer_min = 15
    rec = db.base_fields()
    rec.update({
        "clinic_id": clinic_id,
        "name": name,
        "cleanup_buffer_minutes": buffer_min,
        "booked_minutes": 0,
    })
    db.fluoroscopy_suites[rec["id"]] = rec
    return response.created(serialize.fluoroscopy_suite(rec))


@app.route("/clinics/<clinic_id>/fluoroscopy-suites", methods=["GET"])
def list_clinic_suites(clinic_id):
    require_role(["ClinicAdmin", "IntakeCoordinator", "Prescriber", "PriorAuthClerk"])
    helpers.get_clinic(clinic_id)
    items = [s for s in db.fluoroscopy_suites.values() if s["clinic_id"] == clinic_id]
    items = helpers.sort_created(items)
    page, limit, offset, total = helpers.paginate(items)
    return response.list_ok([serialize.fluoroscopy_suite(s) for s in page], limit, offset, total)


# ===========================================================================
# Prior authorizations
# ===========================================================================
@app.route("/clinics/<clinic_id>/patients/<patient_id>/prior-authorizations", methods=["POST"])
def create_pa(clinic_id, patient_id):
    require_role(["PriorAuthClerk"])
    helpers.get_clinic(clinic_id)
    helpers.get_patient(clinic_id, patient_id)
    b = body()
    target_kind = util.require(b, "target_kind")
    payer = util.require(b, "payer")
    authorized_units = util.require(b, "authorized_units")
    if target_kind not in ("PROCEDURE", "PRESCRIPTION"):
        raise errors.ApiError(errors.ERR_INVALID_ENUM_VALUE, 422, "invalid target_kind")
    rec = db.base_fields()
    rec.update({
        "patient_id": patient_id,
        "target_kind": target_kind,
        "payer": payer,
        "authorized_units": authorized_units,
        "status": "SUBMITTED",
    })
    db.prior_authorizations[rec["id"]] = rec
    return response.created(serialize.prior_authorization(rec))


@app.route("/clinics/<clinic_id>/patients/<patient_id>/prior-authorizations", methods=["GET"])
def list_pa(clinic_id, patient_id):
    require_role(["ClinicAdmin", "IntakeCoordinator", "Prescriber", "PriorAuthClerk"])
    helpers.get_clinic(clinic_id)
    helpers.get_patient(clinic_id, patient_id)
    items = [pa for pa in db.prior_authorizations.values() if pa["patient_id"] == patient_id]
    items = helpers.sort_created(items)
    page, limit, offset, total = helpers.paginate(items)
    return response.list_ok([serialize.prior_authorization(pa) for pa in page], limit, offset, total)


def _get_pa(clinic_id, patient_id, pa_id):
    pa = db.prior_authorizations.get(pa_id)
    if pa is None or pa["patient_id"] != patient_id:
        raise errors.ApiError(errors.ERR_PRIOR_AUTH_NOT_FOUND, 404, "prior authorization not found")
    return pa


@app.route("/clinics/<clinic_id>/patients/<patient_id>/prior-authorizations/<pa_id>/decide", methods=["POST"])
def decide_pa(clinic_id, patient_id, pa_id):
    require_role(["PriorAuthClerk"])
    helpers.get_clinic(clinic_id)
    helpers.get_patient(clinic_id, patient_id)
    pa = _get_pa(clinic_id, patient_id, pa_id)
    b = body()
    decision = util.require(b, "decision")
    if decision not in ("APPROVED", "DENIED"):
        raise errors.ApiError(errors.ERR_INVALID_ENUM_VALUE, 422, "invalid decision")
    if pa["status"] != "SUBMITTED":
        raise errors.ApiError(errors.ERR_PA_STATE_INVALID, 409, "prior auth not SUBMITTED")
    pa["status"] = decision
    db.touch(pa)
    return response.ok(serialize.prior_authorization(pa))


# ===========================================================================
# Procedures
# ===========================================================================
@app.route("/clinics/<clinic_id>/patients/<patient_id>/procedures", methods=["POST"])
def create_procedure(clinic_id, patient_id):
    require_role(["IntakeCoordinator"])
    helpers.get_clinic(clinic_id)
    helpers.get_patient(clinic_id, patient_id)
    b = body()
    treatment_plan_id = util.require(b, "treatment_plan_id")
    suite_id = util.require(b, "suite_id")
    prior_auth_id = util.require(b, "prior_auth_id")
    start_utc = util.require(b, "start_utc")
    duration_minutes = util.require(b, "duration_minutes")
    util.parse_iso(start_utc)
    # FK existence (same clinic as enclosing patient).
    tp = db.treatment_plans.get(treatment_plan_id)
    if tp is None or tp["patient_id"] != patient_id:
        raise errors.ApiError(errors.ERR_TREATMENT_PLAN_NOT_FOUND, 404, "treatment plan not found")
    suite = db.fluoroscopy_suites.get(suite_id)
    if suite is None or suite["clinic_id"] != clinic_id:
        raise errors.ApiError(errors.ERR_SUITE_NOT_FOUND, 404, "suite not found")
    pa = db.prior_authorizations.get(prior_auth_id)
    if pa is None or pa["patient_id"] != patient_id:
        raise errors.ApiError(errors.ERR_PRIOR_AUTH_NOT_FOUND, 404, "prior authorization not found")
    rec = db.base_fields()
    rec.update({
        "patient_id": patient_id,
        "treatment_plan_id": treatment_plan_id,
        "suite_id": suite_id,
        "prior_auth_id": prior_auth_id,
        "start_utc": start_utc,
        "duration_minutes": duration_minutes,
        "status": "REQUESTED",
    })
    db.procedures[rec["id"]] = rec
    return response.created(serialize.procedure(rec))


@app.route("/clinics/<clinic_id>/patients/<patient_id>/procedures", methods=["GET"])
def list_procedures(clinic_id, patient_id):
    require_role(["ClinicAdmin", "IntakeCoordinator", "Prescriber", "PriorAuthClerk"])
    helpers.get_clinic(clinic_id)
    helpers.get_patient(clinic_id, patient_id)
    suite_id = request.args.get("suite_id")
    items = [p for p in db.procedures.values() if p["patient_id"] == patient_id]
    if suite_id:
        items = [p for p in items if p["suite_id"] == suite_id]
    items = helpers.sort_created(items)
    page, limit, offset, total = helpers.paginate(items)
    return response.list_ok([serialize.procedure(p) for p in page], limit, offset, total)


def _get_procedure(clinic_id, patient_id, procedure_id):
    proc = db.procedures.get(procedure_id)
    if proc is None or proc["patient_id"] != patient_id:
        raise errors.ApiError(errors.ERR_PROCEDURE_NOT_FOUND, 404, "procedure not found")
    return proc


@app.route("/clinics/<clinic_id>/patients/<patient_id>/procedures/<procedure_id>/schedule", methods=["POST"])
def schedule_procedure(clinic_id, patient_id, procedure_id):
    require_role(["IntakeCoordinator"])
    c = helpers.get_clinic(clinic_id)
    helpers.get_patient(clinic_id, patient_id)
    proc = _get_procedure(clinic_id, patient_id, procedure_id)
    b = body()
    expected_version = util.require(b, "expected_clinic_version")
    # Priority 5: OCC check, before business logic.
    if expected_version != c["version"]:
        raise errors.ApiError(errors.ERR_STALE_CLINIC_VERSION, 412, "stale clinic version")
    # Priority 6: state.
    if proc["status"] != "REQUESTED":
        raise errors.ApiError(errors.ERR_PROCEDURE_STATE_INVALID, 409, "procedure not REQUESTED")
    # Priority 7: prior-auth approved + target_kind match.
    pa = db.prior_authorizations.get(proc["prior_auth_id"])
    if pa is None or pa["status"] != "APPROVED" or pa["target_kind"] != "PROCEDURE":
        raise errors.ApiError(errors.ERR_PRIOR_AUTH_NOT_APPROVED, 409, "prior auth not approved for procedure")
    # Priority 8: plan on PROCEDURE_PATH.
    tp = db.treatment_plans.get(proc["treatment_plan_id"])
    if tp is None or tp["status"] != "PROCEDURE_PATH":
        raise errors.ApiError(errors.ERR_PLAN_NOT_ON_PROCEDURE_PATH, 409, "plan not on procedure path")
    # Priority 12: suite time conflict.
    suite = db.fluoroscopy_suites.get(proc["suite_id"])
    buffer_min = suite["cleanup_buffer_minutes"]
    new_start = util.parse_iso(proc["start_utc"])
    new_buffered_end = new_start + _timedelta_minutes(proc["duration_minutes"] + buffer_min)
    for other in db.procedures.values():
        if other["id"] == proc["id"]:
            continue
        if other["suite_id"] != proc["suite_id"] or other["status"] != "SCHEDULED":
            continue
        x_start = util.parse_iso(other["start_utc"])
        x_buffered_end = x_start + _timedelta_minutes(other["duration_minutes"] + buffer_min)
        if new_start < x_buffered_end and x_start < new_buffered_end:
            raise errors.ApiError(errors.ERR_SUITE_TIME_CONFLICT, 409, "suite time conflict")
    # Priority 15: authorized_units >= 1 for a procedure.
    if pa["authorized_units"] < 1:
        raise errors.ApiError(errors.ERR_AUTHORIZED_UNITS_EXCEEDED, 402, "authorized units exceeded")
    # Commit.
    proc["status"] = "SCHEDULED"
    db.touch(proc)
    suite["booked_minutes"] += proc["duration_minutes"]
    db.touch(suite)
    c["version"] = c["version"] + 1
    c["updated_at"] = util.now_iso()
    return response.ok(serialize.procedure(proc))


@app.route("/clinics/<clinic_id>/patients/<patient_id>/procedures/<procedure_id>/complete", methods=["POST"])
def complete_procedure(clinic_id, patient_id, procedure_id):
    require_role(["Prescriber"])
    c = helpers.get_clinic(clinic_id)
    helpers.get_patient(clinic_id, patient_id)
    proc = _get_procedure(clinic_id, patient_id, procedure_id)
    if proc["status"] != "SCHEDULED":
        raise errors.ApiError(errors.ERR_PROCEDURE_STATE_INVALID, 409, "procedure not SCHEDULED")
    if clinic_utc(c) < util.parse_iso(proc["start_utc"]):
        raise errors.ApiError(errors.ERR_PROCEDURE_NOT_STARTED, 409, "procedure not started")
    proc["status"] = "COMPLETED"
    db.touch(proc)
    suite = db.fluoroscopy_suites.get(proc["suite_id"])
    if suite is not None:
        suite["booked_minutes"] -= proc["duration_minutes"]
        db.touch(suite)
    return response.ok(serialize.procedure(proc))


@app.route("/clinics/<clinic_id>/patients/<patient_id>/procedures/<procedure_id>/cancel", methods=["POST"])
def cancel_procedure(clinic_id, patient_id, procedure_id):
    require_role(["IntakeCoordinator"])
    helpers.get_clinic(clinic_id)
    helpers.get_patient(clinic_id, patient_id)
    proc = _get_procedure(clinic_id, patient_id, procedure_id)
    if proc["status"] not in ("SCHEDULED", "REQUESTED"):
        raise errors.ApiError(errors.ERR_PROCEDURE_STATE_INVALID, 409, "procedure not cancellable")
    was_scheduled = proc["status"] == "SCHEDULED"
    proc["status"] = "CANCELLED"
    db.touch(proc)
    if was_scheduled:
        suite = db.fluoroscopy_suites.get(proc["suite_id"])
        if suite is not None:
            suite["booked_minutes"] -= proc["duration_minutes"]
            db.touch(suite)
    return response.ok(serialize.procedure(proc))


# ===========================================================================
# Prescriptions
# ===========================================================================
@app.route("/clinics/<clinic_id>/patients/<patient_id>/prescriptions", methods=["POST"])
def create_prescription(clinic_id, patient_id):
    require_role(["Prescriber"])
    c = helpers.get_clinic(clinic_id)
    helpers.get_patient(clinic_id, patient_id)
    b = body()
    prescriber_id = util.require(b, "prescriber_id")
    drug_name = util.require(b, "drug_name")
    dose_mg = util.require(b, "dose_mg")
    units_per_day = util.require(b, "units_per_day")
    conversion_factor = util.require(b, "conversion_factor")
    day_supply = util.require(b, "day_supply")
    pills_dispensed = util.require(b, "pills_dispensed")
    prior_auth_id = b.get("prior_auth_id")
    taper_step_pct = b.get("taper_step_pct")
    prescriber = db.providers.get(prescriber_id)
    if prescriber is None or prescriber["clinic_id"] != clinic_id:
        raise errors.ApiError(errors.ERR_PROVIDER_NOT_FOUND, 404, "prescriber not found")
    if prior_auth_id is not None:
        pa = db.prior_authorizations.get(prior_auth_id)
        if pa is None or pa["patient_id"] != patient_id:
            raise errors.ApiError(errors.ERR_PRIOR_AUTH_NOT_FOUND, 404, "prior authorization not found")
    provisional = util.round2(dose_mg * units_per_day * conversion_factor)
    # created_at anchored to the clinic logical clock so elapsed-day
    # calculations (final MED at discontinue, pill-count audit) are
    # deterministic under the test-driven clock.
    rec = db.base_fields(clock=c["current_utc"])
    rec.update({
        "patient_id": patient_id,
        "prescriber_id": prescriber_id,
        "prior_auth_id": prior_auth_id,
        "drug_name": drug_name,
        "dose_mg": dose_mg,
        "units_per_day": units_per_day,
        "conversion_factor": conversion_factor,
        "day_supply": day_supply,
        "pills_dispensed": pills_dispensed,
        "provisional_daily_med_mg": provisional,
        "final_daily_med_mg": None,
        "taper_step_pct": taper_step_pct,
        "status": "PROPOSED",
    })
    db.prescriptions[rec["id"]] = rec
    return response.created(serialize.prescription(rec))


@app.route("/clinics/<clinic_id>/patients/<patient_id>/prescriptions", methods=["GET"])
def list_prescriptions(clinic_id, patient_id):
    require_role(["ClinicAdmin", "Prescriber", "ComplianceOfficer", "PriorAuthClerk"])
    helpers.get_clinic(clinic_id)
    helpers.get_patient(clinic_id, patient_id)
    items = [rx for rx in db.prescriptions.values() if rx["patient_id"] == patient_id]
    items = helpers.sort_created(items)
    page, limit, offset, total = helpers.paginate(items)
    return response.list_ok([serialize.prescription(rx) for rx in page], limit, offset, total)


def _get_rx(clinic_id, patient_id, rx_id):
    rx = db.prescriptions.get(rx_id)
    if rx is None or rx["patient_id"] != patient_id:
        raise errors.ApiError(errors.ERR_PRESCRIPTION_NOT_FOUND, 404, "prescription not found")
    return rx


@app.route("/clinics/<clinic_id>/patients/<patient_id>/prescriptions/<rx_id>/activate", methods=["POST"])
def activate_prescription(clinic_id, patient_id, rx_id):
    require_role(["Prescriber"])
    c = helpers.get_clinic(clinic_id)
    patient = helpers.get_patient(clinic_id, patient_id)
    rx = _get_rx(clinic_id, patient_id, rx_id)
    # Priority 6: state.
    if rx["status"] != "PROPOSED":
        raise errors.ApiError(errors.ERR_RX_STATE_INVALID, 409, "prescription not PROPOSED")
    at_threshold = rx["provisional_daily_med_mg"] >= c["med_review_threshold_mg"]
    if at_threshold:
        # Priority 9: ACTIVE unexpired opioid agreement.
        now = clinic_utc(c)
        has_agreement = any(
            a["patient_id"] == patient_id and a["status"] == "ACTIVE"
            and a["expires_utc"] is not None and now < util.parse_iso(a["expires_utc"])
            for a in db.opioid_agreements.values()
        )
        if not has_agreement:
            raise errors.ApiError(errors.ERR_OPIOID_AGREEMENT_REQUIRED, 403, "opioid agreement required")
        # Priority 10: fresh PDMP check.
        has_fresh_pdmp = any(
            x["patient_id"] == patient_id
            and now < util.parse_iso(x["queried_utc"]) + _timedelta_days(PDMP_FRESHNESS_DAYS)
            for x in db.pdmp_checks.values()
        )
        if not has_fresh_pdmp:
            raise errors.ApiError(errors.ERR_PDMP_CHECK_REQUIRED, 403, "fresh PDMP check required")
        # Priority 11: patient not FLAGGED (checked below independently too).
        if patient["compliance_flag"] == "FLAGGED":
            raise errors.ApiError(errors.ERR_PATIENT_FLAGGED, 403, "patient is flagged")
        # Priority 7: prior auth approved + target_kind PRESCRIPTION.
        pa = db.prior_authorizations.get(rx.get("prior_auth_id"))
        if pa is None or pa["status"] != "APPROVED" or pa["target_kind"] != "PRESCRIPTION":
            raise errors.ApiError(errors.ERR_PRIOR_AUTH_NOT_APPROVED, 409, "prior auth not approved for prescription")
        # Priority 15: authorized_units >= day_supply.
        if pa["authorized_units"] < rx["day_supply"]:
            raise errors.ApiError(errors.ERR_AUTHORIZED_UNITS_EXCEEDED, 402, "authorized units exceeded")
    else:
        # Below threshold: only the patient-flag gate applies to opioid activation.
        if patient["compliance_flag"] == "FLAGGED":
            raise errors.ApiError(errors.ERR_PATIENT_FLAGGED, 403, "patient is flagged")
    rx["status"] = "ACTIVE"
    db.touch(rx)
    ledger_service.reconcile(patient_id)
    rx = db.prescriptions[rx_id]
    return response.ok(serialize.prescription(rx))


@app.route("/clinics/<clinic_id>/patients/<patient_id>/prescriptions/<rx_id>/start-taper", methods=["POST"])
def start_taper(clinic_id, patient_id, rx_id):
    require_role(["Prescriber"])
    helpers.get_clinic(clinic_id)
    helpers.get_patient(clinic_id, patient_id)
    rx = _get_rx(clinic_id, patient_id, rx_id)
    if rx["status"] != "ACTIVE":
        raise errors.ApiError(errors.ERR_RX_STATE_INVALID, 409, "prescription not ACTIVE")
    step = rx.get("taper_step_pct")
    if step is None or not (0 < step <= 100):
        raise errors.ApiError(errors.ERR_TAPER_STEP_INVALID, 422, "invalid taper step")
    rx["status"] = "TAPERING"
    db.touch(rx)
    return response.ok(serialize.prescription(rx))


@app.route("/clinics/<clinic_id>/patients/<patient_id>/prescriptions/<rx_id>/re-escalate", methods=["POST"])
def re_escalate(clinic_id, patient_id, rx_id):
    require_role(["Prescriber"])
    helpers.get_clinic(clinic_id)
    helpers.get_patient(clinic_id, patient_id)
    rx = _get_rx(clinic_id, patient_id, rx_id)
    if rx["status"] != "TAPERING":
        raise errors.ApiError(errors.ERR_RX_STATE_INVALID, 409, "prescription not TAPERING")
    rx["status"] = "ACTIVE"
    db.touch(rx)
    return response.ok(serialize.prescription(rx))


@app.route("/clinics/<clinic_id>/patients/<patient_id>/prescriptions/<rx_id>/discontinue", methods=["POST"])
def discontinue(clinic_id, patient_id, rx_id):
    require_role(["Prescriber"])
    c = helpers.get_clinic(clinic_id)
    helpers.get_patient(clinic_id, patient_id)
    rx = _get_rx(clinic_id, patient_id, rx_id)
    if rx["status"] not in ("TAPERING", "ACTIVE", "SUSPENDED"):
        raise errors.ApiError(errors.ERR_RX_STATE_INVALID, 409, "prescription not discontinuable")
    # final_daily_med chronological.
    created = util.parse_iso(rx["created_at"])
    now = clinic_utc(c)
    elapsed_seconds = (now - created).total_seconds()
    elapsed_days = max(1, math.floor(elapsed_seconds / SECONDS_PER_DAY))
    effective_days = min(elapsed_days, rx["day_supply"])
    if rx["day_supply"]:
        final_med = util.round2(rx["provisional_daily_med_mg"] * (effective_days / rx["day_supply"]))
    else:
        final_med = util.round2(rx["provisional_daily_med_mg"])
    rx["final_daily_med_mg"] = final_med
    rx["status"] = "DISCONTINUED"
    db.touch(rx)
    ledger_service.reconcile(patient_id)
    rx = db.prescriptions[rx_id]
    return response.ok(serialize.prescription(rx))


# ===========================================================================
# Urine drug screens
# ===========================================================================
@app.route("/clinics/<clinic_id>/patients/<patient_id>/urine-drug-screens", methods=["POST"])
def create_uds(clinic_id, patient_id):
    require_role(["ComplianceOfficer"])
    helpers.get_clinic(clinic_id)
    helpers.get_patient(clinic_id, patient_id)
    b = body()
    due_utc = util.require(b, "due_utc")
    expected = util.require(b, "expected_substances")
    util.parse_iso(due_utc)
    rec = db.base_fields()
    rec.update({
        "patient_id": patient_id,
        "due_utc": due_utc,
        "collected_utc": None,
        "expected_substances": expected,
        "detected_substances": None,
        "recollect_count": 0,
        "status": "SCHEDULED",
    })
    db.urine_drug_screens[rec["id"]] = rec
    ledger_service.refresh_open_uds_count(patient_id)
    return response.created(serialize.urine_drug_screen(rec))


@app.route("/clinics/<clinic_id>/patients/<patient_id>/urine-drug-screens", methods=["GET"])
def list_uds(clinic_id, patient_id):
    require_role(["ClinicAdmin", "IntakeCoordinator", "Prescriber", "ComplianceOfficer"])
    helpers.get_clinic(clinic_id)
    helpers.get_patient(clinic_id, patient_id)
    items = [u for u in db.urine_drug_screens.values() if u["patient_id"] == patient_id]
    items = helpers.sort_created(items)
    page, limit, offset, total = helpers.paginate(items)
    return response.list_ok([serialize.urine_drug_screen(u) for u in page], limit, offset, total)


def _get_uds(clinic_id, patient_id, uds_id):
    u = db.urine_drug_screens.get(uds_id)
    if u is None or u["patient_id"] != patient_id:
        raise errors.ApiError(errors.ERR_UDS_NOT_FOUND, 404, "urine drug screen not found")
    return u


@app.route("/clinics/<clinic_id>/patients/<patient_id>/urine-drug-screens/<uds_id>/collect", methods=["POST"])
def collect_uds(clinic_id, patient_id, uds_id):
    require_role(["IntakeCoordinator"])
    c = helpers.get_clinic(clinic_id)
    helpers.get_patient(clinic_id, patient_id)
    u = _get_uds(clinic_id, patient_id, uds_id)
    if u["status"] != "SCHEDULED":
        raise errors.ApiError(errors.ERR_UDS_STATE_INVALID, 409, "screen not SCHEDULED")
    if clinic_utc(c) < util.parse_iso(u["due_utc"]):
        raise errors.ApiError(errors.ERR_UDS_NOT_DUE, 409, "screen not due yet")
    u["status"] = "COLLECTED"
    u["collected_utc"] = c["current_utc"]
    db.touch(u)
    return response.ok(serialize.urine_drug_screen(u))


@app.route("/clinics/<clinic_id>/patients/<patient_id>/urine-drug-screens/<uds_id>/result", methods=["POST"])
def result_uds(clinic_id, patient_id, uds_id):
    require_role(["ComplianceOfficer"])
    helpers.get_clinic(clinic_id)
    patient = helpers.get_patient(clinic_id, patient_id)
    u = _get_uds(clinic_id, patient_id, uds_id)
    if u["status"] != "COLLECTED":
        raise errors.ApiError(errors.ERR_UDS_STATE_INVALID, 409, "screen not COLLECTED")
    b = body()
    detected = util.require(b, "detected_substances")
    u["detected_substances"] = detected
    expected_set = set(u["expected_substances"] or [])
    detected_set = set(detected or [])
    if detected_set == expected_set:
        u["status"] = "RESULTED_CONSISTENT"
        db.touch(u)
    else:
        u["status"] = "RESULTED_INCONSISTENT"
        db.touch(u)
        ledger_service.compliance_cascade(patient)
    ledger_service.refresh_open_uds_count(patient_id)
    u = db.urine_drug_screens[uds_id]
    return response.ok(serialize.urine_drug_screen(u))


@app.route("/clinics/<clinic_id>/patients/<patient_id>/urine-drug-screens/<uds_id>/recollect", methods=["POST"])
def recollect_uds(clinic_id, patient_id, uds_id):
    require_role(["ComplianceOfficer"])
    helpers.get_clinic(clinic_id)
    helpers.get_patient(clinic_id, patient_id)
    u = _get_uds(clinic_id, patient_id, uds_id)
    if u["status"] != "RESULTED_INCONSISTENT":
        raise errors.ApiError(errors.ERR_UDS_STATE_INVALID, 409, "screen not RESULTED_INCONSISTENT")
    b = body()
    due_utc = util.require(b, "due_utc")
    util.parse_iso(due_utc)
    u["status"] = "SCHEDULED"
    u["recollect_count"] += 1
    u["detected_substances"] = None
    u["collected_utc"] = None
    u["due_utc"] = due_utc
    db.touch(u)
    ledger_service.refresh_open_uds_count(patient_id)
    return response.ok(serialize.urine_drug_screen(u))


# ===========================================================================
# Pill-count audits
# ===========================================================================
@app.route("/clinics/<clinic_id>/patients/<patient_id>/pill-count-audits", methods=["POST"])
def create_pill_count(clinic_id, patient_id):
    require_role(["ComplianceOfficer"])
    c = helpers.get_clinic(clinic_id)
    patient = helpers.get_patient(clinic_id, patient_id)
    b = body()
    prescription_id = util.require(b, "prescription_id")
    audit_utc = util.require(b, "audit_utc")
    counted_pills = util.require(b, "counted_pills")
    rx = db.prescriptions.get(prescription_id)
    if rx is None or rx["patient_id"] != patient_id:
        raise errors.ApiError(errors.ERR_PRESCRIPTION_NOT_FOUND, 404, "prescription not found")
    audit_dt = util.parse_iso(audit_utc)
    created = util.parse_iso(rx["created_at"])
    elapsed_days = max(0, math.floor((audit_dt - created).total_seconds() / SECONDS_PER_DAY))
    capped_days = min(elapsed_days, rx["day_supply"])
    units_per_day = rx["units_per_day"]
    pills_dispensed = rx["pills_dispensed"]
    per_day_consumption = math.ceil(units_per_day)
    expected_forward = util.round2(pills_dispensed - (units_per_day * capped_days))
    expected_chronological = pills_dispensed - (per_day_consumption * capped_days)
    discrepancy = abs(expected_chronological - counted_pills)
    result = "CONSISTENT" if discrepancy <= c["pill_count_tolerance"] else "INCONSISTENT"
    rec = db.base_fields()
    rec.update({
        "patient_id": patient_id,
        "prescription_id": prescription_id,
        "audit_utc": audit_utc,
        "counted_pills": counted_pills,
        "expected_pills_forward": expected_forward,
        "expected_pills_chronological": expected_chronological,
        "discrepancy_pills": discrepancy,
        "result": result,
    })
    db.pill_count_audits[rec["id"]] = rec
    if result == "INCONSISTENT":
        ledger_service.compliance_cascade(patient)
    return response.created(serialize.pill_count_audit(rec))


@app.route("/clinics/<clinic_id>/patients/<patient_id>/pill-count-audits", methods=["GET"])
def list_pill_count(clinic_id, patient_id):
    require_role(["ClinicAdmin", "Prescriber", "ComplianceOfficer"])
    helpers.get_clinic(clinic_id)
    helpers.get_patient(clinic_id, patient_id)
    prescription_id = request.args.get("prescription_id")
    items = [a for a in db.pill_count_audits.values() if a["patient_id"] == patient_id]
    if prescription_id:
        items = [a for a in items if a["prescription_id"] == prescription_id]
    items = helpers.sort_created(items)
    page, limit, offset, total = helpers.paginate(items)
    return response.list_ok([serialize.pill_count_audit(a) for a in page], limit, offset, total)


# ===========================================================================
# Flat cross-cutting discovery endpoints
# ===========================================================================
def _flat_list(store, filters):
    items = list(store.values())
    for key, val in filters.items():
        if val is not None:
            items = [r for r in items if r.get(key) == val]
    items = helpers.sort_created(items)
    return helpers.paginate(items)


@app.route("/providers/<provider_id>", methods=["GET"])
def flat_get_provider(provider_id):
    require_role(ALL_ROLES)
    p = db.providers.get(provider_id)
    if p is None:
        raise errors.ApiError(errors.ERR_PROVIDER_NOT_FOUND, 404, "provider not found")
    return response.ok(serialize.provider(p))


@app.route("/providers", methods=["GET"])
def flat_list_providers():
    require_role(ALL_ROLES)
    page, limit, offset, total = _flat_list(db.providers, {"clinic_id": request.args.get("clinic_id")})
    return response.list_ok([serialize.provider(p) for p in page], limit, offset, total)


@app.route("/patients/<patient_id>", methods=["GET"])
def flat_get_patient(patient_id):
    require_role(ALL_ROLES)
    p = db.patients.get(patient_id)
    if p is None:
        raise errors.ApiError(errors.ERR_PATIENT_NOT_FOUND, 404, "patient not found")
    return response.ok(serialize.patient(p))


@app.route("/patients", methods=["GET"])
def flat_list_patients():
    require_role(ALL_ROLES)
    page, limit, offset, total = _flat_list(
        db.patients, {"clinic_id": request.args.get("clinic_id"), "status": request.args.get("status")})
    return response.list_ok([serialize.patient(p) for p in page], limit, offset, total)


@app.route("/prescriptions/<prescription_id>", methods=["GET"])
def flat_get_prescription(prescription_id):
    require_role(["ClinicAdmin", "Prescriber", "ComplianceOfficer", "PriorAuthClerk"])
    rx = db.prescriptions.get(prescription_id)
    if rx is None:
        raise errors.ApiError(errors.ERR_PRESCRIPTION_NOT_FOUND, 404, "prescription not found")
    return response.ok(serialize.prescription(rx))


@app.route("/prescriptions", methods=["GET"])
def flat_list_prescriptions():
    require_role(["ClinicAdmin", "Prescriber", "ComplianceOfficer", "PriorAuthClerk"])
    page, limit, offset, total = _flat_list(db.prescriptions, {
        "patient_id": request.args.get("patient_id"),
        "prescriber_id": request.args.get("prescriber_id"),
        "prior_auth_id": request.args.get("prior_auth_id"),
    })
    return response.list_ok([serialize.prescription(r) for r in page], limit, offset, total)


@app.route("/prior-authorizations/<pa_id>", methods=["GET"])
def flat_get_pa(pa_id):
    require_role(["ClinicAdmin", "IntakeCoordinator", "Prescriber", "PriorAuthClerk"])
    pa = db.prior_authorizations.get(pa_id)
    if pa is None:
        raise errors.ApiError(errors.ERR_PRIOR_AUTH_NOT_FOUND, 404, "prior authorization not found")
    return response.ok(serialize.prior_authorization(pa))


@app.route("/prior-authorizations", methods=["GET"])
def flat_list_pa():
    require_role(["ClinicAdmin", "IntakeCoordinator", "Prescriber", "PriorAuthClerk"])
    page, limit, offset, total = _flat_list(db.prior_authorizations, {"patient_id": request.args.get("patient_id")})
    return response.list_ok([serialize.prior_authorization(r) for r in page], limit, offset, total)


@app.route("/opioid-agreements", methods=["GET"])
def flat_list_agreements():
    require_role(["ClinicAdmin", "Prescriber", "ComplianceOfficer"])
    page, limit, offset, total = _flat_list(db.opioid_agreements, {
        "clinic_id": request.args.get("clinic_id"),
        "patient_id": request.args.get("patient_id"),
        "prescriber_id": request.args.get("prescriber_id"),
    })
    return response.list_ok([serialize.opioid_agreement(r) for r in page], limit, offset, total)


@app.route("/opioid-agreements/<agreement_id>", methods=["GET"])
def flat_get_agreement(agreement_id):
    require_role(["ClinicAdmin", "Prescriber", "ComplianceOfficer"])
    a = db.opioid_agreements.get(agreement_id)
    if a is None:
        raise errors.ApiError(errors.ERR_AGREEMENT_NOT_FOUND, 404, "agreement not found")
    return response.ok(serialize.opioid_agreement(a))


@app.route("/pdmp-checks", methods=["GET"])
def flat_list_pdmp():
    require_role(["ClinicAdmin", "Prescriber", "ComplianceOfficer"])
    page, limit, offset, total = _flat_list(db.pdmp_checks, {
        "clinic_id": request.args.get("clinic_id"),
        "patient_id": request.args.get("patient_id"),
        "queried_by_provider_id": request.args.get("queried_by_provider_id"),
    })
    return response.list_ok([serialize.pdmp_check(r) for r in page], limit, offset, total)


@app.route("/pdmp-checks/<pdmp_id>", methods=["GET"])
def flat_get_pdmp(pdmp_id):
    require_role(["ClinicAdmin", "Prescriber", "ComplianceOfficer"])
    x = db.pdmp_checks.get(pdmp_id)
    if x is None:
        raise errors.ApiError(errors.ERR_PDMP_CHECK_NOT_FOUND, 404, "pdmp check not found")
    return response.ok(serialize.pdmp_check(x))


@app.route("/treatment-plans", methods=["GET"])
def flat_list_plans():
    require_role(ALL_ROLES)
    page, limit, offset, total = _flat_list(db.treatment_plans, {"patient_id": request.args.get("patient_id")})
    return response.list_ok([serialize.treatment_plan(r) for r in page], limit, offset, total)


@app.route("/treatment-plans/<plan_id>", methods=["GET"])
def flat_get_plan(plan_id):
    require_role(ALL_ROLES)
    tp = db.treatment_plans.get(plan_id)
    if tp is None:
        raise errors.ApiError(errors.ERR_TREATMENT_PLAN_NOT_FOUND, 404, "treatment plan not found")
    return response.ok(serialize.treatment_plan(tp))


@app.route("/fluoroscopy-suites", methods=["GET"])
def flat_list_suites():
    require_role(["ClinicAdmin", "IntakeCoordinator", "Prescriber", "PriorAuthClerk"])
    page, limit, offset, total = _flat_list(db.fluoroscopy_suites, {"clinic_id": request.args.get("clinic_id")})
    return response.list_ok([serialize.fluoroscopy_suite(r) for r in page], limit, offset, total)


@app.route("/fluoroscopy-suites/<suite_id>", methods=["GET"])
def flat_get_suite(suite_id):
    require_role(["ClinicAdmin", "IntakeCoordinator", "Prescriber", "PriorAuthClerk"])
    s = db.fluoroscopy_suites.get(suite_id)
    if s is None:
        raise errors.ApiError(errors.ERR_SUITE_NOT_FOUND, 404, "suite not found")
    return response.ok(serialize.fluoroscopy_suite(s))


@app.route("/procedures", methods=["GET"])
def flat_list_procedures():
    require_role(["ClinicAdmin", "IntakeCoordinator", "Prescriber", "PriorAuthClerk"])
    page, limit, offset, total = _flat_list(db.procedures, {
        "patient_id": request.args.get("patient_id"),
        "suite_id": request.args.get("suite_id"),
        "treatment_plan_id": request.args.get("treatment_plan_id"),
        "prior_auth_id": request.args.get("prior_auth_id"),
    })
    return response.list_ok([serialize.procedure(r) for r in page], limit, offset, total)


@app.route("/procedures/<procedure_id>", methods=["GET"])
def flat_get_procedure(procedure_id):
    require_role(["ClinicAdmin", "IntakeCoordinator", "Prescriber", "PriorAuthClerk"])
    p = db.procedures.get(procedure_id)
    if p is None:
        raise errors.ApiError(errors.ERR_PROCEDURE_NOT_FOUND, 404, "procedure not found")
    return response.ok(serialize.procedure(p))


@app.route("/urine-drug-screens", methods=["GET"])
def flat_list_uds():
    require_role(["ClinicAdmin", "IntakeCoordinator", "Prescriber", "ComplianceOfficer"])
    page, limit, offset, total = _flat_list(db.urine_drug_screens, {"patient_id": request.args.get("patient_id")})
    return response.list_ok([serialize.urine_drug_screen(r) for r in page], limit, offset, total)


@app.route("/urine-drug-screens/<uds_id>", methods=["GET"])
def flat_get_uds(uds_id):
    require_role(["ClinicAdmin", "IntakeCoordinator", "Prescriber", "ComplianceOfficer"])
    u = db.urine_drug_screens.get(uds_id)
    if u is None:
        raise errors.ApiError(errors.ERR_UDS_NOT_FOUND, 404, "urine drug screen not found")
    return response.ok(serialize.urine_drug_screen(u))


@app.route("/pill-count-audits", methods=["GET"])
def flat_list_audits():
    require_role(["ClinicAdmin", "Prescriber", "ComplianceOfficer"])
    page, limit, offset, total = _flat_list(db.pill_count_audits, {
        "patient_id": request.args.get("patient_id"),
        "prescription_id": request.args.get("prescription_id"),
    })
    return response.list_ok([serialize.pill_count_audit(r) for r in page], limit, offset, total)


@app.route("/pill-count-audits/<audit_id>", methods=["GET"])
def flat_get_audit(audit_id):
    require_role(["ClinicAdmin", "Prescriber", "ComplianceOfficer"])
    a = db.pill_count_audits.get(audit_id)
    if a is None:
        raise errors.ApiError(errors.ERR_PILL_COUNT_AUDIT_NOT_FOUND, 404, "pill count audit not found")
    return response.ok(serialize.pill_count_audit(a))


@app.route("/controlled-substance-ledger", methods=["GET"])
def flat_list_ledgers():
    require_role(["ClinicAdmin", "Prescriber", "ComplianceOfficer"])
    page, limit, offset, total = _flat_list(db.ledgers, {"patient_id": request.args.get("patient_id")})
    return response.list_ok([serialize.ledger(r) for r in page], limit, offset, total)


@app.route("/controlled-substance-ledger/<ledger_id>", methods=["GET"])
def flat_get_ledger(ledger_id):
    require_role(["ClinicAdmin", "Prescriber", "ComplianceOfficer"])
    l = db.ledgers.get(ledger_id)
    if l is None:
        raise errors.ApiError(errors.ERR_LEDGER_NOT_FOUND, 404, "ledger not found")
    return response.ok(serialize.ledger(l))


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------
def _timedelta_days(days):
    import datetime
    return datetime.timedelta(days=days)


def _timedelta_minutes(minutes):
    import datetime
    return datetime.timedelta(minutes=minutes)


def _to_iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    # Prefer a production-grade WSGI server (waitress). The Werkzeug dev server
    # can drop connections mid-response (BadStatusLine) under heavy concurrent
    # load, which surfaces as spurious ConnectionError failures during the
    # 8x-parallel per-test-server sweep. Fall back to app.run if unavailable.
    try:
        from waitress import serve
        serve(app, host="0.0.0.0", port=port, threads=8)
    except Exception:
        app.run(host="0.0.0.0", port=port, threaded=True)
