"""Payload factories — one per entity, input fields only.

Each factory returns the minimal valid create/transition body and accepts
**overrides so individual tests can control the values that matter.
"""

DEFAULTS = {
    "HOLDER_EMAIL": "holder@example.com",
    "SYMBOL": "TESTCO",
    "LAST_PRICE_CENTS": 10000,
    "DEPOSIT_AMOUNT_CENTS": 100000,
    "FILL_PRICE_CENTS": 10000,
}

# Monotonic suffix so default emails / symbols stay unique within a test.
_counter = {"n": 0}


def _next() -> int:
    _counter["n"] += 1
    return _counter["n"]


def create_account_payload(**overrides) -> dict:
    defaults = {"holder_email": f"holder{_next()}@example.com"}
    defaults.update(overrides)
    return defaults


def create_security_payload(**overrides) -> dict:
    defaults = {
        "symbol": f"SEC{_next()}",
        "instrument_type": "EQUITY",
        "last_price_cents": DEFAULTS["LAST_PRICE_CENTS"],
        "fractional_enabled": True,
    }
    defaults.update(overrides)
    return defaults


def create_deposit_payload(**overrides) -> dict:
    defaults = {"amount_cents": DEFAULTS["DEPOSIT_AMOUNT_CENTS"], "instant_eligible": True}
    defaults.update(overrides)
    return defaults


def create_order_payload(account_id, security_id, expected_account_version, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "security_id": security_id,
        "side": "BUY",
        "order_type": "MARKET",
        "expected_account_version": expected_account_version,
    }
    defaults.update(overrides)
    return defaults


def create_fill_payload(fill_quantity, fill_price_cents=None, **overrides) -> dict:
    defaults = {
        "fill_quantity": fill_quantity,
        "fill_price_cents": fill_price_cents if fill_price_cents is not None else DEFAULTS["FILL_PRICE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_dividend_payload(account_id, position_id, rate_per_share_cents, ex_date, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "position_id": position_id,
        "rate_per_share_cents": rate_per_share_cents,
        "ex_date": ex_date,
    }
    defaults.update(overrides)
    return defaults


def create_options_approval_payload(account_id, requested_level, stated_experience_years,
                                    liquid_net_worth_cents, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "requested_level": requested_level,
        "stated_experience_years": stated_experience_years,
        "liquid_net_worth_cents": liquid_net_worth_cents,
    }
    defaults.update(overrides)
    return defaults


def decide_options_approval_payload(decision, expected_account_version, **overrides) -> dict:
    defaults = {"decision": decision, "expected_account_version": expected_account_version}
    defaults.update(overrides)
    return defaults


def compliance_hold_payload(compliance_hold: bool, **overrides) -> dict:
    defaults = {"compliance_hold": compliance_hold}
    defaults.update(overrides)
    return defaults


def drip_payload(drip_enabled: bool, **overrides) -> dict:
    defaults = {"drip_enabled": drip_enabled}
    defaults.update(overrides)
    return defaults


def quote_payload(last_price_cents: int, **overrides) -> dict:
    defaults = {"last_price_cents": last_price_cents}
    defaults.update(overrides)
    return defaults


def advance_clock_payload(to_iso8601: str, **overrides) -> dict:
    defaults = {"to_iso8601": to_iso8601}
    defaults.update(overrides)
    return defaults
