"""Contesting an incumbent hold: challenges, rulings, displacement, withdrawal."""

from flask import Blueprint

import calc
import cascade
import serial
import validate as v
from envelope import created, ok, ok_list
from errors import ApiError
from routes_booking import get_booking
from store import db, now_logical, ordered, stamp_new, touch

bp = Blueprint("challenges", __name__)

DECISIONS = ("UPHELD", "DENIED")


def get_challenge(challenge_id):
    challenge = db.challenges.get(challenge_id)
    if challenge is None:
        raise ApiError("ERR_CHALLENGE_NOT_FOUND")
    return challenge


def _other_open_challenge(booking_id, exclude_id):
    for challenge in db.challenges.values():
        if challenge["booking_id"] != booking_id or challenge["id"] == exclude_id:
            continue
        if challenge["status"] == "OPEN":
            return True
    return False


def _restore_incumbent(booking, challenge_id):
    """CHALLENGED -> HELD once no challenge against the booking remains OPEN."""
    if booking["status"] != "CHALLENGED":
        return
    if _other_open_challenge(booking["id"], challenge_id):
        return
    booking["status"] = "HELD"
    touch(booking)


@bp.post("/hold-challenges")
def create_challenge():
    user_id, _role = v.auth(("AnchorTenantRep",))
    payload = v.body()

    # Ladder 3: the acting principal must be the challenging tenant.
    if payload.get("challenger_tenant_id") != user_id:
        raise ApiError("ERR_TENANT_SCOPE_VIOLATION")

    # Ladder 5: shape.
    booking_id = v.req_id(payload, "booking_id")
    tenant_id = v.req_id(payload, "challenger_tenant_id")
    challenger_booking_id = v.req_id(payload, "challenger_booking_id")

    # Ladder 7: existence, body identifiers in declaration order.
    incumbent = get_booking(booking_id)
    tenant = db.tenants.get(tenant_id)
    if tenant is None:
        raise ApiError("ERR_TENANT_NOT_FOUND")
    challenger_booking = get_booking(challenger_booking_id)

    # Ladder 9: from-state legality on both bookings.
    if incumbent["status"] not in ("HELD", "CHALLENGED"):
        raise ApiError("ERR_INVALID_BOOKING_STATE")
    if challenger_booking["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_BOOKING_STATE")

    # Ladder 16: constraint satisfaction — the credit budget.
    if int(tenant["challenge_credits"]) < 1:
        raise ApiError("ERR_CHALLENGE_CREDITS_EXHAUSTED")

    # Ladder 17: referential scoping, then duplicate detection.
    if challenger_booking["venue_id"] != incumbent["venue_id"]:
        raise ApiError("ERR_VENUE_SCOPE_MISMATCH")
    if tenant["venue_id"] != incumbent["venue_id"]:
        raise ApiError("ERR_VENUE_SCOPE_MISMATCH")
    for existing in db.challenges.values():
        if (existing["booking_id"] == incumbent["id"]
                and existing["challenger_tenant_id"] == tenant["id"]
                and existing["status"] == "OPEN"):
            raise ApiError("ERR_DUPLICATE_CHALLENGE")

    row = {
        "booking_id": incumbent["id"],
        "challenger_tenant_id": tenant["id"],
        "challenger_booking_id": challenger_booking["id"],
        "status": "OPEN",
        "priority_delta": calc.priority_delta(incumbent["hold_tier"],
                                              tenant["hold_priority_tier"]),
        "ruled_at": None,
        "ruling_note": None,
    }
    stamp_new(row)
    db.challenges[row["id"]] = row

    tenant["challenge_credits"] = int(tenant["challenge_credits"]) - 1
    if incumbent["status"] == "HELD":
        incumbent["status"] = "CHALLENGED"
        touch(incumbent)
    venue = db.venues.get(incumbent["venue_id"])
    if venue is not None:
        cascade.bump_venue(venue)
    return created(serial.challenge(row))


@bp.get("/hold-challenges/<challenge_id>")
def read_challenge(challenge_id):
    v.auth(v.ALL_ROLES)
    return ok(serial.challenge(get_challenge(challenge_id)))


@bp.get("/hold-challenges")
def list_challenges():
    v.auth(v.ALL_ROLES)
    limit, offset = v.pagination()
    matched = list(db.challenges.values())
    for field in ("booking_id", "challenger_tenant_id", "challenger_booking_id", "status"):
        value = v.filter_arg(field)
        if value is not None:
            matched = [c for c in matched if c[field] == value]
    matched = ordered(matched)
    page, total = v.paginate(matched, limit, offset)
    return ok_list([serial.challenge(c) for c in page], limit, offset, total)


@bp.post("/hold-challenges/<challenge_id>/rule")
def rule_challenge(challenge_id):
    v.auth(("BookingManager",))
    payload = v.body()
    decision = v.req_enum(payload, "decision", DECISIONS)
    ruling_note = v.opt_str(payload, "ruling_note", None, 1, 1000)

    challenge = get_challenge(challenge_id)
    # Ladder 9: from-state legality.
    if challenge["status"] != "OPEN":
        raise ApiError("ERR_INVALID_CHALLENGE_STATE")

    incumbent = db.bookings.get(challenge["booking_id"])
    if decision == "UPHELD":
        # Ladder 16, in the pinned internal order.
        if incumbent is not None and incumbent["hold_tier"] == "TIER_1":
            raise ApiError("ERR_ANCHOR_HOLD_PROTECTED")
        if int(challenge["priority_delta"]) < 1:
            raise ApiError("ERR_HOLD_PRIORITY_INSUFFICIENT")

    challenge["status"] = decision
    challenge["ruled_at"] = now_logical()
    if ruling_note is not None:
        challenge["ruling_note"] = ruling_note
    touch(challenge)

    if incumbent is not None:
        if decision == "UPHELD":
            cascade.displace_booking(incumbent, challenge["challenger_booking_id"])
        else:
            _restore_incumbent(incumbent, challenge["id"])
        venue = db.venues.get(incumbent["venue_id"])
        if venue is not None:
            cascade.bump_venue(venue)
    return ok(serial.challenge(challenge))


@bp.post("/hold-challenges/<challenge_id>/withdraw")
def withdraw_challenge(challenge_id):
    user_id, _role = v.auth(("AnchorTenantRep",))
    challenge = get_challenge(challenge_id)

    # Ladder 3: only the challenging tenant may withdraw.
    if challenge["challenger_tenant_id"] != user_id:
        raise ApiError("ERR_TENANT_SCOPE_VIOLATION")
    # Ladder 9: from-state legality.
    if challenge["status"] != "OPEN":
        raise ApiError("ERR_INVALID_CHALLENGE_STATE")

    challenge["status"] = "WITHDRAWN"
    touch(challenge)

    tenant = db.tenants.get(challenge["challenger_tenant_id"])
    if tenant is not None:
        tenant["challenge_credits"] = int(tenant["challenge_credits"]) + 1

    incumbent = db.bookings.get(challenge["booking_id"])
    if incumbent is not None:
        _restore_incumbent(incumbent, challenge["id"])
        venue = db.venues.get(incumbent["venue_id"])
        if venue is not None:
            cascade.bump_venue(venue)
    return ok(serial.challenge(challenge))
