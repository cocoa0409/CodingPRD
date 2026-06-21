"""Bookings: create, lifecycle transitions, screening, confirm/cancel cascade (PRD §3.4-3.9)."""
from datetime import timedelta

from flask import Blueprint, request

from db import db
from errors import err
from middleware import require_auth
from models import make_entity, serialize, touch
from response import success, list_success
from services.access import (
    get_or_404, fk_or_404, require_host_owns_listing, require_guest_owns_booking,
    listing_of_booking,
)
from services import calendar as cal
from services import calc
from services.listing_util import sort_and_paginate
from util import parse_datetime, date_only
from validators import (
    get_body, req_str, opt_int, req_int, check_range, parse_pagination,
)

bp = Blueprint("bookings", __name__)


# ---- helpers --------------------------------------------------------------

def _latest_screening(booking_id):
    results = [s for s in db.screening_results.values() if s["booking_id"] == booking_id]
    if not results:
        return None
    results.sort(key=lambda s: (s["created_at"], s["_seq"]))
    return results[-1]


def _deposit_of_booking(booking_id):
    for dep in db.security_deposits.values():
        if dep["booking_id"] == booking_id:
            return dep
    return None


def _payout_of_booking(booking_id):
    for p in db.payouts.values():
        if p["booking_id"] == booking_id:
            return p
    return None


def _claims_of_deposit(deposit_id):
    return [c for c in db.damage_claims.values() if c["security_deposit_id"] == deposit_id]


def _has_blocking_claim(deposit_id):
    """True if any claim on the deposit is FILED/UNDER_REVIEW/DISPUTED."""
    for c in _claims_of_deposit(deposit_id):
        if c["status"] in ("FILED", "UNDER_REVIEW", "DISPUTED"):
            return True
    return False


# ---- create ---------------------------------------------------------------

@bp.post("/bookings")
def create_booking():
    user_id, role = require_auth({"Guest"})
    body = get_body()
    listing_id = req_str(body, "listing_id")
    guest_id = req_str(body, "guest_id")
    # Body FK existence (priority 4).
    listing = fk_or_404(db.listings, listing_id)
    fk_or_404(db.guests, guest_id)
    # Ownership (priority 5): a Guest may only book as themselves.
    if role == "Guest" and guest_id != user_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "guest_id must match the acting guest")

    ci_raw = req_str(body, "check_in")
    co_raw = req_str(body, "check_out")
    expected = req_int(body, "expected_listing_calendar_version")
    pets_count = opt_int(body, "pets_count", 0)
    check_range(pets_count, "pets_count", lo=0)

    # Priority 7: listing must be LISTED.
    if listing["status"] != "LISTED":
        raise err("ERR_LISTING_NOT_BOOKABLE", "listing is not bookable")

    # Priority 9: valid date range.
    ci = parse_datetime(ci_raw)
    co = parse_datetime(co_raw)
    if co <= ci:
        raise err("ERR_INVALID_DATE_RANGE", "check_out must be after check_in")

    # Priority 10: min_nights.
    nights = (date_only(co) - date_only(ci)).days
    if nights < listing["min_nights"]:
        raise err("ERR_MIN_NIGHTS", "stay shorter than min_nights")

    # Priority 11: availability + gap.
    if not cal.interval_available(listing, ci, co):
        raise err("ERR_DATES_UNAVAILABLE", "dates overlap a block or violate gap")

    # Priority 15: OCC against live calendar_version.
    if expected != listing["calendar_version"]:
        raise err("ERR_STALE_CALENDAR_VERSION", "stale calendar version")

    # Pricing (this may raise ERR_RATE_PLAN_OVERLAP, priority 12).
    rate_plans = [rp for rp in db.rate_plans.values() if rp["listing_id"] == listing_id]
    nightly = calc.nightly_pricing(listing, rate_plans, ci, co)
    fees, tax, total = calc.booking_total(listing, nightly, pets_count)

    # Reserve: create ACTIVE BOOKING block + calendar/channel propagation.
    block = cal.create_active_block(listing, "BOOKING", ci, co)

    booking = make_entity({
        "listing_id": listing_id,
        "guest_id": guest_id,
        "calendar_block_id": block["id"],
        "check_in": ci,
        "check_out": co,
        "nights": nights,
        "pets_count": pets_count,
        "nightly_subtotal_cents": nightly,
        "fees_cents": fees,
        "tax_cents": tax,
        "total_cents": total,
        "cancellation_tier_snapshot": listing["cancellation_tier"],
        "refund_cents": 0,
        "status": "REQUESTED",
    })
    db.bookings[booking["id"]] = booking
    return success(serialize(booking), status=201)


@bp.get("/bookings/<bid>")
def get_booking(bid):
    require_auth({"Guest", "Host", "PlatformAdmin"})
    booking = get_or_404(db.bookings, bid)
    return success(serialize(booking))


@bp.get("/bookings")
def list_bookings():
    require_auth({"Guest", "Host", "PlatformAdmin"})
    limit, offset = parse_pagination()
    listing_id = request.args.get("listing_id")
    guest_id = request.args.get("guest_id")
    cbid = request.args.get("calendar_block_id")
    status = request.args.get("status")
    items = []
    for b in db.bookings.values():
        if listing_id is not None and b["listing_id"] != listing_id:
            continue
        if guest_id is not None and b["guest_id"] != guest_id:
            continue
        if cbid is not None and b["calendar_block_id"] != cbid:
            continue
        if status is not None and b["status"] != status:
            continue
        items.append(b)
    page, total = sort_and_paginate(items, limit, offset)
    return list_success(page, limit, offset, total)


# ---- screening transitions ------------------------------------------------

@bp.post("/bookings/<bid>/screen")
def screen_booking(bid):
    user_id, role = require_auth({"Host"})
    booking = get_or_404(db.bookings, bid)
    listing = listing_of_booking(booking)
    require_host_owns_listing(listing, user_id, role)
    if booking["status"] != "REQUESTED":
        raise err("ERR_INVALID_STATE", "screen requires REQUESTED")

    guest = db.guests[booking["guest_id"]]
    risk = calc.guest_risk_score(guest)
    guest["risk_score"] = risk
    touch(guest)
    status, reason = calc.screening_outcome(guest, risk)
    sr = make_entity({
        "booking_id": bid,
        "guest_id": booking["guest_id"],
        "computed_risk_score": risk,
        "status": status,
        "failure_reason": reason,
    })
    db.screening_results[sr["id"]] = sr
    booking["status"] = "SCREENING"
    touch(booking)
    return success(serialize(booking))


@bp.post("/bookings/<bid>/request-info")
def request_info(bid):
    user_id, role = require_auth({"Host"})
    booking = get_or_404(db.bookings, bid)
    listing = listing_of_booking(booking)
    require_host_owns_listing(listing, user_id, role)
    if booking["status"] != "SCREENING":
        raise err("ERR_INVALID_STATE", "request-info requires SCREENING")
    # Discard the latest ScreeningResult rather than marking it failed (PRD §3.5).
    latest = _latest_screening(bid)
    if latest is not None:
        del db.screening_results[latest["id"]]
    booking["status"] = "REQUESTED"
    touch(booking)
    return success(serialize(booking))


@bp.post("/bookings/<bid>/approve")
def approve_booking(bid):
    user_id, role = require_auth({"Host"})
    booking = get_or_404(db.bookings, bid)
    listing = listing_of_booking(booking)
    require_host_owns_listing(listing, user_id, role)
    if booking["status"] != "SCREENING":
        raise err("ERR_INVALID_STATE", "approve requires SCREENING")
    # Priority 8: latest ScreeningResult must be PASSED.
    latest = _latest_screening(bid)
    if latest is None or latest["status"] != "PASSED":
        raise err("ERR_SCREENING_NOT_PASSED", "latest screening result is not PASSED")
    booking["status"] = "APPROVED"
    touch(booking)
    return success(serialize(booking))


@bp.post("/bookings/<bid>/decline")
def decline_booking(bid):
    user_id, role = require_auth({"Host"})
    booking = get_or_404(db.bookings, bid)
    listing = listing_of_booking(booking)
    require_host_owns_listing(listing, user_id, role)
    if booking["status"] != "SCREENING":
        raise err("ERR_INVALID_STATE", "decline requires SCREENING")
    # Release the booking's calendar block + calendar/channel cascade.
    block = db.calendar_blocks.get(booking["calendar_block_id"])
    if block is not None and block["status"] == "ACTIVE":
        cal.release_block(block, listing)
    booking["calendar_block_id"] = None
    booking["status"] = "DECLINED"
    touch(booking)
    return success(serialize(booking))


# ---- confirm / stay / completion -----------------------------------------

@bp.post("/bookings/<bid>/confirm")
def confirm_booking(bid):
    user_id, role = require_auth({"Guest"})
    booking = get_or_404(db.bookings, bid)
    require_guest_owns_booking(booking, user_id, role)
    if booking["status"] != "APPROVED":
        raise err("ERR_INVALID_STATE", "confirm requires APPROVED")
    block = db.calendar_blocks.get(booking["calendar_block_id"])
    if block is None or block["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "booking calendar block is not ACTIVE")
    listing = listing_of_booking(booking)

    # Create SecurityDeposit (AUTHORIZED), held_cents := authorized_cents.
    authorized = listing["security_deposit_cents"]
    deposit = make_entity({
        "booking_id": bid,
        "authorized_cents": authorized,
        "held_cents": authorized,
        "status": "AUTHORIZED",
    })
    db.security_deposits[deposit["id"]] = deposit

    # Create Payout (SCHEDULED); estimated_cents := ESTIMATE; release_after := checkout + delay.
    estimated = calc.payout_estimate(listing, booking)
    release_after = booking["check_out"] + timedelta(days=listing["payout_delay_days"])
    payout = make_entity({
        "booking_id": bid,
        "host_id": listing["host_id"],
        "estimated_cents": estimated,
        "actual_cents": 0,
        "release_after": release_after,
        "status": "SCHEDULED",
    })
    db.payouts[payout["id"]] = payout

    booking["status"] = "CONFIRMED"
    touch(booking)
    return success(serialize(booking))


@bp.post("/bookings/<bid>/check-in")
def check_in_booking(bid):
    user_id, role = require_auth({"Host"})
    booking = get_or_404(db.bookings, bid)
    listing = listing_of_booking(booking)
    require_host_owns_listing(listing, user_id, role)
    if booking["status"] != "CONFIRMED":
        raise err("ERR_INVALID_STATE", "check-in requires CONFIRMED")
    if db.current_utc < booking["check_in"]:
        raise err("ERR_INVALID_STATE", "current time is before check_in")
    booking["status"] = "IN_STAY"
    touch(booking)
    return success(serialize(booking))


@bp.post("/bookings/<bid>/complete")
def complete_booking(bid):
    user_id, role = require_auth({"Host"})
    booking = get_or_404(db.bookings, bid)
    listing = listing_of_booking(booking)
    require_host_owns_listing(listing, user_id, role)
    if booking["status"] != "IN_STAY":
        raise err("ERR_INVALID_STATE", "complete requires IN_STAY")
    if db.current_utc < booking["check_out"]:
        raise err("ERR_INVALID_STATE", "current time is before check_out")
    # If deposit has no open claim, release it.
    deposit = _deposit_of_booking(bid)
    if deposit is not None and not _has_blocking_claim(deposit["id"]):
        if deposit["status"] in ("AUTHORIZED", "CLAIM_OPEN"):
            deposit["held_cents"] = 0
            deposit["status"] = "RELEASED"
            touch(deposit)
    booking["status"] = "COMPLETED"
    touch(booking)
    return success(serialize(booking))


# ---- cancellation ---------------------------------------------------------

@bp.get("/bookings/<bid>/cancellation-quote")
def cancellation_quote(bid):
    require_auth({"Guest", "Host", "PlatformAdmin"})
    booking = get_or_404(db.bookings, bid)
    refund, pct, lead = calc.cancellation_refund(booking, db.current_utc)
    return success({
        "refund_cents": refund,
        "applied_pct": pct,
        "lead_hours": lead,
    })


@bp.post("/bookings/<bid>/cancel")
def cancel_booking(bid):
    user_id, role = require_auth({"Guest"})
    booking = get_or_404(db.bookings, bid)
    require_guest_owns_booking(booking, user_id, role)
    if booking["status"] not in ("REQUESTED", "CONFIRMED"):
        raise err("ERR_INVALID_STATE", "cancel requires REQUESTED or CONFIRMED")
    was_confirmed = booking["status"] == "CONFIRMED"
    listing = listing_of_booking(booking)

    # FINAL refund at the cancel instant.
    refund, _pct, _lead = calc.cancellation_refund(booking, db.current_utc)
    booking["refund_cents"] = refund

    # Release the booking's calendar block + calendar/channel cascade.
    block = db.calendar_blocks.get(booking["calendar_block_id"])
    if block is not None and block["status"] == "ACTIVE":
        cal.release_block(block, listing)
    booking["calendar_block_id"] = None

    if was_confirmed:
        # Cascade: payout reversed -> deposit released -> open claims voided.
        payout = _payout_of_booking(bid)
        if payout is not None and payout["status"] not in ("REVERSED", "PAID"):
            payout["status"] = "REVERSED"
            payout["actual_cents"] = 0
            touch(payout)
        deposit = _deposit_of_booking(bid)
        if deposit is not None and deposit["status"] not in ("RELEASED",):
            deposit["held_cents"] = 0
            deposit["status"] = "RELEASED"
            touch(deposit)
            for claim in _claims_of_deposit(deposit["id"]):
                if claim["status"] not in ("APPROVED", "DENIED", "VOID"):
                    claim["status"] = "VOID"
                    claim["approved_cents"] = 0
                    touch(claim)

    booking["status"] = "CANCELLED"
    touch(booking)
    return success(serialize(booking))


# ---- screening result reads ----------------------------------------------

@bp.get("/bookings/<bid>/screening-results")
def list_booking_screenings(bid):
    require_auth({"Guest", "Host", "PlatformAdmin"})
    get_or_404(db.bookings, bid)
    limit, offset = parse_pagination()
    status = request.args.get("status")
    items = [s for s in db.screening_results.values()
             if s["booking_id"] == bid and (status is None or s["status"] == status)]
    page, total = sort_and_paginate(items, limit, offset)
    return list_success(page, limit, offset, total)


@bp.get("/bookings/<bid>/security-deposits")
def list_booking_deposits(bid):
    require_auth({"Guest", "Host", "PlatformAdmin"})
    get_or_404(db.bookings, bid)
    limit, offset = parse_pagination()
    status = request.args.get("status")
    items = [d for d in db.security_deposits.values()
             if d["booking_id"] == bid and (status is None or d["status"] == status)]
    page, total = sort_and_paginate(items, limit, offset)
    return list_success(page, limit, offset, total)


@bp.get("/bookings/<bid>/payouts")
def list_booking_payouts(bid):
    require_auth({"Host", "PlatformAdmin"})
    get_or_404(db.bookings, bid)
    limit, offset = parse_pagination()
    status = request.args.get("status")
    items = [p for p in db.payouts.values()
             if p["booking_id"] == bid and (status is None or p["status"] == status)]
    page, total = sort_and_paginate(items, limit, offset)
    return list_success(page, limit, offset, total)
