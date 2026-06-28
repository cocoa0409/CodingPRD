"""Payload factories — one per create/write endpoint, input fields only."""

DEFAULTS = {
    "FAMILY_NAME": "Test Family",
    "CHILD_NAME": "Test Child",
    # A young child (born 2015) is under 13 at the typical test clock; teen tests override.
    "CHILD_BIRTHDATE": "2015-01-01",
    "TEEN_BIRTHDATE": "2010-01-01",
    "CHORE_TITLE": "Test Chore",
    "REWARD_CENTS": 500,
}


def create_family_payload(**overrides) -> dict:
    defaults = {"family_name": DEFAULTS["FAMILY_NAME"]}
    defaults.update(overrides)
    return defaults


def deposit_payload(amount_cents: int, **overrides) -> dict:
    defaults = {"amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults


def alert_thresholds_payload(large_spend_threshold_cents: int, low_balance_threshold_cents: int, **overrides) -> dict:
    defaults = {
        "large_spend_threshold_cents": large_spend_threshold_cents,
        "low_balance_threshold_cents": low_balance_threshold_cents,
    }
    defaults.update(overrides)
    return defaults


def create_child_payload(**overrides) -> dict:
    defaults = {
        "display_name": DEFAULTS["CHILD_NAME"],
        "birthdate": DEFAULTS["CHILD_BIRTHDATE"],
    }
    defaults.update(overrides)
    return defaults


def fund_jar_payload(jar_type: str, amount_cents: int, **overrides) -> dict:
    defaults = {"jar_type": jar_type, "amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults


def create_chore_payload(**overrides) -> dict:
    # payout_jar_type and is_recurring are optional (PRD defaults SPEND / false).
    defaults = {
        "title": DEFAULTS["CHORE_TITLE"],
        "reward_cents": DEFAULTS["REWARD_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_control_payload(control_kind: str, match_value: str, rule: str,
                           expected_debit_card_version: int, **overrides) -> dict:
    defaults = {
        "control_kind": control_kind,
        "match_value": match_value,
        "rule": rule,
        "expected_debit_card_version": expected_debit_card_version,
    }
    defaults.update(overrides)
    return defaults


def authorize_payload(merchant_id: str, category: str, amount_cents: int, **overrides) -> dict:
    # record_decline is optional.
    defaults = {
        "merchant_id": merchant_id,
        "category": category,
        "amount_cents": amount_cents,
    }
    defaults.update(overrides)
    return defaults


def settle_payload(settled_amount_cents: int, **overrides) -> dict:
    defaults = {"settled_amount_cents": settled_amount_cents}
    defaults.update(overrides)
    return defaults


def lock_payload(expected_debit_card_version: int, **overrides) -> dict:
    defaults = {"expected_debit_card_version": expected_debit_card_version}
    defaults.update(overrides)
    return defaults


def create_schedule_payload(amount_cents: int, cadence_days: int, next_run_at: str, **overrides) -> dict:
    # payout_jar_type is optional (PRD default SPEND).
    defaults = {
        "amount_cents": amount_cents,
        "cadence_days": cadence_days,
        "next_run_at": next_run_at,
    }
    defaults.update(overrides)
    return defaults


def configure_interest_payload(annual_rate_bps: int, monthly_cap_cents: int, accrual_method: str, **overrides) -> dict:
    defaults = {
        "annual_rate_bps": annual_rate_bps,
        "monthly_cap_cents": monthly_cap_cents,
        "accrual_method": accrual_method,
    }
    defaults.update(overrides)
    return defaults


def accrue_payload(period_days: int, **overrides) -> dict:
    # avg_balance_cents is optional (only used by DAILY_AVERAGE).
    defaults = {"period_days": period_days}
    defaults.update(overrides)
    return defaults


def order_payload(side: str, symbol: str, shares_milli: int, price_cents_per_share: int, **overrides) -> dict:
    defaults = {
        "side": side,
        "symbol": symbol,
        "shares_milli": shares_milli,
        "price_cents_per_share": price_cents_per_share,
    }
    defaults.update(overrides)
    return defaults


def set_clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}
