"""Payload factories — one per creatable resource, input fields only."""

# A default unbounded single-band overage tier; tests that exercise tiered
# pricing pass an explicit overage_tiers override.
DEFAULT_OVERAGE_TIERS = [{"up_to_units": None, "rate_cents_per_unit": 1}]

# The standard 3-band marginal tier ladder used across overage tests.
TIERED_OVERAGE_TIERS = [
    {"up_to_units": 4000, "rate_cents_per_unit": 2},
    {"up_to_units": 19000, "rate_cents_per_unit": 1},
    {"up_to_units": None, "rate_cents_per_unit": 3},
]


def create_plan_payload(
    tier="BASIC",
    monthly_fee_cents=3000,
    included_usage_units=1000,
    overage_tiers=None,
    trial_days=0,
    **overrides,
) -> dict:
    payload = {
        "tier": tier,
        "monthly_fee_cents": monthly_fee_cents,
        "included_usage_units": included_usage_units,
        "overage_tiers": overage_tiers if overage_tiers is not None else list(DEFAULT_OVERAGE_TIERS),
        "trial_days": trial_days,
    }
    payload.update(overrides)
    return payload


def create_price_schedule_payload(monthly_fee_cents, effective_from, effective_to, **overrides) -> dict:
    payload = {
        "monthly_fee_cents": monthly_fee_cents,
        "effective_from": effective_from,
        "effective_to": effective_to,
    }
    payload.update(overrides)
    return payload


def create_addon_payload(code="SEATS", monthly_fee_cents=2000, **overrides) -> dict:
    payload = {"code": code, "monthly_fee_cents": monthly_fee_cents}
    payload.update(overrides)
    return payload


def create_coupon_payload(
    code="PCT10",
    discount_type="PERCENT",
    duration="RECURRING",
    max_redemptions=5,
    percent_off=10,
    amount_off_cents=None,
    **overrides,
) -> dict:
    payload = {
        "code": code,
        "discount_type": discount_type,
        "duration": duration,
        "max_redemptions": max_redemptions,
    }
    if discount_type == "PERCENT":
        payload["percent_off"] = percent_off
    elif discount_type == "FIXED":
        payload["amount_off_cents"] = amount_off_cents if amount_off_cents is not None else 500
    payload.update(overrides)
    return payload


def create_tax_jurisdiction_payload(region_code="US-CA", tax_rate_bps=875, **overrides) -> dict:
    payload = {"region_code": region_code, "tax_rate_bps": tax_rate_bps}
    payload.update(overrides)
    return payload


def create_account_payload(
    email="acct@x.com",
    company_name="Acme",
    region_code="US-CA",
    payment_method_ok=True,
    **overrides,
) -> dict:
    payload = {
        "email": email,
        "company_name": company_name,
        "region_code": region_code,
        "payment_method_ok": payment_method_ok,
    }
    payload.update(overrides)
    return payload


def create_subscription_payload(plan_id, coupon_id=None, **overrides) -> dict:
    payload = {"plan_id": plan_id}
    if coupon_id is not None:
        payload["coupon_id"] = coupon_id
    payload.update(overrides)
    return payload


def change_plan_payload(plan_id, expected_subscription_version, **overrides) -> dict:
    payload = {
        "plan_id": plan_id,
        "expected_subscription_version": expected_subscription_version,
    }
    payload.update(overrides)
    return payload


def add_addon_payload(addon_id, **overrides) -> dict:
    payload = {"addon_id": addon_id}
    payload.update(overrides)
    return payload


def create_pause_window_payload(pause_from, pause_to, **overrides) -> dict:
    payload = {"pause_from": pause_from, "pause_to": pause_to}
    payload.update(overrides)
    return payload


def record_usage_payload(units, recorded_at, **overrides) -> dict:
    payload = {"units": units, "recorded_at": recorded_at}
    payload.update(overrides)
    return payload


def set_clock_payload(to_iso8601) -> dict:
    return {"to_iso8601": to_iso8601}


def set_card_state_payload(account_id, payment_method_ok) -> dict:
    return {"account_id": account_id, "payment_method_ok": payment_method_ok}
