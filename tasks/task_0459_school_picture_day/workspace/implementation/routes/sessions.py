"""PictureDaySession routes: CRUD, lifecycle transitions, gallery, yearbook."""
import random
import string

from flask import Blueprint

import db
import store
from common import (
    get_body,
    paginate,
    parse_pagination,
    require_fields,
    require_int,
    require_str,
    sort_by_creation,
)
from errors import err
from middleware import get_user_context, require_role
from response import array_response, object_response
from services import ledger

bp = Blueprint("sessions", __name__)

ALL_OPERATORS = ["SchoolCoordinator", "StudioPhotographer", "FulfillmentClerk"]


def _mint_access_code():
    return "GAL-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=12))


def _orders_for(session_id):
    return [o for o in db.photo_orders.values() if o["picture_day_session_id"] == session_id]


def _photos_for(session_id):
    return [p for p in db.photos.values() if p["picture_day_session_id"] == session_id]


def _students_for(session_id):
    return [s for s in db.students.values() if s["picture_day_session_id"] == session_id]


# ---------------------------------------------------------------------------
# Create / list / get
# ---------------------------------------------------------------------------
@bp.route("/api/picture-day-sessions", methods=["POST"])
def create_session():
    _uid, role = get_user_context()
    require_role(role, ["SchoolCoordinator"])
    body = get_body()

    require_fields(body, ["school_name", "scheduled_date", "gallery_closes_at", "retouch_budget_cents"])
    school_name = require_str(body, "school_name")
    scheduled_date = require_str(body, "scheduled_date")
    gallery_closes_at = require_str(body, "gallery_closes_at")
    retouch_budget = require_int(body, "retouch_budget_cents")
    if retouch_budget < 0:
        raise err("ERR_INVALID_REQUEST", "retouch_budget_cents must be >= 0")

    with db.LOCK:
        row = store.new_row("session", {
            "school_name": school_name,
            "scheduled_date": scheduled_date,
            "gallery_access_code": None,
            "gallery_opens_at": None,
            "gallery_closes_at": gallery_closes_at,
            "retouch_budget_cents": retouch_budget,
            "retouch_credit_balance_cents": retouch_budget,
            "school_commission_balance_cents": 0,
            "total_merchandise_cents": 0,
            "status": "DRAFT",
        })
        db.sessions[row["id"]] = row
    return object_response(store.serialize(row), 201)


@bp.route("/api/picture-day-sessions", methods=["GET"])
def list_sessions():
    _uid, role = get_user_context()
    require_role(role, ALL_OPERATORS)
    limit, offset = parse_pagination()
    from flask import request
    status = request.args.get("status")

    rows = list(db.sessions.values())
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows = sort_by_creation(rows)
    page, total = paginate(rows, limit, offset)
    return array_response([store.serialize(r) for r in page], limit, offset, total)


@bp.route("/api/picture-day-sessions/<sid>", methods=["GET"])
def get_session(sid):
    _uid, role = get_user_context()
    require_role(role, ALL_OPERATORS)
    row = store.get_session(sid)
    return object_response(store.serialize(row))


# ---------------------------------------------------------------------------
# Lifecycle transitions
# ---------------------------------------------------------------------------
@bp.route("/api/picture-day-sessions/<sid>/lock-roster", methods=["POST"])
def lock_roster(sid):
    _uid, role = get_user_context()
    require_role(role, ["SchoolCoordinator"])
    with db.LOCK:
        session = store.get_session(sid)
        if session["status"] != "DRAFT":
            raise err("ERR_INVALID_SESSION_TRANSITION", "lock-roster only valid from DRAFT")
        if not _students_for(sid):
            raise err("ERR_EMPTY_ROSTER", "Cannot lock an empty roster")
        session["status"] = "ROSTER_LOCKED"
        store.touch(session)
    return object_response(store.serialize(session))


@bp.route("/api/picture-day-sessions/<sid>/open-capture", methods=["POST"])
def open_capture(sid):
    _uid, role = get_user_context()
    require_role(role, ["StudioPhotographer"])
    with db.LOCK:
        session = store.get_session(sid)
        if session["status"] != "ROSTER_LOCKED":
            raise err("ERR_INVALID_SESSION_TRANSITION", "open-capture only valid from ROSTER_LOCKED")
        has_active = any(
            p["picture_day_session_id"] == sid and p["active"]
            for p in db.packages.values()
        )
        if not has_active:
            raise err("ERR_EMPTY_CATALOG", "No active package item in catalog")
        session["status"] = "CAPTURE_OPEN"
        store.touch(session)
    return object_response(store.serialize(session))


@bp.route("/api/picture-day-sessions/<sid>/open-gallery", methods=["POST"])
def open_gallery(sid):
    _uid, role = get_user_context()
    require_role(role, ["SchoolCoordinator"])
    with db.LOCK:
        session = store.get_session(sid)
        if session["status"] != "CAPTURE_OPEN":
            raise err("ERR_INVALID_SESSION_TRANSITION", "open-gallery only valid from CAPTURE_OPEN")
        if any(s["status"] == "ENROLLED" for s in _students_for(sid)):
            raise err("ERR_CAPTURE_INCOMPLETE", "Some students are still ENROLLED")
        if any(p["status"] == "RETAKE_REQUESTED" for p in _photos_for(sid)):
            raise err("ERR_RETAKE_PENDING", "A photo is awaiting retake")
        session["status"] = "GALLERY_OPEN"
        session["gallery_access_code"] = _mint_access_code()
        session["gallery_opens_at"] = db.format_iso(db.clock_now())
        store.touch(session)
    return object_response(store.serialize(session))


@bp.route("/api/picture-day-sessions/<sid>/close-ordering", methods=["POST"])
def close_ordering(sid):
    _uid, role = get_user_context()
    require_role(role, ["SchoolCoordinator"])
    with db.LOCK:
        session = store.get_session(sid)
        if session["status"] != "GALLERY_OPEN":
            raise err("ERR_INVALID_SESSION_TRANSITION", "close-ordering only valid from GALLERY_OPEN")
        if any(o["status"] == "SUBMITTED" for o in _orders_for(sid)):
            raise err("ERR_OPEN_ORDERS_EXIST", "A submitted order is still open")
        session["status"] = "ORDERING_CLOSED"
        store.touch(session)
    return object_response(store.serialize(session))


@bp.route("/api/picture-day-sessions/<sid>/settle", methods=["POST"])
def settle(sid):
    _uid, role = get_user_context()
    require_role(role, ["SchoolCoordinator"])
    body = get_body()
    require_fields(body, ["expected_picture_day_session_version"])
    expected = require_int(body, "expected_picture_day_session_version")

    with db.LOCK:
        session = store.get_session(sid)
        if session["status"] != "ORDERING_CLOSED":
            raise err("ERR_INVALID_SESSION_TRANSITION", "settle only valid from ORDERING_CLOSED")
        # OCC check (priority 13, after structural checks).
        if expected != session["version"]:
            raise err("ERR_STALE_SESSION_VERSION", "Session version is stale")
        orders = _orders_for(sid)
        # Every PAID order must have a non-VOIDED shipment.
        for o in orders:
            if o["status"] == "PAID":
                live = any(
                    sh["photo_order_id"] == o["id"] and sh["status"] != "VOIDED"
                    for sh in db.shipments.values()
                )
                if not live:
                    raise err("ERR_UNSHIPPED_ORDERS", "A paid order has no live shipment")
        ledger.reconcile_final_commission(session, orders)
        session["status"] = "SETTLED"
        store.touch(session)
    return object_response(store.serialize(session))


@bp.route("/api/picture-day-sessions/<sid>/cancel", methods=["POST"])
def cancel_session(sid):
    _uid, role = get_user_context()
    require_role(role, ["SchoolCoordinator"])
    with db.LOCK:
        session = store.get_session(sid)
        if session["status"] not in ("DRAFT", "ROSTER_LOCKED", "CAPTURE_OPEN"):
            raise err("ERR_INVALID_SESSION_TRANSITION", "cancel only valid from DRAFT/ROSTER_LOCKED/CAPTURE_OPEN")
        if any(o["status"] in ("PAID", "FULFILLED") for o in _orders_for(sid)):
            raise err("ERR_PAID_ORDERS_EXIST", "A paid or fulfilled order blocks cancellation")

        # Cascade: cancel REQUESTED/APPROVED retouch orders for this session's
        # photos; release reserved credit for APPROVED ones; revert RETAKE photos.
        session_photo_ids = {p["id"] for p in _photos_for(sid)}
        for r in db.retouch_orders.values():
            if r["photo_id"] not in session_photo_ids:
                continue
            if r["status"] in ("REQUESTED", "APPROVED"):
                if r["status"] == "APPROVED":
                    ledger.release_retouch_credit(session, r["net_cost_cents"])
                if r["kind"] == "RETAKE":
                    photo = db.photos.get(r["photo_id"])
                    if photo is not None and photo["status"] == "RETAKE_REQUESTED":
                        photo["status"] = "MATCHED"
                        store.touch(photo)
                r["status"] = "CANCELLED"
                store.touch(r)

        # Cascade: cancel SCHEDULED capture slots.
        for slot in db.capture_slots.values():
            if slot["picture_day_session_id"] == sid and slot["status"] == "SCHEDULED":
                slot["status"] = "CANCELLED"
                store.touch(slot)

        session["status"] = "CANCELLED"
        store.touch(session)
    return object_response(store.serialize(session))


# ---------------------------------------------------------------------------
# Gallery / yearbook
# ---------------------------------------------------------------------------
@bp.route("/api/picture-day-sessions/<sid>/gallery", methods=["GET"])
def gallery(sid):
    _uid, role = get_user_context()
    require_role(role, ["Guardian", "SchoolCoordinator", "StudioPhotographer", "FulfillmentClerk"])
    session = store.get_session(sid)
    from flask import request
    limit, offset = parse_pagination()
    access_code = request.args.get("access_code")

    closes_at = session.get("gallery_closes_at")
    valid_code = (
        session.get("gallery_access_code") is not None
        and access_code == session["gallery_access_code"]
    )
    not_expired = False
    if closes_at is not None:
        try:
            from datetime import datetime, timezone
            closes_dt = datetime.fromisoformat(closes_at.replace("Z", "+00:00"))
            if closes_dt.tzinfo is None:
                closes_dt = closes_dt.replace(tzinfo=timezone.utc)
            not_expired = db.clock_now() < closes_dt
        except ValueError:
            not_expired = False
    if not (valid_code and not_expired):
        raise err("ERR_GALLERY_ACCESS_DENIED", "Invalid or expired gallery access code")

    rows = [p for p in _photos_for(sid) if p["status"] == "APPROVED"]
    rows = sort_by_creation(rows)
    page, total = paginate(rows, limit, offset)
    return array_response([store.serialize(p) for p in page], limit, offset, total)


@bp.route("/api/picture-day-sessions/<sid>/yearbook-export", methods=["GET"])
def yearbook_export(sid):
    _uid, role = get_user_context()
    require_role(role, ["SchoolCoordinator"])
    limit, offset = parse_pagination()
    with db.LOCK:
        session = store.get_session(sid)
        rows = [p for p in _photos_for(sid) if p["status"] == "APPROVED"]
        rows = sort_by_creation(rows)
        page, total = paginate(rows, limit, offset)
        # Side effect: mark each returned photo exported.
        for p in page:
            if not p["yearbook_exported"]:
                p["yearbook_exported"] = True
                store.touch(p)
        result = [store.serialize(p) for p in page]
    return array_response(result, limit, offset, total)
