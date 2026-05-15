"""Routes for /cleaning-tasks and nested /inspect, /inspection."""

from flask import Blueprint, request, g

from db import DB, LOCK
from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_ROOM_NOT_FOUND,
    ERR_TASK_NOT_FOUND,
    ERR_TASK_NOT_ASSIGNED,
    ERR_TASK_NOT_ACCEPTED,
    ERR_TASK_NOT_IN_PROGRESS,
    ERR_TASK_NOT_SUBMITTED,
    ERR_TASK_TERMINAL,
    ERR_NOT_TASK_ASSIGNEE,
    ERR_INVALID_REASSIGN_TARGET,
    ERR_NO_ELIGIBLE_HOUSEKEEPER,
    ERR_HOUSEKEEPER_NOT_FOUND,
    ERR_INVALID_INSPECTION_CHECKLIST,
    ERR_INSPECTION_NOT_FOUND,
)
from middleware import auth_required
from response import success_response, list_response
from services.audit import append_audit
from services.calculations import (
    compute_estimated_minutes,
    compute_sampled_flag,
    refresh_priority,
)
from services.cleaning_task_service import (
    build_cleaning_task,
    cancel_open_tasks_for_room,
    create_and_dispatch,
    try_auto_dispatch,
)
from services.common import (
    bump,
    check_version,
    require_body_dict,
    require_enum,
    require_field,
    round_half_up,
    stamp_create,
    stamp_subordinate,
)
from services.pagination import parse_pagination, paginate
from services.room_machine import transition_room
from services.serializers import serialize_cleaning_task, serialize_inspection
from services.time_util import now_utc, parse_iso, utc_now_iso


bp = Blueprint("cleaning_tasks", __name__)


TASK_SOURCES = {"CHECK_OUT", "STAYOVER", "SCHEDULED"}
INSPECTION_OUTCOMES = {"PASS", "FAIL"}


def get_task_or_404(task_id):
    t = DB["cleaning_tasks"].get(task_id)
    if t is None:
        raise_error(ERR_TASK_NOT_FOUND, "CleaningTask not found")
    return t


def get_room_or_404(room_id):
    r = DB["rooms"].get(room_id)
    if r is None:
        raise_error(ERR_ROOM_NOT_FOUND, "Room not found")
    return r


# --------------------------------------------------------------------------- #
# Create / list / get
# --------------------------------------------------------------------------- #
@bp.route("/cleaning-tasks", methods=["POST"])
@auth_required(["FrontDesk", "Supervisor"])
def create_cleaning_task():
    body = require_body_dict(request.get_json(silent=True))
    room_id = require_field(body, "room_id", str)
    task_source = require_enum(body, "task_source", TASK_SOURCES)
    expedite_flag = body.get("expedite_flag", False)
    early_check_in_at = body.get("early_check_in_at")
    if not isinstance(expedite_flag, bool):
        raise_error(ERR_INVALID_REQUEST, "expedite_flag must be boolean")
    if early_check_in_at is not None and not isinstance(early_check_in_at, str):
        raise_error(ERR_INVALID_REQUEST, "early_check_in_at must be ISO string")

    with LOCK:
        room = get_room_or_404(room_id)
        task = create_and_dispatch(
            room=room,
            task_source=task_source,
            expedite_flag=expedite_flag,
            early_check_in_at=early_check_in_at,
            parent_task_id=None,
        )
    return success_response(serialize_cleaning_task(task), http_status=201)


@bp.route("/cleaning-tasks", methods=["GET"])
@auth_required(["FrontDesk", "Supervisor", "Housekeeper", "Engineer"])
def list_cleaning_tasks():
    limit, offset = parse_pagination()
    status = request.args.get("status")
    housekeeper_id = request.args.get("housekeeper_id")
    room_id = request.args.get("room_id")
    priority_tier = request.args.get("priority_tier")
    items = list(DB["cleaning_tasks"].values())
    if status:
        items = [t for t in items if t["status"] == status]
    if housekeeper_id:
        items = [t for t in items if t.get("assigned_housekeeper_id") == housekeeper_id]
    if room_id:
        items = [t for t in items if t["room_id"] == room_id]
    if priority_tier:
        items = [t for t in items if t.get("priority_tier") == priority_tier]
    items.sort(key=lambda t: t["created_at"])
    page, total = paginate(items, limit, offset)
    return list_response(
        [serialize_cleaning_task(t) for t in page], total, limit, offset
    )


@bp.route("/cleaning-tasks/<task_id>", methods=["GET"])
@auth_required(["FrontDesk", "Supervisor", "Housekeeper", "Engineer"])
def get_cleaning_task(task_id):
    t = get_task_or_404(task_id)
    return success_response(serialize_cleaning_task(t))


@bp.route("/cleaning-tasks/<task_id>", methods=["PATCH"])
@auth_required(["Supervisor"])
def patch_cleaning_task(task_id):
    body = require_body_dict(request.get_json(silent=True))
    with LOCK:
        t = get_task_or_404(task_id)
        if t["status"] in {"COMPLETED", "CANCELLED"}:
            raise_error(ERR_TASK_TERMINAL,
                        "Cannot edit a terminal cleaning task")
        check_version(t, body)
        changed = False
        if "task_source" in body and body["task_source"] is not None:
            if body["task_source"] not in TASK_SOURCES:
                raise_error(ERR_INVALID_REQUEST,
                            "Invalid task_source")
            t["task_source"] = body["task_source"]
            changed = True
        if "expedite_flag" in body and body["expedite_flag"] is not None:
            if not isinstance(body["expedite_flag"], bool):
                raise_error(ERR_INVALID_REQUEST,
                            "expedite_flag must be boolean")
            t["expedite_flag"] = body["expedite_flag"]
            changed = True
        if "early_check_in_at" in body:
            v = body["early_check_in_at"]
            if v is not None and not isinstance(v, str):
                raise_error(ERR_INVALID_REQUEST,
                            "early_check_in_at must be ISO string or null")
            t["early_check_in_at"] = v
            changed = True
        if changed:
            room = DB["rooms"].get(t["room_id"])
            t["estimated_minutes"] = compute_estimated_minutes(room, t["task_source"])
            refresh_priority(t, room)
            bump(t)
    return success_response(serialize_cleaning_task(t))


# --------------------------------------------------------------------------- #
# Dispatch / accept / reassign / start / submit
# --------------------------------------------------------------------------- #
@bp.route("/cleaning-tasks/<task_id>/dispatch", methods=["POST"])
@auth_required(["Supervisor"])
def manual_dispatch(task_id):
    with LOCK:
        t = get_task_or_404(task_id)
        if t["status"] in {"COMPLETED", "CANCELLED"}:
            raise_error(ERR_TASK_TERMINAL, "Cannot dispatch a terminal task")
        if t["status"] != "PENDING":
            # Same family: not-pending → must be ASSIGNED or later
            raise_error(ERR_TASK_NOT_ASSIGNED,
                        "Task is not in PENDING state")
        room = DB["rooms"].get(t["room_id"])
        ok = try_auto_dispatch(t, room)
        if not ok:
            raise_error(ERR_NO_ELIGIBLE_HOUSEKEEPER,
                        "No eligible housekeeper in zone")
    return success_response(serialize_cleaning_task(t))


@bp.route("/cleaning-tasks/<task_id>/accept", methods=["POST"])
@auth_required(["Housekeeper"])
def accept_task(task_id):
    with LOCK:
        t = get_task_or_404(task_id)
        if t["status"] in {"COMPLETED", "CANCELLED"}:
            raise_error(ERR_TASK_TERMINAL, "Task is terminal")
        if t["status"] != "ASSIGNED":
            raise_error(ERR_TASK_NOT_ASSIGNED,
                        "Task is not in ASSIGNED state")
        if t.get("assigned_housekeeper_id") != g.user_id:
            raise_error(ERR_NOT_TASK_ASSIGNEE,
                        "Only the assigned housekeeper may accept")
        t["status"] = "ACCEPTED"
        t["accepted_at"] = utc_now_iso()
        bump(t)
    return success_response(serialize_cleaning_task(t))


@bp.route("/cleaning-tasks/<task_id>/reassign", methods=["POST"])
@auth_required(["Supervisor"])
def reassign_task(task_id):
    body = require_body_dict(request.get_json(silent=True))
    new_hk_id = require_field(body, "new_housekeeper_id", str)
    with LOCK:
        t = get_task_or_404(task_id)
        if t["status"] in {"COMPLETED", "CANCELLED"}:
            raise_error(ERR_TASK_TERMINAL, "Task is terminal")
        if t["status"] not in {"ASSIGNED", "ACCEPTED"}:
            raise_error(ERR_TASK_NOT_ASSIGNED,
                        "Task is not in ASSIGNED/ACCEPTED state")
        new_hk = DB["housekeepers"].get(new_hk_id)
        if new_hk is None:
            raise_error(ERR_HOUSEKEEPER_NOT_FOUND, "Target housekeeper not found")
        if new_hk_id == t.get("assigned_housekeeper_id"):
            raise_error(ERR_INVALID_REASSIGN_TARGET,
                        "Target equals current assignee")
        if new_hk.get("shift_status") != "ON_SHIFT":
            raise_error(ERR_INVALID_REASSIGN_TARGET,
                        "Target housekeeper is not ON_SHIFT")
        t["assigned_housekeeper_id"] = new_hk_id
        t["accepted_at"] = None
        t["status"] = "ASSIGNED"
        bump(t)
    return success_response(serialize_cleaning_task(t))


@bp.route("/cleaning-tasks/<task_id>/start", methods=["POST"])
@auth_required(["Housekeeper"])
def start_task(task_id):
    with LOCK:
        t = get_task_or_404(task_id)
        if t["status"] in {"COMPLETED", "CANCELLED"}:
            raise_error(ERR_TASK_TERMINAL, "Task is terminal")
        if t["status"] != "ACCEPTED":
            raise_error(ERR_TASK_NOT_ACCEPTED,
                        "Task is not in ACCEPTED state")
        if t.get("assigned_housekeeper_id") != g.user_id:
            raise_error(ERR_NOT_TASK_ASSIGNEE,
                        "Only the assigned housekeeper may start")
        t["status"] = "IN_PROGRESS"
        t["started_at"] = utc_now_iso()
        bump(t)
    return success_response(serialize_cleaning_task(t))


@bp.route("/cleaning-tasks/<task_id>/submit", methods=["POST"])
@auth_required(["Housekeeper"])
def submit_task(task_id):
    with LOCK:
        t = get_task_or_404(task_id)
        if t["status"] in {"COMPLETED", "CANCELLED"}:
            raise_error(ERR_TASK_TERMINAL, "Task is terminal")
        if t["status"] != "IN_PROGRESS":
            raise_error(ERR_TASK_NOT_IN_PROGRESS,
                        "Task is not in IN_PROGRESS state")
        if t.get("assigned_housekeeper_id") != g.user_id:
            raise_error(ERR_NOT_TASK_ASSIGNEE,
                        "Only the assigned housekeeper may submit")
        sub_at = utc_now_iso()
        started = parse_iso(t.get("started_at"))
        now_dt = parse_iso(sub_at)
        elapsed_seconds = (now_dt - started).total_seconds() if started else 0
        actual_minutes = round_half_up(elapsed_seconds / 60.0)
        t["status"] = "SUBMITTED"
        t["submitted_at"] = sub_at
        t["actual_minutes"] = int(actual_minutes)
        bump(t)
    return success_response(serialize_cleaning_task(t))


# --------------------------------------------------------------------------- #
# Inspect + Inspection record
# --------------------------------------------------------------------------- #
@bp.route("/cleaning-tasks/<task_id>/inspect", methods=["POST"])
@auth_required(["Supervisor"])
def inspect_task(task_id):
    body = require_body_dict(request.get_json(silent=True))
    outcome = require_enum(body, "outcome", INSPECTION_OUTCOMES)
    checklist_items = body.get("checklist_items")
    notes = body.get("notes")

    # Checklist validation (structural)
    if not isinstance(checklist_items, list) or len(checklist_items) == 0:
        raise_error(ERR_INVALID_INSPECTION_CHECKLIST,
                    "checklist_items must be a non-empty array")
    for it in checklist_items:
        if not isinstance(it, dict):
            raise_error(ERR_INVALID_INSPECTION_CHECKLIST,
                        "checklist_item must be an object")
        if "item_code" not in it or not isinstance(it.get("item_code"), str):
            raise_error(ERR_INVALID_INSPECTION_CHECKLIST,
                        "each checklist_item needs item_code")
        if "passed" not in it or not isinstance(it.get("passed"), bool):
            raise_error(ERR_INVALID_INSPECTION_CHECKLIST,
                        "each checklist_item needs boolean passed")
    if outcome == "PASS":
        if any(not it["passed"] for it in checklist_items):
            raise_error(ERR_INVALID_INSPECTION_CHECKLIST,
                        "PASS outcome requires every checklist item passed=true")

    with LOCK:
        t = get_task_or_404(task_id)
        if t["status"] in {"COMPLETED", "CANCELLED"}:
            raise_error(ERR_TASK_TERMINAL, "Task is terminal")
        if t["status"] != "SUBMITTED":
            raise_error(ERR_TASK_NOT_SUBMITTED,
                        "Task is not in SUBMITTED state")

        room = DB["rooms"].get(t["room_id"])

        # Build the inspection record
        rec = {
            "cleaning_task_id": t["id"],
            "room_id": t["room_id"],
            "supervisor_id": g.user_id,
            "sampled_flag": compute_sampled_flag(t),
            "checklist_items": checklist_items,
            "outcome": outcome,
            "notes": notes,
        }
        stamp_subordinate(rec)
        DB["inspection_records"][rec["id"]] = rec

        if outcome == "PASS":
            t["status"] = "COMPLETED"
            bump(t)
            # Room transition + last_cleaned_at
            room["last_cleaned_at"] = rec["created_at"]
            if t["task_source"] == "STAYOVER":
                # Stayover passes return to OCCUPIED_CLEAN
                transition_room(
                    room, "OCCUPIED_CLEAN",
                    change_reason="INSPECTION_PASS",
                    actor_id=g.user_id,
                    write_audit=True,
                )
            else:
                transition_room(
                    room, "INSPECTED",
                    change_reason="INSPECTION_PASS",
                    actor_id=g.user_id,
                    write_audit=True,
                )
            append_audit(
                actor_id=g.user_id,
                actor_role=g.user_role,
                action_type="ROOM_STATUS_CHANGE",
                subject_entity="CleaningTask",
                subject_id=t["id"],
                detail={"inspection_outcome": "PASS"},
            )
        else:
            # FAIL — original cancels, auto-create rework
            t["status"] = "CANCELLED"
            bump(t)
            rework = build_cleaning_task(
                room=room,
                task_source=t["task_source"],
                expedite_flag=True,
                early_check_in_at=t.get("early_check_in_at"),
                parent_task_id=t["id"],
            )
            try_auto_dispatch(rework, room)
            append_audit(
                actor_id=g.user_id,
                actor_role=g.user_role,
                action_type="ROOM_STATUS_CHANGE",
                subject_entity="CleaningTask",
                subject_id=t["id"],
                detail={"inspection_outcome": "FAIL", "rework_task_id": rework["id"]},
            )

    return success_response(serialize_inspection(rec), http_status=201)


@bp.route("/cleaning-tasks/<task_id>/inspection", methods=["GET"])
@auth_required(["FrontDesk", "Supervisor", "Housekeeper", "Engineer"])
def get_inspection(task_id):
    get_task_or_404(task_id)
    rec = None
    for r in DB["inspection_records"].values():
        if r.get("cleaning_task_id") == task_id:
            if rec is None or r["created_at"] > rec["created_at"]:
                rec = r
    if rec is None:
        raise_error(ERR_INSPECTION_NOT_FOUND,
                    "No inspection record for this task")
    return success_response(serialize_inspection(rec))
