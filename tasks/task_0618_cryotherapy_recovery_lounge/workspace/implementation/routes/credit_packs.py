"""Credit-pack endpoints (PRD §3.6)."""

from flask import Blueprint, request, g

import errors
from clock import clock, add_days, format_iso8601_ms
from db import db
from helpers import (
    get_body, require_int_min, require_bool, parse_pagination, sort_by_created,
    paginate, stamp_new, touch,
)
from middleware import require_roles
from response import success, list_success
from serializers import serialize_credit_pack
from services.calculations import (
    credit_pack_price_cents, credit_pack_refund_cents, PACK_VALIDITY_DAYS,
)
from services.compute import recompute_credit_balance
from services.lookups import (
    get_member_or_404, get_pack_or_404, require_member_ownership,
)

bp = Blueprint("credit_packs", __name__)


@bp.post("/members/<member_id>/credit-packs")
@require_roles("Member", "LocationManager")
def purchase_pack(member_id):
    member = get_member_or_404(member_id)
    require_member_ownership(member_id)
    body = get_body()
    total_credits = require_int_min(body, "total_credits", 1)
    is_intro = require_bool(body, "is_intro")
    # Priority 18: intro-offer uniqueness.
    if is_intro and member["intro_offer_used"]:
        raise errors.ApiError(
            errors.ERR_INTRO_ALREADY_USED, 409,
            "Member has already used the one-time intro pack")
    price = credit_pack_price_cents(total_credits, is_intro)
    expires_at = format_iso8601_ms(add_days(clock.now(), PACK_VALIDITY_DAYS))
    pack = stamp_new({
        "member_id": member_id,
        "is_intro": is_intro,
        "total_credits": total_credits,
        "remaining_credits": total_credits,
        "price_paid_cents": price,
        "status": "ACTIVE",
        "expires_at": expires_at,
    })
    db.credit_packs[pack["id"]] = pack
    if is_intro:
        member["intro_offer_used"] = True
        touch(member)
    recompute_credit_balance(member)
    return success(serialize_credit_pack(pack), 201)


@bp.get("/credit-packs")
@require_roles("PlatformAdmin", "LocationManager", "Member")
def list_packs():
    limit, offset = parse_pagination()
    member_id = request.args.get("member_id")
    status = request.args.get("status")
    items = list(db.credit_packs.values())
    if g.user_role == "Member":
        items = [p for p in items if p["member_id"] == g.user_id]
    if member_id is not None:
        items = [p for p in items if p["member_id"] == member_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    items = sort_by_created(items)
    page, total = paginate(items, limit, offset)
    return list_success([serialize_credit_pack(p) for p in page], limit, offset, total)


@bp.get("/credit-packs/<pack_id>")
@require_roles("PlatformAdmin", "LocationManager", "Member")
def get_pack(pack_id):
    pack = get_pack_or_404(pack_id)
    if g.user_role == "Member" and g.user_id != pack["member_id"]:
        raise errors.forbidden("A member may read only their own credit packs")
    return success(serialize_credit_pack(pack), 200)


@bp.post("/members/<member_id>/credit-packs/<pack_id>/refund")
@require_roles("LocationManager")
def refund_pack(member_id, pack_id):
    # Path existence left-to-right: member, then pack.
    get_member_or_404(member_id)
    pack = get_pack_or_404(pack_id)
    if pack["member_id"] != member_id:
        raise errors.not_found("CreditPack not found")
    # Refund permitted only while ACTIVE and remaining_credits > 0 (PRD §3.6).
    if pack["status"] != "ACTIVE" or pack["remaining_credits"] <= 0:
        raise errors.invalid_state("Credit pack is not refundable")
    # Compute refund per the dual-variant rule before zeroing remaining_credits.
    refund_amount = credit_pack_refund_cents(pack)
    pack["refund_amount_cents"] = refund_amount  # internal bookkeeping, not emitted
    pack["remaining_credits"] = 0
    pack["status"] = "REFUNDED"
    touch(pack)
    member = db.members.get(member_id)
    recompute_credit_balance(member)
    return success(serialize_credit_pack(pack), 200)
