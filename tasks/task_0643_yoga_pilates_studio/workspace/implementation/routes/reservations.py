"""Reservation endpoints: book (OCC + capacity resolution), check-in, cancel."""
from datetime import timedelta

from flask import Blueprint, request

import constants as C
from db import store
from errors import err
from clock import parse_iso
from middleware import authenticate, require_roles
from models import make_reservation, serialize, touch
from response import success, list_success
from helpers import (get_json_body, parse_pagination, paginate, find_or_404)
from services import (recompute_session_counts, recompute_session_posture,
                      effective_capacity, charge_credit, refund_credit,
                      raise_fee, promote_waitlist_head, repack_waitlist)

bp = Blueprint("reservations", __name__)


@bp.post("/reservations")
def book_reservation():
    principal = authenticate()
    require_roles(principal, {"Member", "StudioManager"})
    body = get_json_body()

    member_id = body.get("member_id")
    class_session_id = body.get("class_session_id")
    entitlement_id = body.get("entitlement_id")
    if not isinstance(member_id, str) or not member_id:
        raise err("ERR_INVALID_REQUEST", "member_id is required")
    if not isinstance(class_session_id, str) or not class_session_id:
        raise err("ERR_INVALID_REQUEST", "class_session_id is required")
    if not isinstance(entitlement_id, str) or not entitlement_id:
        raise err("ERR_INVALID_REQUEST", "entitlement_id is required")

    # Existence left-to-right: member, session, entitlement.
    member = find_or_404(store.members, member_id, "Member")
    session = find_or_404(store.class_sessions, class_session_id, "ClassSession")
    ent = find_or_404(store.entitlements, entitlement_id, "Entitlement")

    # Ownership: a Member books only for themselves.
    if principal.is_member and principal.user_id != member_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "Members may only book for themselves")

    # OCC (priority 6): expected_class_session_version mandatory.
    if "expected_class_session_version" not in body or body["expected_class_session_version"] is None:
        raise err("ERR_VERSION_REQUIRED", "expected_class_session_version is required")
    expected = body["expected_class_session_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise err("ERR_INVALID_REQUEST", "expected_class_session_version must be an integer")
    if expected != session["version"]:
        raise err("ERR_STALE_VERSION", "Session version mismatch")

    # Member standing (priority 7).
    if member["account_status"] != "ACTIVE":
        raise err("ERR_MEMBER_SUSPENDED", "Member account is SUSPENDED")

    # Entitlement usability (priority 8): owned by member, ACTIVE, UNFROZEN.
    if ent["member_id"] != member_id \
            or ent["lifecycle_status"] != "ACTIVE" \
            or ent["freeze_status"] != "UNFROZEN":
        raise err("ERR_ENTITLEMENT_NOT_USABLE", "Entitlement is not usable")

    # Finite-credit availability (priority 14).
    if ent["credits_total"] != -1 and ent["credits_remaining"] < 1:
        raise err("ERR_NO_CREDITS_REMAINING", "No credits remaining")

    # Bookability by clock + state (priority 17): clock < start_utc, not in-progress/terminal.
    recompute_session_counts(session)
    if session["status"] in ("IN_PROGRESS", "COMPLETED", "CANCELLED"):
        raise err("ERR_SESSION_NOT_BOOKABLE", "Session is not bookable")
    if store.clock.now() >= parse_iso(session["start_utc"]):
        raise err("ERR_SESSION_NOT_BOOKABLE", "Session has already started")

    # Capacity resolution.
    cap = effective_capacity(session)
    open_seats = max(0, cap - session["booked_count"])
    now_iso = store.now_iso()

    if open_seats >= 1:
        res = make_reservation(member_id, class_session_id, entitlement_id,
                               "BOOKED", None, True, now_iso)
        store.reservations[res["id"]] = res
        charge_credit(ent)
        recompute_session_counts(session)
        # Booking bumps session version (OCC) and recomputes posture.
        if session["booked_count"] >= cap and session["status"] == "OPEN":
            session["status"] = "FULL"
        touch(session)
        return success(serialize(res), status=201)

    # No open seats: waitlist if room remains (priority 15).
    if session["waitlisted_count"] < session["waitlist_capacity"]:
        position = session["waitlisted_count"] + 1
        res = make_reservation(member_id, class_session_id, entitlement_id,
                               "WAITLISTED", position, True, now_iso)
        store.reservations[res["id"]] = res
        charge_credit(ent)
        recompute_session_counts(session)
        touch(session)
        return success(serialize(res), status=201)

    raise err("ERR_WAITLIST_FULL", "Waitlist is full")


@bp.get("/reservations/<rid>")
def get_reservation(rid):
    principal = authenticate()
    require_roles(principal, {"StudioManager", "Member"})
    res = find_or_404(store.reservations, rid, "Reservation")
    if principal.is_member and principal.user_id != res["member_id"]:
        raise err("ERR_NOT_RESOURCE_OWNER", "Members may only fetch their own reservations")
    return success(serialize(res))


@bp.get("/reservations")
def list_reservations():
    principal = authenticate()
    require_roles(principal, {"StudioManager", "Member"})
    limit, offset = parse_pagination()
    items = list(store.reservations.values())
    # Members only see their own; scoping by member_id filter or implicit own-only.
    if principal.is_member:
        items = [r for r in items if r["member_id"] == principal.user_id]
    for key in ("member_id", "class_session_id", "entitlement_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [r for r in items if r.get(key) == val]
    window, total = paginate(items, limit, offset)
    return list_success([serialize(r) for r in window], 200, limit, offset, total)


@bp.post("/reservations/<rid>/check-in")
def check_in(rid):
    principal = authenticate()
    require_roles(principal, {"Member", "StudioManager"})
    res = find_or_404(store.reservations, rid, "Reservation")
    if principal.is_member and principal.user_id != res["member_id"]:
        raise err("ERR_NOT_RESOURCE_OWNER", "Members may only check in their own reservations")
    session = store.class_sessions.get(res["class_session_id"])
    if res["status"] != "BOOKED":
        raise err("ERR_INVALID_STATE", "Reservation is not BOOKED")
    if session is None or session["status"] != "IN_PROGRESS":
        raise err("ERR_INVALID_STATE", "Session is not IN_PROGRESS")
    res["status"] = "CHECKED_IN"
    touch(res)
    return success(serialize(res))


@bp.post("/reservations/<rid>/cancel")
def cancel_reservation(rid):
    principal = authenticate()
    require_roles(principal, {"Member", "StudioManager"})
    res = find_or_404(store.reservations, rid, "Reservation")
    if principal.is_member and principal.user_id != res["member_id"]:
        raise err("ERR_NOT_RESOURCE_OWNER", "Members may only cancel their own reservations")

    session = store.class_sessions.get(res["class_session_id"])
    ent = store.entitlements.get(res["entitlement_id"])
    member = store.members.get(res["member_id"])

    if res["status"] == "WAITLISTED":
        # WAITLISTED cancel any time -> CANCELLED_EARLY; refund held credit; re-pack queue.
        res["status"] = "CANCELLED_EARLY"
        if res["credit_charged"] and ent is not None:
            refund_credit(ent)
        res["credit_charged"] = False
        res["waitlist_position"] = None
        touch(res)
        if session is not None:
            repack_waitlist(session["id"])
            recompute_session_counts(session)
            recompute_session_posture(session)
        return success(serialize(res))

    if res["status"] != "BOOKED":
        raise err("ERR_INVALID_STATE", "Reservation cannot be cancelled from its current state")

    # BOOKED: classify EARLY vs LATE by the late-cancel window.
    cutoff = parse_iso(session["start_utc"]) - timedelta(hours=C.LATE_CANCEL_WINDOW_HOURS)
    now = store.clock.now()

    if now < cutoff:
        # EARLY: refund credit, auto-promote waitlist head.
        res["status"] = "CANCELLED_EARLY"
        if res["credit_charged"] and ent is not None:
            refund_credit(ent)
        res["credit_charged"] = False
        touch(res)
        recompute_session_counts(session)
        recompute_session_posture(session)
        promote_waitlist_head(session)
        return success(serialize(res))

    # LATE: permitted only while session is OPEN or FULL.
    if session["status"] not in ("OPEN", "FULL"):
        raise err("ERR_INVALID_STATE", "Late cancel only permitted while session is OPEN/FULL")
    res["status"] = "CANCELLED_LATE"
    # Fee assessed (strikes read before; late cancel does NOT increment strikes).
    if member is not None:
        raise_fee(member, res, "LATE_CANCEL")
    # Credit forfeited (not refunded).
    touch(res)
    recompute_session_counts(session)
    recompute_session_posture(session)
    promote_waitlist_head(session)
    return success(serialize(res))
