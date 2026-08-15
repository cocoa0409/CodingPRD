"""WaitlistEntry endpoints: join, list, get, claim, decline-offer, withdraw."""

from flask import Blueprint, request

import db
import errors
import middleware
import response
import serializers
import util
from services import core

bp = Blueprint("waitlist", __name__)

WAITLIST_ROLES = {"SchoolAdmin", "FrontOfficeStaff", "FamilyGuardian"}


@bp.route("/conf/waitlist-entries", methods=["POST"])
def create_entry():
    role, uid = middleware.get_auth()
    middleware.require_roles(role, WAITLIST_ROLES)
    body = util.get_body()
    util.require_fields(body, ["window_id", "student_id", "teacher_id", "channel_pref"])
    window_id = body["window_id"]
    student_id = body["student_id"]
    teacher_id = body["teacher_id"]
    for f in (window_id, student_id, teacher_id):
        if not isinstance(f, str):
            raise errors.validation("window_id, student_id and teacher_id must be strings")
    channel_pref = util.require_enum(body, "channel_pref", {"IN_PERSON", "VIRTUAL", "EITHER"})

    window = core.get_window_or_404(window_id)
    student = core.get_student_or_404(student_id)
    teacher = core.get_teacher_or_404(teacher_id)
    family = core.get_family_or_404(student["family_id"])

    # Ownership (p3)
    middleware.check_family_owns(role, uid, family["id"])

    # Window state (p7)
    if window["status"] != "BOOKING_OPEN":
        raise errors.invalid_window_state("waitlist join requires BOOKING_OPEN")

    # Entity state (p8): family restriction (staff bypass)
    if role == "FamilyGuardian" and family["status"] != "ACTIVE":
        raise errors.family_restricted()

    # Referential (p12): student enrolled + link
    if student["enrollment_status"] != "ENROLLED":
        raise errors.student_not_bookable()
    link = core.find_link(student_id, teacher_id)
    if link is None:
        raise errors.teacher_not_linked()
    if window["format"] == "ELEMENTARY" and link["is_homeroom"] is False:
        raise errors.teacher_not_linked()

    # Uniqueness (p11): one WAITING|OFFERED per (student, teacher, window);
    # none when a CONFIRMED booking exists for the pair
    for e in db.waitlist_entries.values():
        if (e["student_id"] == student_id and e["teacher_id"] == teacher_id
                and e["window_id"] == window_id and e["status"] in ("WAITING", "OFFERED")):
            raise errors.duplicate_waitlist_entry()
    for b in db.bookings.values():
        if (b["student_id"] == student_id and b["teacher_id"] == teacher_id
                and b["window_id"] == window_id and b["status"] == "CONFIRMED"):
            raise errors.duplicate_waitlist_entry()

    now = util.now_iso()
    entry = {
        "id": util.new_id(),
        "window_id": window_id,
        "family_id": family["id"],
        "student_id": student_id,
        "teacher_id": teacher_id,
        "channel_pref": channel_pref,
        "status": "WAITING",
        "offers_made_count": 0,
        "offered_slot_id": None,
        "offer_expires_at": None,
        "declined_slot_ids": [],
        "priority_score": 0.0,
        "created_seq": db.next_seq(),
        "created_at": now,
        # Logical-clock reading at creation; the patience term measures elapsed
        # logical time from this point (created_at itself is wall-clock).
        "created_clock": db.logical_clock,
        "updated_at": now,
        "version": 1,
    }
    # At creation the patience (wait) term is zero: the entry has just been
    # created, so elapsed time is measured from this moment onward and only
    # accrues on later refreshes (run-ops).
    entry["priority_score"] = core.compute_priority_score(entry, include_wait_bonus=False)
    db.waitlist_entries[entry["id"]] = entry
    return response.success_object(serializers.waitlist_view(entry), status=201)


@bp.route("/conf/waitlist-entries", methods=["GET"])
def list_entries():
    role, uid = middleware.get_auth()
    middleware.require_roles(role, WAITLIST_ROLES)
    limit, offset = util.parse_pagination(request.args)
    filters = {
        "window_id": request.args.get("window_id"),
        "family_id": request.args.get("family_id"),
        "student_id": request.args.get("student_id"),
        "teacher_id": request.args.get("teacher_id"),
        "offered_slot_id": request.args.get("offered_slot_id"),
        "status": request.args.get("status"),
    }
    items = list(db.waitlist_entries.values())
    if role == "FamilyGuardian":
        items = [e for e in items if e["family_id"] == uid]
    for key, value in filters.items():
        if value is not None:
            items = [e for e in items if e.get(key) == value]
    items.sort(key=lambda e: e["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return response.success_list([serializers.waitlist_view(e) for e in page],
                                 total, limit, offset)


@bp.route("/conf/waitlist-entries/<eid>", methods=["GET"])
def get_entry(eid):
    role, uid = middleware.get_auth()
    middleware.require_roles(role, WAITLIST_ROLES)
    entry = core.get_entry_or_404(eid)
    middleware.check_family_owns(role, uid, entry["family_id"])
    return response.success_object(serializers.waitlist_view(entry))


@bp.route("/conf/waitlist-entries/<eid>/claim", methods=["POST"])
def claim_entry(eid):
    role, uid = middleware.get_auth()
    middleware.require_roles(role, WAITLIST_ROLES)
    body = util.get_body()
    entry = core.get_entry_or_404(eid)
    middleware.check_family_owns(role, uid, entry["family_id"])

    if entry["status"] != "OFFERED":
        raise errors.no_active_offer()
    if util.clock_dt() > util.parse_dt(entry["offer_expires_at"]):
        raise errors.offer_expired()

    slot = core.get_slot_or_404(entry["offered_slot_id"])
    window = core.get_window_or_404(entry["window_id"])
    student = core.get_student_or_404(entry["student_id"])
    teacher = core.get_teacher_or_404(entry["teacher_id"])
    family = core.get_family_or_404(entry["family_id"])

    if role == "FamilyGuardian" and family["status"] != "ACTIVE":
        raise errors.family_restricted()

    if slot["status"] != "HELD":
        raise errors.slot_not_available("offered slot is no longer held")

    # Channel: explicit input wins, else the entry's preference constrained by the slot
    channel = body.get("channel")
    if channel is not None:
        channel = util.require_enum(body, "channel", {"IN_PERSON", "VIRTUAL"})
    else:
        channel = core._offer_channel_for_entry(slot, entry)

    # Booking validations re-run against the offered slot (slot is HELD, so we
    # bypass the OPEN-only check and validate the remaining battery manually)
    if teacher["status"] != "ACTIVE":
        raise errors.teacher_inactive()
    if student["enrollment_status"] != "ENROLLED":
        raise errors.student_not_bookable()
    if core.family_gap_conflict(family["id"], window["id"], slot, channel):
        raise errors.family_schedule_conflict()
    for b in db.bookings.values():
        if b["window_id"] != window["id"] or b["status"] != "CONFIRMED":
            continue
        if b["student_id"] == student["id"] and b["teacher_id"] == teacher["id"]:
            raise errors.duplicate_booking()
        if window["format"] == "ELEMENTARY" and b["student_id"] == student["id"]:
            raise errors.duplicate_booking()
    if not core.channel_compatible(slot, teacher, channel):
        raise errors.channel_not_allowed()
    link = core.find_link(student["id"], teacher["id"])
    if link is None or (window["format"] == "ELEMENTARY" and link["is_homeroom"] is False):
        raise errors.teacher_not_linked()
    effective_cap = window["teacher_daily_conf_cap"]
    if teacher["daily_conf_cap_override"] is not None:
        effective_cap = min(effective_cap, teacher["daily_conf_cap_override"])
    if core.teacher_daily_confirmed_count(teacher["id"], window["id"], slot["day_label"]) >= effective_cap:
        raise errors.teacher_day_full()
    if core.family_confirmed_count(family["id"], window["id"]) >= window["family_conf_cap"]:
        raise errors.family_limit_reached()

    interpreter_language = util.optional_string(body, "interpreter_language", default=None)

    booked_by_role = "FAMILY_SELF" if role == "FamilyGuardian" else "FRONT_OFFICE"
    booking = core.create_booking(window, slot, student, channel, booked_by_role,
                                  interpreter_language)
    entry["status"] = "CLAIMED"
    entry["version"] += 1
    entry["updated_at"] = util.now_iso()
    return response.success_object(serializers.booking_view(booking), status=201)


@bp.route("/conf/waitlist-entries/<eid>/decline-offer", methods=["POST"])
def decline_offer(eid):
    role, uid = middleware.get_auth()
    middleware.require_roles(role, WAITLIST_ROLES)
    util.get_body()
    entry = core.get_entry_or_404(eid)
    middleware.check_family_owns(role, uid, entry["family_id"])
    if entry["status"] != "OFFERED":
        raise errors.no_active_offer()
    core.release_offer(entry)
    return response.success_object(serializers.waitlist_view(entry))


@bp.route("/conf/waitlist-entries/<eid>/withdraw", methods=["POST"])
def withdraw_entry_route(eid):
    role, uid = middleware.get_auth()
    middleware.require_roles(role, WAITLIST_ROLES)
    util.get_body()  # optional reason
    entry = core.get_entry_or_404(eid)
    middleware.check_family_owns(role, uid, entry["family_id"])
    if entry["status"] not in ("WAITING", "OFFERED"):
        raise errors.invalid_state("only WAITING or OFFERED entries can be withdrawn")
    core.withdraw_entry(entry)
    return response.success_object(serializers.waitlist_view(entry))
