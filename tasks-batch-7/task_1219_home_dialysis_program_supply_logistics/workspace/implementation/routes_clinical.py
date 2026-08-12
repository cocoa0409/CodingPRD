"""Treatment logs and clinical reviews."""
from flask import Blueprint, request

import db
import errors
import services as svc
from middleware import require_roles, ALL_ROLES, check_patient_ownership
from response import success_obj, success_list, paginate
from routes_programs import body, require_fields, get_or_404

bp = Blueprint("clinical", __name__)
S = db.STORES


def _validate_consumption(program, consumption):
    if not isinstance(consumption, list):
        raise errors.err_invalid_request("consumption must be an array")
    catalog = svc.catalog_map(program)
    for line in consumption:
        if not isinstance(line, dict):
            raise errors.err_invalid_request("consumption line must be an object")
        if line.get("sku") not in catalog:
            raise errors.err_invalid_request(f"unknown sku: {line.get('sku')}")
        units = line.get("units")
        if not isinstance(units, int) or isinstance(units, bool) or units < 1:
            raise errors.err_invalid_request("consumption units must be >= 1")


# ---------------------------------------------------------------------------
# treatment logs
# ---------------------------------------------------------------------------

@bp.route("/api/treatment-logs", methods=["POST"])
@require_roles("Patient")
def create_log(_user_id, _role):
    p = require_fields(body(), ["patient_id", "machine_id", "treatment_date",
                                "duration_minutes", "consumption"])
    check_patient_ownership(_user_id, _role, p["patient_id"])
    patient = get_or_404("patients", p["patient_id"])
    machine = get_or_404("dialysis_machines", p["machine_id"])
    tdate = svc.parse_date(p["treatment_date"])
    if tdate is None:
        raise errors.err_invalid_request("treatment_date must be YYYY-MM-DD")
    dur = p["duration_minutes"]
    if not isinstance(dur, int) or isinstance(dur, bool) or not (30 <= dur <= 600):
        raise errors.err_invalid_request("duration_minutes must be 30..600")
    program = get_or_404("dialysis_programs", patient["program_id"])
    _validate_consumption(program, p["consumption"])
    # temporal
    if tdate > db.now().date():
        raise errors.ApiError("ERR_LOG_DATE_IN_FUTURE", 422,
                              "treatment_date is in the future")
    # uniqueness
    for l in S["treatment_logs"].values():
        if l["patient_id"] == patient["id"] and l["treatment_date"] == tdate.isoformat():
            raise errors.ApiError("ERR_DUPLICATE_TREATMENT_DATE", 409,
                                  "A log already exists for this patient and date")
    # referential: patient ACTIVE_HOME; machine assigned to this patient
    if patient["program_status"] != "ACTIVE_HOME":
        raise errors.ApiError("ERR_PATIENT_NOT_ACTIVE_HOME", 409,
                              "Patient is not ACTIVE_HOME")
    if not (machine["status"] == "ASSIGNED"
            and machine.get("assigned_patient_id") == patient["id"]):
        raise errors.ApiError("ERR_MACHINE_NOT_ASSIGNED_TO_PATIENT", 409,
                              "Machine is not ASSIGNED to this patient")
    consumption_units = sum(int(l["units"]) for l in p["consumption"])
    svc.patient_view(patient, recompute=False)
    if consumption_units > patient["on_hand_units"]:
        raise errors.ApiError("ERR_QUANTITY_EXCEEDS_ON_HAND", 422,
                              "consumption exceeds on_hand_units")
    rec = {
        "patient_id": patient["id"],
        "machine_id": machine["id"],
        "treatment_date": tdate.isoformat(),
        "duration_minutes": dur,
        "consumption": [{"sku": l["sku"], "units": l["units"]} for l in p["consumption"]],
        "consumption_units": consumption_units,
        "flag_note": None,
        "status": "SUBMITTED",
    }
    db.stamp_new(rec)
    S["treatment_logs"][rec["id"]] = rec
    svc.patient_view(patient)  # on_hand debit + posture recompute
    svc.review_cadence_trigger(patient)
    return success_obj(rec, 201)


@bp.route("/api/patients/<pid>/treatment-logs", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_patient_logs(pid, _user_id, _role):
    get_or_404("patients", pid)
    rows = [l for l in S["treatment_logs"].values() if l["patient_id"] == pid]
    status = request.args.get("status")
    tdate = request.args.get("treatment_date")
    if status:
        rows = [r for r in rows if r["status"] == status]
    if tdate:
        rows = [r for r in rows if r["treatment_date"] == tdate]
    rows.sort(key=lambda r: (r["created_at"], r.get("_seq", 0)))
    items, limit, offset, total = paginate(rows, request.args)
    return success_list(items, limit, offset, total)


@bp.route("/api/treatment-logs/<lid>/mark-reviewed", methods=["POST"])
@require_roles("HomeNurse")
def mark_reviewed(lid, _user_id, _role):
    log = get_or_404("treatment_logs", lid)
    if log["status"] != "SUBMITTED":
        raise errors.ApiError("ERR_LOG_INVALID_STATE", 409,
                              "Log is not SUBMITTED")
    log["status"] = "REVIEWED"
    db.touch(log)
    return success_obj(log)


@bp.route("/api/treatment-logs/<lid>/flag", methods=["POST"])
@require_roles("HomeNurse")
def flag_log(lid, _user_id, _role):
    log = get_or_404("treatment_logs", lid)
    if log["status"] != "SUBMITTED":
        raise errors.ApiError("ERR_LOG_INVALID_STATE", 409,
                              "Log is not SUBMITTED")
    p = require_fields(body(), ["flag_note"])
    if not isinstance(p["flag_note"], str) or not p["flag_note"].strip():
        raise errors.err_invalid_request("flag_note must be non-empty")
    log["flag_note"] = p["flag_note"]
    log["status"] = "FLAGGED"
    db.touch(log)
    return success_obj(log)


@bp.route("/api/treatment-logs/<lid>/amend", methods=["POST"])
@require_roles("Patient")
def amend_log(lid, _user_id, _role):
    log = get_or_404("treatment_logs", lid)
    check_patient_ownership(_user_id, _role, log["patient_id"])
    if log["status"] != "FLAGGED":
        raise errors.ApiError("ERR_LOG_INVALID_STATE", 409,
                              "Log is not FLAGGED")
    p = body()
    patient = get_or_404("patients", log["patient_id"])
    program = get_or_404("dialysis_programs", patient["program_id"])
    new_duration = log["duration_minutes"]
    if "duration_minutes" in p and p["duration_minutes"] is not None:
        new_duration = p["duration_minutes"]
        if not isinstance(new_duration, int) or isinstance(new_duration, bool) \
                or not (30 <= new_duration <= 600):
            raise errors.err_invalid_request("duration_minutes must be 30..600")
    new_consumption = log["consumption"]
    if "consumption" in p and p["consumption"] is not None:
        _validate_consumption(program, p["consumption"])
        new_consumption = [{"sku": l["sku"], "units": l["units"]}
                           for l in p["consumption"]]
    new_units = sum(int(l["units"]) for l in new_consumption)
    old_units = log["consumption_units"]
    # restore-then-subtract: net increase must fit on-hand
    svc.patient_view(patient, recompute=False)
    if new_units - old_units > patient["on_hand_units"]:
        raise errors.ApiError("ERR_QUANTITY_EXCEEDS_ON_HAND", 422,
                              "amendment delta exceeds on_hand_units")
    log["duration_minutes"] = new_duration
    log["consumption"] = new_consumption
    log["consumption_units"] = new_units
    log["flag_note"] = None
    log["status"] = "SUBMITTED"
    db.touch(log)
    svc.patient_view(patient)
    return success_obj(log)


# ---------------------------------------------------------------------------
# clinical reviews
# ---------------------------------------------------------------------------

@bp.route("/api/patients/<pid>/clinical-reviews", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_patient_reviews(pid, _user_id, _role):
    get_or_404("patients", pid)
    rows = [r for r in S["clinical_reviews"].values() if r["patient_id"] == pid]
    status = request.args.get("status")
    reason = request.args.get("due_reason")
    if status:
        rows = [r for r in rows if r["status"] == status]
    if reason:
        rows = [r for r in rows if r["due_reason"] == reason]
    rows.sort(key=lambda r: (r["created_at"], r.get("_seq", 0)))
    items, limit, offset, total = paginate(rows, request.args)
    return success_list(items, limit, offset, total)


@bp.route("/api/clinical-reviews/<rid>/sign-off", methods=["POST"])
@require_roles("Nephrologist")
def sign_off_review(rid, _user_id, _role):
    review = get_or_404("clinical_reviews", rid)
    if review["status"] != "PENDING":
        raise errors.ApiError("ERR_REVIEW_NOT_PENDING", 409,
                              "Review is not PENDING")
    p = require_fields(body(), ["outcome"])
    if p["outcome"] not in ("CONTINUE", "MODIFY_PRESCRIPTION",
                            "REQUIRE_RETRAINING", "RECOMMEND_TRANSITION"):
        raise errors.err_invalid_request("invalid outcome")
    start, end = svc.parse_date(review["period_start"]), svc.parse_date(review["period_end"])
    for l in S["treatment_logs"].values():
        if l["patient_id"] != review["patient_id"]:
            continue
        d = svc.parse_date(l["treatment_date"])
        if d is not None and start <= d <= end and l["status"] in ("SUBMITTED", "FLAGGED"):
            raise errors.ApiError("ERR_UNREVIEWED_LOGS_REMAIN", 409,
                                  "Unreviewed logs remain in the review period")
    patient = get_or_404("patients", review["patient_id"])
    review["outcome"] = p["outcome"]
    review["signed_off_at"] = db.iso(db.now())
    review["adherence_rolling_pct"] = svc.compute_adherence_rolling_pct(patient)
    review["status"] = "SIGNED_OFF"
    db.touch(review)
    patient["waste_alert_active"] = False
    if p["outcome"] == "REQUIRE_RETRAINING":
        patient["retraining_required"] = True
    db.touch(patient)
    svc.patient_view(patient)
    return success_obj(review)


@bp.route("/api/clinical-reviews/<rid>/escalate", methods=["POST"])
@require_roles("HomeNurse", "Nephrologist")
def escalate_review(rid, _user_id, _role):
    review = get_or_404("clinical_reviews", rid)
    if review["status"] != "PENDING":
        raise errors.ApiError("ERR_REVIEW_NOT_PENDING", 409,
                              "Review is not PENDING")
    review["status"] = "ESCALATED"
    db.touch(review)
    patient = get_or_404("patients", review["patient_id"])
    # cascade: open non-approved orders cancelled (APPROVED untouched)
    for o in S["supply_orders"].values():
        if (o["patient_id"] == patient["id"]
                and o["order_status"] in ("DRAFT", "SUBMITTED", "CHANGES_REQUESTED")):
            svc.cancel_order_cascade(o)
    svc.patient_view(patient)
    return success_obj(review)
