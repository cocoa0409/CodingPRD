"""Service assignments, add-ons (PRD §3.10-3.14)."""
from datetime import timedelta

from flask import Blueprint, request

import errors
from db import store, LOCK
from middleware import get_identity, require_role, parse_pagination, get_json_body
from response import object_response, array_response
from services.common import base_fields, touch, paginate
from services import calc
from services.domain import (
    confirmed_faces, invoice_for_event, reconcile_balance,
)
from services.validate import require_datetime, require_enum, require_int_min

bp = Blueprint("assignments", __name__)

TRAVEL_BUFFER = timedelta(minutes=60)
ADDON_TYPES = {"TOUCH_UP", "EXTENDED_STAY"}


def serialize_assignment(a):
    return {
        "id": a["id"],
        "event_id": a["event_id"],
        "artist_id": a["artist_id"],
        "assistant_artist_id": a["assistant_artist_id"],
        "window_start_utc": a["window_start_utc"],
        "window_end_utc": a["window_end_utc"],
        "faces_committed": a["faces_committed"],
        "status": a["status"],
        "extended_until_utc": a["extended_until_utc"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def serialize_addon(ad):
    return {
        "id": ad["id"],
        "assignment_id": ad["assignment_id"],
        "addon_type": ad["addon_type"],
        "quantity": ad["quantity"],
        "amount_cents": ad["amount_cents"],
        "status": ad["status"],
        "created_at": ad["created_at"],
        "updated_at": ad["updated_at"],
        "version": ad["version"],
    }


def _artist_windows(artist_id, exclude_id=None):
    """All non-cancelled windows where artist is lead OR assistant (PRD §3.11)."""
    out = []
    for a in store.assignments.values():
        if exclude_id is not None and a["id"] == exclude_id:
            continue
        if a["status"] == "CANCELLED":
            continue
        if a["artist_id"] == artist_id or a["assistant_artist_id"] == artist_id:
            out.append(a)
    return out


def _buffer_conflict(artist_id, start_dt, end_dt):
    """New window [start,end) expanded by 60 min each side intersects an existing [s,e)."""
    exp_start = start_dt - TRAVEL_BUFFER
    exp_end = end_dt + TRAVEL_BUFFER
    for a in _artist_windows(artist_id):
        s = a["_start_dt"]
        e = a["_end_dt"]
        # intersect iff exp_start < e and s < exp_end
        if exp_start < e and s < exp_end:
            return True
    return False


@bp.route("/bridal-beauty/assignments", methods=["POST"])
def create_assignment():
    user_id, role = get_identity()
    require_role(role, {"Coordinator"})
    body = get_json_body()

    with LOCK:
        # Body well-formedness.
        if "event_id" not in body or not isinstance(body["event_id"], str) or not body["event_id"]:
            raise errors.invalid_request("event_id is required")
        if "artist_id" not in body or not isinstance(body["artist_id"], str) or not body["artist_id"]:
            raise errors.invalid_request("artist_id is required")
        if "expected_event_version" not in body:
            raise errors.invalid_request("expected_event_version is required")
        ev = body["expected_event_version"]
        if not isinstance(ev, int) or isinstance(ev, bool):
            raise errors.invalid_request("expected_event_version must be an integer")
        window_start = require_datetime(body, "window_start_utc")
        window_end = require_datetime(body, "window_end_utc")

        assistant_id = body.get("assistant_artist_id")
        if assistant_id is not None and (not isinstance(assistant_id, str) or not assistant_id):
            raise errors.invalid_request("assistant_artist_id must be a string")

        event_id = body["event_id"]
        artist_id = body["artist_id"]

        # Existence left-to-right (PRD §2.5): event, artist, assistant.
        event = store.events.get(event_id)
        if event is None:
            raise errors.not_found()
        artist = store.artists.get(artist_id)
        if artist is None:
            raise errors.not_found()
        assistant = None
        if assistant_id is not None:
            assistant = store.artists.get(assistant_id)
            if assistant is None:
                raise errors.not_found()

        # OCC (priority 5).
        if ev != event["version"]:
            raise errors.stale_event_version()

        # State (priority 6): event must be CONTRACTED.
        if event["status"] != "CONTRACTED":
            raise errors.invalid_state("Event is not CONTRACTED")

        # window_end strictly after start.
        if not (window_end > window_start):
            raise errors.invalid_request("window_end_utc must be after window_start_utc")

        # A signed contract must exist.
        contract = next((c for c in store.contracts.values()
                         if c["event_id"] == event_id and c["status"] == "SIGNED"), None)
        if contract is None:
            raise errors.invalid_state("No signed contract for this event")

        # Invoice deposit must be PAID.
        inv = invoice_for_event(event_id)
        if inv is None or inv["deposit_status"] != "PAID":
            raise errors.invalid_state("Invoice deposit is not PAID")

        # Artist active (priority 8): lead + assistant.
        if artist["status"] != "ACTIVE":
            raise errors.artist_not_active()
        if assistant is not None and assistant["status"] != "ACTIVE":
            raise errors.artist_not_active()

        # Assistant validity (priority 9).
        if assistant is not None:
            if assistant_id == artist_id or not assistant.get("can_assist"):
                raise errors.invalid_assistant()

        # Window conflict / travel buffer (priority 11).
        if _buffer_conflict(artist_id, window_start, window_end):
            raise errors.assignment_window_conflict()
        if assistant is not None and _buffer_conflict(assistant_id, window_start, window_end):
            raise errors.assignment_window_conflict()

        # window_end <= ready_by (priority 12).
        if window_end > event["_ready_by_dt"]:
            raise errors.window_past_deadline()

        # Throughput (priority 13).
        confirmed = confirmed_faces(event_id)
        confirmed_count = len(confirmed)
        lead_cap = artist["max_faces_per_hour"]
        asst_cap = assistant["max_faces_per_hour"] if assistant is not None else 0
        capacity = calc.throughput_capacity(lead_cap, asst_cap, window_start, window_end)
        if capacity < confirmed_count:
            raise errors.insufficient_throughput()

        rec = base_fields()
        rec.update({
            "event_id": event_id,
            "artist_id": artist_id,
            "assistant_artist_id": assistant_id,
            "window_start_utc": body["window_start_utc"],
            "window_end_utc": body["window_end_utc"],
            "_start_dt": window_start,
            "_end_dt": window_end,
            "faces_committed": confirmed_count,
            "status": "SCHEDULED",
            "extended_until_utc": None,
        })
        store.assignments[rec["id"]] = rec

        # Event CONTRACTED -> SCHEDULED, bump version.
        event["status"] = "SCHEDULED"
        touch(event)

        return object_response(serialize_assignment(rec), 201)


@bp.route("/bridal-beauty/assignments/<assignment_id>", methods=["GET"])
def get_assignment(assignment_id):
    user_id, role = get_identity()
    require_role(role, {"Coordinator", "Artist", "Client"})
    a = store.assignments.get(assignment_id)
    if a is None:
        raise errors.not_found()
    return object_response(serialize_assignment(a), 200)


@bp.route("/bridal-beauty/assignments", methods=["GET"])
def list_assignments():
    user_id, role = get_identity()
    require_role(role, {"Coordinator", "Artist", "Client"})
    limit, offset = parse_pagination()
    event_f = request.args.get("event_id")
    artist_f = request.args.get("artist_id")
    assistant_f = request.args.get("assistant_artist_id")
    status_f = request.args.get("status")
    items = list(store.assignments.values())
    if event_f is not None:
        items = [a for a in items if a["event_id"] == event_f]
    if artist_f is not None:
        items = [a for a in items if a["artist_id"] == artist_f]
    if assistant_f is not None:
        items = [a for a in items if a["assistant_artist_id"] == assistant_f]
    if status_f is not None:
        items = [a for a in items if a["status"] == status_f]
    page, total = paginate(items, limit, offset)
    return array_response([serialize_assignment(a) for a in page], limit, offset, total)


@bp.route("/bridal-beauty/assignments/<assignment_id>/start", methods=["POST"])
def start_assignment(assignment_id):
    user_id, role = get_identity()
    require_role(role, {"Artist"})
    with LOCK:
        a = store.assignments.get(assignment_id)
        if a is None:
            raise errors.not_found()
        if user_id != a["artist_id"]:
            raise errors.forbidden_role("Acting artist is not the assignment's lead artist")
        if a["status"] != "SCHEDULED":
            raise errors.invalid_state("Assignment is not SCHEDULED")
        if not (store.clock_now >= a["_start_dt"]):
            raise errors.invalid_state("Current time has not reached window_start_utc")
        event = store.events.get(a["event_id"])
        if event is None or event["status"] != "SCHEDULED":
            raise errors.invalid_state("Owning event is not SCHEDULED")
        a["status"] = "IN_PROGRESS"
        touch(a)
        return object_response(serialize_assignment(a), 200)


@bp.route("/bridal-beauty/assignments/<assignment_id>/complete", methods=["POST"])
def complete_assignment(assignment_id):
    user_id, role = get_identity()
    require_role(role, {"Artist"})
    with LOCK:
        a = store.assignments.get(assignment_id)
        if a is None:
            raise errors.not_found()
        if user_id != a["artist_id"]:
            raise errors.forbidden_role("Acting artist is not the assignment's lead artist")
        if a["status"] != "IN_PROGRESS":
            raise errors.invalid_state("Assignment is not IN_PROGRESS")
        # Every add-on must be settled (APPLIED or REVERSED) — none pending.
        # (All add-ons are created APPLIED, so this is always satisfied.)
        a["status"] = "COMPLETED"
        touch(a)
        # Bubble-up: if balance NOT_DUE and deposit PAID -> balance DUE.
        inv = invoice_for_event(a["event_id"])
        if inv is not None and inv["balance_status"] == "NOT_DUE" and inv["deposit_status"] == "PAID":
            inv["balance_status"] = "DUE"
            touch(inv)
        return object_response(serialize_assignment(a), 200)


@bp.route("/bridal-beauty/assignments/<assignment_id>/cancel", methods=["POST"])
def cancel_assignment(assignment_id):
    user_id, role = get_identity()
    require_role(role, {"Coordinator"})
    with LOCK:
        a = store.assignments.get(assignment_id)
        if a is None:
            raise errors.not_found()
        if a["status"] not in ("SCHEDULED", "IN_PROGRESS"):
            raise errors.invalid_state("Assignment cannot be cancelled from its current state")
        event = store.events.get(a["event_id"])
        if event is not None and event["status"] == "COMPLETED":
            raise errors.invalid_state("Owning event is already COMPLETED")
        a["status"] = "CANCELLED"
        touch(a)
        # Reverse all APPLIED add-ons on this assignment.
        for ad in store.addons.values():
            if ad["assignment_id"] == assignment_id and ad["status"] == "APPLIED":
                ad["status"] = "REVERSED"
                touch(ad)
        # Re-run balance reconcile.
        inv = invoice_for_event(a["event_id"])
        if inv is not None:
            reconcile_balance(inv)
            touch(inv)
        return object_response(serialize_assignment(a), 200)


@bp.route("/bridal-beauty/assignments/<assignment_id>/addons", methods=["POST"])
def add_addon(assignment_id):
    user_id, role = get_identity()
    require_role(role, {"Coordinator", "Artist"})
    body = get_json_body()
    with LOCK:
        a = store.assignments.get(assignment_id)
        if a is None:
            raise errors.not_found()
        addon_type = require_enum(body, "addon_type", ADDON_TYPES)
        quantity = require_int_min(body, "quantity", 1)

        event = store.events.get(a["event_id"])
        artist = store.artists.get(a["artist_id"])

        rec = base_fields()
        rec.update({
            "assignment_id": assignment_id,
            "addon_type": addon_type,
            "quantity": quantity,
            "amount_cents": 0,
            "status": "APPLIED",
        })

        if addon_type == "TOUCH_UP":
            rec["amount_cents"] = calc.touch_up_amount(
                artist["makeup_rate_per_face_cents"], quantity)
        else:  # EXTENDED_STAY
            rec["amount_cents"] = calc.extended_stay_amount(quantity)
            base_end = a["_end_dt"]
            new_extended = base_end + timedelta(minutes=30 * quantity)
            # Cannot push extended_until_utc past event.ready_by_utc.
            if event is not None and new_extended > event["_ready_by_dt"]:
                raise errors.extension_past_deadline()
            a["extended_until_utc"] = _iso(new_extended)
            a["_extended_dt"] = new_extended
            touch(a)

        store.addons[rec["id"]] = rec

        # Run balance reconcile.
        inv = invoice_for_event(a["event_id"])
        if inv is not None:
            reconcile_balance(inv)
            touch(inv)

        return object_response(serialize_addon(rec), 201)


@bp.route("/bridal-beauty/assignments/<assignment_id>/addons", methods=["GET"])
def list_addons(assignment_id):
    user_id, role = get_identity()
    require_role(role, {"Coordinator", "Artist", "Client"})
    limit, offset = parse_pagination()
    status_f = request.args.get("status")
    a = store.assignments.get(assignment_id)
    if a is None:
        raise errors.not_found()
    items = [ad for ad in store.addons.values() if ad["assignment_id"] == assignment_id]
    if status_f is not None:
        items = [ad for ad in items if ad["status"] == status_f]
    page, total = paginate(items, limit, offset)
    return array_response([serialize_addon(ad) for ad in page], limit, offset, total)


def _iso(dt):
    from db import iso_millis
    return iso_millis(dt)
