"""Admissions and all clinical/level-of-care transitions (PRD §3.4-§3.9)."""
from flask import Blueprint

import errors
from db import store
from errors import ApiError
from middleware import require_auth_and_roles
from response import success, list_response
from services import calc
from services.common import (
    base_record,
    check_fk,
    get_json_body,
    get_optional_json_body,
    get_or_404,
    list_collection,
    require_field,
    serialize,
    touch,
    validate_int,
)
from services.domain import (
    recompute_auth_days,
    recompute_patient_posture,
    recompute_program_counters,
    set_patient_number,
)

bp = Blueprint("admissions", __name__)

ALL_READ_ROLES = ["Admin", "Intake", "Clinician", "Dietitian", "UtilizationReviewer"]
LOC_LADDER = ["RESIDENTIAL", "PHP", "IOP", "OP"]


# --------------------------- Create / read ---------------------------
@bp.route("/edt/admissions", methods=["POST"])
@require_auth_and_roles(["Intake"])
def create_admission():
    body = get_json_body()
    patient_id = require_field(body, "patient_id")
    facility_id = require_field(body, "facility_id")
    program_id = require_field(body, "program_id")
    cohort_id = require_field(body, "cohort_id")
    los = validate_int(
        require_field(body, "requested_length_of_stay_days"),
        "requested_length_of_stay_days",
        minimum=1,
    )
    with store.lock:
        check_fk("patient_id", patient_id)
        check_fk("facility_id", facility_id)
        check_fk("program_id", program_id)
        check_fk("cohort_id", cohort_id)
        rec = base_record()
        rec.update({
            "patient_id": patient_id,
            "facility_id": facility_id,
            "program_id": program_id,
            "cohort_id": cohort_id,
            "requested_length_of_stay_days": los,
            "clinical_status": "WAITLISTED",
            "level_of_care": None,
            "admitted_at_iso": None,
            "loc_entered_at_iso": None,
            "discharged_at_iso": None,
            "waitlist_promoted": False,
        })
        store.admissions[rec["id"]] = rec
        return success(serialize(rec), status=201)


@bp.route("/edt/admissions", methods=["GET"])
@require_auth_and_roles(ALL_READ_ROLES)
def list_admissions():
    page, limit, offset, total = list_collection(
        "admissions",
        filters={
            "patient_id": "patient_id",
            "program_id": "program_id",
            "cohort_id": "cohort_id",
            "facility_id": "facility_id",
        },
    )
    return list_response([serialize(r) for r in page], limit, offset, total)


@bp.route("/edt/admissions/<aid>", methods=["GET"])
@require_auth_and_roles(ALL_READ_ROLES)
def get_admission(aid):
    rec = get_or_404("admissions", aid, errors.ERR_ADMISSION_NOT_FOUND)
    return success(serialize(rec), status=200)


# --------------------------- promote ---------------------------
@bp.route("/edt/admissions/<aid>/promote", methods=["POST"])
@require_auth_and_roles(["Intake"])
def promote_admission(aid):
    get_optional_json_body()
    with store.lock:
        adm = get_or_404("admissions", aid, errors.ERR_ADMISSION_NOT_FOUND)
        # legal only from WAITLISTED (PRD §3.4).
        if adm["clinical_status"] != "WAITLISTED":
            raise ApiError(errors.ERR_INVALID_STATE, 409, "Admission is not WAITLISTED.")
        program = store.programs[adm["program_id"]]
        # only while program OPEN (PRD §3.4).
        if program["status"] != "OPEN":
            raise ApiError(errors.ERR_PROGRAM_CLOSED, 409, "Program is CLOSED.")
        adm["clinical_status"] = "PENDING_ADMISSION"
        touch(adm)
        return success(serialize(adm), status=200)


# --------------------------- admit ---------------------------
@bp.route("/edt/admissions/<aid>/admit", methods=["POST"])
@require_auth_and_roles(["Intake"])
def admit_admission(aid):
    get_optional_json_body()
    with store.lock:
        adm = get_or_404("admissions", aid, errors.ERR_ADMISSION_NOT_FOUND)
        patient = store.patients[adm["patient_id"]]
        program = store.programs[adm["program_id"]]
        cohort = store.cohorts[adm["cohort_id"]]

        # Preconditions evaluated in the order of PRD §3.4.
        # 1. legal state.
        if adm["clinical_status"] != "PENDING_ADMISSION":
            raise ApiError(errors.ERR_INVALID_STATE, 409, "Admission is not PENDING_ADMISSION.")
        # 2. cohort age band must equal patient age band.
        if cohort["age_band"] != patient["age_band"]:
            raise ApiError(errors.ERR_COHORT_AGE_MISMATCH, 409, "Cohort age band does not match patient.")
        # 3. medical-stability admissibility: UNSTABLE only into RESIDENTIAL.
        if patient["medical_stability_posture"] == "UNSTABLE" and program["level_of_care"] != "RESIDENTIAL":
            raise ApiError(errors.ERR_LOC_NOT_ADMISSIBLE, 409, "Unstable patient only admissible into RESIDENTIAL.")
        # 4. program OPEN.
        if program["status"] != "OPEN":
            raise ApiError(errors.ERR_PROGRAM_CLOSED, 409, "Program is CLOSED.")
        # 5. program has room (occupancy posture OPEN: beds_occupied < bed_capacity).
        if program["beds_occupied"] >= program["bed_capacity"]:
            raise ApiError(errors.ERR_PROGRAM_AT_CAPACITY, 409, "Program is at capacity.")
        # 6. cohort has room.
        if cohort["slots_filled"] >= cohort["slot_capacity"]:
            raise ApiError(errors.ERR_COHORT_FULL, 409, "Cohort is full.")
        # 7. financially covered: an APPROVED auth with >= 1 day remaining.
        if not _has_active_authorization(adm["id"]):
            raise ApiError(errors.ERR_NO_ACTIVE_AUTHORIZATION, 402, "No APPROVED authorization with days remaining.")

        # Side effects.
        now = store.now_iso()
        adm["clinical_status"] = "ADMITTED"
        adm["level_of_care"] = program["level_of_care"]
        adm["admitted_at_iso"] = now
        adm["loc_entered_at_iso"] = now
        program["beds_occupied"] += 1
        recompute_program_counters(program)
        touch(program)
        cohort["slots_filled"] += 1
        touch(cohort)
        touch(adm)
        return success(serialize(adm), status=200)


def _has_active_authorization(admission_id):
    for auth in store.authorizations.values():
        if auth["admission_id"] != admission_id:
            continue
        if auth["status"] != "APPROVED":
            continue
        recompute_auth_days(auth)
        if auth["days_remaining"] >= 1:
            return True
    return False


# --------------------------- medical-hold ---------------------------
@bp.route("/edt/admissions/<aid>/medical-hold", methods=["POST"])
@require_auth_and_roles(["Clinician"])
def medical_hold(aid):
    get_optional_json_body()
    with store.lock:
        adm = get_or_404("admissions", aid, errors.ERR_ADMISSION_NOT_FOUND)
        if adm["clinical_status"] != "ADMITTED":
            raise ApiError(errors.ERR_INVALID_STATE, 409, "Admission is not ADMITTED.")
        adm["clinical_status"] = "MEDICAL_HOLD"
        touch(adm)
        # Add 10 to reconciled nutritional_risk_score; recompute posture (PRD §3.5).
        patient = store.patients[adm["patient_id"]]
        new_score = calc.Decimal(str(patient["nutritional_risk_score"])) + calc.MEDICAL_HOLD_RISK_BUMP
        new_score = calc._clamp(new_score, calc.Decimal("0"), calc.Decimal("100"))
        set_patient_number(patient, "nutritional_risk_score", new_score)
        recompute_patient_posture(patient)
        touch(patient)
        return success(serialize(adm), status=200)


# --------------------------- clear-hold ---------------------------
@bp.route("/edt/admissions/<aid>/clear-hold", methods=["POST"])
@require_auth_and_roles(["Clinician"])
def clear_hold(aid):
    get_optional_json_body()
    with store.lock:
        adm = get_or_404("admissions", aid, errors.ERR_ADMISSION_NOT_FOUND)
        if adm["clinical_status"] != "MEDICAL_HOLD":
            raise ApiError(errors.ERR_INVALID_STATE, 409, "Admission is not on MEDICAL_HOLD.")
        # No risk reversal (PRD §3.5).
        adm["clinical_status"] = "ADMITTED"
        touch(adm)
        return success(serialize(adm), status=200)


# --------------------------- step-down ---------------------------
@bp.route("/edt/admissions/<aid>/step-down", methods=["POST"])
@require_auth_and_roles(["Clinician"])
def step_down(aid):
    get_optional_json_body()
    with store.lock:
        adm = get_or_404("admissions", aid, errors.ERR_ADMISSION_NOT_FOUND)
        # Preconditions in PRD §3.8 order.
        if adm["clinical_status"] != "ADMITTED":
            raise ApiError(errors.ERR_INVALID_STATE, 409, "Admission is not ADMITTED.")
        current_loc = adm["level_of_care"]
        if current_loc == "OP":
            raise ApiError(errors.ERR_ALREADY_LOWEST_LOC, 409, "Already at lowest level of care.")

        tp = _active_treatment_plan(adm["id"])
        if tp is None:
            raise ApiError(errors.ERR_TREATMENT_PLAN_NOT_ACTIVE, 409, "No ACTIVE treatment plan.")

        meal_plan = _meal_plan_for(adm["id"])
        rate = calc.Decimal(str(meal_plan["meal_compliance_rate"])) if meal_plan else calc.Decimal("0")
        meals_logged = meal_plan["meals_logged"] if meal_plan else 0
        if rate < calc.MEAL_COMPLIANCE_FLOOR or meals_logged < calc.MIN_MEALS_FOR_STEP_DOWN:
            raise ApiError(errors.ERR_INSUFFICIENT_MEAL_COMPLIANCE, 409, "Insufficient meal compliance.")

        patient = store.patients[adm["patient_id"]]
        readiness = calc.step_down_readiness(
            tp["goals_met"], tp["goals_total"], rate, patient["medical_stability_posture"]
        )
        if readiness < calc.STEP_DOWN_THRESHOLD:
            raise ApiError(errors.ERR_STEP_DOWN_NOT_READY, 409, "Step-down readiness below threshold.")

        # Advance LOC one rung; re-stamp loc_entered_at_iso (PRD §3.8).
        idx = LOC_LADDER.index(current_loc)
        adm["level_of_care"] = LOC_LADDER[idx + 1]
        adm["loc_entered_at_iso"] = store.now_iso()
        touch(adm)
        return success(serialize(adm), status=200)


def _active_treatment_plan(admission_id):
    for tp in store.treatment_plans.values():
        if tp["admission_id"] == admission_id and tp["status"] == "ACTIVE":
            return tp
    return None


def _meal_plan_for(admission_id):
    """Return the meal plan governing this admission's step-down. Prefer an
    ACTIVE plan; the compliance rate feeds the step-down check (PRD §3.8)."""
    plans = [mp for mp in store.meal_plans.values() if mp["admission_id"] == admission_id]
    if not plans:
        return None
    active = [mp for mp in plans if mp["status"] == "ACTIVE"]
    pool = active if active else plans
    pool.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return pool[-1]


# --------------------------- begin-discharge ---------------------------
@bp.route("/edt/admissions/<aid>/begin-discharge", methods=["POST"])
@require_auth_and_roles(["Clinician"])
def begin_discharge(aid):
    get_optional_json_body()
    with store.lock:
        adm = get_or_404("admissions", aid, errors.ERR_ADMISSION_NOT_FOUND)
        if adm["clinical_status"] != "ADMITTED":
            raise ApiError(errors.ERR_INVALID_STATE, 409, "Admission is not ADMITTED.")
        adm["clinical_status"] = "DISCHARGE_PENDING"
        touch(adm)
        return success(serialize(adm), status=200)


# --------------------------- discharge ---------------------------
@bp.route("/edt/admissions/<aid>/discharge", methods=["POST"])
@require_auth_and_roles(["Clinician"])
def discharge(aid):
    get_optional_json_body()
    with store.lock:
        adm = get_or_404("admissions", aid, errors.ERR_ADMISSION_NOT_FOUND)
        # legal only from DISCHARGE_PENDING (PRD §3.9).
        if adm["clinical_status"] != "DISCHARGE_PENDING":
            raise ApiError(errors.ERR_INVALID_STATE, 409, "Admission is not DISCHARGE_PENDING.")
        # FINALIZED discharge plan required.
        if not _has_finalized_discharge_plan(adm["id"]):
            raise ApiError(errors.ERR_DISCHARGE_PLAN_NOT_FINALIZED, 409, "Discharge plan not FINALIZED.")
        # family-program enrollment in COMPLETED or WAIVED.
        if not _family_program_ok(adm["id"]):
            raise ApiError(errors.ERR_FAMILY_PROGRAM_INCOMPLETE, 409, "Family program not COMPLETED/WAIVED.")

        # --- Multi-hop cascade, all atomic ---
        adm["clinical_status"] = "DISCHARGED"
        adm["discharged_at_iso"] = store.now_iso()
        touch(adm)

        program = store.programs[adm["program_id"]]
        cohort = store.cohorts[adm["cohort_id"]]
        prior_posture = program["occupancy_posture"]
        program["beds_occupied"] = max(program["beds_occupied"] - 1, 0)
        recompute_program_counters(program)
        touch(program)
        cohort["slots_filled"] = max(cohort["slots_filled"] - 1, 0)
        touch(cohort)

        patient = store.patients[adm["patient_id"]]
        # hop 1: ACTIVE meal plan(s) -> CLOSED; hop 2: reconcile risk; hop 3: posture.
        for mp in store.meal_plans.values():
            if mp["admission_id"] == adm["id"] and mp["status"] == "ACTIVE":
                _close_meal_plan_reconcile(mp, patient)

        # ACTIVE/REVISION/DRAFT treatment plans -> CLOSED.
        for tp in store.treatment_plans.values():
            if tp["admission_id"] == adm["id"] and tp["status"] in ("ACTIVE", "REVISION", "DRAFT"):
                tp["status"] = "CLOSED"
                touch(tp)

        # Waitlist cascade only on FULL -> OPEN flip (PRD §3.9).
        if prior_posture == "FULL" and program["occupancy_posture"] == "OPEN":
            _promote_earliest_waitlisted(program["id"])

        return success(serialize(adm), status=200)


def _has_finalized_discharge_plan(admission_id):
    for dp in store.discharge_plans.values():
        if dp["admission_id"] == admission_id and dp["status"] == "FINALIZED":
            return True
    return False


def _family_program_ok(admission_id):
    for fp in store.family_programs.values():
        if fp["admission_id"] == admission_id and fp["status"] in ("COMPLETED", "WAIVED"):
            return True
    return False


def _close_meal_plan_reconcile(mp, patient):
    mp["status"] = "CLOSED"
    touch(mp)
    credit = calc.meal_close_credit(mp["meal_compliance_rate"])
    new_score = calc.Decimal(str(patient["nutritional_risk_score"])) - credit
    new_score = calc._clamp(new_score, calc.Decimal("0"), calc.Decimal("100"))
    set_patient_number(patient, "nutritional_risk_score", new_score)
    recompute_patient_posture(patient)
    touch(patient)


def _promote_earliest_waitlisted(program_id):
    candidates = [
        a for a in store.admissions.values()
        if a["program_id"] == program_id and a["clinical_status"] == "WAITLISTED"
    ]
    if not candidates:
        return
    candidates.sort(key=lambda a: (a["created_at"], a["_seq"]))
    promoted = candidates[0]
    promoted["clinical_status"] = "PENDING_ADMISSION"
    promoted["waitlist_promoted"] = True
    touch(promoted)


# --------------------------- admin-discharge ---------------------------
@bp.route("/edt/admissions/<aid>/admin-discharge", methods=["POST"])
@require_auth_and_roles(["Admin"])
def admin_discharge(aid):
    get_optional_json_body()
    with store.lock:
        adm = get_or_404("admissions", aid, errors.ERR_ADMISSION_NOT_FOUND)
        # legal only from WAITLISTED or PENDING_ADMISSION (PRD §3.9).
        if adm["clinical_status"] not in ("WAITLISTED", "PENDING_ADMISSION"):
            raise ApiError(errors.ERR_INVALID_STATE, 409, "Admission is not WAITLISTED/PENDING_ADMISSION.")
        # No bed/cohort counter changes (never occupied a bed).
        adm["clinical_status"] = "ADMINISTRATIVE_DISCHARGE"
        touch(adm)
        return success(serialize(adm), status=200)
