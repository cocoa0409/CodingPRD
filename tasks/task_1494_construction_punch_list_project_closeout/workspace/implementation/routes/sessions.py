"""Training / demonstration sessions (PRD 3.5): 30-minute room turnover
buffer, OCC-gated reschedule with a hard cap of 2, conduct gating."""
from datetime import timedelta

from flask import Blueprint

from authz import GCPM, ALL_ROLES, require_roles
from db import store
from derived import maybe_advance_project, recompute_trade
from errors import (
    invalid_request, invalid_state, no_attendees, reschedule_limit,
    scheduled_in_past, session_not_started, session_room_conflict,
    stale_version, trade_not_in_project,
)
from respond import success
from serialize import ser_session
from store_ops import (
    get_or_404, json_body, new_common_fields, new_id, paginate, query_filters,
    req_int, req_str, req_temporal, sorted_by_creation, touch,
)

bp = Blueprint("sessions", __name__, url_prefix="/closeout")

ROOM_BUFFER = timedelta(minutes=30)
RESCHEDULE_CAP = 2

# Sessions are scheduled while the project is SUBSTANTIALLY_COMPLETE or
# CLOSEOUT_IN_PROGRESS (PRD 3.5).
SCHEDULING_PHASES = ("SUBSTANTIALLY_COMPLETE", "CLOSEOUT_IN_PROGRESS")


def _room_conflict(location_room, start, end, exclude_id=None):
    """A 30-minute buffer must separate any two sessions in the same room:
    violation iff new_start < existing_end + 30m and existing_start <
    new_end + 30m. Exactly 30 minutes after the prior end clears the buffer."""
    for s in store.training_sessions.values():
        if s["location_room"] != location_room or s["id"] == exclude_id:
            continue
        if start < s["scheduled_end"] + ROOM_BUFFER and s["scheduled_start"] < end + ROOM_BUFFER:
            return True
    return False


@bp.route("/training-sessions", methods=["POST"])
def create_session():
    require_roles([GCPM])
    data = json_body()
    project_id = req_str(data, "project_id")
    trade_package_id = req_str(data, "trade_package_id")
    system_name = req_str(data, "system_name")
    location_room = req_str(data, "location_room")
    start = req_temporal(data, "scheduled_start")
    end = req_temporal(data, "scheduled_end")
    if end <= start:
        raise invalid_request("scheduled_end must be after scheduled_start")
    p = get_or_404(store.projects, project_id)
    t = get_or_404(store.trade_packages, trade_package_id)
    if p["status"] not in SCHEDULING_PHASES:
        raise invalid_state(
            "Sessions may only be scheduled while SUBSTANTIALLY_COMPLETE "
            "or CLOSEOUT_IN_PROGRESS")
    if start < store.clock:
        raise scheduled_in_past()
    if _room_conflict(location_room, start, end):
        raise session_room_conflict()
    if t["project_id"] != project_id:
        raise trade_not_in_project()
    s = {
        "id": new_id(),
        "_seq": next(store.seq),
        "project_id": project_id,
        "trade_package_id": trade_package_id,
        "system_name": system_name,
        "location_room": location_room,
        "scheduled_start": start,
        "scheduled_end": end,
        "reschedule_count": 0,
        "attendee_count": None,
        "status": "SCHEDULED",
    }
    s.update(new_common_fields())
    store.training_sessions[s["id"]] = s
    return success(ser_session(s), status=201)


@bp.route("/training-sessions/<sid>", methods=["GET"])
def get_session(sid):
    require_roles(ALL_ROLES)
    return success(ser_session(get_or_404(store.training_sessions, sid)))


@bp.route("/training-sessions", methods=["GET"])
def list_sessions():
    require_roles(ALL_ROLES)
    filters = query_filters("project_id", "trade_package_id", "status")
    items = [s for s in store.training_sessions.values()
             if all(s[k] == v for k, v in filters.items())]
    page, pagination = paginate(sorted_by_creation(items))
    return success([ser_session(s) for s in page], response_type="array",
                   pagination=pagination)


@bp.route("/training-sessions/<sid>/reschedule", methods=["POST"])
def reschedule_session(sid):
    require_roles([GCPM])
    data = json_body()
    start = req_temporal(data, "scheduled_start")
    end = req_temporal(data, "scheduled_end")
    if end <= start:
        raise invalid_request("scheduled_end must be after scheduled_start")
    expected = req_int(data, "expected_training_session_version")
    s = get_or_404(store.training_sessions, sid)
    # OCC (priority 7) precedes the state gate (priority 8) — PRD 2.7/2.10.
    if expected != s["version"]:
        raise stale_version()
    if s["status"] != "SCHEDULED":
        raise invalid_state("Only a SCHEDULED session can be rescheduled")
    if start < store.clock:
        raise scheduled_in_past()
    if s["reschedule_count"] >= RESCHEDULE_CAP:
        raise reschedule_limit()
    if _room_conflict(s["location_room"], start, end, exclude_id=sid):
        raise session_room_conflict()
    s["scheduled_start"] = start
    s["scheduled_end"] = end
    s["reschedule_count"] += 1
    touch(s)
    return success(ser_session(s))


@bp.route("/training-sessions/<sid>/conduct", methods=["POST"])
def conduct_session(sid):
    require_roles([GCPM])
    data = json_body()
    attendee_count = req_int(data, "attendee_count")
    s = get_or_404(store.training_sessions, sid)
    if s["status"] != "SCHEDULED":
        raise invalid_state("Only a SCHEDULED session can be conducted")
    if store.clock < s["scheduled_start"]:
        raise session_not_started()
    if attendee_count < 1:
        raise no_attendees()
    s["attendee_count"] = attendee_count
    s["status"] = "CONDUCTED"
    touch(s)
    # The trade's has_conducted_training flips; closeout_ready recomputes; the
    # cascade may advance the project (PRD 3.5).
    recompute_trade(store.trade_packages[s["trade_package_id"]])
    maybe_advance_project(store.projects[s["project_id"]])
    return success(ser_session(s))
