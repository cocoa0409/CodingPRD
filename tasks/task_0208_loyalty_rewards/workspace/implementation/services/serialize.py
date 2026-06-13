"""Entity serializers. Each returns the public JSON shape for one record,
mirroring SCAFFOLD §1.1 field-for-field and stripping internal fields (_seq).

Member/PointsLot computed fields are re-derived here so reads always reflect
the current logical clock (PRD §2.5).
"""
from db import db
from . import ledger


def _common(rec):
    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def program_out(p):
    out = {
        "name": p["name"],
        "base_earn_rate": p["base_earn_rate"],
        "point_value_cents": p["point_value_cents"],
        "lot_expiration_months": p["lot_expiration_months"],
        "qualifying_window_months": p["qualifying_window_months"],
        "birthday_reward_points": p["birthday_reward_points"],
        "referral_referrer_points": p["referral_referrer_points"],
        "referral_referee_points": p["referral_referee_points"],
        "referral_min_qualifying_cents": p["referral_min_qualifying_cents"],
        "status": p["status"],
    }
    out.update(_common(p))
    return out


def tier_out(t):
    out = {
        "program_id": t["program_id"],
        "code": t["code"],
        "qualify_threshold": t["qualify_threshold"],
        "earn_multiplier": t["earn_multiplier"],
        "transfer_ratio": t["transfer_ratio"],
        "rank": t["rank"],
    }
    out.update(_common(t))
    return out


def member_out(m):
    """Recompute derived balances and tier on read (PRD §2.5)."""
    ledger.recompute_member(m)
    out = {
        "program_id": m["program_id"],
        "email": m["email"],
        "full_name": m["full_name"],
        "birth_month_day": m["birth_month_day"],
        "referred_by_member_id": m["referred_by_member_id"],
        "current_tier_code": m["current_tier_code"],
        "available_points": m["available_points"],
        "projected_points": m["projected_points"],
        "qualifying_points_window": m["qualifying_points_window"],
        "lifetime_earned_points": m["lifetime_earned_points"],
        "status": m["status"],
        "last_birthday_grant_year": m["last_birthday_grant_year"],
    }
    out.update(_common(m))
    return out


def lot_out(lot):
    out = {
        "member_id": lot["member_id"],
        "source_type": lot["source_type"],
        "source_id": lot["source_id"],
        "original_points": lot["original_points"],
        "remaining_points": lot["remaining_points"],
        "expires_at": lot["expires_at"],
        "status": lot["status"],
    }
    out.update(_common(lot))
    return out


def transaction_out(tx):
    # PointsTransaction is append-only: id + created_at only (PRD §2.4).
    return {
        "id": tx["id"],
        "member_id": tx["member_id"],
        "lot_id": tx["lot_id"],
        "type": tx["type"],
        "points_delta": tx["points_delta"],
        "qualifying_points": tx["qualifying_points"],
        "ref_redemption_id": tx["ref_redemption_id"],
        "ref_transfer_id": tx["ref_transfer_id"],
        "created_at": tx["created_at"],
    }


def promotion_out(p):
    out = {
        "program_id": p["program_id"],
        "name": p["name"],
        "bonus_multiplier": p["bonus_multiplier"],
        "starts_at": p["starts_at"],
        "ends_at": p["ends_at"],
        "min_eligible_cents": p["min_eligible_cents"],
        "status": p["status"],
    }
    out.update(_common(p))
    return out


def reward_out(r):
    out = {
        "program_id": r["program_id"],
        "name": r["name"],
        "point_cost": r["point_cost"],
        "tier_discount_pct": r["tier_discount_pct"],
        "stock": r["stock"],
        "status": r["status"],
    }
    out.update(_common(r))
    return out


def redemption_out(r):
    out = {
        "member_id": r["member_id"],
        "quoted_cost_points": r["quoted_cost_points"],
        "final_cost_points": r["final_cost_points"],
        "status": r["status"],
        "expected_member_version": r["expected_member_version"],
    }
    out.update(_common(r))
    return out


def redemption_line_out(l):
    # RedemptionLine: id + created_at only (PRD §2.4).
    return {
        "id": l["id"],
        "redemption_id": l["redemption_id"],
        "reward_id": l["reward_id"],
        "quantity": l["quantity"],
        "line_cost_points": l["line_cost_points"],
        "created_at": l["created_at"],
    }


def referral_out(r):
    out = {
        "program_id": r["program_id"],
        "referrer_member_id": r["referrer_member_id"],
        "referee_member_id": r["referee_member_id"],
        "referee_email": r["referee_email"],
        "status": r["status"],
        "completed_at": r["completed_at"],
    }
    out.update(_common(r))
    return out


def partner_out(p):
    out = {
        "program_id": p["program_id"],
        "name": p["name"],
        "transfer_block_size": p["transfer_block_size"],
        "min_transfer_points": p["min_transfer_points"],
        "status": p["status"],
    }
    out.update(_common(p))
    return out


def blackout_out(b):
    out = {
        "partner_account_id": b["partner_account_id"],
        "starts_at": b["starts_at"],
        "ends_at": b["ends_at"],
        "status": b["status"],
    }
    out.update(_common(b))
    return out


def transfer_out(t):
    out = {
        "member_id": t["member_id"],
        "partner_account_id": t["partner_account_id"],
        "loyalty_points": t["loyalty_points"],
        "partner_points": t["partner_points"],
        "status": t["status"],
        "expected_member_version": t["expected_member_version"],
    }
    out.update(_common(t))
    return out


def purchase_event_out(pe):
    out = {
        "member_id": pe["member_id"],
        "eligible_amount_cents": pe["eligible_amount_cents"],
        "occurred_at": pe["occurred_at"],
        "earned_points": pe["earned_points"],
        "qualifying_points": pe["qualifying_points"],
        "applied_promotion_id": pe["applied_promotion_id"],
        "posted": pe["posted"],
    }
    out.update(_common(pe))
    return out
