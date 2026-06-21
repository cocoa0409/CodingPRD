"""Purchase events (earn). Mints redeemable points, selects a promotion, sets
qualifying points, recomputes tier, completes a pending referral. (PRD §3.3, §3.6)"""
from flask import Blueprint, request

from db import db
from errors import (err, ERR_PROGRAM_NOT_ACTIVE, ERR_MEMBER_NOT_ACTIVE,
                    ERR_NEGATIVE_AMOUNT, ERR_INVALID_REQUEST)
from middleware import require_roles
from response import success
from services import serialize, ledger
from services.helpers import (get_json_body, require_str, require_int, opt_str,
                              parse_iso, fmt_iso, paginate)
from services.lookup import get_member, assert_member_owner, get_purchase_event

bp = Blueprint("purchases", __name__)


def select_promotion(program_id, occurred_at, eligible_amount_cents):
    """Single applicable promotion (PRD §3.10): window covers the moment
    (starts_at <= t < ends_at) and min_eligible_cents is satisfied. The
    promotion's lifecycle status is not required to be ACTIVE — coverage is by
    window. Pick the earliest-created qualifying promotion deterministically."""
    candidates = []
    for promo in db.promotions.values():
        if promo["program_id"] != program_id:
            continue
        if promo["status"] == "CANCELLED":
            continue
        starts = parse_iso(promo["starts_at"])
        ends = parse_iso(promo["ends_at"])
        if starts <= occurred_at < ends and eligible_amount_cents >= promo["min_eligible_cents"]:
            candidates.append(promo)
    if not candidates:
        return None
    candidates.sort(key=lambda p: p["_seq"])
    return candidates[0]


def maybe_complete_referral(member, eligible_amount_cents):
    """Complete the bound PENDING referral if the purchase meets the threshold
    (PRD §3.6). The referee is `member`."""
    program = db.programs[member["program_id"]]
    if eligible_amount_cents < program["referral_min_qualifying_cents"]:
        return
    for ref in db.referrals.values():
        if ref["program_id"] != member["program_id"]:
            continue
        if ref["status"] != "PENDING":
            continue
        if ref["referee_member_id"] != member["id"]:
            continue
        referrer = db.members.get(ref["referrer_member_id"])
        if referrer is None:
            continue
        if member["status"] != "ACTIVE" or referrer["status"] != "ACTIVE":
            continue
        # Complete: mint to referrer and referee.
        ledger.mint_lot(referrer, source_type="REFERRAL",
                        points=program["referral_referrer_points"],
                        source_id=ref["id"], tx_type="REFERRAL")
        ledger.mint_lot(member, source_type="REFERRAL",
                        points=program["referral_referee_points"],
                        source_id=ref["id"], tx_type="REFERRAL")
        ref["status"] = "COMPLETED"
        ref["completed_at"] = fmt_iso(db.current_clock)
        db.touch(ref)
        ledger.recompute_member(referrer)
        db.touch(referrer)
        # referee balances recomputed by caller after earn; recompute now too
        ledger.recompute_member(member)
        break


@bp.post("/purchase-events")
def create_purchase():
    _, role = require_roles("ProgramAdmin", "Member")
    body = get_json_body()
    member_id = require_str(body, "member_id")
    eligible_amount_cents = require_int(body, "eligible_amount_cents")
    occurred_at_raw = opt_str(body, "occurred_at", None)

    member = get_member(member_id)
    user_id = request.headers.get("X-User-ID")
    assert_member_owner(role, user_id, member_id)

    program = db.programs[member["program_id"]]

    # shape: non-negative amount (priority 5)
    if eligible_amount_cents < 0:
        raise err(ERR_NEGATIVE_AMOUNT, "eligible_amount_cents must be >= 0")

    occurred_at = parse_iso(occurred_at_raw) if occurred_at_raw else db.current_clock

    # program-active gate (priority 11)
    if program["status"] != "ACTIVE":
        raise err(ERR_PROGRAM_NOT_ACTIVE, "Program is not ACTIVE")
    # member-active gate (priority 13)
    if member["status"] != "ACTIVE":
        raise err(ERR_MEMBER_NOT_ACTIVE, "Member is not ACTIVE")

    # Resolve tier BEFORE this earn (PRD §3.3).
    ledger.recompute_member(member)
    tier = ledger.tier_for_code(member["program_id"], member["current_tier_code"])
    tier_multiplier = tier["earn_multiplier"] if tier else 1.0

    promo = select_promotion(member["program_id"], occurred_at, eligible_amount_cents)
    promo_multiplier = promo["bonus_multiplier"] if promo else 1.0

    # earned_points: full real product, single floor (PRD §2.7 / §3.3).
    dollars = eligible_amount_cents / 100.0
    earned_points = ledger.floor_product(dollars, program["base_earn_rate"],
                                         tier_multiplier, promo_multiplier)
    # qualifying_points: base spend only (excludes tier & promo).
    qualifying_points = ledger.floor_product(dollars, program["base_earn_rate"])

    pe = {
        "member_id": member_id,
        "eligible_amount_cents": eligible_amount_cents,
        "occurred_at": fmt_iso(occurred_at),
        "earned_points": earned_points,
        "qualifying_points": qualifying_points,
        "applied_promotion_id": promo["id"] if promo else None,
        "posted": True,
    }
    db.stamp_create(pe)
    db.purchase_events[pe["id"]] = pe

    # Mint the EARN_PURCHASE lot + ledger row (qualifying_points carried on row).
    if earned_points > 0:
        ledger.mint_lot(member, source_type="EARN_PURCHASE",
                        points=earned_points, source_id=pe["id"],
                        tx_type="EARN_PURCHASE",
                        qualifying_points=qualifying_points)
    else:
        # No lot to mint (zero earn) but the qualifying contribution must still
        # be recorded for tier evaluation: append a zero-points aggregate row.
        ledger.append_tx(member, lot_id=None, tx_type="EARN_PURCHASE",
                         points_delta=0, qualifying_points=qualifying_points)

    # Recompute tier + balances after the earn (PRD §3.3, §3.4).
    ledger.recompute_member(member)
    db.touch(member)  # version advances by 1 (PRD §3.3)

    # Referral completion side effect (PRD §3.6).
    maybe_complete_referral(member, eligible_amount_cents)
    ledger.recompute_member(member)

    return success(serialize.purchase_event_out(pe), 201)


@bp.get("/purchase-events/<pid>")
def get_purchase(pid):
    _, role = require_roles("ProgramAdmin", "Member")
    pe = get_purchase_event(pid)
    user_id = request.headers.get("X-User-ID")
    assert_member_owner(role, user_id, pe["member_id"])
    return success(serialize.purchase_event_out(pe), 200)


@bp.get("/purchase-events")
def list_purchases():
    _, role = require_roles("ProgramAdmin", "Member")
    user_id = request.headers.get("X-User-ID")
    member_id = request.args.get("member_id")
    applied_promotion_id = request.args.get("applied_promotion_id")
    items = list(db.purchase_events.values())
    if role == "Member":
        items = [pe for pe in items if pe["member_id"] == user_id]
    if member_id is not None:
        items = [pe for pe in items if pe["member_id"] == member_id]
    if applied_promotion_id is not None:
        items = [pe for pe in items if pe["applied_promotion_id"] == applied_promotion_id]
    page, pg = paginate(items)
    return success([serialize.purchase_event_out(x) for x in page], 200, pg)
