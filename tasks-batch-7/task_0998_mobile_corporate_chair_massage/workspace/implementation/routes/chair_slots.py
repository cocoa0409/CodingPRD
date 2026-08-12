"""Chair slot endpoints: assignment lifecycle, travel posture, sign-up sheet."""
from flask import Blueprint, g

import db
import errors
from auth import require_account_owner, require_roles
from clock import clock
from db import stores
from respond import success
from services.domain import (chairs_of_booking, get_or_404, has_valid_license,
                             maybe_waive_leg, recompute_booked_minutes,
                             recompute_draft_invoice, release_chair,
                             therapist_booked_minutes, therapist_double_booked)
from validate import (apply_filters, json_body, opt_int_field, paginate,
                      req_str)

bp = Blueprint("chair_slots", __name__)


def _load_chair(cid):
    return get_or_404("chair_slots", cid, "ChairSlot")


def _load_chair_for_organizer(cid):
    chair = _load_chair(cid)
    booking = get_or_404("bookings", chair["booking_id"], "Booking")
    require_account_owner(booking["corporate_account_id"])
    return chair, booking


@bp.get("/chair-massage/chair-slots")
@require_roles("PlatformAdmin", "Organizer", "Therapist")
def list_chair_slots():
    items = db.all_sorted("chair_slots")
    items = apply_filters(items, {
        "booking_id": (lambda e: e["booking_id"], "str"),
        "therapist_id": (lambda e: e["therapist_id"], "str"),
        "status": (lambda e: e["status"], "str"),
    })
    page, meta = paginate(items)
    return success([db.public(e) for e in page], response_type="array", pagination=meta)


@bp.get("/chair-massage/chair-slots/<cid>")
@require_roles("PlatformAdmin", "Organizer", "Therapist")
def get_chair_slot(cid):
    chair = _load_chair(cid)
    booking = db.get("bookings", chair["booking_id"])
    if booking:
        require_account_owner(booking["corporate_account_id"])
    return success(db.public(chair))


@bp.post("/chair-massage/chair-slots/<cid>/assign")
@require_roles("Organizer")
def assign_chair(cid):
    chair, booking = _load_chair_for_organizer(cid)
    if chair["status"] != "UNASSIGNED":
        raise errors.invalid_state("Only an UNASSIGNED chair slot can be assigned")
    if booking["status"] != "SCHEDULING":
        raise errors.invalid_state("Booking must be SCHEDULING to assign chairs")
    body = json_body()
    therapist_id = req_str(body, "therapist_id")
    therapist = get_or_404("therapists", therapist_id, "Therapist")
    if therapist["status"] != "ACTIVE":
        raise errors.invalid_state("Therapist must be ACTIVE to be assigned")
    # Business checks in fixed order: daily cap, license, double-booking.
    commitment = ((booking["window_duration_minutes"] // booking["slot_minutes"])
                  * booking["slot_minutes"])
    tally = therapist_booked_minutes(therapist_id, booking["event_date"])
    if tally + commitment > therapist["max_minutes_per_day"]:
        raise errors.unprocessable(
            errors.ERR_THERAPIST_DAILY_CAP,
            "Assignment would exceed the therapist's daily chair-minutes cap")
    if not has_valid_license(therapist_id, booking["region_id"], booking["event_date"]):
        raise errors.unprocessable(
            errors.ERR_LICENSE_INVALID,
            "Therapist lacks an ACTIVE license in the booking region covering the event date")
    if therapist_double_booked(therapist_id, booking["event_date"], booking):
        raise errors.unprocessable(
            errors.ERR_THERAPIST_DOUBLE_BOOKED,
            "Therapist has an overlapping buffer-extended window on the event date")
    chair["therapist_id"] = therapist_id
    chair["status"] = "ASSIGNED"
    chair["assigned_at"] = clock.iso()
    db.touch(chair)
    db.touch(booking)  # assignment cascades a Booking.version bump (OCC 2.7)
    return success(db.public(chair))


@bp.post("/chair-massage/chair-slots/<cid>/depart")
@require_roles("Therapist")
def depart_chair(cid):
    chair = _load_chair(cid)
    if g.user_id != chair["therapist_id"]:
        raise errors.forbidden("Only the assigned therapist may depart this chair")
    if chair["status"] != "ASSIGNED":
        raise errors.invalid_state("Only an ASSIGNED chair slot can depart")
    booking = get_or_404("bookings", chair["booking_id"], "Booking")
    if clock.today() != booking["event_date"]:
        raise errors.invalid_state("Departure is only permitted on the event date")
    chair["status"] = "EN_ROUTE"
    db.touch(chair)
    return success(db.public(chair))


@bp.post("/chair-massage/chair-slots/<cid>/arrive")
@require_roles("Therapist")
def arrive_chair(cid):
    chair = _load_chair(cid)
    if g.user_id != chair["therapist_id"]:
        raise errors.forbidden("Only the assigned therapist may arrive at this chair")
    if chair["status"] != "EN_ROUTE":
        raise errors.invalid_state("Only an EN_ROUTE chair slot can arrive on site")
    chair["status"] = "ON_SITE"
    chair["arrived_at"] = clock.iso()
    db.touch(chair)
    return success(db.public(chair))


@bp.post("/chair-massage/chair-slots/<cid>/release")
@require_roles("Organizer")
def release_chair_endpoint(cid):
    chair, booking = _load_chair_for_organizer(cid)
    if chair["status"] != "ASSIGNED":
        raise errors.invalid_state("Only an ASSIGNED chair slot can be released")
    if booking["status"] not in ("SCHEDULING", "CONFIRMED"):
        raise errors.invalid_state(
            "Chairs may be released only while the booking is SCHEDULING or CONFIRMED")
    release_chair(chair, booking)
    db.touch(booking)  # release cascades a Booking.version bump (OCC 2.7)
    recompute_draft_invoice(booking["id"])
    return success(db.public(chair))


@bp.post("/chair-massage/chair-slots/<cid>/mark-no-show")
@require_roles("Organizer")
def mark_chair_no_show(cid):
    chair, booking = _load_chair_for_organizer(cid)
    if chair["status"] != "ASSIGNED":
        raise errors.invalid_state("Only an ASSIGNED chair slot can be marked NO_SHOW")
    if clock.today() <= booking["event_date"]:
        raise errors.invalid_state(
            "A chair may be marked NO_SHOW only after the event date has passed")
    chair["status"] = "NO_SHOW"
    db.touch(chair)
    claims_changed = False
    for claim in stores["slot_claims"].values():
        if claim["chair_slot_id"] == cid and claim["status"] == "CLAIMED":
            claim["status"] = "NO_SHOW"
            db.touch(claim)
            claims_changed = True
    if claims_changed:
        recompute_booked_minutes(booking)
        db.touch(booking)
        db.touch(chair)
        recompute_draft_invoice(booking["id"])
    return success(db.public(chair))


@bp.post("/chair-massage/chair-slots/<cid>/claims")
@require_roles("Organizer")
def create_claim(cid):
    chair, booking = _load_chair_for_organizer(cid)
    body = json_body()
    recipient_name = req_str(body, "recipient_name")
    recipient_email = req_str(body, "recipient_email")
    expected = opt_int_field(body, "expected_chair_slot_version")
    if expected is None:
        raise errors.invalid_request("Field 'expected_chair_slot_version' is required")
    if expected != chair["version"]:
        raise errors.ApiError(errors.ERR_STALE_CHAIR_SLOT_VERSION, 412,
                              "expected_chair_slot_version does not match ChairSlot.version")
    live_claims = [c for c in stores["slot_claims"].values()
                   if c["chair_slot_id"] == cid and c["status"] != "CANCELLED"]
    ordinal = len(live_claims)
    if (ordinal + 1) * booking["slot_minutes"] > booking["window_duration_minutes"]:
        raise errors.unprocessable(
            errors.ERR_SIGNUP_SHEET_FULL,
            "Claiming a new slot would exceed the chair's window capacity")
    for claim in stores["slot_claims"].values():
        if (claim["booking_id"] == booking["id"]
                and claim["recipient_email"] == recipient_email
                and claim["status"] != "CANCELLED"):
            raise errors.unprocessable(
                errors.ERR_DUPLICATE_SIGNUP,
                "recipient_email already has a non-CANCELLED claim on this booking")
    claim = db.stamp_new({
        "id": db.new_id(),
        "chair_slot_id": cid,
        "booking_id": booking["id"],
        "recipient_name": recipient_name,
        "recipient_email": recipient_email,
        "slot_ordinal": ordinal,
        "start_offset_minutes": ordinal * booking["slot_minutes"],
        "status": "CLAIMED",
        "waiver_id": None,
        "checked_in_at": None,
        "completed_at": None,
    })
    db.insert("slot_claims", claim)
    recompute_booked_minutes(booking)
    db.touch(booking)   # derived-field mutation
    db.touch(chair)     # shared sign-up surface advances the chair version
    recompute_draft_invoice(booking["id"])
    return success(db.public(claim), status=201)


@bp.get("/chair-massage/chair-slots/<cid>/claims")
@require_roles("PlatformAdmin", "Organizer", "Therapist")
def list_chair_claims(cid):
    chair = _load_chair(cid)
    booking = db.get("bookings", chair["booking_id"])
    if booking:
        require_account_owner(booking["corporate_account_id"])
    items = [c for c in db.all_sorted("slot_claims") if c["chair_slot_id"] == cid]
    items = apply_filters(items, {"status": (lambda e: e["status"], "str")})
    page, meta = paginate(items)
    return success([db.public(e) for e in page], response_type="array", pagination=meta)
