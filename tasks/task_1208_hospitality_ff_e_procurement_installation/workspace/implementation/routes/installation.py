"""Room, InstallationWindow, and InstallationTask endpoints (PRD 3.7)."""
from datetime import timedelta

from flask import Blueprint

import db
import services as svc
from errors import ApiError
from middleware import auth, require_role, body, req_str, req_int, req_enum
from response import ok, paginate
from routes.projects import ANY

bp = Blueprint("installation", __name__)
S = db.STORE

ROOM_TYPES = ("GUEST_KING", "GUEST_DOUBLE", "SUITE", "CORRIDOR", "LOBBY")
WINDOW_STATUSES = ("PLANNED", "RELEASED", "IN_PROGRESS", "COMPLETE", "CANCELLED")


@bp.route("/api/rooms", methods=["POST"])
def create_room():
    auth_user, role = auth()
    require_role(role, ("InstallationManager",))
    b = body()
    project_id = b.get("project_id")
    if not isinstance(project_id, str):
        raise ApiError("ERR_INVALID_REQUEST", "Missing or invalid field: project_id")
    floor_number = req_int(b, "floor_number", 1)
    room_number = req_str(b, "room_number")
    room_type = req_enum(b, "room_type", ROOM_TYPES)
    svc.get_project(project_id)
    if any(r["project_id"] == project_id and r["room_number"] == room_number
           for r in S["rooms"].values()):
        raise ApiError("ERR_DUPLICATE_ROOM",
                       "A room with this room_number already exists for the project")
    room = db.create("rooms", {
        "project_id": project_id,
        "floor_number": floor_number,
        "room_number": room_number,
        "room_type": room_type,
    })
    return ok(db.pub(room), 201)


@bp.route("/api/rooms/<roomId>", methods=["GET"])
def get_room(roomId):
    auth_user, role = auth()
    require_role(role, ANY)
    return ok(db.pub(svc.get_room(roomId)))


@bp.route("/api/rooms/<id>/installation-tasks", methods=["GET"])
def room_tasks(id):
    auth_user, role = auth()
    require_role(role, ANY)
    svc.get_room(id)
    rows = db.sorted_items(r for r in S["installation_tasks"].values()
                           if r["room_id"] == id)
    page, meta = paginate(rows)
    return ok([db.pub(r) for r in page], 200, meta)


# --- InstallationWindow -------------------------------------------------------

@bp.route("/api/installation-windows", methods=["POST"])
def create_window():
    auth_user, role = auth()
    require_role(role, ("InstallationManager",))
    b = body()
    project_id = b.get("project_id")
    if not isinstance(project_id, str):
        raise ApiError("ERR_INVALID_REQUEST", "Missing or invalid field: project_id")
    floor_number = req_int(b, "floor_number", 1)
    start_raw = b.get("start_date")
    end_raw = b.get("end_date")
    start = svc.parse_iso_date(start_raw, "start_date")
    end = svc.parse_iso_date(end_raw, "end_date")
    crew_count = req_int(b, "crew_count", 1)
    svc.get_project(project_id)
    # stage 10: date sanity (half-open interval: end_date is the day after the
    # last work day and must be strictly after start_date)
    if end <= start:
        raise ApiError("ERR_INVALID_WINDOW_DATES",
                       "end_date must be strictly after start_date")
    window = db.create("installation_windows", {
        "project_id": project_id,
        "floor_number": floor_number,
        "start_date": start_raw,
        "end_date": end_raw,
        "crew_count": crew_count,
        "status": "PLANNED",
    })
    return ok(db.pub(window), 201)


@bp.route("/api/installation-windows/<installationWindowId>", methods=["GET"])
def get_window(installationWindowId):
    auth_user, role = auth()
    require_role(role, ANY)
    return ok(db.pub(svc.get_window(installationWindowId)))


@bp.route("/api/installation-windows/<id>/tasks", methods=["GET"])
def window_tasks(id):
    auth_user, role = auth()
    require_role(role, ANY)
    svc.get_window(id)
    rows = db.sorted_items(r for r in S["installation_tasks"].values()
                           if r["window_id"] == id)
    page, meta = paginate(rows)
    return ok([db.pub(r) for r in page], 200, meta)


def _window_day_range(window):
    start = svc.parse_iso_date(window["start_date"], "start_date")
    end = svc.parse_iso_date(window["end_date"], "end_date")
    days = []
    d = start
    while d < end:
        days.append(d)
        d += timedelta(days=1)
    return days


def _release_guards(window, project):
    """Room half-open overlap, then floor crew capacity (pinned order)."""
    my_tasks = [t for t in S["installation_tasks"].values()
                if t["window_id"] == window["id"] and t["status"] != "CANCELLED"]
    my_start = svc.parse_iso_date(window["start_date"], "start_date")
    my_end = svc.parse_iso_date(window["end_date"], "end_date")
    others = [w for w in S["installation_windows"].values()
              if w["id"] != window["id"] and w["project_id"] == window["project_id"]
              and w["status"] in ("RELEASED", "IN_PROGRESS")]
    my_rooms = {t["room_id"] for t in my_tasks}
    for other in others:
        other_rooms = {t["room_id"] for t in S["installation_tasks"].values()
                       if t["window_id"] == other["id"] and t["status"] != "CANCELLED"}
        if not (my_rooms & other_rooms):
            continue
        o_start = svc.parse_iso_date(other["start_date"], "start_date")
        o_end = svc.parse_iso_date(other["end_date"], "end_date")
        # half-open intersection; pure adjacency is allowed
        if o_start < my_end and my_start < o_end:
            raise ApiError("ERR_ROOM_WINDOW_OVERLAP",
                           "Another RELEASED/IN_PROGRESS window books the same room "
                           "over an intersecting date range")
    capacity = project["default_crew_capacity_per_floor_day"]
    for day in _window_day_range(window):
        used = 0
        for other in others:
            if other["floor_number"] != window["floor_number"]:
                continue
            o_start = svc.parse_iso_date(other["start_date"], "start_date")
            o_end = svc.parse_iso_date(other["end_date"], "end_date")
            if o_start <= day < o_end:
                used += other["crew_count"]
        if used + window["crew_count"] > capacity:
            raise ApiError("ERR_FLOOR_CREW_CAPACITY_EXCEEDED",
                           "Summed crew_count for the floor and day would exceed "
                           "default_crew_capacity_per_floor_day")


@bp.route("/api/installation-windows/<id>/transitions", methods=["POST"])
def window_transition(id):
    auth_user, role = auth()
    require_role(role, ("InstallationManager",))
    window = svc.get_window(id)
    b = body()
    to_status = req_enum(b, "to_status", WINDOW_STATUSES)
    cur = window["status"]
    project = svc.get_project(window["project_id"])
    if to_status == "RELEASED":
        if cur != "PLANNED":
            raise ApiError("ERR_INVALID_WINDOW_TRANSITION",
                           "RELEASED requires the window PLANNED")
        _release_guards(window, project)
        window["status"] = "RELEASED"
    elif to_status == "IN_PROGRESS":
        if cur != "RELEASED":
            raise ApiError("ERR_INVALID_WINDOW_TRANSITION",
                           "IN_PROGRESS requires the window RELEASED")
        scheduled = [t for t in S["installation_tasks"].values()
                     if t["window_id"] == id and t["status"] == "SCHEDULED"]
        if not scheduled:
            raise ApiError("ERR_WINDOW_NO_TASKS",
                           "IN_PROGRESS requires at least one SCHEDULED task")
        demand = {}
        for t in scheduled:
            demand[t["po_line_id"]] = demand.get(t["po_line_id"], 0) + t["quantity"]
        for line_id, qty in demand.items():
            line = svc.get_line(line_id)
            if qty > line["qty_installable"]:
                raise ApiError("ERR_INSUFFICIENT_INSTALLABLE_STOCK",
                               "Summed task quantities exceed the line's qty_installable")
        window["status"] = "IN_PROGRESS"
        # explicit side effect: posture recompute bumps the project version
        svc.recompute_project(project)
        db.touch(project)
    elif to_status == "COMPLETE":
        if cur != "IN_PROGRESS":
            raise ApiError("ERR_INVALID_WINDOW_TRANSITION",
                           "COMPLETE requires the window IN_PROGRESS")
        if any(t["status"] not in ("COMPLETE", "CANCELLED")
               for t in S["installation_tasks"].values() if t["window_id"] == id):
            raise ApiError("ERR_TASKS_OUTSTANDING",
                           "COMPLETE requires all tasks COMPLETE or CANCELLED")
        window["status"] = "COMPLETE"
        svc.recompute_project(project)
        db.touch(project)
    elif to_status == "CANCELLED":
        if cur not in ("PLANNED", "RELEASED"):
            raise ApiError("ERR_INVALID_WINDOW_TRANSITION",
                           "CANCELLED requires the window PLANNED or RELEASED")
        for t in db.sorted_items([t for t in S["installation_tasks"].values()
                                  if t["window_id"] == id]):
            if t["status"] == "SCHEDULED":
                t["status"] = "CANCELLED"
                db.touch(t)
        window["status"] = "CANCELLED"
    else:  # PLANNED is never a legal target
        raise ApiError("ERR_INVALID_WINDOW_TRANSITION",
                       f"{cur} -> {to_status} is not a legal window transition")
    db.touch(window)
    return ok(db.pub(window))


# --- InstallationTask ----------------------------------------------------------

@bp.route("/api/installation-tasks", methods=["POST"])
def create_task():
    auth_user, role = auth()
    require_role(role, ("InstallationManager",))
    b = body()
    window_id = b.get("window_id")
    room_id = b.get("room_id")
    po_line_id = b.get("po_line_id")
    for key, val in (("window_id", window_id), ("room_id", room_id),
                     ("po_line_id", po_line_id)):
        if not isinstance(val, str):
            raise ApiError("ERR_INVALID_REQUEST", f"Missing or invalid field: {key}")
    quantity = req_int(b, "quantity", 1)
    window = svc.get_window(window_id)
    room = svc.get_room(room_id)
    line = svc.get_line(po_line_id)
    line_project = svc.po_of_line(line)["project_id"]
    if not (window["project_id"] == room["project_id"] == line_project):
        raise ApiError("ERR_CROSS_PROJECT_REFERENCE",
                       "Window, room, and line must share one project")
    if line["qty_installable"] < quantity:
        raise ApiError("ERR_INSUFFICIENT_INSTALLABLE_STOCK",
                       "The line's qty_installable does not cover the task quantity")
    task = db.create("installation_tasks", {
        "window_id": window_id,
        "room_id": room_id,
        "po_line_id": po_line_id,
        "quantity": quantity,
        "status": "SCHEDULED",
    })
    return ok(db.pub(task), 201)


@bp.route("/api/installation-tasks/<installationTaskId>", methods=["GET"])
def get_task(installationTaskId):
    auth_user, role = auth()
    require_role(role, ANY)
    return ok(db.pub(svc.get_task(installationTaskId)))


@bp.route("/api/installation-tasks/<installationTaskId>/complete", methods=["POST"])
def complete_task(installationTaskId):
    auth_user, role = auth()
    require_role(role, ("InstallationManager",))
    task = svc.get_task(installationTaskId)
    if task["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_TASK_TRANSITION",
                       "complete requires the task SCHEDULED")
    window = svc.get_window(task["window_id"])
    if window["status"] != "IN_PROGRESS":
        raise ApiError("ERR_WINDOW_NOT_IN_PROGRESS",
                       "Task completion requires its window IN_PROGRESS")
    line = svc.get_line(task["po_line_id"])
    if line["qty_installable"] < task["quantity"]:
        raise ApiError("ERR_INSUFFICIENT_INSTALLABLE_STOCK",
                       "The line's qty_installable is below the task quantity")
    line["qty_installable"] -= task["quantity"]
    line["qty_installed"] += task["quantity"]
    db.touch(line)
    svc.recompute_attic_target(svc.spec_of_line(line))
    task["status"] = "COMPLETE"
    db.touch(task)
    return ok(db.pub(task))
