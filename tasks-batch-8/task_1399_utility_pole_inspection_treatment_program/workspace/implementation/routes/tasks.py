from flask import Blueprint, request

import db
from calc import (remaining_strength, classify, escalated_cost,
                  priority_score, DEFAULT_REPLACEMENT_COST_CENTS)
from errors import ApiError
from middleware import authenticate, require_role, locked
from response import ok, ok_list
from serializers import ser_task
from validators import (body, req_field, opt_field, as_str, as_int, as_num,
                        as_bool, as_enum, as_list, as_dt, pagination,
                        apply_filters, bad)
from routes.cycles import _blank_task_fields

bp = Blueprint("tasks", __name__)

PHOTO_TYPES = ["GROUNDLINE", "DECAY_POCKET", "TAG", "ATTACHMENT"]
NON_TERMINAL = ("OPEN", "SUBMITTED", "REJECTED")


def _get_task(tid):
    t = db.tasks.get(tid)
    if t is None:
        raise ApiError("ERR_TASK_NOT_FOUND", 404,
                       "inspection task id does not resolve")
    return t


@bp.post("/pole-program/inspection-tasks")
@locked
def create_task():
    uid, role = authenticate()
    require_role(role, "ProgramManager")
    d = body()
    cycle_id = as_str(req_field(d, "cycle_id"), "cycle_id")
    pole_id = as_str(req_field(d, "pole_id"), "pole_id")
    win_start = as_dt(req_field(d, "due_window_start"), "due_window_start")
    win_end = as_dt(req_field(d, "due_window_end"), "due_window_end")
    # Body FK resolution order: pole_id, then cycle_id.
    pole = db.poles.get(pole_id)
    if pole is None:
        raise ApiError("ERR_POLE_NOT_FOUND", 404, "pole_id does not resolve")
    cycle = db.cycles.get(cycle_id)
    if cycle is None:
        raise ApiError("ERR_CYCLE_NOT_FOUND", 404, "cycle_id does not resolve")
    if cycle["status"] != "OPEN":
        raise ApiError("ERR_CYCLE_NOT_OPEN", 409,
                       "task creation requires cycle.status == OPEN")
    if pole["status"] == "REPLACED":
        raise ApiError("ERR_POLE_REPLACED", 409,
                       "Operation targets a pole whose status == REPLACED")
    siblings = [t for t in db.tasks.values()
                if t["pole_id"] == pole_id and t["status"] in NON_TERMINAL]
    if any(t["cycle_id"] == cycle_id for t in siblings):
        raise ApiError("ERR_DUPLICATE_INSPECTION", 409,
                       "A non-terminal task for the same pole already exists "
                       "in the same cycle")
    # Closed windows: touching at a single instant IS a conflict.
    for t in siblings:
        if win_start <= t["due_window_end"] and t["due_window_start"] <= win_end:
            raise ApiError("ERR_TASK_WINDOW_OVERLAP", 409,
                           "Closed due-window touches another non-terminal "
                           "task window for the same pole")
    if win_end < win_start:
        raise ApiError("ERR_INVALID_WINDOW", 422,
                       "due_window_end < due_window_start")
    rec = db.new_record()
    rec.update(cycle_id=cycle_id, pole_id=pole_id, due_window_start=win_start,
               due_window_end=win_end, status="OPEN", rework_count=0)
    rec.update(_blank_task_fields())
    db.tasks[rec["id"]] = rec
    return ok(ser_task(rec), 201)


@bp.get("/pole-program/inspection-tasks")
def list_tasks():
    authenticate()
    limit, offset = pagination()
    items = apply_filters(db.tasks.values(), [
        ("pole_id", request.args.get("pole_id")),
        ("cycle_id", request.args.get("cycle_id")),
        ("status", request.args.get("status")),
    ])
    page = items[offset:offset + limit]
    return ok_list([ser_task(t) for t in page], len(items), limit, offset)


@bp.get("/pole-program/inspection-tasks/<tid>")
def get_task(tid):
    authenticate()
    return ok(ser_task(_get_task(tid)), 200)


@bp.post("/pole-program/inspection-tasks/<tid>/submit")
@locked
def submit_task(tid):
    uid, role = authenticate()
    require_role(role, "Inspector")
    d = body()
    shell = as_num(req_field(d, "shell_thickness_in"), "shell_thickness_in")
    sound = as_num(req_field(d, "sound_wood_pct"), "sound_wood_pct", 0, 100)
    decay = as_num(req_field(d, "decay_pocket_depth_in"), "decay_pocket_depth_in")
    moisture = as_num(req_field(d, "moisture_pct"), "moisture_pct")
    hazard = opt_field(d, "hazard_flag", False)
    as_bool(hazard, "hazard_flag")
    photos = as_list(req_field(d, "photos"), "photos")
    for p in photos:
        if not isinstance(p, dict):
            bad("Each photo must be an object")
        as_enum(req_field(p, "photo_type"), "photo_type", PHOTO_TYPES)
        as_str(req_field(p, "url"), "url")
        as_str(req_field(p, "taken_at"), "taken_at")
    found = opt_field(d, "found_attachment_count", None)
    if found is not None:
        found = as_int(found, "found_attachment_count", 0)
    task = _get_task(tid)
    if task["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "submit requires task.status == OPEN")
    cycle = db.cycles[task["cycle_id"]]
    if cycle["status"] != "OPEN":
        raise ApiError("ERR_CYCLE_NOT_OPEN", 409,
                       "submit requires cycle.status == OPEN")
    pole = db.poles[task["pole_id"]]
    if pole["status"] == "REPLACED":
        raise ApiError("ERR_POLE_REPLACED", 409,
                       "Operation targets a pole whose status == REPLACED")
    cons, stat = remaining_strength(pole, shell, sound, decay, moisture)
    effective = cons if cycle["strength_variant_policy"] == "CONSERVATIVE" else stat
    classification = classify(effective)
    if classification == "REJECT_PRIORITY" and hazard is not True:
        raise ApiError("ERR_HAZARD_FLAG_REQUIRED", 422,
                       "Computed classification is REJECT_PRIORITY but "
                       "hazard_flag is not true")
    present = {p["photo_type"] for p in photos}
    required = {"GROUNDLINE", "TAG"}
    if classification in ("REJECT_PRIORITY", "REJECT_ROUTINE"):
        required.add("DECAY_POCKET")
    if not required.issubset(present):
        raise ApiError("ERR_PHOTO_EVIDENCE_REQUIRED", 422,
                       "Required photo_type coverage missing for the "
                       "computed classification")
    task.update(shell_thickness_in=shell, sound_wood_pct=sound,
                decay_pocket_depth_in=decay, moisture_pct=moisture,
                hazard_flag=hazard, photos=photos,
                rs_conservative_pct=cons, rs_statistical_pct=stat,
                effective_rs_pct=effective, classification=classification,
                submitted_by_user_id=uid, status="SUBMITTED")
    db.touch(task)
    if pole["joint_use"]:
        fc = found if found is not None else 0
        a = db.new_record()
        a.update(pole_id=pole["id"], inspection_task_id=task["id"],
                 audit_status="SUBMITTED", violation_status="NONE",
                 found_attachment_count=fc,
                 unauthorized_count=max(0, fc - pole["attachment_count_declared"]),
                 cure_deadline=None, adjudicated_at=None, cured_at=None)
        db.audits[a["id"]] = a
    return ok(ser_task(task), 200)


def _create_cascade_replacement(pole, cycle_id):
    o = db.new_record()
    o.update(pole_id=pole["id"], cycle_id=cycle_id, budget_id=None,
             estimated_cost_cents=DEFAULT_REPLACEMENT_COST_CENTS,
             actual_cost_cents=None, deferral_count=0,
             escalated_cost_cents=escalated_cost(DEFAULT_REPLACEMENT_COST_CENTS, 0),
             priority_score=priority_score(pole, 0), status="QUEUED",
             funded_at=None)
    db.replacements[o["id"]] = o
    return o


@bp.post("/pole-program/inspection-tasks/<tid>/qa-review")
@locked
def qa_review_task(tid):
    uid, role = authenticate()
    require_role(role, "QAReviewer")
    d = body()
    decision = as_enum(req_field(d, "decision"), "decision", ["ACCEPT", "REJECT"])
    task = _get_task(tid)
    if task["status"] != "SUBMITTED":
        raise ApiError("ERR_TASK_NOT_SUBMITTED", 409,
                       "qa-review requires task.status == SUBMITTED")
    if uid == task["submitted_by_user_id"]:
        raise ApiError("ERR_SOD_VIOLATION", 403,
                       "QA reviewer's X-User-ID equals task.submitted_by_user_id")
    n = db.clock_now()
    task["qa_reviewed_by_user_id"] = uid
    if decision == "ACCEPT":
        task["status"] = "ACCEPTED"
        db.touch(task)
        # Pole classification cascade.
        pole = db.poles[task["pole_id"]]
        pole["current_classification"] = task["classification"]
        pole["current_remaining_strength_pct"] = task["effective_rs_pct"]
        pole["last_inspection_date"] = n
        cls = task["classification"]
        if cls == "MONITOR":
            if pole["status"] in ("IN_SERVICE", "MONITOR"):
                pole["status"] = "MONITOR"
        elif cls == "REJECT_PRIORITY":
            if pole["status"] in ("IN_SERVICE", "MONITOR"):
                pole["status"] = "PRIORITY_REJECT"
                _create_cascade_replacement(pole, task["cycle_id"])
        # SERVICEABLE / REJECT_ROUTINE: pole.status unchanged.
        db.touch(pole)
    else:  # REJECT
        if task["rework_count"] < 2:
            task["rework_count"] += 1
            # Clear readings/photos/computed fields to null defaults.
            task.update(shell_thickness_in=None, sound_wood_pct=None,
                        decay_pocket_depth_in=None, moisture_pct=None,
                        hazard_flag=False, photos=[],
                        rs_conservative_pct=None, rs_statistical_pct=None,
                        effective_rs_pct=None, classification=None)
            # REJECTED -> OPEN auto-transition happens immediately.
            task["status"] = "OPEN"
        else:
            task["rework_count"] += 1  # final value 3
            task["status"] = "ESCALATED"
        db.touch(task)
    return ok(ser_task(task), 200)


@bp.post("/pole-program/inspection-tasks/<tid>/waive")
@locked
def waive_task(tid):
    uid, role = authenticate()
    require_role(role, "ProgramManager")
    d = body()
    as_str(req_field(d, "reason"), "reason")
    task = _get_task(tid)
    if task["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "waive requires task.status == OPEN")
    task["status"] = "WAIVED"
    db.touch(task)
    return ok(ser_task(task), 200)
