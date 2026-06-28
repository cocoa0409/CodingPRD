"""Booking endpoints + booking transitions (PRD §3.4, §3.5)."""

from flask import Blueprint, g, request

import errors
from db import db, new_id, now_ts
from clock import clock, parse_iso8601
from helpers import (get_json_body, require_fields, parse_required_datetime,
                     pagination_params, paginate)
from middleware import require_roles
from response import success, list_success
from serializers import booking_view
from services import domain
from services import calculations as calc

bp = Blueprint("bookings", __name__)


def _booking_client(booking):
    eng = db.engagements.get(booking["engagement_id"])
    return db.clients.get(eng["client_id"]) if eng else None


@bp.route("/bookings", methods=["POST"])
@require_roles("Trainer", "Client")
def create_booking():
    body = get_json_body()
    require_fields(body, "engagement_id", "start_utc", "end_utc")

    # Priority 4: FK existence — engagement, then pack if supplied.
    engagement = domain.get_engagement(body["engagement_id"])
    domain.assert_owns_engagement(engagement)

    session_pack_id = body.get("session_pack_id")
    pack = None
    if session_pack_id is not None:
        pack = domain.get_pack(session_pack_id)

    # Priority 5: body well-formedness (datetimes, end > start).
    start = parse_required_datetime(body["start_utc"], "start_utc")
    end = parse_required_datetime(body["end_utc"], "end_utc")
    if not (end > start):
        raise errors.invalid_request("end_utc must be strictly after start_utc")

    client = db.clients.get(engagement["client_id"])

    # Priority 9 (PRD §3.4 order): engagement must be ACTIVE.
    if engagement["status"] != "ACTIVE":
        raise errors.invalid_state(errors.ERR_ENGAGEMENT_NOT_ACTIVE, "Engagement is not ACTIVE")

    # Priority 8: billing-model / pack-ownership fit (independent of seats).
    if engagement["billing_model"] == "SESSION_PACK":
        if session_pack_id is None:
            raise errors.invalid_state(errors.ERR_PACK_MODEL_MISMATCH,
                                       "SESSION_PACK booking requires session_pack_id")
        if pack["engagement_id"] != engagement["id"]:
            raise errors.invalid_state(errors.ERR_PACK_MODEL_MISMATCH,
                                       "Pack does not belong to this engagement")
    else:  # ONLINE_SUBSCRIPTION
        if session_pack_id is not None:
            raise errors.invalid_state(errors.ERR_PACK_MODEL_MISMATCH,
                                       "ONLINE_SUBSCRIPTION booking must omit session_pack_id")

    # Priority 10: acting client's booking privilege.
    if client["booking_privilege"] == "SUSPENDED":
        raise errors.ApiError(errors.ERR_BOOKING_PRIVILEGE_SUSPENDED, 403,
                              "Client booking privilege is SUSPENDED")

    # Priority 11a then 11b: calendar geometry.
    domain.check_calendar_clear(engagement["trainer_id"], engagement["client_id"], start, end)

    # Priority 12: seat availability for SESSION_PACK.
    if engagement["billing_model"] == "SESSION_PACK":
        if pack["sessions_remaining"] <= 0:
            raise errors.invalid_state(errors.ERR_NO_SESSIONS_REMAINING,
                                       "Pack has no sessions remaining")

    # Priority 13: OCC on the pack version (required for SESSION_PACK bookings).
    if engagement["billing_model"] == "SESSION_PACK":
        require_fields(body, "expected_session_pack_version")
        expected = body["expected_session_pack_version"]
        if isinstance(expected, bool) or not isinstance(expected, int):
            raise errors.invalid_request("expected_session_pack_version must be an integer")
        if expected != pack["version"]:
            raise errors.stale_version("expected_session_pack_version does not match pack version")

    bid = new_id()
    ts = now_ts()
    booking = {
        "id": bid,
        "engagement_id": engagement["id"],
        "session_pack_id": session_pack_id,
        "trainer_id": engagement["trainer_id"],
        "start_utc": body["start_utc"] if isinstance(body["start_utc"], str) else None,
        "end_utc": body["end_utc"] if isinstance(body["end_utc"], str) else None,
        "rescheduled_from_booking_id": None,
        "fee_charged_cents": 0,
        "status": "BOOKED",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }
    # Normalize stored datetimes to canonical ISO form.
    from clock import format_iso8601_ms
    booking["start_utc"] = format_iso8601_ms(start)
    booking["end_utc"] = format_iso8601_ms(end)
    db.bookings[bid] = booking

    # Side effect: commit a seat on the pack (bumps pack version, may deplete).
    if engagement["billing_model"] == "SESSION_PACK":
        domain.apply_seat_commit(pack)

    return success(booking_view(booking), 201)


@bp.route("/bookings/<booking_id>", methods=["GET"])
@require_roles("Trainer", "Client")
def get_booking(booking_id):
    booking = domain.get_booking(booking_id)
    engagement = domain.get_engagement(booking["engagement_id"])
    domain.assert_owns_engagement(engagement)
    return success(booking_view(booking), 200)


@bp.route("/bookings", methods=["GET"])
@require_roles("Trainer", "Client", "PlatformAdmin")
def list_bookings():
    limit, offset = pagination_params()
    engagement_filter = request.args.get("engagement_id")
    pack_filter = request.args.get("session_pack_id")
    trainer_filter = request.args.get("trainer_id")
    resched_filter = request.args.get("rescheduled_from_booking_id")

    items = list(db.bookings.values())
    if engagement_filter is not None:
        items = [b for b in items if b["engagement_id"] == engagement_filter]
    if pack_filter is not None:
        items = [b for b in items if b["session_pack_id"] == pack_filter]
    if trainer_filter is not None:
        items = [b for b in items if b["trainer_id"] == trainer_filter]
    if resched_filter is not None:
        items = [b for b in items if b["rescheduled_from_booking_id"] == resched_filter]

    # Ownership scoping for entity-backed roles.
    if g.user_role == "Trainer":
        items = [b for b in items if b["trainer_id"] == g.user_id]
    elif g.user_role == "Client":
        own_eng = {e["id"] for e in db.engagements.values() if e["client_id"] == g.user_id}
        items = [b for b in items if b["engagement_id"] in own_eng]

    items.sort(key=lambda b: (b["created_at"], b["_seq"]))
    page, total = paginate(items, limit, offset)
    return list_success([booking_view(b) for b in page], limit, offset, total, 200)


@bp.route("/bookings/<booking_id>/cancel", methods=["POST"])
@require_roles("Trainer", "Client")
def cancel_booking(booking_id):
    booking = domain.get_booking(booking_id)
    engagement = domain.get_engagement(booking["engagement_id"])
    domain.assert_owns_engagement(engagement)

    if booking["status"] != "BOOKED":
        raise errors.invalid_state(errors.ERR_INVALID_STATE, "Booking is not BOOKED")

    start = parse_iso8601(booking["start_utc"])
    delta_seconds = (start - clock.now()).total_seconds()

    if delta_seconds >= calc.NO_SHOW_CUTOFF_SECONDS:
        # Free cancellation.
        booking["status"] = "CANCELLED"
        booking["fee_charged_cents"] = 0
        domain.touch(booking)
        if engagement["billing_model"] == "SESSION_PACK" and booking["session_pack_id"]:
            pack = db.session_packs.get(booking["session_pack_id"])
            if pack is not None:
                domain.apply_seat_release(pack)
    else:
        # Late cancellation — seat consumed, fee charged, strike recorded.
        booking["status"] = "LATE_CANCELLED"
        booking["fee_charged_cents"] = _fee_for(engagement, booking)
        domain.touch(booking)
        client = db.clients.get(engagement["client_id"])
        domain.recompute_strikes_and_privilege(client)

    return success(booking_view(booking), 200)


@bp.route("/bookings/<booking_id>/complete", methods=["POST"])
@require_roles("Trainer")
def complete_booking(booking_id):
    booking = domain.get_booking(booking_id)
    engagement = domain.get_engagement(booking["engagement_id"])
    domain.assert_owns_engagement(engagement)

    if booking["status"] != "BOOKED":
        raise errors.invalid_state(errors.ERR_INVALID_STATE, "Booking is not BOOKED")
    start = parse_iso8601(booking["start_utc"])
    if clock.now() < start:
        raise errors.invalid_state(errors.ERR_SESSION_NOT_STARTED, "Session has not started")

    booking["status"] = "COMPLETED"
    domain.touch(booking)
    # Seat stays committed; balance unchanged by status set (still committed set).
    return success(booking_view(booking), 200)


@bp.route("/bookings/<booking_id>/mark-no-show", methods=["POST"])
@require_roles("Trainer")
def mark_no_show(booking_id):
    booking = domain.get_booking(booking_id)
    engagement = domain.get_engagement(booking["engagement_id"])
    domain.assert_owns_engagement(engagement)

    if booking["status"] != "BOOKED":
        raise errors.invalid_state(errors.ERR_INVALID_STATE, "Booking is not BOOKED")
    end = parse_iso8601(booking["end_utc"])
    if clock.now() < end:
        raise errors.invalid_state(errors.ERR_SESSION_NOT_ENDED, "Session has not ended")

    booking["status"] = "NO_SHOW"
    booking["fee_charged_cents"] = _fee_for(engagement, booking)
    domain.touch(booking)
    client = db.clients.get(engagement["client_id"])
    domain.recompute_strikes_and_privilege(client)
    return success(booking_view(booking), 200)


@bp.route("/bookings/<booking_id>/reschedule", methods=["POST"])
@require_roles("Trainer", "Client")
def reschedule_booking(booking_id):
    booking = domain.get_booking(booking_id)
    engagement = domain.get_engagement(booking["engagement_id"])
    domain.assert_owns_engagement(engagement)

    body = get_json_body()
    require_fields(body, "start_utc", "end_utc")
    new_start = parse_required_datetime(body["start_utc"], "start_utc")
    new_end = parse_required_datetime(body["end_utc"], "end_utc")
    if not (new_end > new_start):
        raise errors.invalid_request("end_utc must be strictly after start_utc")

    if booking["status"] != "BOOKED":
        raise errors.invalid_state(errors.ERR_INVALID_STATE, "Booking is not BOOKED")

    # Must reschedule at least 24h ahead of the ORIGINAL start.
    orig_start = parse_iso8601(booking["start_utc"])
    delta_seconds = (orig_start - clock.now()).total_seconds()
    if delta_seconds < calc.NO_SHOW_CUTOFF_SECONDS:
        raise errors.invalid_state(errors.ERR_RESCHEDULE_TOO_LATE,
                                   "Cannot reschedule within 24h of start")

    # Calendar checks for the new interval, ignoring the booking being moved.
    domain.check_calendar_clear(
        engagement["trainer_id"], engagement["client_id"], new_start, new_end,
        exclude_booking_id=booking["id"])

    from clock import format_iso8601_ms
    # Create successor booking reusing the same pack seat (no net change).
    nid = new_id()
    ts = now_ts()
    successor = {
        "id": nid,
        "engagement_id": engagement["id"],
        "session_pack_id": booking["session_pack_id"],
        "trainer_id": engagement["trainer_id"],
        "start_utc": format_iso8601_ms(new_start),
        "end_utc": format_iso8601_ms(new_end),
        "rescheduled_from_booking_id": booking["id"],
        "fee_charged_cents": 0,
        "status": "BOOKED",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.bookings[nid] = successor

    # Original -> RESCHEDULED (hands seat to successor; net committed unchanged).
    booking["status"] = "RESCHEDULED"
    domain.touch(booking)

    # Seat accounting net-neutral: original drops out of committed set, successor
    # enters it. Recompute the pack balance to keep counts exact (version bumped
    # once for the reconciliation).
    if booking["session_pack_id"]:
        pack = db.session_packs.get(booking["session_pack_id"])
        if pack is not None:
            domain.recompute_pack_balance(pack)
            domain.touch(pack)

    return success(booking_view(successor), 201)


def _fee_for(engagement, booking):
    """No-show / late-cancel fee for this booking."""
    if engagement["billing_model"] != "SESSION_PACK":
        return 0
    pack = db.session_packs.get(booking["session_pack_id"]) if booking["session_pack_id"] else None
    per_session = pack["per_session_value_cents"] if pack else 0
    return calc.no_show_fee_cents(engagement["billing_model"], per_session)
