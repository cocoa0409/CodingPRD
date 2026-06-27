"""Patient endpoints + enroll/suspend/discharge state machine (PRD §3.1, §3.3)."""
from flask import Blueprint, request

import errors
import serializers
import validation as V
from common import get_json_body, parse_pagination, sort_by_created, paginate
from db import db, stamp_create, touch
from middleware import require_roles
from response import object_response, array_response
from services import lookups

bp = Blueprint("patients", __name__)

ACTIVE_ENROLLMENT = {"PENDING_CONSENT", "ENROLLED", "SUSPENDED"}


def _mrn_collision(mrn, exclude_id=None):
    for p in db.patients.values():
        if exclude_id is not None and p["id"] == exclude_id:
            continue
        if p["mrn"] == mrn and p["enrollment_status"] in ACTIVE_ENROLLMENT:
            return True
    return False


@bp.post("/patients")
@require_roles("CareCoordinator")
def create_patient():
    body = get_json_body()
    # FK existence (priority 4) before required-field type checks (priority 5)?
    # Per PRD §2.5: FK resolution precedes required-field domain checks.
    # payer_id must be present to resolve; treat absence as missing field only
    # after attempting body-FK resolution semantics.
    payer_id = body.get("payer_id")
    if payer_id is not None and not isinstance(payer_id, str):
        raise errors.invalid_request("payer_id must be a string.")
    if payer_id is None or payer_id == "":
        # No FK supplied -> required-field violation.
        raise errors.invalid_request("Missing required field: payer_id.")
    if payer_id not in db.payers:
        raise errors.reference_not_found("payer_id does not resolve.")

    mrn = V.require_string(body, "mrn")
    full_name = V.require_string(body, "full_name")

    # Uniqueness (priority 16) after field validation.
    if _mrn_collision(mrn):
        raise errors.ApiError(errors.ERR_DUPLICATE_RESOURCE, 409,
                              "mrn already in use by an active patient.")

    rec = {
        "payer_id": payer_id,
        "mrn": mrn,
        "full_name": full_name,
        "enrollment_status": "PENDING_CONSENT",
        "monitoring_status": "INACTIVE",
        "care_plan_id": None,
    }
    stamp_create(rec)
    db.patients[rec["id"]] = rec
    return object_response(serializers.patient(rec), 201)


@bp.get("/patients/<pid>")
@require_roles("CareCoordinator", "Physician", "Clinician", "BillingSpecialist")
def get_patient(pid):
    rec = db.patients.get(pid)
    if rec is None:
        raise errors.not_found("Patient not found.")
    return object_response(serializers.patient(rec))


@bp.get("/patients")
@require_roles("CareCoordinator", "Physician", "Clinician", "BillingSpecialist")
def list_patients():
    limit, offset = parse_pagination()
    records = list(db.patients.values())
    payer_id = request.args.get("payer_id")
    if payer_id is not None:
        records = [r for r in records if r["payer_id"] == payer_id]
    enrollment_status = request.args.get("enrollment_status")
    if enrollment_status is not None:
        records = [r for r in records
                   if r["enrollment_status"] == enrollment_status]
    records = sort_by_created(records)
    page, total = paginate(records, limit, offset)
    return array_response([serializers.patient(r) for r in page],
                          limit, offset, total)


def _get_patient_or_404(pid):
    rec = db.patients.get(pid)
    if rec is None:
        raise errors.not_found("Patient not found.")
    return rec


@bp.post("/patients/<pid>/enroll")
@require_roles("CareCoordinator")
def enroll_patient(pid):
    patient = _get_patient_or_404(pid)
    status = patient["enrollment_status"]
    # State legality (priority 6): enroll defined only from PENDING_CONSENT or SUSPENDED.
    if status not in ("PENDING_CONSENT", "SUSPENDED"):
        raise errors.invalid_state("Patient cannot be enrolled from its current state.")

    # Enrollment readiness (priority 12): ACTIVE consent (RPM/BOTH) before ACTIVE care plan.
    consent = lookups.active_consent(pid)
    if consent is None or consent["consent_type"] not in ("RPM", "BOTH"):
        raise errors.ApiError(errors.ERR_CONSENT_REQUIRED, 409,
                              "An ACTIVE consent covering RPM or BOTH is required.")
    if lookups.active_care_plan(pid) is None:
        raise errors.ApiError(errors.ERR_CONSENT_REQUIRED, 409,
                              "An ACTIVE care plan is required.")

    resuming = status == "SUSPENDED"
    patient["enrollment_status"] = "ENROLLED"
    touch(patient)

    # Resume monitoring as a cross-dimension consequence (PRD §3.3): only when
    # resuming from SUSPENDED, monitoring is PAUSED, and an ACTIVE device exists.
    if resuming and patient["monitoring_status"] == "PAUSED":
        has_active_device = any(d["status"] == "ACTIVE"
                                for d in lookups.devices_of(pid))
        if has_active_device:
            patient["monitoring_status"] = "MONITORING"
            touch(patient)

    return object_response(serializers.patient(patient))


@bp.post("/patients/<pid>/suspend")
@require_roles("CareCoordinator")
def suspend_patient(pid):
    patient = _get_patient_or_404(pid)
    if patient["enrollment_status"] != "ENROLLED":
        raise errors.invalid_state("Only an ENROLLED patient can be suspended.")

    patient["enrollment_status"] = "SUSPENDED"
    touch(patient)

    # Cross-dimension cascade: if MONITORING, move to PAUSED (one extra version bump).
    if patient["monitoring_status"] == "MONITORING":
        patient["monitoring_status"] = "PAUSED"
        touch(patient)

    return object_response(serializers.patient(patient))


@bp.post("/patients/<pid>/discharge")
@require_roles("CareCoordinator")
def discharge_patient(pid):
    patient = _get_patient_or_404(pid)
    if patient["enrollment_status"] == "DISCHARGED":
        raise errors.invalid_state("Patient is already discharged.")

    # State guard: blocked if any OPEN period has provisional_total_minutes > 0.
    for bp_rec in lookups.billing_periods_of(pid):
        if bp_rec["status"] == "OPEN" and bp_rec["provisional_total_minutes"] > 0:
            raise errors.invalid_state(
                "Cannot discharge: an OPEN billing period has accrued minutes."
            )

    patient["enrollment_status"] = "DISCHARGED"
    patient["monitoring_status"] = "INACTIVE"
    touch(patient)

    # Cascade: every device ENROLLED/ACTIVE -> RETURNED (each bumps its own version).
    for d in lookups.devices_of(pid):
        if d["status"] in ("ENROLLED", "ACTIVE"):
            d["status"] = "RETURNED"
            touch(d)

    # Cascade: ACTIVE care plan -> RETIRED, clear care_plan_id.
    active_plan = lookups.active_care_plan(pid)
    if active_plan is not None:
        active_plan["status"] = "RETIRED"
        touch(active_plan)
        patient["care_plan_id"] = None
        # care_plan_id clear is part of the discharge mutation already counted;
        # the plan retirement bumps its own version above.

    return object_response(serializers.patient(patient))
