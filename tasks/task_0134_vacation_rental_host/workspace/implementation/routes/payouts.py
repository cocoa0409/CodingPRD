"""Payouts: reads + hold/unhold/release/mark-paid (PRD §3.8)."""
from flask import Blueprint, request

from db import db
from errors import err
from middleware import require_auth
from models import serialize, touch
from response import success, list_success
from services.access import get_or_404
from services import calc
from services.listing_util import sort_and_paginate
from validators import parse_pagination

bp = Blueprint("payouts", __name__)


def _deposit_of_booking(booking_id):
    for dep in db.security_deposits.values():
        if dep["booking_id"] == booking_id:
            return dep
    return None


def _claims_of_deposit(deposit_id):
    return [c for c in db.damage_claims.values() if c["security_deposit_id"] == deposit_id]


def _has_blocking_claim(deposit_id):
    for c in _claims_of_deposit(deposit_id):
        if c["status"] in ("FILED", "UNDER_REVIEW", "DISPUTED"):
            return True
    return False


def _approved_deductions(deposit_id):
    return sum(c["approved_cents"] for c in _claims_of_deposit(deposit_id)
               if c["status"] == "APPROVED")


@bp.get("/payouts/<pid>")
def get_payout(pid):
    require_auth({"Host", "PlatformAdmin"})
    p = get_or_404(db.payouts, pid)
    return success(serialize(p))


@bp.get("/payouts")
def list_payouts():
    require_auth({"Host", "PlatformAdmin"})
    limit, offset = parse_pagination()
    host_id = request.args.get("host_id")
    status = request.args.get("status")
    items = []
    for p in db.payouts.values():
        if host_id is not None and p["host_id"] != host_id:
            continue
        if status is not None and p["status"] != status:
            continue
        items.append(p)
    page, total = sort_and_paginate(items, limit, offset)
    return list_success(page, limit, offset, total)


@bp.post("/payouts/<pid>/hold")
def hold_payout(pid):
    require_auth({"PlatformAdmin"})
    p = get_or_404(db.payouts, pid)
    if p["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "hold requires SCHEDULED")
    deposit = _deposit_of_booking(p["booking_id"])
    # Hold only when a claim is FILED/UNDER_REVIEW/DISPUTED (PRD §3.8).
    if deposit is None or not _has_blocking_claim(deposit["id"]):
        raise err("ERR_INVALID_STATE", "no open damage claim to justify a hold")
    p["status"] = "HELD"
    touch(p)
    return success(serialize(p))


@bp.post("/payouts/<pid>/unhold")
def unhold_payout(pid):
    require_auth({"PlatformAdmin"})
    p = get_or_404(db.payouts, pid)
    if p["status"] != "HELD":
        raise err("ERR_INVALID_STATE", "unhold requires HELD")
    deposit = _deposit_of_booking(p["booking_id"])
    # Unhold only once no claim remains FILED/UNDER_REVIEW/DISPUTED (PRD §3.8).
    if deposit is not None and _has_blocking_claim(deposit["id"]):
        raise err("ERR_INVALID_STATE", "a damage claim is still open")
    p["status"] = "SCHEDULED"
    touch(p)
    return success(serialize(p))


@bp.post("/payouts/<pid>/release")
def release_payout(pid):
    require_auth({"PlatformAdmin"})
    p = get_or_404(db.payouts, pid)
    if p["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "release requires SCHEDULED")
    # Priority 14: payout must be due.
    if db.current_utc < p["release_after"]:
        raise err("ERR_PAYOUT_NOT_DUE", "payout is not yet due")
    deposit = _deposit_of_booking(p["booking_id"])
    # Cross-entity gate: blocked while a claim is FILED/UNDER_REVIEW/DISPUTED.
    if deposit is not None and _has_blocking_claim(deposit["id"]):
        raise err("ERR_CLAIM_BLOCKS_PAYOUT", "an open damage claim blocks release")
    booking = db.bookings[p["booking_id"]]
    listing = db.listings[booking["listing_id"]]
    deductions = _approved_deductions(deposit["id"]) if deposit else 0
    p["actual_cents"] = calc.payout_actual(listing, booking, deductions)
    p["status"] = "RELEASED"
    touch(p)
    return success(serialize(p))


@bp.post("/payouts/<pid>/mark-paid")
def mark_paid(pid):
    require_auth({"PlatformAdmin"})
    p = get_or_404(db.payouts, pid)
    if p["status"] != "RELEASED":
        raise err("ERR_INVALID_STATE", "mark-paid requires RELEASED")
    p["status"] = "PAID"
    touch(p)
    return success(serialize(p))
