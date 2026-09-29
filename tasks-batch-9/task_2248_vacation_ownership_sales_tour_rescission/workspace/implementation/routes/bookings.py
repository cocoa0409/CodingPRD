"""Tour bookings: slots, reschedules, check-in, no-show and cancellation
(PRD 3.4 and 3.5)."""

from datetime import timedelta

from flask import Blueprint

import auth
import calc
import derive
import errors
import validators
from envelope import created, listing, ok
from errors import fail
from helpers import (
    collect,
    get_booking,
    get_channel,
    get_gallery,
    get_prospect,
    page,
)
from store import db, ordered

bp = Blueprint("bookings", __name__)

BOOKING_STATUSES = (
    "SCHEDULED",
    "RESCHEDULE_PENDING",
    "CHECKED_IN",
    "TOURED",
    "NO_SHOW",
    "CANCELLED",
)


def _require_channel_active(channel):
    if channel["status"] != "ACTIVE":
        fail(errors.ERR_CHANNEL_SUSPENDED, "channel is not ACTIVE")


def _require_gallery_open(gallery):
    if gallery["status"] != "OPEN":
        fail(errors.ERR_GALLERY_NOT_OPEN, "gallery is not OPEN")


def _require_lead_time(start):
    if start < db.now() + timedelta(minutes=calc.MIN_BOOKING_LEAD_MINUTES):
        fail(
            errors.ERR_TOUR_SLOT_IN_PAST,
            "scheduled start must be at least %d minutes ahead of the clock"
            % calc.MIN_BOOKING_LEAD_MINUTES,
        )


def _require_capacity(gallery, start, end, exclude_id=None):
    overlap = calc.gallery_overlap_count(
        db.bookings.values(), gallery, start, end, exclude_id
    )
    if overlap >= gallery["concurrent_tour_capacity"]:
        fail(errors.ERR_GALLERY_CAPACITY_EXCEEDED, "gallery capacity is exhausted")


@bp.post("/tour-bookings")
def create_booking():
    auth.require(auth.MARKETING_MANAGER)
    data = validators.body()
    channel_id = validators.identifier(data, "channel_id")
    prospect_id = validators.identifier(data, "prospect_id")
    gallery_id = validators.identifier(data, "gallery_id")
    start = validators.datetime_field(data, "scheduled_start_utc")

    channel = get_channel(channel_id)
    prospect = get_prospect(prospect_id)
    gallery = get_gallery(gallery_id)

    _require_channel_active(channel)
    _require_gallery_open(gallery)
    _require_lead_time(start)

    end = start + timedelta(minutes=gallery["presentation_minutes"])
    _require_capacity(gallery, start, end)

    if not calc.meets_hard_criteria(prospect, channel):
        fail(
            errors.ERR_PROSPECT_BELOW_MINIMUM_CRITERIA,
            "prospect fails the channel's hard minimums",
        )
    score, penalty = calc.qualification_score(prospect, channel)
    if score < channel["min_qualification_score"]:
        fail(
            errors.ERR_PROSPECT_NOT_QUALIFIED,
            "qualification score %d is below the channel minimum" % score,
        )

    now = db.now()
    booking = {
        "id": db.new_id(),
        "_seq": db.next_seq(),
        "channel_id": channel["id"],
        "prospect_id": prospect["id"],
        "gallery_id": gallery["id"],
        "assigned_rep_id": None,
        "scheduled_start_utc": start,
        "scheduled_end_utc": end,
        "status": "SCHEDULED",
        "qualification_score": score,
        "qualification_penalty_points": penalty,
        "gift_issued": False,
        "gift_value_cents": 0,
        "reschedule_count": 0,
        "reschedule_reason": None,
        "cancel_reason": None,
        "checked_in_at": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.bookings[booking["id"]] = booking

    derive.setf(channel, "booked_count", channel["booked_count"] + 1)
    derive.recompute_gallery_slots(gallery)
    return created(booking)


@bp.post("/tour-bookings/<booking_id>/reschedule-requests")
def open_reschedule(booking_id):
    auth.require(auth.MARKETING_MANAGER)
    data = validators.body()
    reason = validators.string(data, "reason", 1, 300)
    booking = get_booking(booking_id)
    if booking["status"] != "SCHEDULED":
        fail(errors.ERR_INVALID_BOOKING_STATE, "booking is not SCHEDULED")
    if booking["reschedule_count"] >= calc.RESCHEDULE_LIMIT:
        fail(errors.ERR_RESCHEDULE_LIMIT_EXCEEDED, "reschedule limit reached")
    derive.setf(booking, "status", "RESCHEDULE_PENDING")
    derive.setf(booking, "reschedule_reason", reason)
    return ok(booking)


@bp.post("/tour-bookings/<booking_id>/reschedule")
def commit_reschedule(booking_id):
    auth.require(auth.MARKETING_MANAGER)
    data = validators.body()
    start = validators.datetime_field(data, "new_scheduled_start_utc")
    booking = get_booking(booking_id)
    if booking["status"] != "RESCHEDULE_PENDING":
        fail(errors.ERR_INVALID_BOOKING_STATE, "booking is not RESCHEDULE_PENDING")

    channel = db.channels.get(booking["channel_id"])
    gallery = db.galleries.get(booking["gallery_id"])
    _require_channel_active(channel)
    _require_gallery_open(gallery)
    _require_lead_time(start)

    end = start + timedelta(minutes=gallery["presentation_minutes"])
    _require_capacity(gallery, start, end, exclude_id=booking["id"])

    derive.setf(booking, "scheduled_start_utc", start)
    derive.setf(booking, "scheduled_end_utc", end)
    derive.setf(booking, "reschedule_count", booking["reschedule_count"] + 1)
    derive.setf(booking, "status", "SCHEDULED")
    derive.recompute_gallery_slots(gallery)
    return ok(booking)


@bp.post("/tour-bookings/<booking_id>/check-in")
def check_in(booking_id):
    auth.require(auth.GALLERY_MANAGER)
    data = validators.body()
    issue_gift = validators.boolean(data, "issue_incentive_gift")
    booking = get_booking(booking_id)
    if booking["status"] != "SCHEDULED":
        fail(errors.ERR_INVALID_BOOKING_STATE, "booking is not SCHEDULED")

    channel = db.channels.get(booking["channel_id"])
    gallery = db.galleries.get(booking["gallery_id"])
    _require_channel_active(channel)
    _require_gallery_open(gallery)

    winner = _rotation_winner(booking)
    if winner is None:
        fail(errors.ERR_NO_ELIGIBLE_REPRESENTATIVE, "no eligible representative")

    now = db.now()
    derive.setf(booking, "status", "CHECKED_IN")
    derive.setf(booking, "assigned_rep_id", winner["id"])
    derive.setf(booking, "checked_in_at", now)
    derive.setf(winner, "status", "ON_TOUR")
    derive.setf(winner, "last_assigned_at", now)

    if issue_gift:
        derive.setf(booking, "gift_issued", True)
        derive.setf(booking, "gift_value_cents", channel["incentive_gift_value_cents"])
        derive.recompute_channel_gift_liability(channel)
    return ok(booking)


def _rotation_winner(booking):
    """Deterministic rotation: tours_taken_count, rotation_position, created_at."""
    candidates = []
    for rep in ordered(db.reps.values()):
        if rep["gallery_id"] != booking["gallery_id"]:
            continue
        if rep["status"] != "ACTIVE":
            continue
        if not calc.rep_window_available(
            db.presentations.values(),
            rep["id"],
            booking["scheduled_start_utc"],
            booking["scheduled_end_utc"],
        ):
            continue
        candidates.append(rep)
    if not candidates:
        return None
    candidates.sort(
        key=lambda rep: (
            rep["tours_taken_count"],
            rep["rotation_position"],
            rep["created_at"],
            rep["_seq"],
        )
    )
    return candidates[0]


@bp.post("/tour-bookings/<booking_id>/no-show")
def mark_no_show(booking_id):
    auth.require(auth.MARKETING_MANAGER)
    booking = get_booking(booking_id)
    if booking["status"] != "SCHEDULED":
        fail(errors.ERR_INVALID_BOOKING_STATE, "booking is not SCHEDULED")
    if db.now() < booking["scheduled_start_utc"]:
        fail(
            errors.ERR_INVALID_BOOKING_STATE,
            "the clock has not reached the scheduled start",
        )

    derive.setf(booking, "status", "NO_SHOW")
    channel = db.channels.get(booking["channel_id"])
    # CASCADE STEPS 1-5
    derive.setf(channel, "no_show_count", channel["no_show_count"] + 1)
    derive.recompute_channel_rate(channel)
    derive.suspend_channel_cascade(channel)
    # Independent of the chain: this booking's own gallery.
    derive.recompute_gallery_slots(db.galleries.get(booking["gallery_id"]))
    return ok(booking)


@bp.post("/tour-bookings/<booking_id>/cancel")
def cancel_booking(booking_id):
    auth.require(auth.MARKETING_MANAGER)
    data = validators.body()
    reason = validators.string(data, "reason", 1, 300)
    booking = get_booking(booking_id)
    if booking["status"] not in ("SCHEDULED", "RESCHEDULE_PENDING", "CHECKED_IN"):
        fail(errors.ERR_INVALID_BOOKING_STATE, "booking cannot be cancelled")

    was_checked_in = booking["status"] == "CHECKED_IN"
    if was_checked_in and _presentation_for(booking["id"]) is not None:
        fail(
            errors.ERR_INVALID_BOOKING_STATE,
            "a presentation has already been opened for this booking",
        )

    derive.setf(booking, "status", "CANCELLED")
    derive.setf(booking, "cancel_reason", reason)
    derive.recompute_gallery_slots(db.galleries.get(booking["gallery_id"]))
    if was_checked_in:
        rep = db.reps.get(booking["assigned_rep_id"])
        if rep is not None and rep["status"] == "ON_TOUR":
            derive.setf(rep, "status", "ACTIVE")
        derive.recompute_channel_gift_liability(db.channels.get(booking["channel_id"]))
    return ok(booking)


def _presentation_for(booking_id):
    for presentation in db.presentations.values():
        if presentation["booking_id"] == booking_id:
            return presentation
    return None


@bp.get("/tour-bookings/<booking_id>")
def read_booking(booking_id):
    auth.require_any()
    return ok(get_booking(booking_id))


@bp.get("/tour-bookings")
def list_bookings():
    auth.require_any()
    limit, offset = page()
    rows = collect(
        db.bookings,
        (
            ("channel_id", "channel_id"),
            ("prospect_id", "prospect_id"),
            ("gallery_id", "gallery_id"),
            ("assigned_rep_id", "assigned_rep_id"),
            ("status", "status", BOOKING_STATUSES),
        ),
    )
    return listing(rows, limit, offset)
