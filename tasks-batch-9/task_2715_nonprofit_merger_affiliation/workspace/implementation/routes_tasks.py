"""Integration planning and the half-open crew window — PRD 3.8."""

from flask import Blueprint

import enums
import services
from auth import authenticate
from clock import CLOCK, fmt_date, parse_date
from db import TASKS, create_row, touch
from errors import fail
from response import ok_row
from validate import (CREW_PATTERN, bad, body_object, opt_id, opt_str, req_date,
                      req_enum, req_id, req_str)

bp = Blueprint("tasks", __name__)

PLAN_DEAL_STATES = ("STRUCTURE_SELECTED", "BOARD_APPROVAL", "REGULATORY_REVIEW",
                    "INTEGRATION")
HELD_POSTURES = ("RESTRICTED_PENDING", "BLOCKED")


@bp.post("/integration-tasks")
def plan_task():
    authenticate(["IntegrationManager"])
    body = body_object()
    restructuring_id = req_id(body, "restructuring_id")
    workstream = req_enum(body, "workstream", enums.TASK_WORKSTREAMS)
    crew_code = req_str(body, "crew_code", pattern=CREW_PATTERN)
    title = req_str(body, "title", min_len=1, max_len=160)
    start_date = req_date(body, "planned_start_date")
    end_date = req_date(body, "planned_end_date")
    depends_on_task_id = opt_id(body, "depends_on_task_id")
    # The window is half-open, so the end date must fall strictly after the start.
    if end_date <= start_date:
        bad("planned_end_date must fall strictly after planned_start_date.")

    deal = services.find_deal(restructuring_id)
    # Ladder rule 12: a predecessor identifier that resolves to nothing at all.
    predecessor = None
    if depends_on_task_id is not None:
        predecessor = services.find_task(depends_on_task_id)
    # Ladder rule 16.
    if deal["status"] not in PLAN_DEAL_STATES:
        fail("ERR_INVALID_DEAL_STATE",
             "Integration work cannot be planned while the deal is %s."
             % deal["status"])
    # Ladder rule 28.
    if predecessor is not None and predecessor["restructuring_id"] != deal["id"]:
        fail("ERR_DEPENDENCY_NOT_IN_SAME_DEAL",
             "The predecessor task belongs to another deal.")
    # Ladder rule 42: half-open overlap, so adjacency is not a conflict.
    for other in TASKS.values():
        if other["crew_code"] != crew_code or other["status"] == "CANCELLED":
            continue
        o_start = parse_date(other["planned_start_date"])
        o_end = parse_date(other["planned_end_date"])
        if o_start is None or o_end is None:
            continue
        if start_date < o_end and o_start < end_date:
            fail("ERR_CREW_WINDOW_CONFLICT",
                 "This crew already occupies an overlapping window.")

    held = (workstream == "PROGRAM_CONTINUITY"
            and deal["restricted_asset_posture"] in HELD_POSTURES)
    row = create_row("IntegrationTask", {
        "restructuring_id": deal["id"],
        "workstream": workstream,
        "crew_code": crew_code,
        "title": title,
        "planned_start_date": fmt_date(start_date),
        "planned_end_date": fmt_date(end_date),
        "depends_on_task_id": predecessor["id"] if predecessor is not None else None,
        "status": "HELD" if held else "PLANNED",
        "held_reason": "RESTRICTED_ASSETS_UNRESOLVED" if held else None,
        "started_at": None,
        "completed_at": None,
    })
    return ok_row(row, 201)


@bp.post("/integration-tasks/<task_id>/start")
def start_task(task_id):
    authenticate(["IntegrationManager"])
    body = body_object()
    opt_str(body, "started_note", min_len=1)

    task = services.find_task(task_id)
    deal = services.find_deal(task["restructuring_id"])
    # Ladder rule 16: planning may run early, but execution may not.
    if deal["status"] != "INTEGRATION":
        fail("ERR_INVALID_DEAL_STATE",
             "An integration task can only start once the deal is in INTEGRATION.")
    # Ladder rule 21.
    if task["status"] != "PLANNED":
        fail("ERR_INVALID_TASK_STATE", "Only a PLANNED task can be started.")
    # Ladder rule 35.
    if deal["ag_review_required"] and not services.has_ag_clearance(deal["id"]):
        fail("ERR_AG_APPROVAL_MISSING",
             "An approved attorney-general filing is required before work starts.")
    # Ladder rule 43.
    if task["depends_on_task_id"] is not None:
        predecessor = TASKS.get(task["depends_on_task_id"])
        if predecessor is None or predecessor["status"] != "COMPLETE":
            fail("ERR_DEPENDENCY_NOT_COMPLETE",
                 "The predecessor task is not COMPLETE.")

    task["status"] = "IN_PROGRESS"
    task["started_at"] = CLOCK.now_iso()
    touch(task)
    return ok_row(task)


@bp.post("/integration-tasks/<task_id>/complete")
def complete_task(task_id):
    authenticate(["IntegrationManager"])
    body = body_object()
    opt_str(body, "completion_note", min_len=1)

    task = services.find_task(task_id)
    # Ladder rule 21.
    if task["status"] != "IN_PROGRESS":
        fail("ERR_INVALID_TASK_STATE", "Only an IN_PROGRESS task can be completed.")

    task["status"] = "COMPLETE"
    task["completed_at"] = CLOCK.now_iso()
    touch(task)
    return ok_row(task)
