"""Transition records (home-to-center reason coding)."""
from datetime import timedelta

from flask import Blueprint, request

import db
import errors
import services as svc
from middleware import require_roles, ALL_ROLES, check_patient_ownership
from response import success_obj, success_list, paginate
from routes_programs import body, require_fields, get_or_404

bp = Blueprint("transitions", __name__)
S = db.STORES

REASON_CODES = ["PATIENT_CHOICE", "MEDICAL_COMPLICATION", "SUPPLY_FAILURE",
                "MACHINE_FAILURE", "HOME_UNSUITABLE", "TRAINING_INCOMPLETE",
                "NON_ADHERENCE"]


@bp.route("/api/transition-records", methods=["POST"])
@require_roles("Patient", "Nephrologist")
def create_transition(_user_id, _role):
    p = require_fields(body(), ["patient_id", "direction", "reason_code",
                                "effective_from"])
    check_patient_ownership(_user_id, _role, p["patient_id"])
    patient = get_or_404("patients", p["patient_id"])
    if p["direction"] not in ("HOME_TO_CENTER", "CENTER_TO_HOME"):
        raise errors.err_invalid_request("invalid direction")
    if p["reason_code"] not in REASON_CODES:
        raise errors.err_invalid_request("invalid reason_code")
    eff_from = svc.parse_date(p["effective_from"])
    if eff_from is None:
        raise errors.err_invalid_request("effective_from must be YYYY-MM-DD")
    effective_to = p.get("effective_to")
    eff_to = None
    if effective_to is not None:
        eff_to = svc.parse_date(effective_to)
        if eff_to is None:
            raise errors.err_invalid_request("effective_to must be YYYY-MM-DD")
    reversal_of_id = p.get("reversal_of_id")
    reversal_target = None
    if reversal_of_id is not None:
        reversal_target = get_or_404("transition_records", reversal_of_id)

    # shape rules (ERR_INVALID_EFFECTIVE_RANGE)
    if p["direction"] == "CENTER_TO_HOME" and effective_to is not None:
        raise errors.ApiError("ERR_INVALID_EFFECTIVE_RANGE", 400,
                              "effective_to must be null for CENTER_TO_HOME")
    if p["direction"] == "HOME_TO_CENTER" and eff_to is not None and eff_to <= eff_from:
        raise errors.ApiError("ERR_INVALID_EFFECTIVE_RANGE", 400,
                              "effective_to must be > effective_from")
    if p["direction"] == "CENTER_TO_HOME" and reversal_of_id is None:
        raise errors.ApiError("ERR_REVERSAL_TARGET_REQUIRED", 400,
                              "CENTER_TO_HOME requires reversal_of_id")

    # clinical safety: MEDICAL_COMPLICATION only by Nephrologist
    if p["reason_code"] == "MEDICAL_COMPLICATION" and _role != "Nephrologist":
        raise errors.ApiError("ERR_REASON_REQUIRES_PHYSICIAN", 403,
                              "MEDICAL_COMPLICATION requires a Nephrologist")

    # uniqueness: one open HOME_TO_CENTER
    if p["direction"] == "HOME_TO_CENTER":
        for tr in S["transition_records"].values():
            if (tr["patient_id"] == patient["id"]
                    and tr["direction"] == "HOME_TO_CENTER"
                    and tr["status"] in ("REQUESTED", "APPROVED", "ACTIVE")):
                raise errors.ApiError("ERR_OPEN_TRANSITION_EXISTS", 409,
                                      "An open HOME_TO_CENTER transition exists")

    # reversal target validity
    if p["direction"] == "CENTER_TO_HOME":
        svc.lazy_eval_transition(reversal_target)
        if not (reversal_target["patient_id"] == patient["id"]
                and reversal_target["direction"] == "HOME_TO_CENTER"
                and reversal_target["status"] == "ACTIVE"):
            raise errors.ApiError("ERR_REVERSAL_TARGET_INVALID", 409,
                                  "reversal_of_id must reference an ACTIVE HOME_TO_CENTER of this patient")

    # substantiation
    if p["reason_code"] == "MACHINE_FAILURE":
        machine = svc.assigned_machine(patient["id"])
        ok = False
        if machine is not None:
            for e in S["maintenance_events"].values():
                if (e["machine_id"] == machine["id"] and e["event_type"] == "REPAIR"
                        and e["status"] in ("IN_PROGRESS", "COMPLETED")):
                    we = svc.parse_dt(e["window_end"])
                    if we is not None and we >= db.now() - timedelta(days=30):
                        ok = True
                        break
        if not ok:
            raise errors.ApiError("ERR_REASON_NOT_SUBSTANTIATED", 409,
                                  "MACHINE_FAILURE not substantiated")
    elif p["reason_code"] == "SUPPLY_FAILURE":
        ok = False
        for a in S["delivery_appointments"].values():
            if a["status"] != "FAILED":
                continue
            order = get_or_404("supply_orders", a["supply_order_id"])
            if order["patient_id"] != patient["id"]:
                continue
            ws = svc.parse_dt(a["window_start"])
            if ws is not None and ws >= db.now() - timedelta(days=30):
                ok = True
                break
        if not ok:
            raise errors.ApiError("ERR_REASON_NOT_SUBSTANTIATED", 409,
                                  "SUPPLY_FAILURE not substantiated")
    elif p["reason_code"] == "TRAINING_INCOMPLETE":
        svc.patient_view(patient)
        if patient["posture"] != "NOT_READY":
            raise errors.ApiError("ERR_REASON_NOT_SUBSTANTIATED", 409,
                                  "TRAINING_INCOMPLETE requires posture NOT_READY")

    rec = {
        "patient_id": patient["id"],
        "reversal_of_id": reversal_of_id,
        "direction": p["direction"],
        "reason_code": p["reason_code"],
        "effective_from": eff_from.isoformat(),
        "effective_to": eff_to.isoformat() if eff_to else None,
        "status": "REQUESTED",
    }
    db.stamp_new(rec)
    S["transition_records"][rec["id"]] = rec
    return success_obj(rec, 201)


@bp.route("/api/transition-records/<tid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_transition(tid, _user_id, _role):
    return success_obj(svc.lazy_eval_transition(get_or_404("transition_records", tid)))


@bp.route("/api/patients/<pid>/transition-records", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_patient_transitions(pid, _user_id, _role):
    get_or_404("patients", pid)
    rows = [svc.lazy_eval_transition(t) for t in S["transition_records"].values()
            if t["patient_id"] == pid]
    status = request.args.get("status")
    direction = request.args.get("direction")
    if status:
        rows = [r for r in rows if r["status"] == status]
    if direction:
        rows = [r for r in rows if r["direction"] == direction]
    rows.sort(key=lambda r: (r["created_at"], r.get("_seq", 0)))
    items, limit, offset, total = paginate(rows, request.args)
    return success_list(items, limit, offset, total)


@bp.route("/api/transition-records/<tid>/reversals", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_reversals(tid, _user_id, _role):
    get_or_404("transition_records", tid)
    rows = [t for t in S["transition_records"].values()
            if t.get("reversal_of_id") == tid and t["direction"] == "CENTER_TO_HOME"]
    rows.sort(key=lambda r: (r["created_at"], r.get("_seq", 0)))
    items, limit, offset, total = paginate(rows, request.args)
    return success_list(items, limit, offset, total)


@bp.route("/api/transition-records/<tid>/approve", methods=["POST"])
@require_roles("Nephrologist")
def approve_transition(tid, _user_id, _role):
    rec = get_or_404("transition_records", tid)
    if rec["status"] != "REQUESTED":
        raise errors.ApiError("ERR_TRANSITION_INVALID_STATE", 409,
                              "Transition is not REQUESTED")
    rec["status"] = "APPROVED"
    db.touch(rec)
    return success_obj(rec)


@bp.route("/api/transition-records/<tid>/deny", methods=["POST"])
@require_roles("Nephrologist")
def deny_transition(tid, _user_id, _role):
    rec = get_or_404("transition_records", tid)
    if rec["status"] != "REQUESTED":
        raise errors.ApiError("ERR_TRANSITION_INVALID_STATE", 409,
                              "Transition is not REQUESTED")
    rec["status"] = "DENIED"
    db.touch(rec)
    return success_obj(rec)


@bp.route("/api/transition-records/<tid>/activate", methods=["POST"])
@require_roles("Nephrologist")
def activate_transition(tid, _user_id, _role):
    rec = get_or_404("transition_records", tid)
    if rec["status"] != "APPROVED":
        raise errors.ApiError("ERR_TRANSITION_INVALID_STATE", 409,
                              "Transition is not APPROVED")
    patient = get_or_404("patients", rec["patient_id"])
    svc.lazy_eval_patient_scoped(patient["id"])
    # temporal: effective_from reached
    if svc.parse_date(rec["effective_from"]) > db.now().date():
        raise errors.ApiError("ERR_TRANSITION_EFFECTIVE_IN_FUTURE", 409,
                              "effective_from is in the future")
    # referential: patient state compatibility
    if rec["direction"] == "HOME_TO_CENTER":
        if patient["program_status"] not in ("ACTIVE_HOME", "SUSPENDED"):
            raise errors.ApiError("ERR_PATIENT_STATE_BLOCKS_TRANSITION", 409,
                                  "HOME_TO_CENTER requires ACTIVE_HOME or SUSPENDED")
    else:  # CENTER_TO_HOME
        if patient["program_status"] != "SUSPENDED":
            raise errors.ApiError("ERR_PATIENT_STATE_BLOCKS_TRANSITION", 409,
                                  "CENTER_TO_HOME requires SUSPENDED")
        gates = svc.readiness_gates(patient)
        if not all(gates.values()):
            raise errors.ApiError("ERR_READINESS_GATES_NOT_MET", 409,
                                  "One or more readiness gates fail")

    rec["status"] = "ACTIVE"
    db.touch(rec)

    if rec["direction"] == "HOME_TO_CENTER":
        permanent = rec.get("effective_to") is None
        svc.transition_cascade(patient, permanent)
        patient["program_status"] = ("TRANSITIONED_OUT" if permanent else "SUSPENDED")
        db.touch(patient)
    else:
        # reversal: patient SUSPENDED -> ACTIVE_HOME; reversed record -> REVERSED
        patient["program_status"] = "ACTIVE_HOME"
        db.touch(patient)
        target = get_or_404("transition_records", rec["reversal_of_id"])
        if target["status"] == "ACTIVE":
            target["status"] = "REVERSED"
            db.touch(target)
    svc.patient_view(patient)
    return success_obj(rec)
