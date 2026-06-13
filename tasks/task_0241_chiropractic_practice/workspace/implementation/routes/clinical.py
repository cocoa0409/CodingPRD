"""Exams and treatment plans (propose, phases, activate, discontinue, regress)."""
from flask import Blueprint, request

import db
from errors import err
from middleware import authenticate, authorize, get_json_body, paginate
from models import new_record, touch, serialize, serialize_list
from lookups import get_patient_or_404, leaf_or_404, ref_or_404
from response import ok, created
from services.calculations import REGRESSION_SEVERITY_THRESHOLD
from services.plans import recompute_plan_totals, discontinue_plan
import validators as V

bp = Blueprint("clinical", __name__)

EXAM_TYPES = {"INITIAL", "RE_EXAM"}
PHASE_TYPES = {"ACUTE", "CORRECTIVE", "MAINTENANCE"}


def _guard_not_dismissed(patient):
    if patient["status"] == "DISMISSED" or patient.get("is_dismissed"):
        raise err("ERR_PATIENT_DISMISSED", "Patient is dismissed")


# ---- Exams ----
@bp.route("/patients/<patient_id>/exams", methods=["POST"])
def create_exam(patient_id):
    uid, role = authenticate()
    authorize(role, ["Provider"])
    patient = get_patient_or_404(patient_id)
    body = get_json_body()
    provider_id = V.require_str(body, "provider_id")
    ref_or_404(db.providers, provider_id)
    exam_type = V.require_enum(body, "exam_type", EXAM_TYPES)
    imaging = V.optional_bool(body, "imaging_ordered", False)
    severity = V.require_int(body, "severity_score")
    # Semantic validation (priority 22): severity 1..10.
    if severity < 1 or severity > 10:
        raise err("ERR_VALIDATION", "severity_score must be between 1 and 10")
    _guard_not_dismissed(patient)
    rec = new_record({
        "patient_id": patient["id"],
        "provider_id": provider_id,
        "exam_type": exam_type,
        "imaging_ordered": imaging,
        "severity_score": severity,
        "findings": body.get("findings"),
        "status": "DRAFT",
    })
    db.exam_records[rec["id"]] = rec
    return created(serialize(rec))


@bp.route("/patients/<patient_id>/exams", methods=["GET"])
def list_exams(patient_id):
    _, role = authenticate()
    authorize(role, ["Provider", "FrontDesk", "PracticeAdmin"])
    get_patient_or_404(patient_id)
    items = [e for e in db.exam_records.values() if e["patient_id"] == patient_id]
    status = request.args.get("status")
    exam_type = request.args.get("exam_type")
    if status is not None:
        items = [e for e in items if e["status"] == status]
    if exam_type is not None:
        items = [e for e in items if e["exam_type"] == exam_type]
    window, pg = paginate(items)
    return ok(serialize_list(window), pagination=pg)


@bp.route("/patients/<patient_id>/exams/<exam_id>/finalize", methods=["POST"])
def finalize_exam(patient_id, exam_id):
    uid, role = authenticate()
    authorize(role, ["Provider"])
    get_patient_or_404(patient_id)
    exam = leaf_or_404(db.exam_records, exam_id, patient_id, "patient_id")
    if exam["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Exam is not DRAFT")
    if exam["provider_id"] != uid:
        raise err("ERR_FORBIDDEN_ROLE", "Only the authoring provider may finalize this exam")
    exam["status"] = "FINALIZED"
    touch(exam)
    return ok(serialize(exam))


# ---- Treatment plans ----
@bp.route("/patients/<patient_id>/treatment-plans", methods=["POST"])
def propose_plan(patient_id):
    _, role = authenticate()
    authorize(role, ["Provider"])
    patient = get_patient_or_404(patient_id)
    body = get_json_body()
    exam_record_id = V.require_str(body, "exam_record_id")
    exam = ref_or_404(db.exam_records, exam_record_id)
    _guard_not_dismissed(patient)
    # Plan must reference a FINALIZED exam (priority 19).
    if exam["status"] != "FINALIZED":
        raise err("ERR_PLAN_NOT_READY", "Referenced exam is not FINALIZED")
    rec = new_record({
        "patient_id": patient["id"],
        "exam_record_id": exam_record_id,
        "current_phase": "ACUTE",
        "total_planned_visits": 0,
        "visits_delivered": 0,
        "status": "PROPOSED",
    })
    db.treatment_plans[rec["id"]] = rec
    return created(serialize(rec))


@bp.route("/patients/<patient_id>/treatment-plans", methods=["GET"])
def list_plans(patient_id):
    _, role = authenticate()
    authorize(role, ["Provider", "FrontDesk", "PracticeAdmin", "BillingClerk"])
    get_patient_or_404(patient_id)
    items = [p for p in db.treatment_plans.values() if p["patient_id"] == patient_id]
    status = request.args.get("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    window, pg = paginate(items)
    return ok(serialize_list(window), pagination=pg)


@bp.route("/patients/<patient_id>/treatment-plans/<plan_id>", methods=["GET"])
def get_plan(patient_id, plan_id):
    _, role = authenticate()
    authorize(role, ["Provider", "FrontDesk", "PracticeAdmin", "BillingClerk"])
    get_patient_or_404(patient_id)
    plan = leaf_or_404(db.treatment_plans, plan_id, patient_id, "patient_id")
    return ok(serialize(plan))


@bp.route("/patients/<patient_id>/treatment-plans/<plan_id>/phases", methods=["POST"])
def add_phase(patient_id, plan_id):
    _, role = authenticate()
    authorize(role, ["Provider"])
    patient = get_patient_or_404(patient_id)
    plan = leaf_or_404(db.treatment_plans, plan_id, patient_id, "patient_id")
    body = get_json_body()
    phase_type = V.require_enum(body, "phase_type", PHASE_TYPES)
    seq = V.require_int(body, "sequence_index")
    vpw = V.require_int(body, "visits_per_week")
    pvc = V.require_int(body, "planned_visit_count")
    if seq < 0:
        raise err("ERR_INVALID_REQUEST", "sequence_index must be >= 0")
    if vpw < 1 or vpw > 7:
        raise err("ERR_INVALID_REQUEST", "visits_per_week must be between 1 and 7")
    if pvc < 1:
        raise err("ERR_INVALID_REQUEST", "planned_visit_count must be >= 1")
    _guard_not_dismissed(patient)
    # Semantic validation (priority 22): sequence_index unique within the plan.
    for p in db.plan_phases.values():
        if p["treatment_plan_id"] == plan_id and p["sequence_index"] == seq:
            raise err("ERR_VALIDATION", "sequence_index must be unique within the plan")
    rec = new_record({
        "treatment_plan_id": plan["id"],
        "phase_type": phase_type,
        "sequence_index": seq,
        "visits_per_week": vpw,
        "planned_visit_count": pvc,
        "visits_completed": 0,
        "status": "PENDING",
    })
    db.plan_phases[rec["id"]] = rec
    recompute_plan_totals(plan)
    return created(serialize(rec))


@bp.route("/patients/<patient_id>/treatment-plans/<plan_id>/phases", methods=["GET"])
def list_phases(patient_id, plan_id):
    _, role = authenticate()
    authorize(role, ["Provider", "FrontDesk", "PracticeAdmin"])
    get_patient_or_404(patient_id)
    leaf_or_404(db.treatment_plans, plan_id, patient_id, "patient_id")
    items = [p for p in db.plan_phases.values() if p["treatment_plan_id"] == plan_id]
    status = request.args.get("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    window, pg = paginate(items)
    return ok(serialize_list(window), pagination=pg)


@bp.route("/patients/<patient_id>/treatment-plans/<plan_id>/activate", methods=["POST"])
def activate_plan(patient_id, plan_id):
    _, role = authenticate()
    authorize(role, ["Provider"])
    patient = get_patient_or_404(patient_id)
    plan = leaf_or_404(db.treatment_plans, plan_id, patient_id, "patient_id")
    body = get_json_body()
    # expected_patient_version is required well-formedness (priority 6).
    expected = V.require_int(body, "expected_patient_version")
    # State legality (priority 7).
    if plan["status"] != "PROPOSED":
        raise err("ERR_INVALID_STATE", "Plan is not PROPOSED")
    # OCC (priority 8).
    if expected != patient["version"]:
        raise err("ERR_STALE_PATIENT_VERSION", "Stale patient version")
    # Dismissed guard (priority 9).
    _guard_not_dismissed(patient)
    # Active-plan uniqueness (priority 18).
    for p in db.treatment_plans.values():
        if p["patient_id"] == patient_id and p["status"] == "ACTIVE":
            raise err("ERR_ACTIVE_PLAN_EXISTS", "Patient already has an ACTIVE plan")
    # Plan readiness (priority 19): exam FINALIZED + at least one phase.
    exam = db.exam_records.get(plan["exam_record_id"])
    if exam is None or exam["status"] != "FINALIZED":
        raise err("ERR_PLAN_NOT_READY", "Referenced exam is not FINALIZED")
    phases = [p for p in db.plan_phases.values() if p["treatment_plan_id"] == plan_id]
    if not phases:
        raise err("ERR_PLAN_NOT_READY", "Plan has no phases")

    plan["status"] = "ACTIVE"
    lowest = min(phases, key=lambda p: p["sequence_index"])
    lowest["status"] = "IN_PROGRESS"
    touch(lowest)
    plan["current_phase"] = lowest["phase_type"]
    touch(plan)
    patient["version"] += 1
    patient["updated_at"] = db.now_iso()
    return ok(serialize(plan))


@bp.route("/patients/<patient_id>/treatment-plans/<plan_id>/discontinue", methods=["POST"])
def discontinue(patient_id, plan_id):
    _, role = authenticate()
    authorize(role, ["Provider", "PracticeAdmin"])
    get_patient_or_404(patient_id)
    plan = leaf_or_404(db.treatment_plans, plan_id, patient_id, "patient_id")
    if plan["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Plan is not ACTIVE")
    discontinue_plan(plan)
    return ok(serialize(plan))


@bp.route("/patients/<patient_id>/treatment-plans/<plan_id>/re-exam-regress", methods=["POST"])
def regress(patient_id, plan_id):
    _, role = authenticate()
    authorize(role, ["Provider"])
    patient = get_patient_or_404(patient_id)
    plan = leaf_or_404(db.treatment_plans, plan_id, patient_id, "patient_id")
    body = get_json_body()
    exam_record_id = V.require_str(body, "exam_record_id")
    plan_phase_id = V.require_str(body, "plan_phase_id")
    exam = ref_or_404(db.exam_records, exam_record_id)
    phase = ref_or_404(db.plan_phases, plan_phase_id)
    _guard_not_dismissed(patient)

    # Regression eligibility (priority 21): CORRECTIVE phase IN_PROGRESS,
    # FINALIZED RE_EXAM with severity >= threshold.
    if phase["treatment_plan_id"] != plan_id:
        raise err("ERR_REGRESSION_NOT_ALLOWED", "Phase does not belong to this plan")
    if phase["phase_type"] != "CORRECTIVE" or phase["status"] != "IN_PROGRESS":
        raise err("ERR_REGRESSION_NOT_ALLOWED", "Phase is not a CORRECTIVE phase IN_PROGRESS")
    if exam["status"] != "FINALIZED" or exam["exam_type"] != "RE_EXAM" \
            or exam["severity_score"] < REGRESSION_SEVERITY_THRESHOLD:
        raise err("ERR_REGRESSION_NOT_ALLOWED", "Re-exam does not justify regression")

    # CORRECTIVE phase -> PENDING.
    phase["status"] = "PENDING"
    touch(phase)
    # Lowest sequence_index ACUTE phase that COMPLETED -> IN_PROGRESS, counters reset.
    acute_completed = sorted(
        [p for p in db.plan_phases.values()
         if p["treatment_plan_id"] == plan_id
         and p["phase_type"] == "ACUTE" and p["status"] == "COMPLETED"],
        key=lambda p: p["sequence_index"],
    )
    if acute_completed:
        acute = acute_completed[0]
        acute["status"] = "IN_PROGRESS"
        acute["visits_completed"] = 0
        touch(acute)
        plan["current_phase"] = "ACUTE"
        touch(plan)
        regen_phase_id = acute["id"]
    else:
        plan["current_phase"] = "ACUTE"
        touch(plan)
        regen_phase_id = None

    _regenerate_series(plan, phase, regen_phase_id)
    return ok(serialize(plan))


def _regenerate_series(plan, corrective_phase, acute_phase_id):
    """REGENERATE the SCHEDULED series for the regressed phases and materialize a
    fresh series at the acute frequency, re-reserving cap slots (PRD §3.4).
    """
    from services.series import generate_series_internal
    from services.plans import cancel_release_appointment

    target_phase_ids = {corrective_phase["id"]}
    if acute_phase_id:
        target_phase_ids.add(acute_phase_id)

    regenerated = []
    for s in db.appointment_series.values():
        if s["treatment_plan_id"] != plan["id"]:
            continue
        if s["status"] != "SCHEDULED":
            continue
        if s["plan_phase_id"] in target_phase_ids:
            s["status"] = "REGENERATED"
            touch(s)
            for appt in db.appointments.values():
                if appt.get("appointment_series_id") == s["id"]:
                    cancel_release_appointment(appt)
            regenerated.append(s)

    if acute_phase_id is None:
        return
    acute = db.plan_phases.get(acute_phase_id)
    template = next((s for s in regenerated if s["plan_phase_id"] == acute_phase_id), None)
    if template is None:
        template = next((s for s in regenerated), None)
    if template is None:
        return
    generate_series_internal(
        plan=plan,
        plan_phase=acute,
        provider_id=template["provider_id"],
        treatment_room_id=template["treatment_room_id"],
        start_date=template["start_date"],
        weekday_pattern=template["weekday_pattern"],
        start_time_minutes=template["start_time_minutes"],
        duration_minutes=template["duration_minutes"],
        insurance_policy_id=template.get("insurance_policy_id"),
    )
