"""Payload factories — one per entity, input fields only (PRD §3.1-§3.8).

Only `source: input` fields appear here; computed and system fields (risk_score, fee_cents,
amount_cents, status, version, ...) are never sent by the client.
"""
import itertools

# Monotonic EIN generator so every merchant created in a test gets a unique 9-digit EIN
# (PRD §3.1: ein must be exactly nine digits and unique across all merchants).
_ein_counter = itertools.count(300000001)


def next_ein() -> str:
    return str(next(_ein_counter))


def create_merchant_payload(**overrides) -> dict:
    defaults = {
        "legal_name": "Test Merchant LLC",
        "ein": next_ein(),
        "state_code": "CA",
        "monthly_revenue_cents": 2_000_000,
    }
    defaults.update(overrides)
    return defaults


def create_bank_feed_payload(**overrides) -> dict:
    defaults = {
        "plaid_item_id": "plaid_test",
        "pulled_at": "2026-04-28T00:00:00Z",
        "avg_daily_balance_cents": 2_000_000,
        "nsf_count_90d": 0,
        "deposit_volume_cents": 9_000_000,
    }
    defaults.update(overrides)
    return defaults


def create_application_payload(merchant_id: str, bank_feed_id: str, **overrides) -> dict:
    defaults = {
        "merchant_id": merchant_id,
        "bank_feed_id": bank_feed_id,
        "requested_limit_cents": 1_000_000,
    }
    defaults.update(overrides)
    return defaults


def submit_application_payload(**overrides) -> dict:
    """The optional resubmission feed override (PRD §3.2)."""
    defaults: dict = {}
    defaults.update(overrides)
    return defaults


def decline_application_payload(decline_reason: str = "LOW_SCORE", **overrides) -> dict:
    defaults = {"decline_reason": decline_reason}
    defaults.update(overrides)
    return defaults


def create_credit_line_payload(application_id: str, **overrides) -> dict:
    defaults = {
        "application_id": application_id,
        "remittance_cadence": "DAILY",
    }
    defaults.update(overrides)
    return defaults


def create_draw_payload(principal_cents: int = 100_000, **overrides) -> dict:
    defaults = {"principal_cents": principal_cents}
    defaults.update(overrides)
    return defaults


def create_remittance_payload(scheduled_for: str, **overrides) -> dict:
    defaults = {"scheduled_for": scheduled_for}
    defaults.update(overrides)
    return defaults


def settle_remittance_payload(outcome: str = "SUCCESS", **overrides) -> dict:
    defaults = {"outcome": outcome}
    defaults.update(overrides)
    return defaults


def declare_default_payload(expected_credit_line_version: int, **overrides) -> dict:
    defaults = {"expected_credit_line_version": expected_credit_line_version}
    defaults.update(overrides)
    return defaults


def charge_off_payload(expected_credit_line_version: int, **overrides) -> dict:
    defaults = {"expected_credit_line_version": expected_credit_line_version}
    defaults.update(overrides)
    return defaults


def create_line_increase_request_payload(
    latest_bank_feed_id: str, requested_limit_cents: int = 1_500_000, **overrides
) -> dict:
    defaults = {
        "latest_bank_feed_id": latest_bank_feed_id,
        "requested_limit_cents": requested_limit_cents,
    }
    defaults.update(overrides)
    return defaults


def approve_line_increase_payload(expected_credit_line_version: int, **overrides) -> dict:
    defaults = {"expected_credit_line_version": expected_credit_line_version}
    defaults.update(overrides)
    return defaults


def deny_line_increase_payload(denial_reason: str = "SCORE_REGRESSION", **overrides) -> dict:
    defaults = {"denial_reason": denial_reason}
    defaults.update(overrides)
    return defaults


def create_renewal_offer_payload(
    new_fee_factor_bps: int = 1200, term_days: int = 180, **overrides
) -> dict:
    defaults = {"new_fee_factor_bps": new_fee_factor_bps, "term_days": term_days}
    defaults.update(overrides)
    return defaults


def create_statement_payload(period_start: str, period_end: str, **overrides) -> dict:
    defaults = {"period_start": period_start, "period_end": period_end}
    defaults.update(overrides)
    return defaults
