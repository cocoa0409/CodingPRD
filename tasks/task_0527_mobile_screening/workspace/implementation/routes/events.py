from flask import Blueprint, request
from db import db
from middleware import require_user_context, require_role
from response import object_response, array_response
from services.common import (stamp_new, bump, public, get_json_body, require_str,
                             require_int, require_enum, paginate, sorted_by_creation,
                             round_half_up)
from services.lookup import get_or_404
from services.calc import recompute_grant
from errors import err

bp = Blueprint("events", __name__)

MODALITIES = {"MAMMOGRAPHY", "BLOOD_PANEL", "BONE_DENSITY", "SKIN"}
BOOKED_STATES = {"SCHEDULED", "CHECKED_IN", "SCREENED", "RESULT_READY", "CLOSED"}
SCREENED_STATES = {"SCREENED", "RESULT_READY", "CLOSED"}
ALL_READ = {"ProgramManager", "ClinicalStaff", "BillingClerk", "SponsorViewer"}


def event_booked_count(event_id):
    return sum(1 for a in db.appointments.values()
               if a["event_id"] == event_id and a["status"] in BOOKED_STATES)


@bp.route("/screening-events", methods=["POST"])
def create_event():
    _, role = require_user_context()
    require_role(role, {"ProgramManager"})
    body = get_json_body()
    sponsor_id = require_str(body, "sponsor_id")
    mobile_unit_id = require_str(body, "mobile_unit_id")
    modality = require_enum(body, "modality", MODALITIES)
    site_label = require_str(body, "site_label")
    event_date = require_str(body, "event_date")
    _validate_date(event_date)
    window_start = require_int(body, "window_start_min")
    window_end = require_int(body, "window_end_min")
    if not (0 <= window_start <= 1439):
        raise err("ERR_INVALID_REQUEST", "window_start_min out of range")
    if not (1 <= window_end <= 1440):
        raise err("ERR_INVALID_REQUEST", "window_end_min out of range")
    if window_end <= window_start:
        raise err("ERR_INVALID_REQUEST", "window_end_min must be > window_start_min")
    # FK existence (priority 4)
    get_or_404("sponsors", sponsor_id)
    get_or_404("mobile_units", mobile_unit_id)
    event = stamp_new({
        "sponsor_id": sponsor_id, "mobile_unit_id": mobile_unit_id,
        "modality": modality, "site_label": site_label, "event_date": event_date,
        "window_start_min": window_start, "window_end_min": window_end,
        "booked_count": 0, "status": "DRAFT",
    })
    db.events[event["id"]] = event
    return object_response(_view(event), 201)


def _validate_date(s):
    parts = s.split("-")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        raise err("ERR_INVALID_REQUEST", "date must be YYYY-MM-DD")
    try:
        from datetime import date
        date(int(parts[0]), int(parts[1]), int(parts[2]))
    except ValueError:
        raise err("ERR_INVALID_REQUEST", "invalid calendar date")


def _view(event):
    out = public(event)
    out["booked_count"] = event_booked_count(event["id"])
    return out


@bp.route("/screening-events", methods=["GET"])
def list_events():
    user_id, role = require_user_context()
    require_role(role, ALL_READ)
    items = list(db.events.values())
    for f in ("sponsor_id", "mobile_unit_id", "status"):
        val = request.args.get(f)
        if val is not None:
            items = [e for e in items if e[f] == val]
    if role == "SponsorViewer":
        # restrict to events of sponsors this viewer owns
        owned = {s["id"] for s in db.sponsors.values() if s.get("viewer_user_id") == user_id}
        items = [e for e in items if e["sponsor_id"] in owned]
    items = sorted_by_creation(items)
    page, limit, offset, total = paginate(items)
    return array_response([_view(e) for e in page], limit, offset, total)


@bp.route("/screening-events/<rid>", methods=["GET"])
def get_event(rid):
    user_id, role = require_user_context()
    require_role(role, ALL_READ)
    event = get_or_404("events", rid)
    if role == "SponsorViewer":
        sponsor = db.sponsors.get(event["sponsor_id"])
        if not sponsor or user_id != sponsor.get("viewer_user_id"):
            raise err("ERR_INSUFFICIENT_PERMISSIONS", "Not the sponsor's viewer")
    return object_response(_view(event), 200)


@bp.route("/screening-events/<rid>/summary", methods=["GET"])
def event_summary(rid):
    _, role = require_user_context()
    require_role(role, {"ProgramManager", "ClinicalStaff"})
    event = get_or_404("events", rid)
    appts = [a for a in db.appointments.values() if a["event_id"] == rid]
    booked = sum(1 for a in appts if a["status"] in BOOKED_STATES)
    screened = sum(1 for a in appts if a["status"] in SCREENED_STATES)
    no_shows = sum(1 for a in appts if a["status"] == "NO_SHOW")
    unit = db.mobile_units.get(event["mobile_unit_id"])
    capacity = unit["daily_capacity"] if unit else 0
    fill_rate = round_half_up((booked / capacity) * 100) if capacity > 0 else 0
    show_rate = round_half_up((screened / booked) * 100) if booked > 0 else 0
    return object_response({
        "booked_count": booked, "screened_count": screened,
        "no_show_count": no_shows, "capacity": capacity,
        "fill_rate_pct": fill_rate, "show_rate_pct": show_rate,
    }, 200)


@bp.route("/screening-events/<rid>/publish", methods=["POST"])
def publish_event(rid):
    _, role = require_user_context()
    require_role(role, {"ProgramManager"})
    event = get_or_404("events", rid)
    body = get_json_body()
    if body.get("expected_event_version") is None:
        raise err("ERR_INVALID_REQUEST", "expected_event_version required")
    if isinstance(body["expected_event_version"], bool) or \
            not isinstance(body["expected_event_version"], int):
        raise err("ERR_INVALID_REQUEST", "expected_event_version must be an integer")
    if event["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Event not in DRAFT")
    unit = db.mobile_units.get(event["mobile_unit_id"])
    if not unit or unit["status"] != "AVAILABLE":
        raise err("ERR_UNIT_UNAVAILABLE", "Mobile unit not AVAILABLE")
    if event["modality"] != unit["modality"]:
        raise err("ERR_MODALITY_MISMATCH", "Event modality != unit modality")
    for other in db.events.values():
        if other["id"] == event["id"]:
            continue
        if other["mobile_unit_id"] == event["mobile_unit_id"] \
                and other["event_date"] == event["event_date"] \
                and other["status"] in ("PUBLISHED", "CLOSED"):
            raise err("ERR_UNIT_DAY_CONFLICT", "Unit already occupies this day")
    event["status"] = "PUBLISHED"
    bump(event)
    return object_response(_view(event), 200)


@bp.route("/screening-events/<rid>/close", methods=["POST"])
def close_event(rid):
    _, role = require_user_context()
    require_role(role, {"ProgramManager"})
    event = get_or_404("events", rid)
    if event["status"] != "PUBLISHED":
        raise err("ERR_INVALID_STATE", "Event not PUBLISHED")
    for a in db.appointments.values():
        if a["event_id"] == rid and a["status"] in ("CHECKED_IN", "SCREENED", "RESULT_READY"):
            raise err("ERR_OPEN_APPOINTMENTS_EXIST", "In-progress appointments exist")
    event["status"] = "CLOSED"
    bump(event)
    return object_response(_view(event), 200)


@bp.route("/screening-events/<rid>/cancel", methods=["POST"])
def cancel_event(rid):
    _, role = require_user_context()
    require_role(role, {"ProgramManager"})
    event = get_or_404("events", rid)
    if event["status"] not in ("DRAFT", "PUBLISHED"):
        raise err("ERR_INVALID_STATE", "Event not DRAFT or PUBLISHED")
    was_published = event["status"] == "PUBLISHED"
    event["status"] = "CANCELLED"
    if was_published:
        _cascade_cancel(rid)
    bump(event)
    return object_response(_view(event), 200)


def _cascade_cancel(event_id):
    # hop 1: appointments in {SCHEDULED, CHECKED_IN} -> CANCELLED
    cancelled_appt_ids = []
    for a in db.appointments.values():
        if a["event_id"] == event_id and a["status"] in ("SCHEDULED", "CHECKED_IN"):
            a["status"] = "CANCELLED"
            bump(a)
            cancelled_appt_ids.append(a["id"])
    ids = set(cancelled_appt_ids)
    # hop 2: reminders PENDING -> CANCELLED
    for r in db.reminders.values():
        if r["appointment_id"] in ids and r["status"] == "PENDING":
            r["status"] = "CANCELLED"
            bump(r)
    # hop 2 (billing): charges DRAFT/ADJUDICATED -> VOID; restore grant headroom
    for c in db.charges.values():
        if c["appointment_id"] in ids and c["status"] in ("DRAFT", "ADJUDICATED"):
            c["status"] = "VOID"
            bump(c)
            if c.get("grant_id"):
                grant = db.grants.get(c["grant_id"])
                if grant:
                    recompute_grant(grant)
                    bump(grant)
