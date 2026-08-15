"""LoadSchedule endpoints: dock-window conflict, authorization gate."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_RESOURCE_NOT_FOUND,
    ERR_DOCK_WINDOW_CONFLICT,
    ERR_SCHEDULE_NOT_AUTHORIZED,
)
from middleware import require_roles
from response import success_object, success_list
from services.domain import (
    check_declared,
    check_terminal,
    check_transition_owner,
    half_open_windows_intersect,
    parse_to,
)
from util import (
    get_json_body,
    paginate,
    parse_iso8601,
    parse_pagination,
    serialize,
    serialize_list,
    sort_by_created_at,
)

bp = Blueprint("load_schedules", __name__)

SCHEDULE_STATES = {"PLANNED", "CONFIRMED", "AUTHORIZED", "COMPLETE", "CANCELLED"}
SCHEDULE_TERMINAL = {"COMPLETE", "CANCELLED"}
SCHEDULE_TO_OWNERS = {
    "CONFIRMED": {"ProductionManager"},
    "AUTHORIZED": {"ProductionManager"},
    "COMPLETE": {"ProductionManager"},
    "CANCELLED": {"ProductionManager"},
}
SCHEDULE_DECLARED = {
    "PLANNED": {"CONFIRMED", "CANCELLED"},
    "CONFIRMED": {"AUTHORIZED", "CANCELLED"},
    "AUTHORIZED": {"COMPLETE"},
}


def get_schedule_or_404(schedule_id: str) -> dict:
    schedule = db.load_schedules.get(schedule_id)
    if schedule is None:
        raise_err(ERR_RESOURCE_NOT_FOUND, "LoadSchedule id does not exist")
    return schedule


@bp.route("/load-schedules/<schedule_id>", methods=["GET"])
@require_roles("Any")
def get_schedule(schedule_id: str, _user_id: str, _role: str):
    return success_object(serialize(get_schedule_or_404(schedule_id)))


@bp.route("/load-schedules/<schedule_id>/pull-list-entries", methods=["GET"])
@require_roles("Any")
def list_schedule_entries(schedule_id: str, _user_id: str, _role: str):
    get_schedule_or_404(schedule_id)
    limit, offset = parse_pagination()
    items = [
        e for e in db.pull_list_entries.values() if e.get("load_schedule_id") == schedule_id
    ]
    items = sort_by_created_at(items)
    page, total = paginate(items, limit, offset)
    return success_list(serialize_list(page), limit, offset, total)


@bp.route("/load-schedules/<schedule_id>/transition", methods=["POST"])
@require_roles("ProductionManager")
def transition_schedule(schedule_id: str, _user_id: str, _role: str):
    body = get_json_body()
    to = parse_to(body, SCHEDULE_STATES)
    check_transition_owner(to, SCHEDULE_TO_OWNERS, _role)
    schedule = get_schedule_or_404(schedule_id)
    check_terminal(schedule, SCHEDULE_TERMINAL, to, SCHEDULE_DECLARED)
    check_declared(schedule, to, SCHEDULE_DECLARED)

    production = db.productions.get(schedule["production_id"])

    if to == "CONFIRMED":
        venue_id = production["venue_id"]
        s_start = parse_iso8601(schedule["window_start"], "window_start")
        s_end = parse_iso8601(schedule["window_end"], "window_end")
        for other in db.load_schedules.values():
            if other["id"] == schedule["id"]:
                continue
            if other["status"] not in ("CONFIRMED", "AUTHORIZED"):
                continue
            if other["dock_door_index"] != schedule["dock_door_index"]:
                continue
            other_production = db.productions.get(other["production_id"])
            if other_production is None or other_production["venue_id"] != venue_id:
                continue
            o_start = parse_iso8601(other["window_start"], "window_start")
            o_end = parse_iso8601(other["window_end"], "window_end")
            if half_open_windows_intersect(s_start, s_end, o_start, o_end):
                raise_err(ERR_DOCK_WINDOW_CONFLICT, "Dock door window already occupied")
        schedule["status"] = "CONFIRMED"
        db.touch(schedule)
        return success_object(serialize(schedule))

    if to == "AUTHORIZED":
        if schedule["direction"] == "LOAD_IN":
            allowed = ("READY_FOR_LOADIN", "LOAD_IN")
        else:
            allowed = ("SHOW_COMPLETE", "LOAD_OUT")
        if production is None or production["status"] not in allowed:
            raise_err(
                ERR_SCHEDULE_NOT_AUTHORIZED,
                "Production state does not match the schedule direction",
            )
        schedule["status"] = "AUTHORIZED"
        db.touch(schedule)
        return success_object(serialize(schedule))

    if to == "COMPLETE":
        schedule["status"] = "COMPLETE"
        db.touch(schedule)
        return success_object(serialize(schedule))

    # to == "CANCELLED"
    schedule["status"] = "CANCELLED"
    db.touch(schedule)
    return success_object(serialize(schedule))
