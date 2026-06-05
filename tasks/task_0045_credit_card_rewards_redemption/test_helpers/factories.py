"""Payload factories — one per entity, input fields only (PRD §3).

Each factory returns the minimal set of client-supplied (input) fields for the
corresponding create endpoint, with sensible defaults that tests override.
"""

DEFAULTS = {
    "PRODUCT_NAME": "Cash Visa",
    "BASE_EARN_RATE_BPS": 100,
    "SIGNUP_BONUS_POINTS": 0,
    "SIGNUP_BONUS_SPEND_THRESHOLD_CENTS": 100_000,
    "SIGNUP_BONUS_WINDOW_DAYS": 90,
    "POINTS_EXPIRY_MONTHS": 24,
    "CARDHOLDER_NAME": "Ada",
    "PARTNER_NAME": "SkyMiles",
    "CATEGORY_CODE": "OTHER",
}


# ─── Clock (PRD §3.10) ──────────────────────────────────────────
def set_clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}


# ─── CardProduct (PRD §3.1) ─────────────────────────────────────
def create_product_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["PRODUCT_NAME"],
        "base_earn_rate_bps": DEFAULTS["BASE_EARN_RATE_BPS"],
        "signup_bonus_points": DEFAULTS["SIGNUP_BONUS_POINTS"],
        "signup_bonus_spend_threshold_cents": DEFAULTS["SIGNUP_BONUS_SPEND_THRESHOLD_CENTS"],
        "signup_bonus_window_days": DEFAULTS["SIGNUP_BONUS_WINDOW_DAYS"],
        "tier_thresholds": [],
        "points_expiry_months": DEFAULTS["POINTS_EXPIRY_MONTHS"],
    }
    payload.update(overrides)
    return payload


# ─── CashbackCategory (PRD §3.1) ────────────────────────────────
def create_cashback_category_payload(card_product_id, code, earn_multiplier_bps, **overrides) -> dict:
    payload = {
        "card_product_id": card_product_id,
        "code": code,
        "earn_multiplier_bps": earn_multiplier_bps,
    }
    payload.update(overrides)
    return payload


# ─── QuarterlyCategory (PRD §3.1) ───────────────────────────────
def create_quarterly_category_payload(
    card_product_id,
    code="GROCERY",
    quarter_label="2026-Q3",
    window_start="2026-07-01T00:00:00Z",
    window_end="2026-10-01T00:00:00Z",
    earn_multiplier_bps=500,
    bonus_cap_cents=50_000,
    **overrides,
) -> dict:
    payload = {
        "card_product_id": card_product_id,
        "code": code,
        "quarter_label": quarter_label,
        "window_start": window_start,
        "window_end": window_end,
        "earn_multiplier_bps": earn_multiplier_bps,
        "bonus_cap_cents": bonus_cap_cents,
    }
    payload.update(overrides)
    return payload


# ─── TransferPartner (PRD §3.1) ─────────────────────────────────
def create_transfer_partner_payload(
    name=DEFAULTS["PARTNER_NAME"],
    partner_type="AIRLINE",
    transfer_ratio_num=1,
    transfer_ratio_den=1,
    min_transfer_points=1000,
    **overrides,
) -> dict:
    payload = {
        "name": name,
        "partner_type": partner_type,
        "transfer_ratio_num": transfer_ratio_num,
        "transfer_ratio_den": transfer_ratio_den,
        "min_transfer_points": min_transfer_points,
    }
    payload.update(overrides)
    return payload


# ─── CardAccount (PRD §3.2) ─────────────────────────────────────
def create_account_payload(card_product_id, cardholder_name=DEFAULTS["CARDHOLDER_NAME"], **overrides) -> dict:
    payload = {
        "card_product_id": card_product_id,
        "cardholder_name": cardholder_name,
    }
    payload.update(overrides)
    return payload


# ─── Transaction (PRD §3.3) ─────────────────────────────────────
def create_transaction_payload(
    card_account_id,
    amount_cents,
    category_code=DEFAULTS["CATEGORY_CODE"],
    transacted_at="2026-07-02T00:00:00Z",
    **overrides,
) -> dict:
    payload = {
        "card_account_id": card_account_id,
        "amount_cents": amount_cents,
        "category_code": category_code,
        "transacted_at": transacted_at,
    }
    payload.update(overrides)
    return payload


# ─── Redemption (PRD §3.8) ──────────────────────────────────────
def create_redemption_payload(
    card_account_id,
    redemption_type,
    points_requested,
    expected_card_account_version,
    transfer_partner_id=None,
    **overrides,
) -> dict:
    payload = {
        "card_account_id": card_account_id,
        "redemption_type": redemption_type,
        "points_requested": points_requested,
        "expected_card_account_version": expected_card_account_version,
    }
    if transfer_partner_id is not None:
        payload["transfer_partner_id"] = transfer_partner_id
    payload.update(overrides)
    return payload


# ─── CategoryActivation (PRD §3.9) ──────────────────────────────
def create_category_activation_payload(card_account_id, quarterly_category_id, **overrides) -> dict:
    payload = {
        "card_account_id": card_account_id,
        "quarterly_category_id": quarterly_category_id,
    }
    payload.update(overrides)
    return payload
