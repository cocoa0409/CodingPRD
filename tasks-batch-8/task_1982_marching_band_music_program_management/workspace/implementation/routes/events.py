"""Event endpoints."""
from flask import Blueprint, request
from db import store, new_id, now, now_iso, parse_dt
from errors import (
    raise_err, ERR_EVENT_NOT_FOUND, ERR_EVENT_NOT_SCHEDULED, ERR_EVENT_TERMINAL,
    ERR_EVENT_WINDOW_INVALID, ERR_FACILITY_CONFLICT, ERR_EVENT_NOT_OUTDOOR,
    ERR_INVALID_REQUEST,
)
from middleware import require_roles
from response import success, parse_pagination, paginate
from services.serializers import event_out
from services.validators import body, require, check_unknown, to_str, to_enum, to_bool
from services.clock_eval import apply_time_transitions
from routes.programs import _get_program_or_404, _program_posture_open

bp = Blueprint("events", __name__)

EVENT_TYPES = {"REHEARSAL", "SECTIONAL", "COMPETITION", "PERFORMANCE", "FUNDRAISER"}


def _get_event_or_404(eid):
    e = store.events.get(eid)
    if e is None:
        raise_err(ERR_EVENT_NOT_FOUND, f"event {eid} not found")
    return e


def _facility_conflict(program_id, facility, starts_at, ends_at, exclude_event_id=None):
    """Half-open overlap against other non-terminal events."""
    for e in store.events.values():
        if e["id"] == exclude_event_id:
            continue
        if e["program_id"] != program_id:
            continue
        if e["facility"] != facility:
            continue
        if e["status"] not in ("SCHEDULED", "WEATHER_WATCH", "INDOOR_RELOCATED"):
            continue
        if starts_at < e["ends_at"] and e["starts_at"] < ends_at:
            return True
    return False


def _cancel_event_cascade(event):
    """Cancel linked trips and refund enrollments."""
    from services.ledger import post_ledger, recompute_enrollment, recompute_student
    for trip in list(store.trips.values()):
        if trip["event_id"] != event["id"]:
            continue
        if trip["status"] not in ("PLANNING", "ROSTER_OPEN", "ROSTER_LOCKED", "FINALIZED"):
            continue
        trip["status"] = "CANCELLED"
        trip["version"] += 1
        trip["updated_at"] = now_iso()
        # cascade enrollments
        for te in list(store.trip_enrollments.values()):
            if te["trip_id"] != trip["id"]:
                continue
            if te["attendance_status"] in ("REGISTERED", "CONFIRMED", "WAITLISTED"):
                te["attendance_status"] = "EXCUSED"
                if te["net_paid_cents"] > 0:
                    refund = te["net_paid_cents"]
                    post_ledger(te["student_id"], "REFUND", refund, trip_enrollment_id=te["id"])
                    te["payment_status"] = "REFUNDED"
                te["version"] += 1
                te["updated_at"] = now_iso()
                student = store.students.get(te["student_id"])
                if student:
                    recompute_student(student)


@bp.route("/band/events", methods=["POST"])
def create_event():
    require_roles(["BandDirector", "AssistantDirector"])
    data = body()
    check_unknown(data, {"program_id", "event_type", "facility", "starts_at", "ends_at", "is_outdoor"})
    require(data, "program_id", "event_type", "facility", "starts_at", "ends_at", "is_outdoor")
    pid = to_str(data["program_id"], "program_id")
    event_type = to_enum(data["event_type"], "event_type", EVENT_TYPES)
    facility = to_str(data["facility"], "facility")
    try:
        starts_at = parse_dt(data["starts_at"])
        ends_at = parse_dt(data["ends_at"])
    except (ValueError, TypeError):
        raise_err(ERR_INVALID_REQUEST, "starts_at/ends_at must be ISO8601")
    is_outdoor = to_bool(data["is_outdoor"], "is_outdoor")

    program = _get_program_or_404(pid)
    _program_posture_open(program)

    if ends_at <= starts_at:
        raise_err(ERR_EVENT_WINDOW_INVALID, "ends_at must be strictly after starts_at")

    if _facility_conflict(pid, facility, starts_at, ends_at):
        raise_err(ERR_FACILITY_CONFLICT, "facility already committed in that window")

    eid = new_id()
    now_s = now_iso()
    e = {
        "id": eid,
        "program_id": pid,
        "event_type": event_type,
        "facility": facility,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "is_outdoor": is_outdoor,
        "status": "SCHEDULED",
        "created_at": now_s,
        "updated_at": now_s,
        "version": 1,
    }
    store.events[eid] = e
    return success(event_out(e), status=201)


@bp.route("/band/events", methods=["GET"])
def list_events():
    require_roles(["Any"])
    apply_time_transitions()
    limit, offset = parse_pagination(request.args)
    items = list(store.events.values())
    pid = request.args.get("program_id")
    if pid:
        items = [e for e in items if e["program_id"] == pid]
    fac = request.args.get("facility")
    if fac:
        items = [e for e in items if e["facility"] == fac]
    st = request.args.get("status")
    if st:
        items = [e for e in items if e["status"] == st]
    et = request.args.get("event_type")
    if et:
        items = [e for e in items if e["event_type"] == et]
    items.sort(key=lambda x: x["created_at"])
    page, pag = paginate(items, limit, offset)
    return success([event_out(e) for e in page], is_list=True, pagination=pag)


@bp.route("/band/events/<eid>", methods=["GET"])
def get_event(eid):
    require_roles(["Any"])
    apply_time_transitions()
    e = _get_event_or_404(eid)
    return success(event_out(e))


@bp.route("/band/events/<eid>/weather-watch", methods=["POST"])
def weather_watch(eid):
    require_roles(["BandDirector", "AssistantDirector"])
    e = _get_event_or_404(eid)
    if e["status"] != "SCHEDULED":
        raise_err(ERR_EVENT_NOT_SCHEDULED, "event is not SCHEDULED")
    if not e["is_outdoor"]:
        raise_err(ERR_EVENT_NOT_OUTDOOR, "event is not outdoor")
    e["status"] = "WEATHER_WATCH"
    e["version"] += 1
    e["updated_at"] = now_iso()
    return success(event_out(e))


@bp.route("/band/events/<eid>/relocate-indoor", methods=["POST"])
def relocate_indoor(eid):
    require_roles(["BandDirector", "AssistantDirector"])
    e = _get_event_or_404(eid)
    data = body()
    check_unknown(data, {"facility"})
    require(data, "facility")
    new_facility = to_str(data["facility"], "facility")
    if e["status"] != "WEATHER_WATCH":
        raise_err(ERR_EVENT_NOT_SCHEDULED, "event is not WEATHER_WATCH")
    if _facility_conflict(e["program_id"], new_facility, e["starts_at"], e["ends_at"], exclude_event_id=e["id"]):
        raise_err(ERR_FACILITY_CONFLICT, "new facility is committed in that window")
    e["facility"] = new_facility
    e["is_outdoor"] = False
    e["status"] = "INDOOR_RELOCATED"
    e["version"] += 1
    e["updated_at"] = now_iso()
    return success(event_out(e))


@bp.route("/band/events/<eid>/postpone", methods=["POST"])
def postpone_event(eid):
    require_roles(["BandDirector", "AssistantDirector"])
    e = _get_event_or_404(eid)
    data = body()
    check_unknown(data, {"new_starts_at", "new_ends_at"})
    if e["status"] not in ("SCHEDULED", "WEATHER_WATCH", "POSTPONED"):
        raise_err(ERR_EVENT_TERMINAL, "event is in terminal state")
    # PRD §3.6: postponement moves SCHEDULED/WEATHER_WATCH/POSTPONED to
    # POSTPONED and leaves the times unchanged; only postponing a POSTPONED
    # event again with fresh new_starts_at/new_ends_at reschedules it back to
    # SCHEDULED with the new window (validated: strictly increasing and
    # conflict-free).
    has_new_start = "new_starts_at" in data and data["new_starts_at"] is not None
    has_new_end = "new_ends_at" in data and data["new_ends_at"] is not None
    if e["status"] == "POSTPONED" and has_new_start and has_new_end:
        try:
            new_starts = parse_dt(data["new_starts_at"])
            new_ends = parse_dt(data["new_ends_at"])
        except (ValueError, TypeError):
            raise_err(ERR_INVALID_REQUEST, "new_starts_at/new_ends_at must be ISO8601")
        if new_ends <= new_starts:
            raise_err(ERR_EVENT_WINDOW_INVALID, "new window must be strictly increasing")
        if _facility_conflict(e["program_id"], e["facility"], new_starts, new_ends, exclude_event_id=e["id"]):
            raise_err(ERR_FACILITY_CONFLICT, "new window conflicts with facility")
        e["starts_at"] = new_starts
        e["ends_at"] = new_ends
        e["status"] = "SCHEDULED"
    elif has_new_start != has_new_end:
        raise_err(ERR_INVALID_REQUEST, "must provide both new_starts_at and new_ends_at")
    else:
        e["status"] = "POSTPONED"
    e["version"] += 1
    e["updated_at"] = now_iso()
    return success(event_out(e))


@bp.route("/band/events/<eid>/complete", methods=["POST"])
def complete_event(eid):
    require_roles(["BandDirector", "AssistantDirector"])
    e = _get_event_or_404(eid)
    if e["status"] not in ("SCHEDULED", "WEATHER_WATCH", "INDOOR_RELOCATED"):
        raise_err(ERR_EVENT_TERMINAL, "event is not completable from current state")
    e["status"] = "COMPLETED"
    e["version"] += 1
    e["updated_at"] = now_iso()
    return success(event_out(e))


@bp.route("/band/events/<eid>/cancel", methods=["POST"])
def cancel_event(eid):
    require_roles(["BandDirector"])
    e = _get_event_or_404(eid)
    if e["status"] not in ("SCHEDULED", "WEATHER_WATCH", "INDOOR_RELOCATED", "POSTPONED"):
        raise_err(ERR_EVENT_TERMINAL, "event is in terminal state")
    e["status"] = "CANCELLED"
    e["version"] += 1
    e["updated_at"] = now_iso()
    _cancel_event_cascade(e)
    return success(event_out(e))
