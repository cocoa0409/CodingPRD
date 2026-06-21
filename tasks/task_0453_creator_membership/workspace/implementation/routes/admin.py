"""Administrative endpoints: logical clock + billing cycle (PRD §3.3).

POST /_clock/set_current_utc — set the logical clock (default boot value
  2026-01-01T00:00:00Z; never wall-clock).
POST /_billing/run-cycle — lapse grace, expire offers, renew ACTIVE MONTHLY.
"""
import calendar
from datetime import datetime, timezone

from flask import Blueprint

import errors
import response
from db import db, iso_millis
from middleware import require_auth, require_role
from services import calc
from services.common import touch, get_body
from services.ledger import create_charge, recompute_active_pledge_count
from services.common import init_common

bp = Blueprint("admin", __name__)


def _parse_iso(s):
    if s is None:
        return None
    if not isinstance(s, str):
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@bp.post("/_clock/set_current_utc")
def set_clock():
    ctx = require_auth()
    require_role(ctx, {"PlatformAdmin"})
    body = get_body()
    to_iso = body.get("to_iso8601")
    if to_iso is None:
        errors.fail(errors.ERR_INVALID_REQUEST, "Missing required field: to_iso8601")
    dt = _parse_iso(to_iso)
    if dt is None:
        errors.fail(errors.ERR_INVALID_REQUEST, "to_iso8601 is not a valid ISO 8601 instant")
    db.clock = dt
    return response.success({"current_utc": iso_millis(db.clock)})


def _next_anchor(anchor_dt):
    """First day (00:00:00Z) of the month after anchor_dt's month."""
    year = anchor_dt.year
    month = anchor_dt.month
    if month == 12:
        return datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    return datetime(year, month + 1, 1, tzinfo=timezone.utc)


@bp.post("/_billing/run-cycle")
def run_cycle():
    ctx = require_auth()
    require_role(ctx, {"PlatformAdmin"})

    now = db.now()
    lapsed_pledge_ids = []
    expired_offer_ids = []
    renewal_charge_ids = []

    # Duty 1: lapse grace. A pledge in GRACE whose grace_deadline <= now
    # advances GRACE->LAPSED with the cancellation cascade + auto WinBackOffer
    # (PRD §3.3).
    for pledge in list(db.pledges.values()):
        if pledge["billing_status"] != "GRACE":
            continue
        deadline = _parse_iso(pledge.get("grace_deadline"))
        if deadline is None:
            continue
        if now >= deadline:
            pledge["billing_status"] = "LAPSED"
            pledge["lifecycle_status"] = "CANCELLED"
            pledge["lapsed_at"] = iso_millis(now)
            pledge["grace_deadline"] = None
            touch(pledge)
            tier = db.tiers.get(pledge["tier_id"])
            if tier is not None:
                recompute_active_pledge_count(tier)
            # Auto-create a WinBackOffer for the freshly lapsed pledge (PRD §3.3).
            offer = init_common({
                "pledge_id": pledge["id"],
                "discount_pct": 0.30,
                "expires_at": iso_millis(calc.win_back_offer_expiry(now)),
                "status": "OFFERED",
            })
            db.win_back_offers[offer["id"]] = offer
            lapsed_pledge_ids.append(pledge["id"])

    # Duty 2: expire offers. An OFFERED offer whose expires_at is now in the
    # past (now > expires_at) advances to EXPIRED (PRD §3.3).
    for offer in db.win_back_offers.values():
        if offer["status"] != "OFFERED":
            continue
        exp = _parse_iso(offer.get("expires_at"))
        if exp is None:
            continue
        if now > exp:
            offer["status"] = "EXPIRED"
            touch(offer)
            expired_offer_ids.append(offer["id"])

    # Duty 3: renew. Every ACTIVE MONTHLY pledge whose next cycle anchor is at or
    # before now receives a fresh CYCLE_RENEWAL charge PENDING, has its
    # cycle_anchor_date advanced, and current_cycle_charged_cents reset to 0
    # (PRD §3.3).
    for pledge in db.pledges.values():
        if pledge["lifecycle_status"] != "ACTIVE":
            continue
        if pledge["billing_model"] != "MONTHLY":
            continue
        anchor = _parse_iso(pledge.get("cycle_anchor_date"))
        if anchor is None:
            continue
        next_anchor = _next_anchor(anchor)
        if next_anchor > now:
            continue
        creator = db.creators.get(pledge["creator_id"])
        patron = db.patrons.get(pledge["patron_id"])
        tier = db.tiers.get(pledge["tier_id"])
        if creator is None or patron is None or tier is None:
            continue
        # Full-month renewal at the new anchor (the 1st => full month).
        gross = tier.get("monthly_fee_cents") or 0
        # Advance the cycle first so the charge carries the new anchor.
        pledge["cycle_anchor_date"] = iso_millis(next_anchor)
        pledge["current_cycle_charged_cents"] = 0
        touch(pledge)
        charge = create_charge(pledge, creator, patron, "CYCLE_RENEWAL", gross, next_anchor)
        renewal_charge_ids.append(charge["id"])

    return response.success({
        "lapsed_pledge_ids": lapsed_pledge_ids,
        "expired_offer_ids": expired_offer_ids,
        "renewal_charge_ids": renewal_charge_ids,
    })
