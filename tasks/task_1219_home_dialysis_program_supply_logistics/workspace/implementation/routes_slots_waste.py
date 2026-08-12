"""In-center chairs, backup slot reservations, waste/return records."""
from flask import Blueprint, request

import db
import errors
import services as svc
from middleware import require_roles, ALL_ROLES, check_patient_ownership
from response import success_obj, success_list, paginate
from routes_programs import body, require_fields, get_or_404

bp = Blueprint("slots_waste", __name__)
S = db.STORES


# ---------------------------------------------------------------------------
# in-center chairs
# ---------------------------------------------------------------------------

@bp.route("/api/in-center-chairs", methods=["POST"])
@require_roles("ProgramAdmin")
def create_chair(_user_id, _role):
    p = require_fields(body(), ["program_id", "chair_code"])
    get_or_404("dialysis_programs", p["program_id"])
    for c in S["in_center_chairs"].values():
        if c["program_id"] == p["program_id"] and c["chair_code"] == p["chair_code"]:
            raise errors.err_invalid_request("chair_code already used within the program")
    rec = {
        "program_id": p["program_id"],
        "chair_code": p["chair_code"],
        "in_service": bool(p.get("in_service", True)),
    }
    db.stamp_new(rec)
    S["in_center_chairs"][rec["id"]] = rec
    return success_obj(rec, 201)


@bp.route("/api/in-center-chairs/<cid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_chair(cid, _user_id, _role):
    return success_obj(get_or_404("in_center_chairs", cid))


@bp.route("/api/in-center-chairs/<cid>", methods=["PATCH"])
@require_roles("ProgramAdmin")
def patch_chair(cid, _user_id, _role):
    chair = get_or_404("in_center_chairs", cid)
    p = require_fields(body(), ["in_service"])
    if not isinstance(p["in_service"], bool):
        raise errors.err_invalid_request("in_service must be boolean")
    chair["in_service"] = p["in_service"]
    db.touch(chair)
    return success_obj(chair)


# ---------------------------------------------------------------------------
# backup slot reservations
# ---------------------------------------------------------------------------

@bp.route("/api/backup-slot-reservations", methods=["POST"])
@require_roles("Patient")
def create_reservation(_user_id, _role):
    p = require_fields(body(), ["patient_id", "chair_id", "slot_start", "slot_end"])
    check_patient_ownership(_user_id, _role, p["patient_id"])
    patient = get_or_404("patients", p["patient_id"])
    chair = get_or_404("in_center_chairs", p["chair_id"])
    start, end = svc.parse_dt(p["slot_start"]), svc.parse_dt(p["slot_end"])
    if start is None or end is None:
        raise errors.err_invalid_request("invalid slot datetimes")
    duration = (end - start).total_seconds() / 60
    if not (end > start) or not (60 <= duration <= 480):
        raise errors.ApiError("ERR_SLOT_DURATION_INVALID", 400,
                              "Slot duration outside 60..480 minutes")
    # temporal
    if start < db.now():
        raise errors.ApiError("ERR_SLOT_IN_PAST", 422, "slot_start is before now")
    # half-open overlap with RESERVED reservations on the same chair
    for r in S["backup_slot_reservations"].values():
        if r["chair_id"] == chair["id"]:
            svc.lazy_eval_reservation(r)
            if r["status"] != "RESERVED":
                continue
            rs, re_ = svc.parse_dt(r["slot_start"]), svc.parse_dt(r["slot_end"])
            if start < re_ and end > rs:  # half-open: adjacency allowed
                raise errors.ApiError("ERR_CHAIR_SLOT_OVERLAP", 409,
                                      "Slot overlaps another reservation on the chair")
    # daily cap 2 per calendar service day
    same_day = 0
    for r in S["backup_slot_reservations"].values():
        if r["patient_id"] == patient["id"]:
            svc.lazy_eval_reservation(r)
            if r["status"] == "RESERVED" and svc.parse_dt(r["slot_start"]).date() == start.date():
                same_day += 1
    if same_day >= 2:
        raise errors.ApiError("ERR_SLOT_DAILY_CAP_EXCEEDED", 422,
                              "Patient already has 2 RESERVED reservations that day")
    # referential: patient ACTIVE_HOME, plan ACTIVE, chair in service
    if patient["program_status"] != "ACTIVE_HOME":
        raise errors.ApiError("ERR_PATIENT_NOT_ACTIVE_HOME", 409,
                              "Patient is not ACTIVE_HOME")
    if svc.active_plan(patient["id"]) is None:
        raise errors.ApiError("ERR_PLAN_NOT_ACTIVE", 409,
                              "No ACTIVE emergency backup plan")
    if not chair["in_service"]:
        raise errors.ApiError("ERR_CHAIR_OUT_OF_SERVICE", 409,
                              "Chair is out of service")
    rec = {
        "patient_id": patient["id"],
        "chair_id": chair["id"],
        "slot_start": db.iso(start),
        "slot_end": db.iso(end),
        "status": "RESERVED",
    }
    db.stamp_new(rec)
    S["backup_slot_reservations"][rec["id"]] = rec
    return success_obj(rec, 201)


@bp.route("/api/patients/<pid>/backup-slot-reservations", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_patient_reservations(pid, _user_id, _role):
    get_or_404("patients", pid)
    rows = [svc.lazy_eval_reservation(r) for r in S["backup_slot_reservations"].values()
            if r["patient_id"] == pid]
    status = request.args.get("status")
    if status:
        rows = [r for r in rows if r["status"] == status]
    rows.sort(key=lambda r: (r["created_at"], r.get("_seq", 0)))
    items, limit, offset, total = paginate(rows, request.args)
    return success_list(items, limit, offset, total)


@bp.route("/api/in-center-chairs/<cid>/backup-slot-reservations", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_chair_reservations(cid, _user_id, _role):
    get_or_404("in_center_chairs", cid)
    rows = [svc.lazy_eval_reservation(r) for r in S["backup_slot_reservations"].values()
            if r["chair_id"] == cid]
    status = request.args.get("status")
    if status:
        rows = [r for r in rows if r["status"] == status]
    rows.sort(key=lambda r: (r["created_at"], r.get("_seq", 0)))
    items, limit, offset, total = paginate(rows, request.args)
    return success_list(items, limit, offset, total)


@bp.route("/api/backup-slot-reservations/<rid>/cancel", methods=["POST"])
@require_roles("Patient")
def cancel_reservation(rid, _user_id, _role):
    res = svc.lazy_eval_reservation(get_or_404("backup_slot_reservations", rid))
    check_patient_ownership(_user_id, _role, res["patient_id"])
    if res["status"] != "RESERVED":
        raise errors.ApiError("ERR_SLOT_INVALID_STATE", 409,
                              "Reservation is not RESERVED")
    if db.now() >= svc.parse_dt(res["slot_start"]):
        raise errors.ApiError("ERR_SLOT_TOO_LATE_TO_CANCEL", 422,
                              "Cancellation at or after slot_start")
    res["status"] = "CANCELLED"
    db.touch(res)
    return success_obj(res)


@bp.route("/api/backup-slot-reservations/<rid>/complete", methods=["POST"])
@require_roles("HomeNurse")
def complete_reservation(rid, _user_id, _role):
    res = svc.lazy_eval_reservation(get_or_404("backup_slot_reservations", rid))
    if res["status"] != "RESERVED":
        raise errors.ApiError("ERR_SLOT_INVALID_STATE", 409,
                              "Reservation is not RESERVED")
    res["status"] = "COMPLETED"
    db.touch(res)
    return success_obj(res)


# ---------------------------------------------------------------------------
# waste / return records
# ---------------------------------------------------------------------------

@bp.route("/api/waste-return-records", methods=["POST"])
@require_roles("Patient")
def create_waste_record(_user_id, _role):
    p = require_fields(body(), ["patient_id", "record_type", "activity_month", "lines"])
    check_patient_ownership(_user_id, _role, p["patient_id"])
    patient = get_or_404("patients", p["patient_id"])
    if p["record_type"] not in ("WASTE", "RETURN"):
        raise errors.err_invalid_request("invalid record_type")
    if not svc.valid_month(p["activity_month"]):
        raise errors.err_invalid_request("activity_month must be YYYY-MM")
    if not isinstance(p["lines"], list) or not p["lines"]:
        raise errors.err_invalid_request("lines must be a non-empty array")
    program = get_or_404("dialysis_programs", patient["program_id"])
    catalog = svc.catalog_map(program)
    for line in p["lines"]:
        if not isinstance(line, dict):
            raise errors.err_invalid_request("line must be an object")
        if line.get("sku") not in catalog:
            raise errors.err_invalid_request(f"unknown sku: {line.get('sku')}")
        units = line.get("units")
        if not isinstance(units, int) or isinstance(units, bool) or units < 1:
            raise errors.err_invalid_request("units must be >= 1")
        if not isinstance(line.get("expired"), bool):
            raise errors.err_invalid_request("expired must be boolean")
    total_units = sum(int(l["units"]) for l in p["lines"])
    svc.patient_view(patient, recompute=False)
    if total_units > patient["on_hand_units"]:
        raise errors.ApiError("ERR_QUANTITY_EXCEEDS_ON_HAND", 422,
                              "total_units exceeds on_hand_units")
    rec = {
        "patient_id": patient["id"],
        "record_type": p["record_type"],
        "activity_month": p["activity_month"],
        "lines": [{"sku": l["sku"], "units": l["units"], "expired": l["expired"]}
                  for l in p["lines"]],
        "total_units": total_units,
        "credit_cents": 0,
        "status": "REPORTED",
    }
    db.stamp_new(rec)
    S["waste_return_records"][rec["id"]] = rec
    return success_obj(rec, 201)


@bp.route("/api/patients/<pid>/waste-return-records", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_patient_waste_records(pid, _user_id, _role):
    get_or_404("patients", pid)
    rows = [w for w in S["waste_return_records"].values() if w["patient_id"] == pid]
    rtype = request.args.get("record_type")
    status = request.args.get("status")
    month = request.args.get("activity_month")
    if rtype:
        rows = [r for r in rows if r["record_type"] == rtype]
    if status:
        rows = [r for r in rows if r["status"] == status]
    if month:
        rows = [r for r in rows if r["activity_month"] == month]
    rows.sort(key=lambda r: (r["created_at"], r.get("_seq", 0)))
    items, limit, offset, total = paginate(rows, request.args)
    return success_list(items, limit, offset, total)


@bp.route("/api/waste-return-records/<wid>/verify", methods=["POST"])
@require_roles("SupplyCoordinator")
def verify_waste_record(wid, _user_id, _role):
    rec = get_or_404("waste_return_records", wid)
    if rec["status"] != "REPORTED":
        raise errors.ApiError("ERR_WASTE_RECORD_NOT_REPORTED", 409,
                              "Record is not REPORTED")
    p = require_fields(body(), ["approved"])
    if not isinstance(p["approved"], bool):
        raise errors.err_invalid_request("approved must be boolean")
    patient = get_or_404("patients", rec["patient_id"])
    if not p["approved"]:
        rec["status"] = "REJECTED"
        rec["credit_cents"] = 0
        db.touch(rec)
        return success_obj(rec)
    if rec["record_type"] == "RETURN":
        rec["credit_cents"] = svc.compute_return_credit(patient, rec)
        rec["status"] = "CREDITED"
    else:
        rec["credit_cents"] = 0
        rec["status"] = "VERIFIED"
    db.touch(rec)
    # on_hand -= total_units (recomputed from ledger)
    svc.patient_view(patient, recompute=False)
    if rec["record_type"] == "WASTE":
        svc.compute_waste_ratio_and_maybe_escalate(patient, rec["activity_month"])
    svc.patient_view(patient)
    return success_obj(rec)
