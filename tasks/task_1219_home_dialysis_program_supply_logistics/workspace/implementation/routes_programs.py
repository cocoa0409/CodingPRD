"""Programs, clock, patients, training, assessments, work orders."""
from flask import Blueprint, request

import db
import errors
import services as svc
from middleware import require_roles, ALL_ROLES, check_patient_ownership
from response import success_obj, success_list, paginate

bp = Blueprint("programs", __name__)
S = db.STORES


def body():
    return request.get_json(silent=True) or {}


def require_fields(payload, fields):
    for f in fields:
        if f not in payload or payload[f] is None:
            raise errors.err_invalid_request(f"Missing required field: {f}")
    return payload


def get_or_404(store, rid):
    rec = S[store].get(rid)
    if rec is None:
        raise errors.err_not_found()
    return rec


# ---------------------------------------------------------------------------
# programs & clock
# ---------------------------------------------------------------------------

@bp.route("/api/dialysis-programs", methods=["POST"])
@require_roles("ProgramAdmin")
def create_program(_user_id, _role):
    p = require_fields(body(), ["name", "review_cadence_treatments",
                                "max_missed_log_streak",
                                "waste_ratio_alert_threshold", "supply_catalog"])
    if not isinstance(p["review_cadence_treatments"], int) or p["review_cadence_treatments"] < 1:
        raise errors.err_invalid_request("review_cadence_treatments must be >= 1")
    if not isinstance(p["max_missed_log_streak"], int) or p["max_missed_log_streak"] < 1:
        raise errors.err_invalid_request("max_missed_log_streak must be >= 1")
    thr = p["waste_ratio_alert_threshold"]
    if not isinstance(thr, (int, float)) or isinstance(thr, bool) or not (0 < thr <= 1):
        raise errors.err_invalid_request("waste_ratio_alert_threshold must be in (0, 1]")
    if not isinstance(p["supply_catalog"], list):
        raise errors.err_invalid_request("supply_catalog must be an array")
    seen = set()
    for entry in p["supply_catalog"]:
        if not isinstance(entry, dict) or "sku" not in entry:
            raise errors.err_invalid_request("catalog entries require sku")
        if entry["sku"] in seen:
            raise errors.err_invalid_request("duplicate sku in supply_catalog")
        seen.add(entry["sku"])
    rec = {
        "name": p["name"],
        "review_cadence_treatments": p["review_cadence_treatments"],
        "max_missed_log_streak": p["max_missed_log_streak"],
        "waste_ratio_alert_threshold": thr,
        "supply_catalog": p["supply_catalog"],
    }
    db.stamp_new(rec)
    S["dialysis_programs"][rec["id"]] = rec
    return success_obj(rec, 201)


@bp.route("/api/dialysis-programs/<pid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_program(pid, _user_id, _role):
    return success_obj(get_or_404("dialysis_programs", pid))


@bp.route("/api/_clock/set_current_utc", methods=["POST"])
@require_roles("ProgramAdmin")
def set_clock(_user_id, _role):
    p = require_fields(body(), ["to_iso8601"])
    dt = svc.parse_dt(p["to_iso8601"])
    if dt is None:
        raise errors.err_invalid_request("to_iso8601 is not a valid ISO 8601 datetime")
    db.set_now(dt)
    return success_obj({"current_utc": db.iso(db.now())})


@bp.route("/api/dialysis-programs/<pid>/patients", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_program_patients(pid, _user_id, _role):
    get_or_404("dialysis_programs", pid)
    rows = [svc.patient_view(p) for p in S["patients"].values()
            if p["program_id"] == pid]
    posture = request.args.get("posture")
    pstatus = request.args.get("program_status")
    if posture:
        rows = [r for r in rows if r["posture"] == posture]
    if pstatus:
        rows = [r for r in rows if r["program_status"] == pstatus]
    rows.sort(key=lambda r: (r["created_at"], r.get("_seq", 0)))
    items, limit, offset, total = paginate(rows, request.args)
    return success_list(items, limit, offset, total)


@bp.route("/api/dialysis-programs/<pid>/dialysis-machines", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_program_machines(pid, _user_id, _role):
    get_or_404("dialysis_programs", pid)
    rows = [svc.machine_view(m) for m in S["dialysis_machines"].values()
            if m["program_id"] == pid]
    status = request.args.get("status")
    assigned = request.args.get("assigned_patient_id")
    if status:
        rows = [r for r in rows if r["status"] == status]
    if assigned:
        rows = [r for r in rows if r.get("assigned_patient_id") == assigned]
    rows.sort(key=lambda r: (r["created_at"], r.get("_seq", 0)))
    items, limit, offset, total = paginate(rows, request.args)
    return success_list(items, limit, offset, total)


@bp.route("/api/dialysis-programs/<pid>/in-center-chairs", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_program_chairs(pid, _user_id, _role):
    get_or_404("dialysis_programs", pid)
    rows = [c for c in S["in_center_chairs"].values() if c["program_id"] == pid]
    in_service = request.args.get("in_service")
    if in_service is not None and in_service != "":
        want = in_service.lower() == "true"
        rows = [r for r in rows if r["in_service"] == want]
    rows.sort(key=lambda r: (r["created_at"], r.get("_seq", 0)))
    items, limit, offset, total = paginate(rows, request.args)
    return success_list(items, limit, offset, total)


# ---------------------------------------------------------------------------
# patients
# ---------------------------------------------------------------------------

@bp.route("/api/patients", methods=["POST"])
@require_roles("HomeNurse")
def create_patient(_user_id, _role):
    p = require_fields(body(), ["program_id", "full_name",
                                "prescription_treatments_per_week",
                                "prescription_units_per_treatment"])
    get_or_404("dialysis_programs", p["program_id"])
    tpw = p["prescription_treatments_per_week"]
    upt = p["prescription_units_per_treatment"]
    if not isinstance(tpw, int) or isinstance(tpw, bool) or not (1 <= tpw <= 7):
        raise errors.err_invalid_request("prescription_treatments_per_week must be 1..7")
    if not isinstance(upt, int) or isinstance(upt, bool) or upt < 1:
        raise errors.err_invalid_request("prescription_units_per_treatment must be >= 1")
    rec = {
        "program_id": p["program_id"],
        "full_name": p["full_name"],
        "prescription_treatments_per_week": tpw,
        "prescription_units_per_treatment": upt,
        "program_status": "TRAINING",
        "ever_home_ready": False,
        "retraining_required": False,
        "waste_alert_active": False,
        "no_show_count": 0,
        "posture": "NOT_READY",
        "storage_cap_units": 0,
        "on_hand_units": 0,
        "missed_log_streak": 0,
    }
    db.stamp_new(rec)
    S["patients"][rec["id"]] = rec
    return success_obj(svc.patient_view(rec), 201)


@bp.route("/api/patients/<pid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_patient(pid, _user_id, _role):
    return success_obj(svc.patient_view(get_or_404("patients", pid)))


@bp.route("/api/patients/<pid>/prescription", methods=["PATCH"])
@require_roles("Nephrologist")
def patch_prescription(pid, _user_id, _role):
    patient = get_or_404("patients", pid)
    p = body()
    if "prescription_treatments_per_week" in p and p["prescription_treatments_per_week"] is not None:
        v = p["prescription_treatments_per_week"]
        if not isinstance(v, int) or isinstance(v, bool) or not (1 <= v <= 7):
            raise errors.err_invalid_request("prescription_treatments_per_week must be 1..7")
        patient["prescription_treatments_per_week"] = v
    if "prescription_units_per_treatment" in p and p["prescription_units_per_treatment"] is not None:
        v = p["prescription_units_per_treatment"]
        if not isinstance(v, int) or isinstance(v, bool) or v < 1:
            raise errors.err_invalid_request("prescription_units_per_treatment must be >= 1")
        patient["prescription_units_per_treatment"] = v
    db.touch(patient)
    return success_obj(svc.patient_view(patient))


@bp.route("/api/patients/<pid>/activate", methods=["POST"])
@require_roles("Nephrologist")
def activate_patient(pid, _user_id, _role):
    patient = get_or_404("patients", pid)
    if patient["program_status"] != "TRAINING":
        raise errors.err_patient_invalid_state()
    svc.lazy_eval_patient_scoped(pid)
    # gates in pinned order: training -> assessment -> machine -> plan
    if not svc.cert_current(pid):
        raise errors.ApiError("ERR_TRAINING_INCOMPLETE", 409,
                              "Some module lacks a current SIGNED_OFF passing attempt")
    if not svc.assessment_current(pid):
        raise errors.ApiError("ERR_ASSESSMENT_NOT_CURRENT", 409,
                              "No ACCEPTED assessment within 730 days")
    if svc.assigned_machine(pid) is None:
        raise errors.ApiError("ERR_NO_MACHINE_ASSIGNED", 409,
                              "No ASSIGNED machine for the patient")
    if svc.active_plan(pid) is None:
        raise errors.ApiError("ERR_NO_ACTIVE_PLAN", 409,
                              "No ACTIVE emergency backup plan")
    patient["program_status"] = "ACTIVE_HOME"
    patient["ever_home_ready"] = True
    db.touch(patient)
    return success_obj(svc.patient_view(patient))


@bp.route("/api/patients/<pid>/suspend", methods=["POST"])
@require_roles("Nephrologist")
def suspend_patient(pid, _user_id, _role):
    patient = get_or_404("patients", pid)
    if patient["program_status"] != "ACTIVE_HOME":
        raise errors.err_patient_invalid_state()
    p = body()
    reason = p.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        raise errors.err_invalid_request("reason must be a non-empty string")
    patient["program_status"] = "SUSPENDED"
    db.touch(patient)
    return success_obj(svc.patient_view(patient))


@bp.route("/api/patients/<pid>/reinstate", methods=["POST"])
@require_roles("Nephrologist")
def reinstate_patient(pid, _user_id, _role):
    patient = get_or_404("patients", pid)
    if patient["program_status"] != "SUSPENDED":
        raise errors.err_patient_invalid_state()
    svc.lazy_eval_patient_scoped(pid)
    for tr in S["transition_records"].values():
        if (tr["patient_id"] == pid and tr["direction"] == "HOME_TO_CENTER"
                and tr["status"] == "ACTIVE"):
            raise errors.ApiError("ERR_ACTIVE_TRANSITION_BLOCKS_REINSTATE", 409,
                                  "An ACTIVE HOME_TO_CENTER transition blocks reinstate")
    gates = svc.readiness_gates(patient)
    if not all(gates.values()):
        raise errors.ApiError("ERR_READINESS_GATES_NOT_MET", 409,
                              "One or more readiness gates fail")
    patient["program_status"] = "ACTIVE_HOME"
    db.touch(patient)
    return success_obj(svc.patient_view(patient))


# ---------------------------------------------------------------------------
# training
# ---------------------------------------------------------------------------

@bp.route("/api/training-attempts", methods=["POST"])
@require_roles("HomeNurse")
def create_attempt(_user_id, _role):
    p = require_fields(body(), ["patient_id", "module_code", "score_pct"])
    get_or_404("patients", p["patient_id"])
    if p["module_code"] not in svc.MODULES:
        raise errors.err_invalid_request("invalid module_code")
    score = p["score_pct"]
    if not isinstance(score, int) or isinstance(score, bool) or not (0 <= score <= 100):
        raise errors.err_invalid_request("score_pct must be 0..100")
    rec = {
        "patient_id": p["patient_id"],
        "module_code": p["module_code"],
        "score_pct": score,
        "trainer_user_id": _user_id,
        "is_passing": score >= svc.MODULE_PASS_PCT,
        "signed_off_by_user_id": None,
        "signed_off_at": None,
        "status": "RECORDED",
    }
    db.stamp_new(rec)
    S["training_attempts"][rec["id"]] = rec
    return success_obj(rec, 201)


@bp.route("/api/training-attempts/<aid>/sign-off", methods=["POST"])
@require_roles("HomeNurse")
def sign_off_attempt(aid, _user_id, _role):
    att = get_or_404("training_attempts", aid)
    if att["status"] != "RECORDED":
        raise errors.ApiError("ERR_ATTEMPT_NOT_RECORDED", 409,
                              "Attempt is not RECORDED")
    if not att["is_passing"]:
        raise errors.ApiError("ERR_ATTEMPT_NOT_PASSING", 409,
                              "Attempt is not passing")
    if _user_id == att["trainer_user_id"]:
        raise errors.ApiError("ERR_SOD_SIGNOFF_BY_TRAINER", 403,
                              "Sign-off nurse is the attempt's trainer")
    att["signed_off_by_user_id"] = _user_id
    att["signed_off_at"] = db.iso(db.now())
    att["status"] = "SIGNED_OFF"
    db.touch(att)
    patient = get_or_404("patients", att["patient_id"])
    if patient.get("retraining_required"):
        patient["retraining_required"] = False
        db.touch(patient)
    svc.patient_view(patient)
    return success_obj(att)


@bp.route("/api/patients/<pid>/training-attempts", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_patient_attempts(pid, _user_id, _role):
    get_or_404("patients", pid)
    rows = [a for a in S["training_attempts"].values() if a["patient_id"] == pid]
    module = request.args.get("module_code")
    status = request.args.get("status")
    if module:
        rows = [r for r in rows if r["module_code"] == module]
    if status:
        rows = [r for r in rows if r["status"] == status]
    rows.sort(key=lambda r: (r["created_at"], r.get("_seq", 0)))
    items, limit, offset, total = paginate(rows, request.args)
    return success_list(items, limit, offset, total)


# ---------------------------------------------------------------------------
# home assessments
# ---------------------------------------------------------------------------

def _compute_assessment(rec):
    cap, result = svc.evaluate_assessment(
        rec["water_chloramine_ppm"], rec["electrical_dedicated_circuit"],
        rec["electrical_voltage_verified"], rec["storage_area_sqft"])
    rec["storage_cap_units"] = cap
    rec["result"] = result


def _validate_measurements(p):
    for f in ["water_chloramine_ppm", "electrical_dedicated_circuit",
              "electrical_voltage_verified", "storage_area_sqft"]:
        if f not in p or p[f] is None:
            raise errors.err_invalid_request(f"Missing required field: {f}")
    ppm = p["water_chloramine_ppm"]
    sqft = p["storage_area_sqft"]
    if not isinstance(ppm, (int, float)) or isinstance(ppm, bool) or ppm < 0:
        raise errors.err_invalid_request("water_chloramine_ppm must be >= 0")
    if not isinstance(p["electrical_dedicated_circuit"], bool):
        raise errors.err_invalid_request("electrical_dedicated_circuit must be boolean")
    if not isinstance(p["electrical_voltage_verified"], bool):
        raise errors.err_invalid_request("electrical_voltage_verified must be boolean")
    if not isinstance(sqft, (int, float)) or isinstance(sqft, bool) or sqft <= 0:
        raise errors.err_invalid_request("storage_area_sqft must be > 0")


@bp.route("/api/home-assessments", methods=["POST"])
@require_roles("HomeNurse")
def create_assessment(_user_id, _role):
    p = require_fields(body(), ["patient_id", "assessment_kind"])
    get_or_404("patients", p["patient_id"])
    if p["assessment_kind"] not in ("INITIAL", "REASSESSMENT", "POST_MODIFICATION"):
        raise errors.err_invalid_request("invalid assessment_kind")
    _validate_measurements(p)
    rec = {
        "patient_id": p["patient_id"],
        "assessment_kind": p["assessment_kind"],
        "water_chloramine_ppm": p["water_chloramine_ppm"],
        "electrical_dedicated_circuit": p["electrical_dedicated_circuit"],
        "electrical_voltage_verified": p["electrical_voltage_verified"],
        "storage_area_sqft": p["storage_area_sqft"],
        "assessed_by_user_id": _user_id,
        "accepted_at": None,
        "status": "SUBMITTED",
    }
    _compute_assessment(rec)
    db.stamp_new(rec)
    S["home_assessments"][rec["id"]] = rec
    return success_obj(rec, 201)


@bp.route("/api/home-assessments/<aid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_assessment(aid, _user_id, _role):
    return success_obj(get_or_404("home_assessments", aid))


@bp.route("/api/patients/<pid>/home-assessments", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_patient_assessments(pid, _user_id, _role):
    get_or_404("patients", pid)
    rows = [a for a in S["home_assessments"].values() if a["patient_id"] == pid]
    status = request.args.get("status")
    if status:
        rows = [r for r in rows if r["status"] == status]
    rows.sort(key=lambda r: (r["created_at"], r.get("_seq", 0)))
    items, limit, offset, total = paginate(rows, request.args)
    return success_list(items, limit, offset, total)


@bp.route("/api/home-assessments/<aid>/accept", methods=["POST"])
@require_roles("HomeNurse")
def accept_assessment(aid, _user_id, _role):
    rec = get_or_404("home_assessments", aid)
    if rec["status"] != "SUBMITTED":
        raise errors.ApiError("ERR_ASSESSMENT_INVALID_STATE", 409,
                              "Assessment is not SUBMITTED")
    if _user_id == rec["assessed_by_user_id"]:
        raise errors.ApiError("ERR_SOD_ASSESSOR_SELF_ACCEPT", 403,
                              "Accept nurse is the assessor")
    if rec["result"] != "PASS":
        raise errors.ApiError("ERR_ASSESSMENT_RESULT_FAIL", 409,
                              "Assessment result is FAIL")
    rec["status"] = "ACCEPTED"
    rec["accepted_at"] = db.iso(db.now())
    db.touch(rec)
    # link 1: supersede other ACCEPTED
    for other in S["home_assessments"].values():
        if (other["patient_id"] == rec["patient_id"] and other["id"] != rec["id"]
                and other["status"] == "ACCEPTED"):
            other["status"] = "SUPERSEDED"
            db.touch(other)
    # link 2: patient storage cap recompute
    patient = get_or_404("patients", rec["patient_id"])
    patient["storage_cap_units"] = rec["storage_cap_units"]
    db.touch(patient)
    # link 3: cap-shrink cascade
    svc.cap_shrink_cascade(patient)
    svc.patient_view(patient)
    return success_obj(rec)


@bp.route("/api/home-assessments/<aid>/require-remediation", methods=["POST"])
@require_roles("HomeNurse")
def require_remediation(aid, _user_id, _role):
    rec = get_or_404("home_assessments", aid)
    if rec["status"] != "SUBMITTED":
        raise errors.ApiError("ERR_ASSESSMENT_INVALID_STATE", 409,
                              "Assessment is not SUBMITTED")
    if _user_id == rec["assessed_by_user_id"]:
        raise errors.ApiError("ERR_SOD_ASSESSOR_SELF_ACCEPT", 403,
                              "Remediation nurse is the assessor")
    rec["status"] = "REMEDIATION_REQUIRED"
    db.touch(rec)
    return success_obj(rec)


@bp.route("/api/home-assessments/<aid>/resubmit", methods=["POST"])
@require_roles("HomeNurse")
def resubmit_assessment(aid, _user_id, _role):
    rec = get_or_404("home_assessments", aid)
    if rec["status"] != "REMEDIATION_REQUIRED":
        raise errors.ApiError("ERR_ASSESSMENT_INVALID_STATE", 409,
                              "Assessment is not REMEDIATION_REQUIRED")
    p = body()
    _validate_measurements(p)
    for wo in S["home_modification_work_orders"].values():
        if (wo["assessment_id"] == aid
                and wo["status"] not in ("INSPECTED_PASS", "CANCELLED")):
            raise errors.ApiError("ERR_WORK_ORDERS_OUTSTANDING", 409,
                                  "Linked work orders are not all settled")
    rec["water_chloramine_ppm"] = p["water_chloramine_ppm"]
    rec["electrical_dedicated_circuit"] = p["electrical_dedicated_circuit"]
    rec["electrical_voltage_verified"] = p["electrical_voltage_verified"]
    rec["storage_area_sqft"] = p["storage_area_sqft"]
    _compute_assessment(rec)
    rec["assessed_by_user_id"] = _user_id
    rec["status"] = "SUBMITTED"
    db.touch(rec)
    return success_obj(rec)


# ---------------------------------------------------------------------------
# home modification work orders
# ---------------------------------------------------------------------------

@bp.route("/api/home-modification-work-orders", methods=["POST"])
@require_roles("HomeNurse")
def create_work_order(_user_id, _role):
    p = require_fields(body(), ["patient_id", "assessment_id", "work_type",
                                "cost_estimate_cents"])
    get_or_404("patients", p["patient_id"])
    get_or_404("home_assessments", p["assessment_id"])
    if p["work_type"] not in ("PLUMBING", "ELECTRICAL", "STORAGE_BUILDOUT"):
        raise errors.err_invalid_request("invalid work_type")
    cost = p["cost_estimate_cents"]
    if not isinstance(cost, int) or isinstance(cost, bool) or cost < 0:
        raise errors.err_invalid_request("cost_estimate_cents must be >= 0")
    rec = {
        "patient_id": p["patient_id"],
        "assessment_id": p["assessment_id"],
        "work_type": p["work_type"],
        "cost_estimate_cents": cost,
        "scheduled_window_start": None,
        "scheduled_window_end": None,
        "final_cost_cents": None,
        "status": "REQUESTED",
    }
    db.stamp_new(rec)
    S["home_modification_work_orders"][rec["id"]] = rec
    return success_obj(rec, 201)


@bp.route("/api/patients/<pid>/home-modification-work-orders", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_patient_work_orders(pid, _user_id, _role):
    get_or_404("patients", pid)
    rows = [w for w in S["home_modification_work_orders"].values()
            if w["patient_id"] == pid]
    status = request.args.get("status")
    wtype = request.args.get("work_type")
    if status:
        rows = [r for r in rows if r["status"] == status]
    if wtype:
        rows = [r for r in rows if r["work_type"] == wtype]
    rows.sort(key=lambda r: (r["created_at"], r.get("_seq", 0)))
    items, limit, offset, total = paginate(rows, request.args)
    return success_list(items, limit, offset, total)


@bp.route("/api/home-assessments/<aid>/home-modification-work-orders", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_assessment_work_orders(aid, _user_id, _role):
    get_or_404("home_assessments", aid)
    rows = [w for w in S["home_modification_work_orders"].values()
            if w["assessment_id"] == aid]
    status = request.args.get("status")
    if status:
        rows = [r for r in rows if r["status"] == status]
    rows.sort(key=lambda r: (r["created_at"], r.get("_seq", 0)))
    items, limit, offset, total = paginate(rows, request.args)
    return success_list(items, limit, offset, total)


@bp.route("/api/home-modification-work-orders/<wid>/approve", methods=["POST"])
@require_roles("ProgramAdmin")
def approve_work_order(wid, _user_id, _role):
    rec = get_or_404("home_modification_work_orders", wid)
    if rec["status"] not in ("REQUESTED", "INSPECTED_FAIL"):
        raise errors.ApiError("ERR_WORK_ORDER_INVALID_STATE", 409,
                              "Work order is not REQUESTED or INSPECTED_FAIL")
    p = require_fields(body(), ["scheduled_window_start", "scheduled_window_end"])
    ws, we = svc.parse_dt(p["scheduled_window_start"]), svc.parse_dt(p["scheduled_window_end"])
    if ws is None or we is None or not (ws < we):
        raise errors.err_invalid_request("scheduled_window_start must be < scheduled_window_end")
    rec["scheduled_window_start"] = db.iso(ws)
    rec["scheduled_window_end"] = db.iso(we)
    rec["status"] = "SCHEDULED"
    db.touch(rec)
    return success_obj(rec)


@bp.route("/api/home-modification-work-orders/<wid>/complete", methods=["POST"])
@require_roles("BiomedTechnician")
def complete_work_order(wid, _user_id, _role):
    rec = get_or_404("home_modification_work_orders", wid)
    if rec["status"] != "SCHEDULED":
        raise errors.ApiError("ERR_WORK_ORDER_INVALID_STATE", 409,
                              "Work order is not SCHEDULED")
    p = require_fields(body(), ["final_cost_cents"])
    cost = p["final_cost_cents"]
    if not isinstance(cost, int) or isinstance(cost, bool) or cost < 0:
        raise errors.err_invalid_request("final_cost_cents must be >= 0")
    rec["final_cost_cents"] = cost
    rec["status"] = "COMPLETED"
    db.touch(rec)
    return success_obj(rec)


@bp.route("/api/home-modification-work-orders/<wid>/inspect", methods=["POST"])
@require_roles("BiomedTechnician")
def inspect_work_order(wid, _user_id, _role):
    rec = get_or_404("home_modification_work_orders", wid)
    if rec["status"] != "COMPLETED":
        raise errors.ApiError("ERR_WORK_ORDER_INVALID_STATE", 409,
                              "Work order is not COMPLETED")
    p = require_fields(body(), ["passed"])
    if not isinstance(p["passed"], bool):
        raise errors.err_invalid_request("passed must be boolean")
    rec["status"] = "INSPECTED_PASS" if p["passed"] else "INSPECTED_FAIL"
    db.touch(rec)
    return success_obj(rec)


@bp.route("/api/home-modification-work-orders/<wid>/cancel", methods=["POST"])
@require_roles("HomeNurse", "ProgramAdmin")
def cancel_work_order(wid, _user_id, _role):
    rec = get_or_404("home_modification_work_orders", wid)
    if rec["status"] not in ("REQUESTED", "SCHEDULED"):
        raise errors.ApiError("ERR_WORK_ORDER_INVALID_STATE", 409,
                              "Work order is not REQUESTED or SCHEDULED")
    rec["status"] = "CANCELLED"
    db.touch(rec)
    return success_obj(rec)
