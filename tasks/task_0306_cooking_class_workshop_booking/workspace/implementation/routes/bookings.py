"""Booking, WaitlistEntry, and SubstitutionRequest routes."""
from flask import Blueprint, request

import db
from errors import err
from helpers import (
    get_json_body, require_fields, require_string, require_int, serialize,
    stamp_create, touch, get_pagination, paginate, sort_by_created,
)
from lookups import (
    get_session, get_member, get_booking, get_waitlist_entry, get_substitution,
    get_ingredient_line, require_booking_owner, require_waitlist_owner,
    require_session_owner,
)
from middleware import authenticate, require_role
from response import success, list_success
from services import calc, engine

bp = Blueprint("bookings", __name__)


# ============================ Booking ============================
@bp.route("/culinary/bookings", methods=["POST"])
def create_booking():
    p = authenticate()
    require_role(p, ["Member", "StudioAdmin"])
    body = get_json_body()
    require_fields(body, ["session_id", "member_id", "seats_requested"])
    session_id = require_string(body, "session_id")
    member_id = require_string(body, "member_id")
    seats = require_int(body, "seats_requested", minimum=1, maximum=40)
    # existence (left-to-right): session then member
    sess = get_session(session_id)
    member = get_member(member_id)
    # Member ownership: a Member may only create its own booking
    if p.role == "Member" and member_id != p.user_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "Member may only create own booking")
    # private buyout rule (priority 20)
    if sess["event_type"] == "PRIVATE" and seats != sess["planned_seats"]:
        raise err("ERR_PRIVATE_REQUIRES_FULL_BUYOUT", "PRIVATE booking must buy out all seats")
    tmpl = db.templates[sess["template_id"]]
    charge = calc.booking_charge(sess, tmpl, seats)
    obj = {
        "session_id": session_id,
        "member_id": member_id,
        "seats_requested": seats,
        "charge_cents": charge,
        "gift_card_applied_cents": 0,
        "wallet_applied_cents": 0,
        "card_applied_cents": 0,
        "refund_cents": 0,
        "refilled_from_waitlist": False,
        "lifecycle_status": "PENDING",
        "payment_status": "UNPAID",
    }
    stamp_create(obj)
    db.bookings[obj["id"]] = obj
    return success(serialize(obj), status=201)


@bp.route("/culinary/bookings/<rid>/confirm", methods=["POST"])
def confirm_booking(rid):
    p = authenticate()
    require_role(p, ["Member"])
    booking = get_booking(rid)
    require_booking_owner(p, booking)
    body = get_json_body()
    require_fields(body, ["expected_session_version"])
    expected_version = require_int(body, "expected_session_version")
    sess = db.sessions[booking["session_id"]]
    member = db.members[booking["member_id"]]
    # state validity (priority 6)
    if booking["lifecycle_status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "Booking not in PENDING")
    if sess["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Session not OPEN")
    # OCC (priority 7) before any seat/business arithmetic
    if sess["version"] != expected_version:
        raise err("ERR_STALE_SESSION_VERSION", "Session version is stale")
    # member blocked (priority 11)
    if member["booking_status"] != "GOOD_STANDING":
        raise err("ERR_MEMBER_BLOCKED", "Member is BLOCKED")
    # gift-card ownership (priority 13): every ACTIVE gift card consulted is the member's;
    # by construction the waterfall only consults the member's own cards, so this holds.
    # seat fit (priority 21)
    if sess["confirmed_seats"] + booking["seats_requested"] > sess["planned_seats"]:
        raise err("ERR_INSUFFICIENT_SEATS", "Seat block does not fit")
    # success: payment waterfall
    gc_a, w_a, c_a = engine.run_payment_waterfall(member, booking["charge_cents"], booking["id"])
    booking["gift_card_applied_cents"] = gc_a
    booking["wallet_applied_cents"] = w_a
    booking["card_applied_cents"] = c_a
    booking["lifecycle_status"] = "CONFIRMED"
    booking["payment_status"] = "PAID"
    touch(booking)
    sess["confirmed_seats"] += booking["seats_requested"]
    calc.refresh_prep_cost(sess)
    sess["version"] = sess.get("version", 1) + 1
    sess["updated_at"] = db.iso_now()
    if sess["confirmed_seats"] == sess["planned_seats"] and sess["status"] == "OPEN":
        sess["status"] = "FULL"
    return success(serialize(booking))


@bp.route("/culinary/bookings/<rid>/cancel", methods=["POST"])
def cancel_booking(rid):
    p = authenticate()
    require_role(p, ["Member"])
    booking = get_booking(rid)
    require_booking_owner(p, booking)
    sess = db.sessions[booking["session_id"]]
    if booking["lifecycle_status"] == "PENDING":
        booking["lifecycle_status"] = "CANCELLED"
        booking["refund_cents"] = 0
        touch(booking)
        return success(serialize(booking))
    if booking["lifecycle_status"] != "CONFIRMED":
        raise err("ERR_INVALID_STATE", "Booking not CONFIRMED or PENDING")
    if sess["status"] not in ("OPEN", "FULL"):
        raise err("ERR_INVALID_STATE", "Session not OPEN or FULL")
    engine.cancel_confirmed_booking(booking, sess)
    return success(serialize(booking))


@bp.route("/culinary/bookings/<rid>/mark-no-show", methods=["POST"])
def mark_no_show(rid):
    p = authenticate()
    require_role(p, ["Instructor"])
    booking = get_booking(rid)
    sess = db.sessions[booking["session_id"]]
    require_session_owner(p, sess)
    if booking["lifecycle_status"] != "CONFIRMED":
        raise err("ERR_INVALID_STATE", "Booking not CONFIRMED")
    if sess["status"] != "LOCKED":
        raise err("ERR_INVALID_STATE", "Session not LOCKED")
    member = db.members[booking["member_id"]]
    engine._create_strike(member, booking, "NO_SHOW")
    booking["lifecycle_status"] = "NO_SHOW"
    booking["refund_cents"] = 0
    touch(booking)
    return success(serialize(booking))


@bp.route("/culinary/bookings/<rid>", methods=["GET"])
def get_booking_route(rid):
    p = authenticate()
    require_role(p, ["StudioAdmin", "Instructor", "Member"])
    return success(serialize(get_booking(rid)))


@bp.route("/culinary/bookings", methods=["GET"])
def list_bookings():
    p = authenticate()
    require_role(p, ["StudioAdmin", "Instructor", "Member"])
    rows = list(db.bookings.values())
    for key in ("session_id", "member_id", "lifecycle_status"):
        val = request.args.get(key)
        if val is not None:
            rows = [r for r in rows if r.get(key) == val]
    rows = sort_by_created(rows)
    limit, offset = get_pagination()
    page, total = paginate(rows, limit, offset)
    return list_success([serialize(r) for r in page], limit, offset, total)


# ============================ WaitlistEntry ============================
@bp.route("/culinary/sessions/<rid>/waitlist", methods=["POST"])
def join_waitlist(rid):
    p = authenticate()
    require_role(p, ["Member"])
    sess = get_session(rid)
    body = get_json_body()
    require_fields(body, ["member_id", "seats_requested"])
    member_id = require_string(body, "member_id")
    seats = require_int(body, "seats_requested", minimum=1, maximum=40)
    get_member(member_id)
    if p.role == "Member" and member_id != p.user_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "Member may only join own waitlist entry")
    # waitlist allowed (priority 24): session FULL and no existing WAITING/CONFIRMED
    if sess["status"] != "FULL":
        raise err("ERR_WAITLIST_NOT_ALLOWED", "Session is not FULL")
    for w in db.waitlist_entries.values():
        if w["session_id"] == sess["id"] and w["member_id"] == member_id and w["queue_status"] == "WAITING":
            raise err("ERR_WAITLIST_NOT_ALLOWED", "Member already WAITING on this session")
    for b in db.bookings.values():
        if b["session_id"] == sess["id"] and b["member_id"] == member_id and b["lifecycle_status"] == "CONFIRMED":
            raise err("ERR_WAITLIST_NOT_ALLOWED", "Member already CONFIRMED on this session")
    obj = {
        "session_id": sess["id"],
        "member_id": member_id,
        "seats_requested": seats,
        "queue_status": "WAITING",
        "promoted_booking_id": None,
    }
    stamp_create(obj)
    db.waitlist_entries[obj["id"]] = obj
    return success(serialize(obj), status=201)


@bp.route("/culinary/waitlist-entries/<rid>/withdraw", methods=["POST"])
def withdraw_waitlist(rid):
    p = authenticate()
    require_role(p, ["Member"])
    entry = get_waitlist_entry(rid)
    require_waitlist_owner(p, entry)
    if entry["queue_status"] != "WAITING":
        raise err("ERR_INVALID_STATE", "Waitlist entry not WAITING")
    entry["queue_status"] = "WITHDRAWN"
    touch(entry)
    return success(serialize(entry))


@bp.route("/culinary/sessions/<rid>/waitlist", methods=["GET"])
def list_session_waitlist(rid):
    p = authenticate()
    require_role(p, ["StudioAdmin", "Instructor", "Member"])
    get_session(rid)
    rows = [w for w in db.waitlist_entries.values() if w["session_id"] == rid]
    rows = sort_by_created(rows)
    limit, offset = get_pagination()
    page, total = paginate(rows, limit, offset)
    return list_success([serialize(r) for r in page], limit, offset, total)


@bp.route("/culinary/waitlist-entries/<rid>", methods=["GET"])
def get_waitlist_route(rid):
    p = authenticate()
    require_role(p, ["StudioAdmin", "Instructor", "Member"])
    return success(serialize(get_waitlist_entry(rid)))


@bp.route("/culinary/waitlist-entries", methods=["GET"])
def list_waitlist():
    p = authenticate()
    require_role(p, ["StudioAdmin", "Member"])
    rows = list(db.waitlist_entries.values())
    for key in ("member_id", "session_id", "promoted_booking_id", "queue_status"):
        val = request.args.get(key)
        if val is not None:
            rows = [r for r in rows if r.get(key) == val]
    rows = sort_by_created(rows)
    limit, offset = get_pagination()
    page, total = paginate(rows, limit, offset)
    return list_success([serialize(r) for r in page], limit, offset, total)


# ============================ SubstitutionRequest ============================
@bp.route("/culinary/substitutions", methods=["POST"])
def create_substitution():
    p = authenticate()
    require_role(p, ["Member"])
    body = get_json_body()
    require_fields(body, ["booking_id", "ingredient_line_id", "alternate_unit_cost_cents"])
    booking_id = require_string(body, "booking_id")
    line_id = require_string(body, "ingredient_line_id")
    alt_cost = require_int(body, "alternate_unit_cost_cents", minimum=0)
    booking = get_booking(booking_id)
    line = get_ingredient_line(line_id)
    require_booking_owner(p, booking)
    # applicability (priority 12): line on the booking's session and not NEUTRAL
    if line["session_id"] != booking["session_id"] or line["dietary_tag"] == "NEUTRAL":
        raise err("ERR_SUBSTITUTION_NOT_APPLICABLE", "Ingredient line not applicable for substitution")
    obj = {
        "booking_id": booking_id,
        "ingredient_line_id": line_id,
        "alternate_unit_cost_cents": alt_cost,
        "surcharge_cents": 0,
        "status": "REQUESTED",
    }
    stamp_create(obj)
    db.substitutions[obj["id"]] = obj
    return success(serialize(obj), status=201)


@bp.route("/culinary/substitutions/<rid>/approve", methods=["POST"])
def approve_substitution(rid):
    p = authenticate()
    require_role(p, ["Instructor"])
    sub = get_substitution(rid)
    booking = db.bookings[sub["booking_id"]]
    sess = db.sessions[booking["session_id"]]
    require_session_owner(p, sess)
    if sub["status"] != "REQUESTED":
        raise err("ERR_INVALID_STATE", "Substitution not REQUESTED")
    if booking["lifecycle_status"] != "CONFIRMED":
        raise err("ERR_INVALID_STATE", "Parent booking not CONFIRMED")
    if sess["status"] not in ("OPEN", "FULL", "LOCKED"):
        raise err("ERR_INVALID_STATE", "Session not OPEN/FULL/LOCKED")
    line = db.ingredient_lines[sub["ingredient_line_id"]]
    if line["dietary_tag"] == "NEUTRAL":
        raise err("ERR_SUBSTITUTION_NOT_APPLICABLE", "Ingredient line is NEUTRAL")
    surcharge = calc.substitution_surcharge(sub["alternate_unit_cost_cents"], line, booking)
    sub["surcharge_cents"] = surcharge
    sub["status"] = "APPROVED"
    touch(sub)
    # settle the surcharge incrementally via the waterfall, accumulate deltas
    member = db.members[booking["member_id"]]
    booking["charge_cents"] += surcharge
    gc_a, w_a, c_a = engine.run_payment_waterfall(member, surcharge, booking["id"])
    booking["gift_card_applied_cents"] += gc_a
    booking["wallet_applied_cents"] += w_a
    booking["card_applied_cents"] += c_a
    # record per-bucket deltas so revert can compensate exactly
    sub["_gc_delta"] = gc_a
    sub["_wallet_delta"] = w_a
    sub["_card_delta"] = c_a
    touch(booking)
    return success(serialize(sub))


@bp.route("/culinary/substitutions/<rid>/reject", methods=["POST"])
def reject_substitution(rid):
    p = authenticate()
    require_role(p, ["Instructor"])
    sub = get_substitution(rid)
    booking = db.bookings[sub["booking_id"]]
    sess = db.sessions[booking["session_id"]]
    require_session_owner(p, sess)
    if sub["status"] != "REQUESTED":
        raise err("ERR_INVALID_STATE", "Substitution not REQUESTED")
    sub["status"] = "REJECTED"
    touch(sub)
    return success(serialize(sub))


@bp.route("/culinary/substitutions/<rid>/revert", methods=["POST"])
def revert_substitution(rid):
    p = authenticate()
    require_role(p, ["Instructor"])
    sub = get_substitution(rid)
    booking = db.bookings[sub["booking_id"]]
    sess = db.sessions[booking["session_id"]]
    require_session_owner(p, sess)
    if sub["status"] != "APPROVED":
        raise err("ERR_INVALID_STATE", "Substitution not APPROVED")
    if sess["status"] not in ("OPEN", "FULL", "LOCKED"):
        raise err("ERR_INVALID_STATE", "Session not OPEN/FULL/LOCKED")
    member = db.members[booking["member_id"]]
    engine.revert_substitution_payment(member, booking, sub)
    sub["status"] = "REVERTED"
    touch(sub)
    return success(serialize(sub))


@bp.route("/culinary/substitutions/<rid>", methods=["GET"])
def get_substitution_route(rid):
    p = authenticate()
    require_role(p, ["StudioAdmin", "Instructor", "Member"])
    return success(serialize(get_substitution(rid)))


@bp.route("/culinary/substitutions", methods=["GET"])
def list_substitutions():
    p = authenticate()
    require_role(p, ["StudioAdmin", "Instructor", "Member"])
    rows = list(db.substitutions.values())
    for key in ("booking_id", "ingredient_line_id", "status"):
        val = request.args.get(key)
        if val is not None:
            rows = [r for r in rows if r.get(key) == val]
    rows = sort_by_created(rows)
    limit, offset = get_pagination()
    page, total = paginate(rows, limit, offset)
    return list_success([serialize(r) for r in page], limit, offset, total)
