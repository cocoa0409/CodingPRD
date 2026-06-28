"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "EMAIL_DOMAIN": "x.com",
    "FULL_NAME": "Test Investor",
    "MONTHLY_FEE_CENTS": 600,
    "MANAGEMENT_FEE_BPS": 0,
    "PORTFOLIO_NAME": "Moderate",
    "DRIFT_BAND_BPS": 500,
    "ACTIVE_FROM": "2026-01-01T00:00:00Z",
    "ACTIVE_UNTIL": "2027-01-01T00:00:00Z",
}


def create_subscription_plan_payload(**overrides) -> dict:
    payload = {
        "tier": "PERSONAL",
        "monthly_fee_cents": DEFAULTS["MONTHLY_FEE_CENTS"],
        "allows_custodial": True,
        "allows_ira": True,
        "management_fee_bps": DEFAULTS["MANAGEMENT_FEE_BPS"],
    }
    payload.update(overrides)
    return payload


def create_model_portfolio_payload(**overrides) -> dict:
    payload = {
        "risk_tier": 3,
        "name": DEFAULTS["PORTFOLIO_NAME"],
        "target_allocation": {"EQUITY": 60, "BOND": 40},
        "drift_band_bps": DEFAULTS["DRIFT_BAND_BPS"],
    }
    payload.update(overrides)
    return payload


def create_found_money_offer_payload(**overrides) -> dict:
    payload = {
        "brand_name": "TestBrand",
        "rebate_mode": "FLAT",
        "rebate_flat_cents": 1000,
        "max_rebate_cents": 1000,
        "min_spend_cents": 0,
        "hold_days": 0,
        "active_from": DEFAULTS["ACTIVE_FROM"],
        "active_until": DEFAULTS["ACTIVE_UNTIL"],
    }
    payload.update(overrides)
    return payload


def register_account_payload(plan_id: str, model_portfolio_id: str, **overrides) -> dict:
    payload = {
        "email": overrides.pop("email", "acct@x.com"),
        "full_name": DEFAULTS["FULL_NAME"],
        "plan_id": plan_id,
        "model_portfolio_id": model_portfolio_id,
    }
    payload.update(overrides)
    return payload


def create_linked_card_payload(account_id: str, **overrides) -> dict:
    payload = {
        "account_id": account_id,
        "last_four": "1111",
        "roundup_multiplier": 1,
    }
    payload.update(overrides)
    return payload


def create_roundup_accrual_payload(account_id: str, linked_card_id: str, **overrides) -> dict:
    payload = {
        "account_id": account_id,
        "linked_card_id": linked_card_id,
        "purchase_amount_cents": 150,
    }
    payload.update(overrides)
    return payload


def create_recurring_contribution_payload(account_id: str, **overrides) -> dict:
    payload = {
        "account_id": account_id,
        "amount_cents": 1000,
        "cadence": "MONTHLY",
        "run_day_index": 10,
    }
    payload.update(overrides)
    return payload


def create_bucket_payload(account_id: str, bucket_type: str = "TAXABLE", **overrides) -> dict:
    payload = {
        "account_id": account_id,
        "bucket_type": bucket_type,
    }
    payload.update(overrides)
    return payload


def create_order_payload(account_id: str, bucket_id: str, order_kind: str = "INVEST",
                         requested_amount_cents: int = 100, **overrides) -> dict:
    payload = {
        "account_id": account_id,
        "bucket_id": bucket_id,
        "order_kind": order_kind,
        "source": "MANUAL",
        "requested_amount_cents": requested_amount_cents,
    }
    payload.update(overrides)
    return payload


def create_found_money_reward_payload(account_id: str, offer_id: str,
                                      qualifying_spend_cents: int = 5000, **overrides) -> dict:
    payload = {
        "account_id": account_id,
        "offer_id": offer_id,
        "qualifying_spend_cents": qualifying_spend_cents,
    }
    payload.update(overrides)
    return payload


def create_referral_payload(referrer_account_id: str, code: str, bonus_cents: int = 1000,
                            **overrides) -> dict:
    payload = {
        "referrer_account_id": referrer_account_id,
        "code": code,
        "bonus_cents": bonus_cents,
    }
    payload.update(overrides)
    return payload
