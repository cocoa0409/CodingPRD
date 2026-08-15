"""ConferenceWindow endpoints: CRUD, lifecycle, slot generation, ops, reports."""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, request

import db
import errors
import middleware
import response
import serializers
import util
from services import core

bp = Blueprint("windows", __name__)

ALL_ROLES = {"SchoolAdmin", "FrontOfficeStaff", "Teacher", "FamilyGuardian", "Interpreter"}

GRID_FIELDS = ("slot_length_minutes", "buffer_minutes", "day_windows")


def _validate_day_windows_semantics(day_windows):
    """Each entry must parse and end strictly after start (ERR_INVALID_DAY_WINDOW)."""
    for d in day_windows:
        s = util.parse_dt(d["start_at"])
        e = util.parse_dt(d["end_at"])
        if s is None or e is None or e <= s:
            raise errors.invalid_day_window()


def _window_has_slots(window_id):
    return any(s["window_id"] == window_id for s in db.slots.values())


@bp.route("/conf/windows", methods=["POST"])
def create_window():
    role, _uid = middleware.get_auth()
    middleware.require_roles(role, {"SchoolAdmin"})
    body = util.get_body()
    util.require_fields(body, ["name", "term_label", "format", "slot_length_minutes",
                               "buffer_minutes", "travel_minutes", "day_windows",
                               "booking_open_at", "booking_close_at",
                               "teacher_daily_conf_cap"])
    name = util.require_string(body, "name")
    term_label = util.require_string(body, "term_label")
    fmt = util.require_enum(body, "format", {"ELEMENTARY", "SECONDARY"})
    slot_length = util.require_int(body, "slot_length_minutes", min_value=1)
    buffer_minutes = util.require_int(body, "buffer_minutes", min_value=0)
    travel_minutes = util.require_int(body, "travel_minutes", min_value=0)
    day_windows = util.parse_day_windows(body)
    # Structural shape is validated here; semantic range (end > start) is a
    # publish-time gate (ERR_INVALID_DAY_WINDOW) per PRD 3.1.
    booking_open_at = util.require_datetime(body, "booking_open_at")
    booking_close_at = util.require_datetime(body, "booking_close_at")
    teacher_cap = util.require_int(body, "teacher_daily_conf_cap", min_value=1)
    family_cap = util.optional_int(body, "family_conf_cap", default=8, min_value=1)
    cancel_cutoff = util.optional_int(body, "cancel_cutoff_hours", default=24, min_value=0)
    offer_ttl = util.optional_int(body, "waitlist_offer_ttl_hours", default=24, min_value=0)
    strike_threshold = util.optional_int(body, "no_show_strike_threshold", default=3, min_value=1)
    grace = util.optional_int(body, "auto_no_show_grace_hours", default=24, min_value=0)

    now = util.now_iso()
    window = {
        "id": util.new_id(),
        "name": name,
        "term_label": term_label,
        "format": fmt,
        "slot_length_minutes": slot_length,
        "buffer_minutes": buffer_minutes,
        "travel_minutes": travel_minutes,
        "day_windows": day_windows,
        "booking_open_at": booking_open_at,
        "booking_close_at": booking_close_at,
        "teacher_daily_conf_cap": teacher_cap,
        "family_conf_cap": family_cap,
        "cancel_cutoff_hours": cancel_cutoff,
        "waitlist_offer_ttl_hours": offer_ttl,
        "no_show_strike_threshold": strike_threshold,
        "auto_no_show_grace_hours": grace,
        "status": "DRAFT",
        "ops_run_index": 0,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.windows[window["id"]] = window
    return response.success_object(serializers.window_view(window), status=201)


@bp.route("/conf/windows", methods=["GET"])
def list_windows():
    role, _uid = middleware.get_auth()
    middleware.require_roles(role, ALL_ROLES)
    limit, offset = util.parse_pagination(request.args)
    status_filter = request.args.get("status")
    format_filter = request.args.get("format")
    items = [w for w in db.windows.values()]
    if status_filter is not None:
        items = [w for w in items if w["status"] == status_filter]
    if format_filter is not None:
        items = [w for w in items if w["format"] == format_filter]
    items.sort(key=lambda w: w["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return response.success_list([serializers.window_view(w) for w in page],
                                 total, limit, offset)


@bp.route("/conf/windows/<wid>", methods=["GET"])
def get_window(wid):
    role, _uid = middleware.get_auth()
    middleware.require_roles(role, ALL_ROLES)
    window = core.get_window_or_404(wid)
    return response.success_object(serializers.window_view(window))


@bp.route("/conf/windows/<wid>", methods=["PATCH"])
def update_window(wid):
    role, _uid = middleware.get_auth()
    middleware.require_roles(role, {"SchoolAdmin"})
    body = util.get_body()
    window = core.get_window_or_404(wid)

    # OCC
    expected = body.get("expected_window_version")
    if expected is not None:
        if isinstance(expected, bool) or not isinstance(expected, int):
            raise errors.validation("expected_window_version must be an integer")
        if expected != window["version"]:
            raise errors.stale_version()

    grid_locked = _window_has_slots(wid)

    # Fixed-at-creation fields are never editable
    if "term_label" in body and body["term_label"] != window["term_label"]:
        raise errors.validation("term_label cannot be edited")
    if "format" in body and body["format"] != window["format"]:
        raise errors.validation("format cannot be edited")

    new_day_windows = None
    if "day_windows" in body and body["day_windows"] is not None:
        new_day_windows = util.parse_day_windows(body)

    if "name" in body and body["name"] is not None:
        if not isinstance(body["name"], str) or body["name"] == "":
            raise errors.validation("name must be a non-empty string")
    if "booking_open_at" in body and body["booking_open_at"] is not None:
        util.require_datetime(body, "booking_open_at")
    if "booking_close_at" in body and body["booking_close_at"] is not None:
        util.require_datetime(body, "booking_close_at")
    int_fields = {
        "teacher_daily_conf_cap": 1,
        "family_conf_cap": 1,
        "cancel_cutoff_hours": 0,
        "waitlist_offer_ttl_hours": 0,
        "no_show_strike_threshold": 1,
        "auto_no_show_grace_hours": 0,
        "travel_minutes": 0,
        "slot_length_minutes": 1,
        "buffer_minutes": 0,
    }
    for f, minv in int_fields.items():
        if f in body and body[f] is not None:
            util.require_int(body, f, min_value=minv)

    # Grid fields frozen once slots exist
    if grid_locked:
        for f in GRID_FIELDS:
            if f in body and body[f] is not None:
                current = window[f]
                incoming = body[f] if f != "day_windows" else new_day_windows
                if incoming != current:
                    raise errors.window_grid_locked()

    if "name" in body and body["name"] is not None:
        window["name"] = body["name"]
    for f in ("booking_open_at", "booking_close_at", "teacher_daily_conf_cap",
              "family_conf_cap", "cancel_cutoff_hours", "waitlist_offer_ttl_hours",
              "no_show_strike_threshold", "auto_no_show_grace_hours", "travel_minutes"):
        if f in body and body[f] is not None:
            window[f] = body[f]
    if not grid_locked:
        if "slot_length_minutes" in body and body["slot_length_minutes"] is not None:
            window["slot_length_minutes"] = body["slot_length_minutes"]
        if "buffer_minutes" in body and body["buffer_minutes"] is not None:
            window["buffer_minutes"] = body["buffer_minutes"]
        if new_day_windows is not None:
            window["day_windows"] = new_day_windows

    window["version"] += 1
    window["updated_at"] = util.now_iso()
    return response.success_object(serializers.window_view(window))


@bp.route("/conf/windows/<wid>/publish", methods=["POST"])
def publish_window(wid):
    role, _uid = middleware.get_auth()
    middleware.require_roles(role, {"SchoolAdmin"})
    util.get_body()
    window = core.get_window_or_404(wid)
    if window["status"] != "DRAFT":
        raise errors.invalid_window_state("publish requires DRAFT")
    if not window["day_windows"]:
        raise errors.invalid_day_window("day_windows must be non-empty")
    _validate_day_windows_semantics(window["day_windows"])
    if window["slot_length_minutes"] <= 0 or window["buffer_minutes"] < 0 \
            or window["travel_minutes"] < 0:
        raise errors.validation("invalid grid geometry")
    window["status"] = "PUBLISHED"
    window["version"] += 1
    window["updated_at"] = util.now_iso()
    return response.success_object(serializers.window_view(window))


@bp.route("/conf/windows/<wid>/generate-slots", methods=["POST"])
def generate_slots(wid):
    role, _uid = middleware.get_auth()
    middleware.require_roles(role, {"SchoolAdmin"})
    body = util.get_body()
    window = core.get_window_or_404(wid)

    expected = body.get("expected_window_version")
    if expected is not None:
        if isinstance(expected, bool) or not isinstance(expected, int):
            raise errors.validation("expected_window_version must be an integer")
        if expected != window["version"]:
            raise errors.stale_version()

    # Regeneration is refused once any booking references the grid, in any
    # window state (PRD 3.2: "the moment any booking exists, regeneration is
    # refused with ERR_SLOTS_ALREADY_BOOKED").
    existing_slots = [s for s in db.slots.values() if s["window_id"] == wid]
    if existing_slots:
        for b in db.bookings.values():
            if b["window_id"] == wid:
                raise errors.slots_already_booked()

    if window["status"] != "PUBLISHED":
        raise errors.invalid_window_state("generate-slots requires PUBLISHED")

    if existing_slots:
        for s in existing_slots:
            s["status"] = "RETIRED"
            s["updated_at"] = util.now_iso()
            s["version"] += 1

    eligible = [t for t in db.teachers.values()
                if t["status"] == "ACTIVE"
                and (t["grade_band"] == window["format"] or t["grade_band"] == "BOTH")
                and (t["supports_in_person"] or t["supports_virtual"])]
    eligible.sort(key=lambda t: t["created_at"])

    L = window["slot_length_minutes"]
    B = window["buffer_minutes"]
    now = util.now_iso()
    for day in window["day_windows"]:
        day_start = util.parse_dt(day["start_at"])
        day_end = util.parse_dt(day["end_at"])
        if day_start is None or day_end is None:
            continue
        for teacher in eligible:
            if teacher["supports_in_person"] and teacher["supports_virtual"]:
                channel_allowed = "EITHER"
            elif teacher["supports_in_person"]:
                channel_allowed = "IN_PERSON"
            else:
                channel_allowed = "VIRTUAL"
            t = day_start
            placed = 0
            while t + timedelta(minutes=L) <= day_end:
                slot = {
                    "id": util.new_id(),
                    "window_id": wid,
                    "teacher_id": teacher["id"],
                    "day_label": day["date"],
                    "start_at": util.format_dt(t),
                    "end_at": util.format_dt(t + timedelta(minutes=L)),
                    "channel_allowed": channel_allowed,
                    "status": "OPEN",
                    "created_at": now,
                    "updated_at": now,
                    "version": 1,
                }
                db.slots[slot["id"]] = slot
                placed += 1
                t = t + timedelta(minutes=L + B)
                if placed % core.BREAK_EVERY == 0:
                    t = t + timedelta(minutes=core.BREAK_EXTRA_MINUTES)

    window["version"] += 1
    window["updated_at"] = util.now_iso()
    return response.success_object(serializers.window_view(window))


@bp.route("/conf/windows/<wid>/open-booking", methods=["POST"])
def open_booking(wid):
    role, _uid = middleware.get_auth()
    middleware.require_roles(role, {"SchoolAdmin"})
    util.get_body()
    window = core.get_window_or_404(wid)
    if window["status"] != "PUBLISHED":
        raise errors.invalid_window_state("open-booking requires PUBLISHED")
    if core.slots_total_count(wid) <= 0:
        raise errors.invalid_window_state("slots must be generated before opening booking")
    if util.clock_dt() < util.parse_dt(window["booking_open_at"]):
        raise errors.booking_window_not_open()
    window["status"] = "BOOKING_OPEN"
    window["version"] += 1
    window["updated_at"] = util.now_iso()
    return response.success_object(serializers.window_view(window))


@bp.route("/conf/windows/<wid>/lock", methods=["POST"])
def lock_window(wid):
    role, _uid = middleware.get_auth()
    middleware.require_roles(role, {"SchoolAdmin"})
    util.get_body()
    window = core.get_window_or_404(wid)
    if window["status"] != "BOOKING_OPEN":
        raise errors.invalid_window_state("lock requires BOOKING_OPEN")
    if util.clock_dt() < util.parse_dt(window["booking_close_at"]):
        raise errors.booking_window_not_closed()
    core.window_lock_cascade(window)
    window["status"] = "LOCKED"
    window["version"] += 1
    window["updated_at"] = util.now_iso()
    return response.success_object(serializers.window_view(window))


@bp.route("/conf/windows/<wid>/start", methods=["POST"])
def start_window(wid):
    role, _uid = middleware.get_auth()
    middleware.require_roles(role, {"SchoolAdmin"})
    util.get_body()
    window = core.get_window_or_404(wid)
    if window["status"] != "LOCKED":
        raise errors.invalid_window_state("start requires LOCKED")
    window["status"] = "IN_PROGRESS"
    window["version"] += 1
    window["updated_at"] = util.now_iso()
    return response.success_object(serializers.window_view(window))


@bp.route("/conf/windows/<wid>/complete", methods=["POST"])
def complete_window(wid):
    role, _uid = middleware.get_auth()
    middleware.require_roles(role, {"SchoolAdmin"})
    util.get_body()
    window = core.get_window_or_404(wid)
    if window["status"] != "IN_PROGRESS":
        raise errors.invalid_window_state("complete requires IN_PROGRESS")
    window["status"] = "COMPLETED"
    window["version"] += 1
    window["updated_at"] = util.now_iso()
    return response.success_object(serializers.window_view(window))


@bp.route("/conf/windows/<wid>/archive", methods=["POST"])
def archive_window(wid):
    role, _uid = middleware.get_auth()
    middleware.require_roles(role, {"SchoolAdmin"})
    util.get_body()
    window = core.get_window_or_404(wid)
    if window["status"] != "COMPLETED":
        raise errors.invalid_window_state("archive requires COMPLETED")
    for t in db.outreach_tasks.values():
        if t["window_id"] == wid and t["status"] in ("OPEN", "CONTACTED"):
            raise errors.open_outreach_tasks()
    window["status"] = "ARCHIVED"
    window["version"] += 1
    window["updated_at"] = util.now_iso()
    return response.success_object(serializers.window_view(window))


@bp.route("/conf/windows/<wid>/run-ops", methods=["POST"])
def run_ops(wid):
    role, _uid = middleware.get_auth()
    middleware.require_roles(role, {"SchoolAdmin"})
    util.get_body()
    window = core.get_window_or_404(wid)
    core.run_ops_sweeps(window)
    window["version"] += 1
    window["updated_at"] = util.now_iso()
    return response.success_object(serializers.window_view(window))


@bp.route("/conf/windows/<wid>/slots", methods=["GET"])
def list_window_slots(wid):
    role, _uid = middleware.get_auth()
    middleware.require_roles(role, ALL_ROLES)
    window = core.get_window_or_404(wid)
    limit, offset = util.parse_pagination(request.args)
    teacher_id = request.args.get("teacher_id")
    status = request.args.get("status")
    day_label = request.args.get("day_label")
    channel_allowed = request.args.get("channel_allowed")
    items = [s for s in db.slots.values() if s["window_id"] == wid]
    if teacher_id is not None:
        items = [s for s in items if s["teacher_id"] == teacher_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    if day_label is not None:
        items = [s for s in items if s["day_label"] == day_label]
    if channel_allowed is not None:
        items = [s for s in items if s["channel_allowed"] == channel_allowed]
    items.sort(key=lambda s: (s["start_at"], s["created_at"]))
    total = len(items)
    page = items[offset:offset + limit]
    return response.success_list([serializers.slot_view(s) for s in page],
                                 total, limit, offset)


@bp.route("/conf/windows/<wid>/attendance-report", methods=["GET"])
def attendance_report(wid):
    role, _uid = middleware.get_auth()
    middleware.require_roles(role, {"SchoolAdmin", "FrontOfficeStaff"})
    window = core.get_window_or_404(wid)
    counts = {"CONFIRMED": 0, "COMPLETED": 0, "NO_SHOW": 0, "EXCUSED": 0,
              "CANCELLED": 0, "RESCHEDULED": 0}
    for b in db.bookings.values():
        if b["window_id"] == wid and b["status"] in counts:
            counts[b["status"]] += 1
    denom = counts["COMPLETED"] + counts["NO_SHOW"]
    if denom == 0:
        attendance_rate = 0.0
        no_show_rate = 0.0
    else:
        attendance_rate = float(Decimal(100 * counts["COMPLETED"] / denom).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP))
        no_show_rate = float(Decimal(100 * counts["NO_SHOW"] / denom).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP))
    open_tasks = sum(1 for t in db.outreach_tasks.values()
                     if t["window_id"] == wid and t["status"] in ("OPEN", "CONTACTED"))
    report = {
        "window_id": wid,
        "bookings_confirmed": counts["CONFIRMED"],
        "bookings_completed": counts["COMPLETED"],
        "bookings_no_show": counts["NO_SHOW"],
        "bookings_excused": counts["EXCUSED"],
        "bookings_cancelled": counts["CANCELLED"],
        "bookings_rescheduled": counts["RESCHEDULED"],
        "attendance_rate_pct": attendance_rate,
        "no_show_rate_pct": no_show_rate,
        "open_outreach_tasks": open_tasks,
    }
    return response.success_object(report)
