"""Pledge endpoints + dual-axis state machine (PRD §3.2, §3.4, §3.6).

lifecycle_status: DRAFT -> ACTIVE -> PAUSED -> ... -> CANCELLED (+ reactivate)
billing_status:   CURRENT -> PAST_DUE -> GRACE -> LAPSED  (parallel axis)
"""
from flask import Blueprint, request

import errors
import response
from db import db, iso_millis, new_id
from middleware import require_auth, require_role
from services import serialize, calc
from services.common import (init_common, touch, get_body, parse_pagination, paginate)
from services.lookups import (get_creator, get_tier, get_patron, get_pledge,
                              require_patron_owner)
from services.ledger import (create_charge, recompute_active_pledge_count)

bp = Blueprint("pledges", __name__)

LIFECYCLE_STATES = {"DRAFT", "ACTIVE", "PAUSED", "CANCELLED"}


def _parse_iso(s):
    from datetime import datetime, timezone
    if s is None:
        return None
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


@bp.post("/pledges")
def create_pledge():
    ctx = require_auth()
    require_role(ctx, {"Patron"})
    body = get_body()

    # body FK existence (priority 5) before ownership decision; but ownership
    # (priority 3) is checked once patron_id is known.
    patron_id = body.get("patron_id")
    creator_id = body.get("creator_id")
    tier_id = body.get("tier_id")
    if patron_id is None:
        errors.fail(errors.ERR_INVALID_REQUEST, "Missing required field: patron_id")
    if creator_id is None:
        errors.fail(errors.ERR_INVALID_REQUEST, "Missing required field: creator_id")
    if tier_id is None:
        errors.fail(errors.ERR_INVALID_REQUEST, "Missing required field: tier_id")

    # Ownership: a Patron may only create its own pledge (PRD §2.1).
    require_patron_owner(ctx, patron_id)

    patron = get_patron(patron_id)
    creator = get_creator(creator_id)
    tier = get_tier(tier_id)

    # State: tier must be PUBLISHED (PRD §3.2).
    if tier["status"] != "PUBLISHED":
        errors.fail(errors.ERR_TIER_NOT_PUBLISHED, "Tier is not PUBLISHED")

    # Cross-link: the tier must belong to the named creator (PRD §3.2).
    if tier["creator_id"] != creator_id:
        errors.fail(errors.ERR_CROSS_LINK_MISMATCH, "Tier does not belong to creator")

    # Membership-interval exclusivity (ERR_DUPLICATE_PLEDGE, PRD §3.2).
    for p in db.pledges.values():
        if p["patron_id"] == patron_id and p["creator_id"] == creator_id and \
                p["lifecycle_status"] in ("DRAFT", "ACTIVE", "PAUSED"):
            errors.fail(errors.ERR_DUPLICATE_PLEDGE,
                        "Patron already holds an open pledge to this creator")

    anchor = db.now()
    rec = init_common({
        "patron_id": patron_id,
        "creator_id": creator_id,
        "tier_id": tier_id,
        "scheduled_tier_id": None,
        "billing_model": tier["billing_model"],
        "cycle_anchor_date": iso_millis(anchor),
        "current_cycle_charged_cents": 0,
        "lifecycle_status": "DRAFT",
        "billing_status": "CURRENT",
        "grace_deadline": None,
        "lapsed_at": None,
        "win_back_applied": False,
    })
    db.pledges[rec["id"]] = rec

    # Initial proration for MONTHLY tiers (PRD §3.4, calc initial_proration).
    if tier["billing_model"] == "MONTHLY":
        prorated = calc.initial_proration(tier["monthly_fee_cents"], anchor)
        if creator["charge_timing"] == "UP_FRONT":
            # Charge created PENDING immediately; settle activates the pledge.
            create_charge(rec, creator, patron, "INITIAL_PRORATION", prorated, anchor)
        # END_OF_MONTH: no immediate charge; rolled into the next run-cycle sweep.

    return response.success(serialize.pledge(rec), status=201)


@bp.get("/pledges")
def list_pledges():
    ctx = require_auth()
    require_role(ctx, {"Creator", "Patron", "PlatformAdmin"})
    limit, offset = parse_pagination()
    items = list(db.pledges.values())
    for key in ("patron_id", "creator_id", "tier_id", "scheduled_tier_id", "lifecycle_status"):
        val = request.args.get(key)
        if val is not None:
            items = [p for p in items if p.get(key) == val]
    page, total = paginate(items, limit, offset)
    return response.list_success([serialize.pledge(r) for r in page], limit, offset, total)


@bp.get("/pledges/<pledge_id>")
def get_one_pledge(pledge_id):
    ctx = require_auth()
    require_role(ctx, {"Creator", "Patron", "PlatformAdmin"})
    rec = get_pledge(pledge_id)
    return response.success(serialize.pledge(rec))


def _check_occ(body, pledge):
    """OCC on expected_pledge_version (PRD §2.7). Required field; mismatch ->
    ERR_STALE_VERSION (412)."""
    if "expected_pledge_version" not in body or body["expected_pledge_version"] is None:
        errors.fail(errors.ERR_INVALID_REQUEST, "Missing required field: expected_pledge_version")
    expected = body["expected_pledge_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        errors.fail(errors.ERR_INVALID_REQUEST, "expected_pledge_version must be an integer")
    if expected != pledge["version"]:
        errors.fail(errors.ERR_STALE_VERSION, "Pledge version mismatch")


@bp.post("/pledges/<pledge_id>/pause")
def pause_pledge(pledge_id):
    ctx = require_auth()
    require_role(ctx, {"Patron"})
    pledge = get_pledge(pledge_id)
    require_patron_owner(ctx, pledge["patron_id"])
    body = get_body()

    # State (priority 7) before OCC (priority 15) per validation ordering.
    if pledge["lifecycle_status"] != "ACTIVE":
        errors.fail(errors.ERR_PLEDGE_NOT_ACTIVE, "Pledge is not ACTIVE")
    _check_occ(body, pledge)

    pledge["lifecycle_status"] = "PAUSED"
    touch(pledge)  # increments version by 1 (PRD §3.2)
    return response.success(serialize.pledge(pledge))


@bp.post("/pledges/<pledge_id>/resume")
def resume_pledge(pledge_id):
    ctx = require_auth()
    require_role(ctx, {"Patron"})
    pledge = get_pledge(pledge_id)
    require_patron_owner(ctx, pledge["patron_id"])

    # Resume is NOT OCC-guarded and takes no version field (PRD §2.7).
    if pledge["lifecycle_status"] != "PAUSED":
        errors.fail(errors.ERR_PLEDGE_NOT_PAUSED, "Pledge is not PAUSED")

    pledge["lifecycle_status"] = "ACTIVE"
    # Re-anchor cycle_anchor_date to the current clock cycle (PRD §3.2).
    pledge["cycle_anchor_date"] = iso_millis(db.now())
    touch(pledge)  # increments version by 1
    return response.success(serialize.pledge(pledge))


@bp.post("/pledges/<pledge_id>/upgrade")
def upgrade_pledge(pledge_id):
    ctx = require_auth()
    require_role(ctx, {"Patron"})
    pledge = get_pledge(pledge_id)
    require_patron_owner(ctx, pledge["patron_id"])
    body = get_body()

    new_tier_id = body.get("new_tier_id")
    if new_tier_id is None:
        errors.fail(errors.ERR_INVALID_REQUEST, "Missing required field: new_tier_id")
    new_tier = get_tier(new_tier_id)

    # OCC (PRD §2.7).
    _check_occ(body, pledge)

    creator = get_creator(pledge["creator_id"])
    patron = get_patron(pledge["patron_id"])
    old_tier = db.tiers.get(pledge["tier_id"])

    anchor = _parse_iso(pledge["cycle_anchor_date"]) or db.now()

    if creator["charge_timing"] == "UP_FRONT":
        # Compute proration delta and create UPGRADE_PRORATION charge PENDING
        # (PRD §3.4). The pledge's tier moves now.
        base = (new_tier.get("monthly_fee_cents") or 0) - (old_tier.get("monthly_fee_cents") or 0)
        delta = calc.initial_proration(base, anchor)
        pledge["tier_id"] = new_tier_id
        pledge["billing_model"] = new_tier["billing_model"]
        pledge["scheduled_tier_id"] = None
        touch(pledge)  # increments version by 1
        create_charge(pledge, creator, patron, "UPGRADE_PRORATION", delta, anchor)
        # Recompute active_pledge_count for old and new tier (PRD §3.4).
        if old_tier is not None:
            recompute_active_pledge_count(old_tier)
        recompute_active_pledge_count(new_tier)
    else:
        # END_OF_MONTH: no immediate charge; record scheduled_tier_id (PRD §3.4).
        pledge["scheduled_tier_id"] = new_tier_id
        touch(pledge)  # increments version by 1

    return response.success(serialize.pledge(pledge))


@bp.post("/pledges/<pledge_id>/cancel")
def cancel_pledge(pledge_id):
    ctx = require_auth()
    require_role(ctx, {"Patron"})
    pledge = get_pledge(pledge_id)
    require_patron_owner(ctx, pledge["patron_id"])

    if pledge["lifecycle_status"] not in ("ACTIVE", "PAUSED"):
        errors.fail(errors.ERR_PLEDGE_NOT_CANCELLABLE, "Pledge is not ACTIVE/PAUSED")

    _do_cancel_cascade(pledge)
    return response.success(serialize.pledge(pledge))


def _do_cancel_cascade(pledge):
    """Four-part cancellation cascade (PRD §3.2)."""
    pledge["lifecycle_status"] = "CANCELLED"
    pledge["billing_status"] = "LAPSED"
    pledge["lapsed_at"] = iso_millis(db.now())
    pledge["grace_deadline"] = None
    touch(pledge)

    tier = db.tiers.get(pledge["tier_id"])
    if tier is not None:
        recompute_active_pledge_count(tier)

    # Cross-entity: close OPEN conversations with this creator if the patron no
    # longer holds any other ACTIVE/PAUSED pledge to that creator (PRD §3.2).
    has_other_live = any(
        p["id"] != pledge["id"]
        and p["patron_id"] == pledge["patron_id"]
        and p["creator_id"] == pledge["creator_id"]
        and p["lifecycle_status"] in ("ACTIVE", "PAUSED")
        for p in db.pledges.values()
    )
    if not has_other_live:
        for conv in db.conversations.values():
            if conv["creator_id"] == pledge["creator_id"] and \
                    conv["patron_id"] == pledge["patron_id"] and \
                    conv["status"] == "OPEN":
                conv["status"] = "CLOSED"
                touch(conv)


@bp.post("/pledges/<pledge_id>/reactivate")
def reactivate_pledge(pledge_id):
    ctx = require_auth()
    require_role(ctx, {"Patron"})
    pledge = get_pledge(pledge_id)
    require_patron_owner(ctx, pledge["patron_id"])
    body = get_body()

    # Reactivate may optionally carry expected_pledge_version, but it is not
    # required and not OCC-enforced (PRD §2.7).
    if "expected_pledge_version" in body and body["expected_pledge_version"] is not None:
        expected = body["expected_pledge_version"]
        if isinstance(expected, bool) or not isinstance(expected, int):
            errors.fail(errors.ERR_INVALID_REQUEST,
                        "expected_pledge_version must be an integer")

    # State: must be CANCELLED + LAPSED (PRD §3.2).
    if pledge["lifecycle_status"] != "CANCELLED" or pledge["billing_status"] != "LAPSED":
        errors.fail(errors.ERR_PLEDGE_NOT_REACTIVATABLE,
                    "Pledge is not CANCELLED+LAPSED")

    creator = get_creator(pledge["creator_id"])
    patron = get_patron(pledge["patron_id"])
    tier = db.tiers.get(pledge["tier_id"])

    # Find a redeemable win-back offer for this pledge (OFFERED + within window).
    now = db.now()
    redeemable = None
    for offer in db.win_back_offers.values():
        if offer["pledge_id"] != pledge["id"]:
            continue
        if offer["status"] != "OFFERED":
            continue
        exp = _parse_iso(offer["expires_at"])
        if exp is not None and now <= exp:
            redeemable = offer
            break

    discount_pct = redeemable["discount_pct"] if redeemable else 0

    anchor = now
    # Reactivation re-anchors the cycle to the current clock.
    pledge["cycle_anchor_date"] = iso_millis(anchor)
    pledge["lifecycle_status"] = "ACTIVE"
    pledge["billing_status"] = "CURRENT"
    pledge["current_cycle_charged_cents"] = 0
    pledge["grace_deadline"] = None
    if redeemable:
        pledge["win_back_applied"] = True
    touch(pledge)

    if tier is not None:
        recompute_active_pledge_count(tier)

    # WIN_BACK charge: prorate first, then discount (calc win_back_first_charge).
    monthly_fee = (tier.get("monthly_fee_cents") if tier else None) or 0
    gross = calc.win_back_first_charge(monthly_fee, anchor, discount_pct)
    create_charge(pledge, creator, patron, "WIN_BACK", gross, anchor)

    # Redeem the offer (OFFERED -> REDEEMED) (PRD §3.6).
    if redeemable:
        redeemable["status"] = "REDEEMED"
        touch(redeemable)

    return response.success(serialize.pledge(pledge))
