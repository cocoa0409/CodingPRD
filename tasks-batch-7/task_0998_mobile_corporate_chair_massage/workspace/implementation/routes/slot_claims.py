"""Slot claim endpoints: check-in, completion, cancellation, waivers, surveys."""
from flask import Blueprint, g

import db
import errors
from auth import require_account_owner, require_roles
from clock import clock
from db import stores
from respond import success
from services import calc
from services.domain import (get_or_404, recompute_booked_minutes,
                             recompute_delivered_minutes,
                             recompute_draft_invoice)
from validate import (apply_filters, json_body, opt_str, paginate, req_int,
                      req_str)

bp = Blueprint("slot_claims", __name__)


def _load_claim(sid):
    return get_or_404("slot_claims", sid, "SlotClaim")


def _claim_context(sid):
    claim = _load_claim(sid)
    chair = db.get("chair_slots", claim["chair_slot_id"])
    booking = db.get("bookings", claim["booking_id"])
    return claim, chair, booking


def _load_claim_for_organizer(sid):
    claim, chair, booking = _claim_context(sid)
    if booking:
        require_account_owner(booking["corporate_account_id"])
    return claim, chair, booking


@bp.get("/chair-massage/slot-claims/<sid>")
@require_roles("PlatformAdmin", "Organizer", "Therapist")
def get_claim(sid):
    claim, chair, booking = _claim_context(sid)
    if booking:
        require_account_owner(booking["corporate_account_id"])
    return success(db.public(claim))


@bp.get("/chair-massage/slot-claims/<sid>/waivers")
@require_roles("PlatformAdmin", "Organizer", "Therapist")
def list_claim_waivers(sid):
    claim, chair, booking = _claim_context(sid)
    if booking:
        require_account_owner(booking["corporate_account_id"])
    items = [w for w in db.all_sorted("waivers") if w["slot_claim_id"] == sid]
    page, meta = paginate(items)
    return success([db.public(e) for e in page], response_type="array", pagination=meta)


@bp.get("/chair-massage/slot-claims/<sid>/satisfaction-surveys")
@require_roles("PlatformAdmin", "Organizer", "Therapist")
def list_claim_surveys(sid):
    claim, chair, booking = _claim_context(sid)
    if booking:
        require_account_owner(booking["corporate_account_id"])
    items = [s for s in db.all_sorted("satisfaction_surveys")
             if s["slot_claim_id"] == sid]
    page, meta = paginate(items)
    return success([db.public(e) for e in page], response_type="array", pagination=meta)


@bp.post("/chair-massage/slot-claims/<sid>/check-in")
@require_roles("Organizer")
def check_in_claim(sid):
    claim, chair, booking = _load_claim_for_organizer(sid)
    if claim["status"] != "CLAIMED":
        raise errors.invalid_state("Only a CLAIMED slot claim can be checked in")
    if booking["status"] != "IN_PROGRESS":
        raise errors.invalid_state("Check-in requires the booking to be IN_PROGRESS")
    waiver = db.get("waivers", claim["waiver_id"]) if claim["waiver_id"] else None
    if waiver is None or waiver["revoked_at"] is not None:
        raise errors.unprocessable(
            errors.ERR_WAIVER_MISSING,
            "Check-in requires an active (non-revoked) waiver for this claim")
    claim["status"] = "CHECKED_IN"
    claim["checked_in_at"] = clock.iso()
    db.touch(claim)
    return success(db.public(claim))


@bp.post("/chair-massage/slot-claims/<sid>/complete")
@require_roles("Therapist")
def complete_claim(sid):
    claim, chair, booking = _claim_context(sid)
    if chair is None or g.user_id != chair["therapist_id"]:
        raise errors.forbidden("Only the chair's assigned therapist may complete this claim")
    if claim["status"] != "CHECKED_IN":
        raise errors.invalid_state("Only a CHECKED_IN slot claim can be completed")
    claim["status"] = "COMPLETED"
    claim["completed_at"] = clock.iso()
    db.touch(claim)
    recompute_delivered_minutes(booking)
    db.touch(booking)  # derived-field mutation
    recompute_draft_invoice(booking["id"])
    return success(db.public(claim))


@bp.post("/chair-massage/slot-claims/<sid>/cancel")
@require_roles("Organizer")
def cancel_claim(sid):
    claim, chair, booking = _load_claim_for_organizer(sid)
    if claim["status"] != "CLAIMED":
        raise errors.invalid_state("Only a CLAIMED slot claim can be cancelled")
    if booking["status"] not in ("SCHEDULING", "CONFIRMED", "IN_PROGRESS"):
        raise errors.invalid_state(
            "Claims may be cancelled only while the booking is SCHEDULING, CONFIRMED or IN_PROGRESS")
    claim["status"] = "CANCELLED"
    db.touch(claim)
    recompute_booked_minutes(booking)
    db.touch(booking)
    if chair:
        db.touch(chair)
    recompute_draft_invoice(booking["id"])
    return success(db.public(claim))


@bp.post("/chair-massage/slot-claims/<sid>/mark-no-show")
@require_roles("Organizer")
def no_show_claim(sid):
    claim, chair, booking = _load_claim_for_organizer(sid)
    if claim["status"] != "CLAIMED":
        raise errors.invalid_state("Only a CLAIMED slot claim can be marked NO_SHOW")
    claim["status"] = "NO_SHOW"
    db.touch(claim)
    recompute_booked_minutes(booking)
    db.touch(booking)
    if chair:
        db.touch(chair)
    recompute_draft_invoice(booking["id"])
    return success(db.public(claim))


@bp.post("/chair-massage/slot-claims/<sid>/waiver")
@require_roles("Organizer")
def sign_waiver(sid):
    claim, chair, booking = _load_claim_for_organizer(sid)
    body = json_body()
    booking_id = req_str(body, "booking_id")
    get_or_404("bookings", booking_id, "Booking")
    if booking_id != claim["booking_id"]:
        raise errors.invalid_request("booking_id does not match the claim's booking")
    signer_email = req_str(body, "signer_email")
    if signer_email != claim["recipient_email"]:
        raise errors.invalid_request("signer_email must equal the claim's recipient_email")
    signature = req_str(body, "signature_payload")
    waiver = db.stamp_new({
        "id": db.new_id(),
        "booking_id": booking_id,
        "slot_claim_id": sid,
        "signer_email": signer_email,
        "signed_at": clock.iso(),
        "signature_payload": signature,
        "revoked_at": None,
    })
    db.insert("waivers", waiver)
    claim["waiver_id"] = waiver["id"]
    db.touch(claim)
    return success(db.public(waiver), status=201)


@bp.post("/chair-massage/slot-claims/<sid>/satisfaction-surveys")
@require_roles("Organizer")
def submit_survey(sid):
    claim, chair, booking = _load_claim_for_organizer(sid)
    if claim["status"] != "COMPLETED" or booking["status"] not in ("IN_PROGRESS", "COMPLETED"):
        raise errors.unprocessable(
            errors.ERR_BOOKING_NOT_COMPLETED,
            "Survey submission requires a COMPLETED claim on an IN_PROGRESS or COMPLETED booking")
    for existing in stores["satisfaction_surveys"].values():
        if existing["slot_claim_id"] == sid:
            raise errors.unprocessable(
                errors.ERR_DUPLICATE_SURVEY,
                "A satisfaction survey already exists for this slot claim")
    body = json_body()
    rating = req_int(body, "rating", min_v=1, max_v=5)
    comment = opt_str(body, "comment") or ""
    survey = db.stamp_new({
        "id": db.new_id(),
        "slot_claim_id": sid,
        "rating": rating,
        "comment": comment,
        "submitted_at": clock.iso(),
    }, with_version=False)
    db.insert("satisfaction_surveys", survey)
    if chair and chair["therapist_id"]:
        calc.recompute_therapist_rating(chair["therapist_id"])
        therapist = db.get("therapists", chair["therapist_id"])
        if therapist:
            db.touch(therapist)
    recompute_draft_invoice(booking["id"])
    return success(db.public(survey), status=201)
