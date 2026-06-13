"""Payload factories — one per entity, input fields only."""
from .constants import PROGRAM_DEFAULTS


def create_program_payload(**overrides) -> dict:
    """Program creation payload with the canonical economic policy."""
    payload = dict(PROGRAM_DEFAULTS)
    payload.update(overrides)
    return payload


def create_tier_payload(program_id, code, qualify_threshold, earn_multiplier,
                        transfer_ratio, rank, **overrides) -> dict:
    payload = {
        "program_id": program_id,
        "code": code,
        "qualify_threshold": qualify_threshold,
        "earn_multiplier": earn_multiplier,
        "transfer_ratio": transfer_ratio,
        "rank": rank,
    }
    payload.update(overrides)
    return payload


def create_member_payload(program_id, email="m@x.com", full_name="M",
                          birth_month_day="03-10", **overrides) -> dict:
    payload = {
        "program_id": program_id,
        "email": email,
        "full_name": full_name,
        "birth_month_day": birth_month_day,
    }
    payload.update(overrides)
    return payload


def create_promotion_payload(program_id, name="DBL", bonus_multiplier=2.0,
                             starts_at="2026-06-01T00:00:00Z",
                             ends_at="2026-07-01T00:00:00Z",
                             min_eligible_cents=0, **overrides) -> dict:
    payload = {
        "program_id": program_id,
        "name": name,
        "bonus_multiplier": bonus_multiplier,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "min_eligible_cents": min_eligible_cents,
    }
    payload.update(overrides)
    return payload


def create_reward_payload(program_id, name="R", point_cost=600,
                          tier_discount_pct=0.0, stock=5, **overrides) -> dict:
    payload = {
        "program_id": program_id,
        "name": name,
        "point_cost": point_cost,
        "tier_discount_pct": tier_discount_pct,
        "stock": stock,
    }
    payload.update(overrides)
    return payload


def create_partner_payload(program_id, name="Air", transfer_block_size=100,
                           min_transfer_points=100, **overrides) -> dict:
    payload = {
        "program_id": program_id,
        "name": name,
        "transfer_block_size": transfer_block_size,
        "min_transfer_points": min_transfer_points,
    }
    payload.update(overrides)
    return payload


def create_blackout_payload(partner_account_id, starts_at, ends_at, **overrides) -> dict:
    payload = {
        "partner_account_id": partner_account_id,
        "starts_at": starts_at,
        "ends_at": ends_at,
    }
    payload.update(overrides)
    return payload


def create_purchase_event_payload(member_id, eligible_amount_cents, **overrides) -> dict:
    payload = {
        "member_id": member_id,
        "eligible_amount_cents": eligible_amount_cents,
    }
    payload.update(overrides)
    return payload


def create_redemption_payload(member_id, lines, **overrides) -> dict:
    payload = {
        "member_id": member_id,
        "lines": lines,
    }
    payload.update(overrides)
    return payload


def redemption_line(reward_id, quantity=1) -> dict:
    return {"reward_id": reward_id, "quantity": quantity}


def create_referral_payload(program_id, referrer_member_id, referee_email, **overrides) -> dict:
    payload = {
        "program_id": program_id,
        "referrer_member_id": referrer_member_id,
        "referee_email": referee_email,
    }
    payload.update(overrides)
    return payload


def create_partner_transfer_payload(member_id, partner_account_id, loyalty_points,
                                    expected_member_version, **overrides) -> dict:
    payload = {
        "member_id": member_id,
        "partner_account_id": partner_account_id,
        "loyalty_points": loyalty_points,
        "expected_member_version": expected_member_version,
    }
    payload.update(overrides)
    return payload
