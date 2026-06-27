"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "MERCHANT_NAME": "Test Merchant",
    "ONLINE_RATE_BPS": 500,
    "INSTORE_RATE_BPS": 200,
    "OFFER_STARTS_AT": "2026-01-01T00:00:00Z",
    "OFFER_EXPIRES_AT": "2027-01-01T00:00:00Z",
}


def create_merchant_payload(**overrides) -> dict:
    """POST /merchants input. Required: name, online_rate_bps, instore_rate_bps.
    attribution_window_hours / double_dip_allowed / maturity_hold_days optional."""
    payload = {
        "name": DEFAULTS["MERCHANT_NAME"],
        "online_rate_bps": DEFAULTS["ONLINE_RATE_BPS"],
        "instore_rate_bps": DEFAULTS["INSTORE_RATE_BPS"],
    }
    payload.update(overrides)
    return payload


def create_offer_payload(merchant_id: str, offer_type: str, **overrides) -> dict:
    """POST /offers input. Required: merchant_id, offer_type, starts_at, expires_at.
    bonus_rate_bps / rebate_cents / min_spend_cents optional."""
    payload = {
        "merchant_id": merchant_id,
        "offer_type": offer_type,
        "starts_at": DEFAULTS["OFFER_STARTS_AT"],
        "expires_at": DEFAULTS["OFFER_EXPIRES_AT"],
    }
    payload.update(overrides)
    return payload


def create_member_payload(email: str, **overrides) -> dict:
    """POST /members input. Required: email. referred_by_member_id optional."""
    payload = {"email": email}
    payload.update(overrides)
    return payload


def create_clickthrough_payload(member_id: str, merchant_id: str, **overrides) -> dict:
    """POST /clickthroughs input. Required: member_id, merchant_id. offer_id optional."""
    payload = {"member_id": member_id, "merchant_id": merchant_id}
    payload.update(overrides)
    return payload


def create_receipt_scan_payload(member_id: str, merchant_id: str, offer_id: str,
                                purchase_total_cents: int, purchased_at: str,
                                **overrides) -> dict:
    """POST /receipt-scans input. Required: member_id, merchant_id, offer_id,
    purchase_total_cents, purchased_at."""
    payload = {
        "member_id": member_id,
        "merchant_id": merchant_id,
        "offer_id": offer_id,
        "purchase_total_cents": purchase_total_cents,
        "purchased_at": purchased_at,
    }
    payload.update(overrides)
    return payload


def create_reward_claim_payload(member_id: str, merchant_id: str, click_through_id: str,
                                purchase_amount_cents: int, **overrides) -> dict:
    """POST /reward-claims input (ONLINE). Required: member_id, merchant_id,
    click_through_id, purchase_amount_cents. offer_id optional."""
    payload = {
        "member_id": member_id,
        "merchant_id": merchant_id,
        "click_through_id": click_through_id,
        "purchase_amount_cents": purchase_amount_cents,
    }
    payload.update(overrides)
    return payload


def create_cashout_payload(member_id: str, method: str, requested_amount_cents: int,
                           expected_member_version: int, **overrides) -> dict:
    """POST /cashouts input. Required: member_id, method, requested_amount_cents,
    expected_member_version."""
    payload = {
        "member_id": member_id,
        "method": method,
        "requested_amount_cents": requested_amount_cents,
        "expected_member_version": expected_member_version,
    }
    payload.update(overrides)
    return payload


def create_return_event_payload(reward_claim_id: str, returned_amount_cents: int,
                                **overrides) -> dict:
    """POST /return-events input. Required: reward_claim_id, returned_amount_cents."""
    payload = {
        "reward_claim_id": reward_claim_id,
        "returned_amount_cents": returned_amount_cents,
    }
    payload.update(overrides)
    return payload


def create_referral_payload(referrer_member_id: str, referee_email: str, **overrides) -> dict:
    """POST /referrals input. Required: referrer_member_id, referee_email.
    referee_qualifying_cents / bonus_cents optional."""
    payload = {
        "referrer_member_id": referrer_member_id,
        "referee_email": referee_email,
    }
    payload.update(overrides)
    return payload
