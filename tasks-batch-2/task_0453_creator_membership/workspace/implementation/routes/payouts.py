"""Payout endpoints + sweep settlement (PRD §3.7, calc payout_settlement)."""
from flask import Blueprint, request

import errors
import response
from db import db, iso_millis
from middleware import require_auth, require_role
from services import serialize, calc
from services.common import (init_common, touch, get_body, require_string,
                             parse_pagination, paginate)
from services.lookups import get_creator, get_payout, require_creator_owner
from services.ledger import adjust_pending_payout

bp = Blueprint("payouts", __name__)


def _norm_anchor(s):
    """Normalize a cycle_anchor_date string to a comparable canonical form."""
    from datetime import datetime, timezone
    if s is None:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return iso_millis(dt)
    except (ValueError, TypeError):
        return s


@bp.post("/payouts")
def create_payout():
    ctx = require_auth()
    require_role(ctx, {"PlatformAdmin"})
    body = get_body()

    creator_id = body.get("creator_id")
    if creator_id is None:
        errors.fail(errors.ERR_INVALID_REQUEST, "Missing required field: creator_id")
    creator = get_creator(creator_id)
    cycle_anchor_date = body.get("cycle_anchor_date")
    if cycle_anchor_date is None:
        errors.fail(errors.ERR_INVALID_REQUEST, "Missing required field: cycle_anchor_date")

    target_anchor = _norm_anchor(cycle_anchor_date)

    # Select SUCCEEDED, unswept charges of the creator for this anchor (PRD §3.7).
    swept = [
        c for c in db.charges.values()
        if c["creator_id"] == creator_id
        and c["status"] == "SUCCEEDED"
        and c.get("swept_into_payout_id") is None
        and _norm_anchor(c["cycle_anchor_date"]) == target_anchor
    ]
    if not swept:
        errors.fail(errors.ERR_NOTHING_TO_PAYOUT,
                    "No SUCCEEDED unswept charge for this creator/cycle anchor")

    # Deterministic order by created_at ASC (stable via _created_seq); id never used.
    swept.sort(key=lambda c: c["_created_seq"])

    gross_cents = sum(c["net_amount_cents"] for c in swept)
    processing_fee_cents = sum(c["processing_fee_cents"] for c in swept)
    platform_fee_cents = calc.platform_fee(gross_cents, creator["platform_plan"])
    payout_amount_cents = gross_cents - platform_fee_cents - processing_fee_cents

    rec = init_common({
        "creator_id": creator_id,
        "cycle_anchor_date": target_anchor,
        "gross_cents": gross_cents,
        "platform_fee_cents": platform_fee_cents,
        "processing_fee_cents": processing_fee_cents,
        "payout_amount_cents": payout_amount_cents,
        "swept_charge_count": len(swept),
        "status": "PENDING",
    })
    db.payouts[rec["id"]] = rec

    # Mark each swept charge and reduce the creator's pending balance.
    for c in swept:
        c["swept_into_payout_id"] = rec["id"]
        touch(c)
    adjust_pending_payout(creator, -gross_cents)

    return response.success(serialize.payout(rec), status=201)


@bp.get("/payouts")
def list_payouts():
    ctx = require_auth()
    require_role(ctx, {"Creator", "PlatformAdmin"})
    limit, offset = parse_pagination()
    items = list(db.payouts.values())
    creator_id = request.args.get("creator_id")
    status = request.args.get("status")
    if creator_id is not None:
        items = [p for p in items if p["creator_id"] == creator_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    # A Creator may only see its own payouts (ownership, PRD §2.1).
    if ctx.is_creator:
        items = [p for p in items if p["creator_id"] == ctx.user_id]
    page, total = paginate(items, limit, offset)
    return response.list_success([serialize.payout(r) for r in page], limit, offset, total)


@bp.get("/payouts/<payout_id>")
def get_one_payout(payout_id):
    ctx = require_auth()
    require_role(ctx, {"Creator", "PlatformAdmin"})
    rec = get_payout(payout_id)
    require_creator_owner(ctx, rec["creator_id"])
    return response.success(serialize.payout(rec))


@bp.post("/payouts/<payout_id>/mark-paid")
def mark_paid(payout_id):
    ctx = require_auth()
    require_role(ctx, {"PlatformAdmin"})
    payout = get_payout(payout_id)
    if payout["status"] != "PENDING":
        errors.fail(errors.ERR_PAYOUT_NOT_PENDING, "Payout is not PENDING")
    payout["status"] = "PAID"
    touch(payout)
    return response.success(serialize.payout(payout))


@bp.post("/payouts/<payout_id>/reverse")
def reverse_payout(payout_id):
    ctx = require_auth()
    require_role(ctx, {"PlatformAdmin"})
    payout = get_payout(payout_id)
    if payout["status"] != "PENDING":
        errors.fail(errors.ERR_PAYOUT_NOT_REVERSIBLE, "Payout is not PENDING")

    payout["status"] = "REVERSED"
    touch(payout)

    # Un-sweep: clear swept_into_payout_id on each charge and restore pending
    # earnings (PRD §3.7).
    creator = db.creators.get(payout["creator_id"])
    restored = 0
    for c in db.charges.values():
        if c.get("swept_into_payout_id") == payout_id:
            c["swept_into_payout_id"] = None
            touch(c)
            restored += c["net_amount_cents"]
    if creator is not None and restored:
        adjust_pending_payout(creator, restored)

    return response.success(serialize.payout(payout))
