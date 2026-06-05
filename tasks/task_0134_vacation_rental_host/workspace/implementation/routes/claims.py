"""Security deposits + damage claims, with waterfall settlement (PRD §3.7)."""
from flask import Blueprint, request

from db import db
from errors import err
from middleware import require_auth
from models import make_entity, serialize, touch
from response import success, list_success
from services.access import (
    get_or_404, fk_or_404, require_host_owns_listing, require_guest_owns_booking,
)
from services.listing_util import sort_and_paginate
from validators import get_body, req_str, req_int, parse_pagination

bp = Blueprint("claims", __name__)


def _booking_of_deposit(deposit):
    return db.bookings.get(deposit["booking_id"])


def _listing_of_deposit(deposit):
    booking = _booking_of_deposit(deposit)
    return db.listings.get(booking["listing_id"]) if booking else None


def _claims_of_deposit(deposit_id):
    return [c for c in db.damage_claims.values() if c["security_deposit_id"] == deposit_id]


def _approved_siblings_sorted(deposit_id, exclude_id):
    """APPROVED sibling claims on a deposit, ordered created_at ASC (PRD §3.7)."""
    sibs = [c for c in _claims_of_deposit(deposit_id)
            if c["status"] == "APPROVED" and c["id"] != exclude_id]
    sibs.sort(key=lambda c: (c["created_at"], c["_seq"]))
    return sibs


def _has_non_terminal_other(deposit_id, exclude_id):
    """True if any OTHER claim on the deposit is non-terminal (FILED/UNDER_REVIEW/DISPUTED)."""
    for c in _claims_of_deposit(deposit_id):
        if c["id"] == exclude_id:
            continue
        if c["status"] in ("FILED", "UNDER_REVIEW", "DISPUTED"):
            return True
    return False


# ---- deposit reads --------------------------------------------------------

@bp.get("/security-deposits/<did>")
def get_deposit(did):
    require_auth({"Guest", "Host", "PlatformAdmin"})
    dep = get_or_404(db.security_deposits, did)
    return success(serialize(dep))


# ---- file a claim ---------------------------------------------------------

@bp.post("/security-deposits/<did>/claims")
def file_claim(did):
    user_id, role = require_auth({"Host"})
    deposit = get_or_404(db.security_deposits, did)
    booking = _booking_of_deposit(deposit)
    listing = db.listings.get(booking["listing_id"]) if booking else None
    require_host_owns_listing(listing, user_id, role)

    body = get_body()
    # security_deposit_id is also a body FK per the endpoint contract; validate it
    # references the same deposit if supplied.
    sec_dep_id = req_str(body, "security_deposit_id")
    fk_or_404(db.security_deposits, sec_dep_id)
    amount = req_int(body, "amount_cents")
    reason = req_str(body, "reason")

    # State: claim may be filed only while deposit is AUTHORIZED (priority 6).
    if deposit["status"] != "AUTHORIZED":
        raise err("ERR_INVALID_STATE", "deposit is not AUTHORIZED")
    # Booking must be IN_STAY or COMPLETED (precondition, PRD §3.7).
    if booking is None or booking["status"] not in ("IN_STAY", "COMPLETED"):
        raise err("ERR_INVALID_STATE", "booking is not IN_STAY or COMPLETED")
    # Claim amount validity (priority 13).
    if amount <= 0 or deposit["authorized_cents"] <= 0:
        raise err("ERR_INVALID_CLAIM_AMOUNT", "amount must be > 0 and deposit authorized > 0")

    claim = make_entity({
        "security_deposit_id": did,
        "amount_cents": amount,
        "approved_cents": 0,
        "reason": reason,
        "status": "FILED",
    })
    db.damage_claims[claim["id"]] = claim
    deposit["status"] = "CLAIM_OPEN"
    touch(deposit)
    return success(serialize(claim), status=201)


@bp.get("/damage-claims/<cid>")
def get_claim(cid):
    require_auth({"Guest", "Host", "PlatformAdmin"})
    claim = get_or_404(db.damage_claims, cid)
    return success(serialize(claim))


@bp.get("/security-deposits/<did>/claims")
def list_deposit_claims(did):
    require_auth({"Guest", "Host", "PlatformAdmin"})
    get_or_404(db.security_deposits, did)
    limit, offset = parse_pagination()
    status = request.args.get("status")
    items = [c for c in db.damage_claims.values()
             if c["security_deposit_id"] == did and (status is None or c["status"] == status)]
    page, total = sort_and_paginate(items, limit, offset)
    return list_success(page, limit, offset, total)


# ---- claim transitions ----------------------------------------------------

@bp.post("/damage-claims/<cid>/review")
def review_claim(cid):
    require_auth({"PlatformAdmin"})
    claim = get_or_404(db.damage_claims, cid)
    # FILED->UNDER_REVIEW or DISPUTED->UNDER_REVIEW.
    if claim["status"] not in ("FILED", "DISPUTED"):
        raise err("ERR_INVALID_STATE", "review requires FILED or DISPUTED")
    claim["status"] = "UNDER_REVIEW"
    touch(claim)
    return success(serialize(claim))


@bp.post("/damage-claims/<cid>/approve")
def approve_claim(cid):
    require_auth({"PlatformAdmin"})
    claim = get_or_404(db.damage_claims, cid)
    if claim["status"] != "UNDER_REVIEW":
        raise err("ERR_INVALID_STATE", "approve requires UNDER_REVIEW")
    deposit = db.security_deposits[claim["security_deposit_id"]]

    # Waterfall: remaining = authorized - sum(already-APPROVED siblings, created_at ASC).
    sum_already = sum(c["approved_cents"] for c in _approved_siblings_sorted(deposit["id"], cid))
    remaining = max(0, deposit["authorized_cents"] - sum_already)
    approved = min(claim["amount_cents"], remaining)
    claim["approved_cents"] = approved
    # held_cents := authorized - (sum_already + approved).
    deposit["held_cents"] = deposit["authorized_cents"] - (sum_already + approved)
    touch(deposit)
    claim["status"] = "APPROVED"
    touch(claim)
    # If no other non-terminal claim remains, deposit -> SETTLED.
    if not _has_non_terminal_other(deposit["id"], cid):
        deposit["status"] = "SETTLED"
        touch(deposit)
    return success(serialize(claim))


@bp.post("/damage-claims/<cid>/deny")
def deny_claim(cid):
    require_auth({"PlatformAdmin"})
    claim = get_or_404(db.damage_claims, cid)
    if claim["status"] != "UNDER_REVIEW":
        raise err("ERR_INVALID_STATE", "deny requires UNDER_REVIEW")
    deposit = db.security_deposits[claim["security_deposit_id"]]
    # Compensating restore if previously APPROVED (approved_cents > 0).
    if claim["approved_cents"] > 0:
        deposit["held_cents"] = deposit["held_cents"] + claim["approved_cents"]
        touch(deposit)
    claim["approved_cents"] = 0
    claim["status"] = "DENIED"
    touch(claim)
    # If no other non-terminal claim remains, deposit -> SETTLED.
    if not _has_non_terminal_other(deposit["id"], cid):
        deposit["status"] = "SETTLED"
        touch(deposit)
    return success(serialize(claim))


@bp.post("/damage-claims/<cid>/dispute")
def dispute_claim(cid):
    user_id, role = require_auth({"Guest"})
    claim = get_or_404(db.damage_claims, cid)
    deposit = db.security_deposits[claim["security_deposit_id"]]
    booking = _booking_of_deposit(deposit)
    require_guest_owns_booking(booking, user_id, role)
    if claim["status"] not in ("UNDER_REVIEW", "APPROVED"):
        raise err("ERR_INVALID_STATE", "dispute requires UNDER_REVIEW or APPROVED")
    was_approved = claim["status"] == "APPROVED"
    claim["status"] = "DISPUTED"
    touch(claim)
    # Disputing an APPROVED claim re-opens the deposit; the prior debit is NOT
    # reversed here (PRD §3.7) — reversal happens only on a later DENY.
    if was_approved:
        deposit["status"] = "CLAIM_OPEN"
        touch(deposit)
    return success(serialize(claim))
