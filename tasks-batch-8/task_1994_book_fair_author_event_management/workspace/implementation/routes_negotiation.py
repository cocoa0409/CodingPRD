"""Consignment agreements and author bookings (the two cyclic negotiations)."""

from flask import Blueprint, g

import db
from errors import fail
from middleware import ALL_ROLES, require_roles, require_scope
from response import success, success_list
from routes_core import get_or_404
from services import (
    AGREEMENT_MAX_ROUNDS,
    BOOKING_MAX_ROUNDS,
    agreement_lazy_expire,
    cancel_booking,
    new_entity,
    offer_expired,
    recompute_availability,
    recompute_honorarium,
    reset_offer_expiry,
    touch,
)
from util import (
    get_body,
    list_filtered,
    page,
    pagination_params,
    v_int,
    v_enum,
    v_pct,
    v_str,
    validate_body,
)

bp = Blueprint("negotiation", __name__)

AGREEMENT_TERMS = [
    ("discount_pct", True, v_pct),
    ("return_cap_pct", True, v_pct),
    ("restocking_fee_pct", True, v_pct),
    ("markdown_allowance_pct", True, v_pct),
    ("freight_responsibility", True, v_enum("PUBLISHER", "ORGANIZER")),
    ("offer_expiry_hours", True, v_int(1)),
]

BOOKING_TERMS = [
    ("base_honorarium_cents", True, v_int(0)),
    ("travel_cap_cents", True, v_int(0)),
    ("bonus_threshold_attendees", True, v_int(1)),
    ("bonus_base_cents", True, v_int(0)),
    ("bonus_per_attendee_cents", True, v_int(0)),
    ("offer_expiry_hours", True, v_int(1)),
]


# ---------------------------------------------------------------------------
# Consignment agreements
# ---------------------------------------------------------------------------

@bp.post("/consignment-agreements")
@require_roles("Organizer")
def create_agreement():
    data = get_body()
    fair_id = data.get("fair_id")
    if isinstance(fair_id, str) and fair_id not in db.fairs:
        fail("ERR_NOT_FOUND", "fair_id references no existing Fair")
    publisher_id = data.get("publisher_party_id")
    if isinstance(publisher_id, str) and publisher_id not in db.parties:
        fail("ERR_NOT_FOUND", "publisher_party_id references no existing Party")
    vals = validate_body(
        data,
        [("fair_id", True, v_str), ("publisher_party_id", True, v_str)] + AGREEMENT_TERMS,
    )
    publisher = db.parties[vals["publisher_party_id"]]
    if publisher["kind"] != "PUBLISHER":
        fail("ERR_VALIDATION", "publisher_party_id must reference a Party of kind PUBLISHER")
    # Duplicate guard: one non-terminal agreement per (fair, publisher).
    for other in db.agreements.values():
        if other["fair_id"] == vals["fair_id"] and other["publisher_party_id"] == vals[
            "publisher_party_id"
        ]:
            agreement_lazy_expire(other)
            if other["status"] in ("PROPOSED", "COUNTERED"):
                fail(
                    "ERR_DUPLICATE_RESOURCE",
                    "A non-terminal agreement already exists for this fair and publisher",
                )
    agreement = new_entity(
        fair_id=vals["fair_id"],
        publisher_party_id=vals["publisher_party_id"],
        discount_pct=vals["discount_pct"],
        return_cap_pct=vals["return_cap_pct"],
        restocking_fee_pct=vals["restocking_fee_pct"],
        markdown_allowance_pct=vals["markdown_allowance_pct"],
        freight_responsibility=vals["freight_responsibility"],
        offer_expiry_hours=vals["offer_expiry_hours"],
        offered_by="ORGANIZER",
        offer_expires_at=None,
        negotiation_round=1,
        status="PROPOSED",
    )
    reset_offer_expiry(agreement, vals["offer_expiry_hours"])
    db.agreements[agreement["id"]] = agreement
    return success(agreement, 201)


@bp.get("/consignment-agreements")
@require_roles(*ALL_ROLES)
def list_agreements():
    for agreement in db.agreements.values():
        agreement_lazy_expire(agreement)
    limit, offset = pagination_params()
    items = list_filtered(
        db.agreements,
        [
            ("fair_id", "fair_id"),
            ("publisher_party_id", "publisher_party_id"),
            ("status", "status"),
        ],
    )
    items, total = page(items, limit, offset)
    return success_list(items, total, limit, offset)


@bp.get("/consignment-agreements/<aid>")
@require_roles(*ALL_ROLES)
def get_agreement(aid):
    agreement = get_or_404(db.agreements, aid, "ConsignmentAgreement")
    agreement_lazy_expire(agreement)
    return success(agreement)


@bp.post("/consignment-agreements/<aid>/counter")
@require_roles("Organizer", "PublisherRep")
def counter_agreement(aid):
    agreement = get_or_404(db.agreements, aid, "ConsignmentAgreement")
    # Party scope (priority 6) precedes request shape (7).
    if g.role == "PublisherRep":
        require_scope(agreement["publisher_party_id"])
    vals = validate_body(
        get_body(), AGREEMENT_TERMS + [("expected_agreement_version", True, v_int())]
    )
    # State (8): PublisherRep counters PROPOSED; Organizer counters COUNTERED.
    if g.role == "PublisherRep":
        if agreement["status"] != "PROPOSED":
            fail("ERR_INVALID_STATE", "No live organizer offer to counter")
    else:
        if agreement["status"] != "COUNTERED":
            fail("ERR_INVALID_STATE", "No live publisher offer to counter")
    # OCC (9)
    if vals["expected_agreement_version"] != agreement["version"]:
        fail("ERR_STALE_VERSION", "Agreement version has advanced since last read")
    # Offer expiry (15): a lapsed agreement offer transitions to EXPIRED.
    if offer_expired(agreement):
        agreement["status"] = "EXPIRED"
        touch(agreement)
        fail("ERR_OFFER_EXPIRED", "The live offer has lapsed")
    # Negotiation round cap (16)
    if agreement["negotiation_round"] >= AGREEMENT_MAX_ROUNDS:
        fail("ERR_NEGOTIATION_ROUNDS_EXHAUSTED", "Agreement negotiation round cap reached")
    for name, _, _ in AGREEMENT_TERMS:
        agreement[name] = vals[name]
    agreement["offered_by"] = "PUBLISHER" if g.role == "PublisherRep" else "ORGANIZER"
    agreement["status"] = "COUNTERED" if g.role == "PublisherRep" else "PROPOSED"
    agreement["negotiation_round"] += 1
    reset_offer_expiry(agreement, vals["offer_expiry_hours"])
    touch(agreement)
    return success(agreement)


@bp.post("/consignment-agreements/<aid>/accept")
@require_roles("Organizer", "PublisherRep")
def accept_agreement(aid):
    agreement = get_or_404(db.agreements, aid, "ConsignmentAgreement")
    if g.role == "PublisherRep":
        require_scope(agreement["publisher_party_id"])
    validate_body(get_body(), [])
    if g.role == "PublisherRep":
        if agreement["status"] != "PROPOSED":
            fail("ERR_INVALID_STATE", "Only the non-offering side may accept")
    else:
        if agreement["status"] != "COUNTERED":
            fail("ERR_INVALID_STATE", "Only the non-offering side may accept")
    if offer_expired(agreement):
        agreement["status"] = "EXPIRED"
        touch(agreement)
        fail("ERR_OFFER_EXPIRED", "The live offer has lapsed")
    agreement["status"] = "ACCEPTED"
    touch(agreement)
    return success(agreement)


@bp.post("/consignment-agreements/<aid>/decline")
@require_roles("Organizer", "PublisherRep")
def decline_agreement(aid):
    agreement = get_or_404(db.agreements, aid, "ConsignmentAgreement")
    if g.role == "PublisherRep":
        require_scope(agreement["publisher_party_id"])
    validate_body(get_body(), [])
    agreement_lazy_expire(agreement)
    if agreement["status"] not in ("PROPOSED", "COUNTERED"):
        fail("ERR_INVALID_STATE", "Agreement negotiation is already terminal")
    agreement["status"] = "DECLINED"
    touch(agreement)
    return success(agreement)


# ---------------------------------------------------------------------------
# Author bookings
# ---------------------------------------------------------------------------

@bp.post("/author-bookings")
@require_roles("Organizer")
def create_booking():
    data = get_body()
    fair_id = data.get("fair_id")
    if isinstance(fair_id, str) and fair_id not in db.fairs:
        fail("ERR_NOT_FOUND", "fair_id references no existing Fair")
    author_id = data.get("author_party_id")
    if isinstance(author_id, str) and author_id not in db.parties:
        fail("ERR_NOT_FOUND", "author_party_id references no existing Party")
    vals = validate_body(
        data,
        [("fair_id", True, v_str), ("author_party_id", True, v_str)] + BOOKING_TERMS,
    )
    author = db.parties[vals["author_party_id"]]
    if author["kind"] != "AUTHOR":
        fail("ERR_VALIDATION", "author_party_id must reference a Party of kind AUTHOR")
    booking = new_entity(
        fair_id=vals["fair_id"],
        author_party_id=vals["author_party_id"],
        base_honorarium_cents=vals["base_honorarium_cents"],
        travel_cap_cents=vals["travel_cap_cents"],
        bonus_threshold_attendees=vals["bonus_threshold_attendees"],
        bonus_base_cents=vals["bonus_base_cents"],
        bonus_per_attendee_cents=vals["bonus_per_attendee_cents"],
        offer_expiry_hours=vals["offer_expiry_hours"],
        offered_by="ORGANIZER",
        offer_expires_at=None,
        negotiation_round=1,
        travel_actual_cents=None,
        accrued_bonus_cents=0,
        kill_fee_cents=0,
        settled_total_cents=None,
        status="INVITED",
    )
    reset_offer_expiry(booking, vals["offer_expiry_hours"])
    db.bookings[booking["id"]] = booking
    return success(booking, 201)


@bp.get("/author-bookings")
@require_roles(*ALL_ROLES)
def list_bookings():
    limit, offset = pagination_params()
    items = list_filtered(
        db.bookings,
        [("fair_id", "fair_id"), ("author_party_id", "author_party_id"), ("status", "status")],
    )
    items, total = page(items, limit, offset)
    return success_list(items, total, limit, offset)


@bp.get("/author-bookings/<bid>")
@require_roles(*ALL_ROLES)
def get_booking(bid):
    return success(get_or_404(db.bookings, bid, "AuthorBooking"))


@bp.post("/author-bookings/<bid>/counter")
@require_roles("Organizer", "AuthorRep")
def counter_booking(bid):
    booking = get_or_404(db.bookings, bid, "AuthorBooking")
    if g.role == "AuthorRep":
        require_scope(booking["author_party_id"])
    vals = validate_body(
        get_body(), BOOKING_TERMS + [("expected_booking_version", True, v_int())]
    )
    # State (8): AuthorRep counters INVITED; Organizer counters NEGOTIATING.
    if g.role == "AuthorRep":
        if booking["status"] != "INVITED":
            fail("ERR_INVALID_STATE", "No live organizer offer to counter")
    else:
        if booking["status"] != "NEGOTIATING":
            fail("ERR_INVALID_STATE", "No live author offer to counter")
    # OCC (9)
    if vals["expected_booking_version"] != booking["version"]:
        fail("ERR_STALE_VERSION", "Booking version has advanced since last read")
    # Offer expiry (15): bookings are never auto-transitioned by the clock.
    if offer_expired(booking):
        fail("ERR_OFFER_EXPIRED", "The live offer has lapsed")
    # Negotiation round cap (16)
    if booking["negotiation_round"] >= BOOKING_MAX_ROUNDS:
        fail("ERR_NEGOTIATION_ROUNDS_EXHAUSTED", "Booking negotiation round cap reached")
    for name, _, _ in BOOKING_TERMS:
        booking[name] = vals[name]
    booking["offered_by"] = "AUTHOR" if g.role == "AuthorRep" else "ORGANIZER"
    booking["status"] = "NEGOTIATING" if g.role == "AuthorRep" else "INVITED"
    booking["negotiation_round"] += 1
    reset_offer_expiry(booking, vals["offer_expiry_hours"])
    touch(booking)
    return success(booking)


@bp.post("/author-bookings/<bid>/accept")
@require_roles("Organizer", "AuthorRep")
def accept_booking(bid):
    booking = get_or_404(db.bookings, bid, "AuthorBooking")
    if g.role == "AuthorRep":
        require_scope(booking["author_party_id"])
    validate_body(get_body(), [])
    if g.role == "AuthorRep":
        if booking["status"] != "INVITED":
            fail("ERR_INVALID_STATE", "Only the non-offering side may accept")
    else:
        if booking["status"] != "NEGOTIATING":
            fail("ERR_INVALID_STATE", "Only the non-offering side may accept")
    if offer_expired(booking):
        fail("ERR_OFFER_EXPIRED", "The live offer has lapsed")
    booking["status"] = "CONFIRMED"
    touch(booking)
    return success(booking)


@bp.post("/author-bookings/<bid>/decline")
@require_roles("Organizer", "AuthorRep")
def decline_booking(bid):
    booking = get_or_404(db.bookings, bid, "AuthorBooking")
    if g.role == "AuthorRep":
        require_scope(booking["author_party_id"])
    validate_body(get_body(), [])
    if booking["status"] not in ("INVITED", "NEGOTIATING"):
        fail("ERR_INVALID_STATE", "Booking negotiation is already terminal")
    booking["status"] = "DECLINED"
    touch(booking)
    return success(booking)


@bp.post("/author-bookings/<bid>/book-travel")
@require_roles("Organizer")
def book_travel(bid):
    booking = get_or_404(db.bookings, bid, "AuthorBooking")
    vals = validate_body(get_body(), [("travel_actual_cents", True, v_int(0))])
    if booking["status"] != "CONFIRMED":
        fail("ERR_INVALID_STATE", "Booking is not in CONFIRMED")
    if vals["travel_actual_cents"] > booking["travel_cap_cents"]:
        fail("ERR_TRAVEL_CAP_EXCEEDED", "travel_actual_cents exceeds travel_cap_cents")
    booking["travel_actual_cents"] = vals["travel_actual_cents"]
    booking["status"] = "TRAVEL_BOOKED"
    touch(booking)
    return success(booking)


@bp.post("/author-bookings/<bid>/settle")
@require_roles("Organizer")
def settle_booking(bid):
    booking = get_or_404(db.bookings, bid, "AuthorBooking")
    validate_body(get_body(), [])
    if booking["status"] != "TRAVEL_BOOKED":
        fail("ERR_INVALID_STATE", "Booking is not in TRAVEL_BOOKED")
    open_sessions = any(
        s["booking_id"] == booking["id"] and s["status"] not in ("RECONCILED", "CANCELLED")
        for s in db.sessions.values()
    )
    if open_sessions:
        fail("ERR_INVALID_STATE", "Every signing session must be RECONCILED or CANCELLED")
    fair = db.fairs[booking["fair_id"]]
    if fair["status"] not in ("OPEN", "RECONCILING"):
        fail("ERR_INVALID_STATE", "Booking's fair must be OPEN or RECONCILING")
    booking["settled_total_cents"] = (
        booking["base_honorarium_cents"]
        + booking["accrued_bonus_cents"]
        + min(booking["travel_actual_cents"], booking["travel_cap_cents"])
    )
    booking["status"] = "SETTLED"
    touch(booking)
    recompute_honorarium(fair)
    return success(booking)


@bp.post("/author-bookings/<bid>/cancel")
@require_roles("Organizer", "AuthorRep")
def cancel_booking_endpoint(bid):
    booking = get_or_404(db.bookings, bid, "AuthorBooking")
    if g.role == "AuthorRep":
        require_scope(booking["author_party_id"])
    validate_body(get_body(), [])
    if booking["status"] not in ("CONFIRMED", "TRAVEL_BOOKED"):
        fail("ERR_INVALID_STATE", "Only a CONFIRMED or TRAVEL_BOOKED booking can be cancelled")
    cancel_booking(booking)
    return success(booking)
