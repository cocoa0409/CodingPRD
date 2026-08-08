"""Prescriptions and their two axes (PRD 3.4) and the titration ladder (PRD 3.5)."""

from flask import Blueprint

import calculations as calc
import envelope
import errors
import serializers
import services
import validation as v
from auth import ANY_ROLE, guard, require_owner
from errors import ApiError
from store import new_record, ordered, parse_iso, store, touch, whole_days_between

bp = Blueprint("prescriptions", __name__)

DRUG_FAMILIES = ("SEMAGLUTIDE", "TIRZEPATIDE")
DISCONTINUE_REASONS = ("PATIENT_REQUEST", "CLINICAL", "SUPERSEDED")


# --- prescriptions ---------------------------------------------------------
@bp.post("/prescriptions")
def create_prescription():
    guard(["Provider"])
    body = v.body()

    patient_id = v.string_field(body, "patient_id", required=True)
    consult_id = v.string_field(body, "consult_id", required=True)
    prescriber_provider_id = v.string_field(body, "prescriber_provider_id", required=True)
    screening_id = v.string_field(body, "screening_id", required=True)
    drug_family = v.enum_field(body, "drug_family", DRUG_FAMILIES, required=True)
    expected_patient_version = v.int_field(body, "expected_patient_version",
                                           required=True)
    units_per_cycle = v.int_field(body, "units_per_cycle", required=False, default=4,
                                  minimum=1, maximum=calc.MAX_UNITS_PER_ORDER)

    patient = services.get_patient(patient_id)
    consult = services.get_consult(consult_id)
    services.get_provider(prescriber_provider_id)
    screening = services.get_screening(screening_id)

    if expected_patient_version != patient["version"]:
        raise ApiError(errors.ERR_STALE_PATIENT_VERSION)

    if consult["status"] != "COMPLETED_PRESCRIBED":
        raise ApiError(errors.ERR_INVALID_STATE)

    if screening["status"] != "ELIGIBLE" or screening["patient_id"] != patient_id:
        raise ApiError(errors.ERR_SCREENING_NOT_ELIGIBLE)

    predecessors = [p for p in ordered(list(store.prescriptions.values()))
                    if p["patient_id"] == patient_id and p["clinical_status"] == "ACTIVE"]

    now_iso = store.now_iso()
    prescription = new_record(store.prescriptions, {
        "patient_id": patient_id,
        "consult_id": consult_id,
        "prescriber_provider_id": prescriber_provider_id,
        "screening_id": screening_id,
        "supersedes_prescription_id": None,
        "drug_family": drug_family,
        "units_per_cycle": units_per_cycle,
        "dose_level": 1,
        "dose_mg": calc.dose_mg_for(drug_family, 1),
        "clinical_status": "ACTIVE",
        "fulfillment_status": "UNROUTED",
        "active_route_mode": patient["payment_mode"],
        "last_dose_change_at": now_iso,
        "severity_index_rolling": 0,
        "severity_index_since_dose_change": 0,
        "discontinue_reason": None,
    })

    # Supersession: the standing ACTIVE prescription is discontinued, its open
    # orders cancelled, but its titration rungs are deliberately left alone.
    for predecessor in predecessors:
        predecessor["clinical_status"] = "DISCONTINUED"
        predecessor["discontinue_reason"] = "SUPERSEDED"
        touch(predecessor)
        prescription["supersedes_prescription_id"] = predecessor["id"]
        for order in services.orders_of_prescription(predecessor["id"]):
            if order["status"] in ("CREATED", "RESERVED"):
                services.cancel_order(order, "CLINICAL_HOLD")

    services.create_titration_step(prescription, 1, 1)
    touch(patient)

    return envelope.success(serializers.dump("prescription", prescription), 201)


@bp.get("/prescriptions/<prescription_id>")
def read_prescription(prescription_id):
    guard(ANY_ROLE)
    prescription = services.get_prescription(prescription_id)
    return envelope.success(serializers.dump("prescription", prescription), 200)


@bp.get("/prescriptions")
def list_prescriptions():
    guard(ANY_ROLE)
    limit, offset = v.pagination()
    filters = v.query_filters("patient_id", "consult_id", "prescriber_provider_id",
                              "screening_id", "supersedes_prescription_id",
                              "clinical_status", "fulfillment_status")
    records = v.apply_filters(ordered(list(store.prescriptions.values())), filters)
    page, total = v.paginate(records, limit, offset)
    return envelope.collection(serializers.dump_many("prescription", page),
                               limit, offset, total)


@bp.post("/prescriptions/<prescription_id>/discontinue")
def discontinue_prescription(prescription_id):
    user_id, role = guard(["Provider", "Patient"])
    prescription = services.get_prescription(prescription_id)
    if role == "Provider":
        require_owner(prescription["prescriber_provider_id"] == user_id)
    else:
        require_owner(prescription["patient_id"] == user_id)

    body = v.body()
    discontinue_reason = v.enum_field(body, "discontinue_reason", DISCONTINUE_REASONS,
                                      required=True)

    if prescription["clinical_status"] == "DISCONTINUED":
        raise ApiError(errors.ERR_INVALID_STATE)

    prescription["clinical_status"] = "DISCONTINUED"
    prescription["discontinue_reason"] = discontinue_reason
    touch(prescription)

    for order in services.orders_of_prescription(prescription_id):
        if order["status"] in ("CREATED", "RESERVED"):
            services.cancel_order(order, "CLINICAL_HOLD")

    for step in services.steps_of(prescription_id):
        if step["status"] in ("DUE", "HELD"):
            step["status"] = "REDUCED"
            step["administered_at"] = store.now_iso()
            touch(step)

    return envelope.success(serializers.dump("prescription", prescription), 200)


@bp.post("/prescriptions/<prescription_id>/request-refill")
def request_refill(prescription_id):
    guard(["Patient", "Provider"])
    prescription = services.get_prescription(prescription_id)

    if prescription["fulfillment_status"] != "DISPENSED":
        raise ApiError(errors.ERR_INVALID_STATE)
    if prescription["clinical_status"] != "ACTIVE":
        raise ApiError(errors.ERR_PRESCRIPTION_NOT_ACTIVE)

    prescription["fulfillment_status"] = "REFILL_DUE"
    touch(prescription)
    return envelope.success(serializers.dump("prescription", prescription), 200)


# --- titration steps -------------------------------------------------------
@bp.get("/titration-steps/<titration_step_id>")
def read_titration_step(titration_step_id):
    guard(ANY_ROLE)
    step = services.get_titration_step(titration_step_id)
    return envelope.success(serializers.dump("titration_step", step), 200)


@bp.get("/titration-steps")
def list_titration_steps():
    guard(ANY_ROLE)
    limit, offset = v.pagination()
    filters = v.query_filters("prescription_id", "second_signer_provider_id", "status")
    records = v.apply_filters(ordered(list(store.titration_steps.values())), filters)
    page, total = v.paginate(records, limit, offset)
    return envelope.collection(serializers.dump_many("titration_step", page),
                               limit, offset, total)


@bp.post("/titration-steps/<titration_step_id>/escalate")
def escalate_titration_step(titration_step_id):
    guard(["Provider"])
    step = services.get_titration_step(titration_step_id)

    body = v.body()
    second_signer_provider_id = v.string_field(body, "second_signer_provider_id",
                                               required=False, default=None)

    if step["status"] != "DUE":
        raise ApiError(errors.ERR_INVALID_STATE)

    prescription = services.get_prescription(step["prescription_id"])
    if prescription["clinical_status"] != "ACTIVE":
        raise ApiError(errors.ERR_PRESCRIPTION_NOT_ACTIVE)

    # Gate 1: no open escalation.
    if services.has_open_escalation(prescription["id"]):
        raise ApiError(errors.ERR_OPEN_ESCALATED_CHECK_IN)

    # Gate 2: ladder ceiling.
    if prescription["dose_level"] >= calc.TITRATION_MAX_DOSE_LEVEL:
        raise ApiError(errors.ERR_TITRATION_MAX_DOSE_REACHED)

    target_level = prescription["dose_level"] + 1

    # Gate 3: second signer present.
    if target_level >= calc.TITRATION_SECOND_SIGNER_MIN_LEVEL \
            and second_signer_provider_id is None:
        raise ApiError(errors.ERR_SECOND_SIGNER_REQUIRED)

    # Gate 4: second signer admissible.
    if second_signer_provider_id is not None:
        signer = services.get_provider(second_signer_provider_id)
        if second_signer_provider_id == prescription["prescriber_provider_id"] \
                or signer["provider_type"] != "CLINICIAN" \
                or signer["status"] != "ACTIVE":
            raise ApiError(errors.ERR_SECOND_SIGNER_CONFLICT)

    # Gate 5: interval, stretched by the tolerability trigger.
    elapsed_days = whole_days_between(parse_iso(prescription["last_dose_change_at"]),
                                      store.now_dt())
    required = calc.required_interval_days(
        prescription["severity_index_since_dose_change"])
    if elapsed_days < required:
        raise ApiError(errors.ERR_TITRATION_INTERVAL_NOT_MET)

    now_iso = store.now_iso()
    step["status"] = "ADMINISTERED"
    step["administered_at"] = now_iso
    if second_signer_provider_id is not None:
        step["second_signer_provider_id"] = second_signer_provider_id
    touch(step)

    prescription["dose_level"] = target_level
    prescription["dose_mg"] = calc.dose_mg_for(prescription["drug_family"], target_level)
    prescription["last_dose_change_at"] = now_iso
    touch(prescription)
    services.recompute_severity_indices(prescription)

    services.create_titration_step(prescription,
                                   services.next_step_number(prescription["id"]),
                                   target_level)

    return envelope.success(serializers.dump("titration_step", step), 200)


@bp.post("/titration-steps/<titration_step_id>/hold")
def hold_titration_step(titration_step_id):
    guard(["Provider"])
    step = services.get_titration_step(titration_step_id)

    if step["status"] != "DUE":
        raise ApiError(errors.ERR_INVALID_STATE)

    prescription = services.get_prescription(step["prescription_id"])
    if prescription["clinical_status"] not in ("ACTIVE", "HELD"):
        raise ApiError(errors.ERR_INVALID_STATE)

    step["status"] = "HELD"
    step["hold_reason"] = "PROVIDER_HOLD"
    touch(step)
    return envelope.success(serializers.dump("titration_step", step), 200)


@bp.post("/titration-steps/<titration_step_id>/reduce")
def reduce_titration_step(titration_step_id):
    guard(["Provider"])
    step = services.get_titration_step(titration_step_id)

    if step["status"] not in ("DUE", "HELD"):
        raise ApiError(errors.ERR_INVALID_STATE)

    prescription = services.get_prescription(step["prescription_id"])
    if prescription["clinical_status"] not in ("ACTIVE", "HELD"):
        raise ApiError(errors.ERR_INVALID_STATE)
    if prescription["dose_level"] <= 1:
        raise ApiError(errors.ERR_INVALID_STATE)

    now_iso = store.now_iso()
    target_level = prescription["dose_level"] - 1

    step["status"] = "REDUCED"
    step["administered_at"] = now_iso
    touch(step)

    prescription["dose_level"] = target_level
    prescription["dose_mg"] = calc.dose_mg_for(prescription["drug_family"], target_level)
    prescription["last_dose_change_at"] = now_iso
    touch(prescription)

    services.create_titration_step(prescription,
                                   services.next_step_number(prescription["id"]),
                                   target_level)

    return envelope.success(serializers.dump("titration_step", step), 200)
