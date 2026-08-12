"""Machines, maintenance events, emergency backup plans."""
from flask import Blueprint, request

import db
import errors
import services as svc
from middleware import require_roles, ALL_ROLES
from response import success_obj, success_list, paginate
from routes_programs import body, require_fields, get_or_404

bp = Blueprint("machines", __name__)
S = db.STORES


# ---------------------------------------------------------------------------
# machines
# ---------------------------------------------------------------------------

@bp.route("/api/dialysis-machines", methods=["POST"])
@require_roles("BiomedTechnician")
def create_machine(_user_id, _role):
    p = require_fields(body(), ["program_id", "serial_number", "model"])
    get_or_404("dialysis_programs", p["program_id"])
    for m in S["dialysis_machines"].values():
        if m["program_id"] == p["program_id"] and m["serial_number"] == p["serial_number"]:
            raise errors.ApiError("ERR_SERIAL_NUMBER_EXISTS", 409,
                                  "serial_number already used within the program")
    rec = {
        "program_id": p["program_id"],
        "serial_number": p["serial_number"],
        "model": p["model"],
        "status": "IN_STOCK",
        "assigned_patient_id": None,
        "total_runtime_hours": 0,
        "runtime_hours_at_last_service": 0,
        "maintenance_due": False,
    }
    db.stamp_new(rec)
    S["dialysis_machines"][rec["id"]] = rec
    return success_obj(svc.machine_view(rec), 201)


@bp.route("/api/dialysis-machines/<mid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_machine(mid, _user_id, _role):
    return success_obj(svc.machine_view(get_or_404("dialysis_machines", mid)))


@bp.route("/api/dialysis-machines/<mid>/assign", methods=["POST"])
@require_roles("BiomedTechnician")
def assign_machine(mid, _user_id, _role):
    machine = get_or_404("dialysis_machines", mid)
    p = require_fields(body(), ["patient_id", "expected_machine_version"])
    patient = get_or_404("patients", p["patient_id"])
    # state stage: OCC + machine state
    if p["expected_machine_version"] != machine["version"]:
        raise errors.err_stale_version()
    if machine["status"] not in ("IN_STOCK", "ASSIGNED"):
        raise errors.ApiError("ERR_MACHINE_INVALID_STATE", 409,
                              "Machine is not IN_STOCK or ASSIGNED")
    svc.machine_view(machine)
    if machine["maintenance_due"]:
        raise errors.ApiError("ERR_MACHINE_MAINTENANCE_DUE", 409,
                              "Machine maintenance is due")
    if patient["program_status"] == "TRANSITIONED_OUT":
        raise errors.ApiError("ERR_PATIENT_NOT_ACTIVE_HOME", 409,
                              "Patient is TRANSITIONED_OUT")
    old_patient_id = machine.get("assigned_patient_id")
    if old_patient_id == patient["id"]:
        raise errors.err_invalid_request("Machine already assigned to this patient")
    machine["assigned_patient_id"] = patient["id"]
    machine["status"] = "ASSIGNED"
    db.touch(machine)
    svc.patient_view(patient)
    if old_patient_id:
        old = get_or_404("patients", old_patient_id)
        svc.patient_view(old)
    return success_obj(svc.machine_view(machine))


@bp.route("/api/dialysis-machines/<mid>/unassign", methods=["POST"])
@require_roles("BiomedTechnician")
def unassign_machine(mid, _user_id, _role):
    machine = get_or_404("dialysis_machines", mid)
    if machine["status"] != "ASSIGNED":
        raise errors.ApiError("ERR_MACHINE_INVALID_STATE", 409,
                              "Machine is not ASSIGNED")
    old_patient_id = machine.get("assigned_patient_id")
    machine["status"] = "IN_STOCK"
    machine["assigned_patient_id"] = None
    db.touch(machine)
    if old_patient_id:
        old = get_or_404("patients", old_patient_id)
        svc.patient_view(old)
    return success_obj(svc.machine_view(machine))


@bp.route("/api/dialysis-machines/<mid>/decommission", methods=["POST"])
@require_roles("ProgramAdmin")
def decommission_machine(mid, _user_id, _role):
    machine = get_or_404("dialysis_machines", mid)
    if machine["status"] != "IN_STOCK":
        raise errors.ApiError("ERR_MACHINE_INVALID_STATE", 409,
                              "Machine is not IN_STOCK")
    for plan in S["emergency_backup_plans"].values():
        if plan.get("backup_machine_id") == mid:
            svc.lazy_eval_plan(plan)
            if plan["status"] in ("ACTIVE", "EXPIRED"):
                raise errors.ApiError("ERR_MACHINE_REFERENCED_BY_PLAN", 409,
                                      "Machine referenced by an ACTIVE/EXPIRED backup plan")
    for e in S["maintenance_events"].values():
        if e["machine_id"] == mid and e["status"] == "SCHEDULED":
            e["status"] = "CANCELLED"
            db.touch(e)
    machine["status"] = "DECOMMISSIONED"
    db.touch(machine)
    return success_obj(svc.machine_view(machine))


@bp.route("/api/dialysis-machines/<mid>/maintenance-events", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_machine_events(mid, _user_id, _role):
    get_or_404("dialysis_machines", mid)
    rows = [e for e in S["maintenance_events"].values() if e["machine_id"] == mid]
    status = request.args.get("status")
    etype = request.args.get("event_type")
    if status:
        rows = [r for r in rows if r["status"] == status]
    if etype:
        rows = [r for r in rows if r["event_type"] == etype]
    rows.sort(key=lambda r: (r["created_at"], r.get("_seq", 0)))
    items, limit, offset, total = paginate(rows, request.args)
    return success_list(items, limit, offset, total)


@bp.route("/api/dialysis-machines/<mid>/treatment-logs", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_machine_logs(mid, _user_id, _role):
    get_or_404("dialysis_machines", mid)
    rows = [l for l in S["treatment_logs"].values() if l["machine_id"] == mid]
    status = request.args.get("status")
    if status:
        rows = [r for r in rows if r["status"] == status]
    rows.sort(key=lambda r: (r["created_at"], r.get("_seq", 0)))
    items, limit, offset, total = paginate(rows, request.args)
    return success_list(items, limit, offset, total)


@bp.route("/api/dialysis-machines/<mid>/emergency-backup-plans", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_machine_plans(mid, _user_id, _role):
    get_or_404("dialysis_machines", mid)
    rows = [svc.lazy_eval_plan(p) for p in S["emergency_backup_plans"].values()
            if p.get("backup_machine_id") == mid]
    status = request.args.get("status")
    if status:
        rows = [r for r in rows if r["status"] == status]
    rows.sort(key=lambda r: (r["created_at"], r.get("_seq", 0)))
    items, limit, offset, total = paginate(rows, request.args)
    return success_list(items, limit, offset, total)


@bp.route("/api/patients/<pid>/dialysis-machines", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_patient_machines(pid, _user_id, _role):
    get_or_404("patients", pid)
    rows = [svc.machine_view(m) for m in S["dialysis_machines"].values()
            if m.get("assigned_patient_id") == pid]
    status = request.args.get("status")
    if status:
        rows = [r for r in rows if r["status"] == status]
    rows.sort(key=lambda r: (r["created_at"], r.get("_seq", 0)))
    items, limit, offset, total = paginate(rows, request.args)
    return success_list(items, limit, offset, total)


# ---------------------------------------------------------------------------
# maintenance events
# ---------------------------------------------------------------------------

@bp.route("/api/maintenance-events", methods=["POST"])
@require_roles("BiomedTechnician")
def create_event(_user_id, _role):
    p = require_fields(body(), ["machine_id", "event_type", "window_start", "window_end"])
    get_or_404("dialysis_machines", p["machine_id"])
    if p["event_type"] not in ("PREVENTIVE", "REPAIR", "DECONTAMINATION"):
        raise errors.err_invalid_request("invalid event_type")
    ws, we = svc.parse_dt(p["window_start"]), svc.parse_dt(p["window_end"])
    if ws is None or we is None or not (we > ws):
        raise errors.err_invalid_request("window_end must be > window_start")
    # closed-interval overlap with SCHEDULED/IN_PROGRESS events on this machine
    for e in S["maintenance_events"].values():
        if e["machine_id"] == p["machine_id"] and e["status"] in ("SCHEDULED", "IN_PROGRESS"):
            ews, ewe = svc.parse_dt(e["window_start"]), svc.parse_dt(e["window_end"])
            if ws <= ewe and we >= ews:  # closed: touching endpoints conflict
                raise errors.ApiError("ERR_EVENT_WINDOW_OVERLAP", 409,
                                      "Maintenance window overlaps another event")
    rec = {
        "machine_id": p["machine_id"],
        "event_type": p["event_type"],
        "window_start": db.iso(ws),
        "window_end": db.iso(we),
        "runtime_hours_at_service": None,
        "status": "SCHEDULED",
    }
    db.stamp_new(rec)
    S["maintenance_events"][rec["id"]] = rec
    return success_obj(rec, 201)


@bp.route("/api/maintenance-events/<eid>/start", methods=["POST"])
@require_roles("BiomedTechnician")
def start_event(eid, _user_id, _role):
    event = get_or_404("maintenance_events", eid)
    if event["status"] != "SCHEDULED":
        raise errors.ApiError("ERR_EVENT_INVALID_STATE", 409,
                              "Event is not SCHEDULED")
    machine = get_or_404("dialysis_machines", event["machine_id"])
    if machine["status"] not in ("IN_STOCK", "ASSIGNED"):
        raise errors.ApiError("ERR_EVENT_INVALID_STATE", 409,
                              "Machine not IN_STOCK or ASSIGNED")
    for e in S["maintenance_events"].values():
        if (e["machine_id"] == machine["id"] and e["id"] != eid
                and e["status"] == "IN_PROGRESS"):
            raise errors.ApiError("ERR_MACHINE_BUSY_MAINTENANCE", 409,
                                  "Another event is IN_PROGRESS on this machine")
    we = svc.parse_dt(event["window_end"])
    if db.now() > we:
        raise errors.ApiError("ERR_EVENT_WINDOW_PASSED", 422,
                              "Maintenance window has passed")
    event["status"] = "IN_PROGRESS"
    db.touch(event)
    machine["status"] = "UNDER_MAINTENANCE"
    db.touch(machine)
    if machine.get("assigned_patient_id"):
        svc.patient_view(get_or_404("patients", machine["assigned_patient_id"]))
    return success_obj(event)


@bp.route("/api/maintenance-events/<eid>/complete", methods=["POST"])
@require_roles("BiomedTechnician")
def complete_event(eid, _user_id, _role):
    event = get_or_404("maintenance_events", eid)
    if event["status"] != "IN_PROGRESS":
        raise errors.ApiError("ERR_EVENT_INVALID_STATE", 409,
                              "Event is not IN_PROGRESS")
    machine = get_or_404("dialysis_machines", event["machine_id"])
    svc.machine_view(machine)
    event["runtime_hours_at_service"] = machine["total_runtime_hours"]
    event["status"] = "COMPLETED"
    db.touch(event)
    machine["status"] = "ASSIGNED" if machine.get("assigned_patient_id") else "IN_STOCK"
    db.touch(machine)
    svc.machine_view(machine)
    if machine.get("assigned_patient_id"):
        svc.patient_view(get_or_404("patients", machine["assigned_patient_id"]))
    return success_obj(event)


@bp.route("/api/maintenance-events/<eid>/cancel", methods=["POST"])
@require_roles("BiomedTechnician")
def cancel_event(eid, _user_id, _role):
    event = get_or_404("maintenance_events", eid)
    if event["status"] != "SCHEDULED":
        raise errors.ApiError("ERR_EVENT_INVALID_STATE", 409,
                              "Event is not SCHEDULED")
    event["status"] = "CANCELLED"
    db.touch(event)
    return success_obj(event)


# ---------------------------------------------------------------------------
# emergency backup plans
# ---------------------------------------------------------------------------

@bp.route("/api/emergency-backup-plans", methods=["POST"])
@require_roles("HomeNurse")
def create_plan(_user_id, _role):
    p = require_fields(body(), ["patient_id", "plan_mode", "expected_patient_version"])
    patient = get_or_404("patients", p["patient_id"])
    if p["plan_mode"] not in ("IN_CENTER_CHAIR", "BACKUP_MACHINE", "BOTH"):
        raise errors.err_invalid_request("invalid plan_mode")
    backup_machine_id = p.get("backup_machine_id")
    machine = None
    if backup_machine_id is not None:
        machine = get_or_404("dialysis_machines", backup_machine_id)
    # OCC on patient version (state stage)
    if p["expected_patient_version"] != patient["version"]:
        raise errors.err_stale_version()
    if p["plan_mode"] != "IN_CENTER_CHAIR" and not backup_machine_id:
        raise errors.ApiError("ERR_BACKUP_MACHINE_REQUIRED", 400,
                              "plan_mode requires backup_machine_id")
    if backup_machine_id is not None and machine["status"] != "IN_STOCK":
        raise errors.ApiError("ERR_BACKUP_MACHINE_NOT_IN_STOCK", 409,
                              "backup machine is not IN_STOCK")
    # supersede prior ACTIVE/EXPIRED plans
    for plan in S["emergency_backup_plans"].values():
        if plan["patient_id"] == patient["id"]:
            svc.lazy_eval_plan(plan)
            if plan["status"] in ("ACTIVE", "EXPIRED"):
                plan["status"] = "SUPERSEDED"
                db.touch(plan)
    rec = {
        "patient_id": patient["id"],
        "plan_mode": p["plan_mode"],
        "backup_machine_id": backup_machine_id,
        "last_drill_at": db.iso(db.now()),
        "status": "ACTIVE",
    }
    db.stamp_new(rec)
    S["emergency_backup_plans"][rec["id"]] = rec
    db.touch(patient)  # plan creation increments Patient.version
    svc.patient_view(patient)
    return success_obj(rec, 201)


@bp.route("/api/emergency-backup-plans/<pid>/drill", methods=["POST"])
@require_roles("HomeNurse")
def drill_plan(pid, _user_id, _role):
    plan = svc.lazy_eval_plan(get_or_404("emergency_backup_plans", pid))
    if plan["status"] not in ("ACTIVE", "EXPIRED"):
        raise errors.ApiError("ERR_PLAN_NOT_ACTIVE", 409,
                              "Plan is not ACTIVE or EXPIRED")
    plan["last_drill_at"] = db.iso(db.now())
    plan["status"] = "ACTIVE"
    db.touch(plan)
    svc.patient_view(get_or_404("patients", plan["patient_id"]))
    return success_obj(plan)


@bp.route("/api/patients/<pid>/emergency-backup-plans", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_patient_plans(pid, _user_id, _role):
    get_or_404("patients", pid)
    rows = [svc.lazy_eval_plan(p) for p in S["emergency_backup_plans"].values()
            if p["patient_id"] == pid]
    status = request.args.get("status")
    if status:
        rows = [r for r in rows if r["status"] == status]
    rows.sort(key=lambda r: (r["created_at"], r.get("_seq", 0)))
    items, limit, offset, total = paginate(rows, request.args)
    return success_list(items, limit, offset, total)
