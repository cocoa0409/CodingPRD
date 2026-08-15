"""Entity assertions and domain invariant checkers.

Field names are PRD-exact (PRD sections 2.5, 2.7, 3.x). BillingEvent is the
append-only exception: no ``updated_at`` / ``version`` (PRD section 2.5).
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

_PLAN_TIERS = ["BASIC", "STANDARD", "PREMIUM"]
_ACCOUNT_STATUSES = ["ACTIVE", "SUSPENDED", "CLOSED"]
_PROFILE_STATUSES = ["ACTIVE", "DEACTIVATED"]
_SUBSCRIPTION_STATUSES = [
    "TRIALING", "ACTIVE", "PAST_DUE", "PAUSED", "CANCELLED", "EXPIRED",
]
_BILLING_STATES = ["CURRENT", "DUNNING", "RECOVERED"]
_BILLING_EVENT_TYPES = [
    "TRIAL_START", "CHARGE", "CHARGE_FAILED", "REFUND",
    "PRORATION_CREDIT", "PRICE_CHANGE_APPLIED", "RECOVERY",
]
_OFFER_TYPES = ["PAUSE_1M", "PAUSE_3M", "DOWNGRADE", "DISCOUNT_50_3M"]
_OFFER_STATUSES = ["PRESENTED", "ACCEPTED", "DECLINED", "EXPIRED", "SUPERSEDED"]
_NOTICE_STATUSES = ["ANNOUNCED", "EFFECTIVE", "CANCELLED"]
_CAMPAIGN_STATUSES = ["DRAFT", "ACTIVE", "CLOSED"]
_REPORT_STATUSES = ["EXPECTED", "RECEIVED", "RECONCILED", "DISCREPANCY", "WRITE_OFF"]
_CHANNELS = ["ORGANIC", "SEARCH", "SOCIAL", "AD", "EMAIL", "REFERRAL"]
_CANCEL_REASONS = [
    "USER_REQUESTED", "PAYMENT_FAILED", "PRICE_REFUSAL", "WINBACK_EXPIRED", "ADMIN",
]


def _assert_common(data: dict, id_field: str):
    assert is_valid_uuid(data.get(id_field, "")), f"{id_field} must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        "version must be a positive integer"


def assert_plan(data: dict):
    _assert_common(data, "plan_id")
    assert isinstance(data["plan_code"], str) and data["plan_code"]
    assert isinstance(data["display_name"], str) and data["display_name"]
    assert data["tier"] in _PLAN_TIERS
    assert isinstance(data["monthly_price_cents"], int)
    assert isinstance(data["trial_days"], int) and data["trial_days"] >= 0
    assert isinstance(data["max_profiles"], int) and data["max_profiles"] >= 1
    assert isinstance(data["max_households"], int) and data["max_households"] >= 1
    assert isinstance(data["is_archived"], bool)


def assert_account(data: dict):
    _assert_common(data, "account_id")
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["country_code"], str) and len(data["country_code"]) == 2
    assert data["account_status"] in _ACCOUNT_STATUSES
    assert isinstance(data["outstanding_balance_cents"], int)


def assert_profile(data: dict):
    _assert_common(data, "profile_id")
    assert is_valid_uuid(data.get("account_id", "")), "account_id must be a UUID"
    assert isinstance(data["display_name"], str) and data["display_name"]
    assert isinstance(data["is_kids"], bool)
    assert isinstance(data["household_id"], str) and data["household_id"]
    assert data["profile_status"] in _PROFILE_STATUSES


def assert_subscription(data: dict):
    _assert_common(data, "subscription_id")
    assert is_valid_uuid(data.get("account_id", "")), "account_id must be a UUID"
    assert is_valid_uuid(data.get("plan_id", "")), "plan_id must be a UUID"
    assert data["subscription_status"] in _SUBSCRIPTION_STATUSES
    assert data["billing_state"] in _BILLING_STATES
    if data.get("cancel_reason") is not None:
        assert data["cancel_reason"] in _CANCEL_REASONS
    assert isinstance(data["dunning_attempt_count"], int)
    assert data["dunning_attempt_count"] >= 0


def assert_save_offer(data: dict):
    _assert_common(data, "save_offer_id")
    assert is_valid_uuid(data.get("account_id", "")), "account_id must be a UUID"
    assert is_valid_uuid(data.get("subscription_id", "")), \
        "subscription_id must be a UUID"
    assert data["offer_type"] in _OFFER_TYPES
    assert data["offer_status"] in _OFFER_STATUSES
    assert isinstance(data["discount_pct"], int)
    assert isinstance(data["discount_duration_months"], int)
    assert is_iso8601_timestamp(data.get("presented_at_utc", ""))
    assert is_iso8601_timestamp(data.get("expires_at_utc", ""))


def assert_price_change_notice(data: dict):
    _assert_common(data, "price_change_notice_id")
    assert is_valid_uuid(data.get("plan_id", "")), "plan_id must be a UUID"
    assert isinstance(data["old_price_cents"], int)
    assert isinstance(data["new_price_cents"], int)
    assert is_iso8601_timestamp(data.get("announced_at_utc", ""))
    assert is_iso8601_timestamp(data.get("effective_at_utc", ""))
    assert data["notice_status"] in _NOTICE_STATUSES
    assert isinstance(data["grandfather_period_months"], int)


def assert_winback_campaign(data: dict):
    _assert_common(data, "winback_campaign_id")
    assert isinstance(data["campaign_code"], str) and data["campaign_code"]
    assert isinstance(data["discount_pct"], int)
    assert isinstance(data["duration_months"], int)
    assert isinstance(data["min_days_since_cancel"], int)
    assert isinstance(data["max_days_since_cancel"], int)
    assert isinstance(data["eligible_cancel_reasons"], list)
    for reason in data["eligible_cancel_reasons"]:
        assert reason in _CANCEL_REASONS
    assert data["campaign_status"] in _CAMPAIGN_STATUSES


def assert_partner_billing_record(data: dict):
    _assert_common(data, "partner_billing_record_id")
    assert isinstance(data["partner_code"], str) and data["partner_code"]
    assert is_valid_uuid(data.get("account_id", "")), "account_id must be a UUID"
    assert isinstance(data["partner_subscription_ref"], str)
    assert data["report_status"] in _REPORT_STATUSES
    assert isinstance(data["expected_amount_cents"], int)


def assert_signup_attribution(data: dict):
    _assert_common(data, "signup_attribution_id")
    assert is_valid_uuid(data.get("account_id", "")), "account_id must be a UUID"
    assert is_valid_uuid(data.get("subscription_id", "")), \
        "subscription_id must be a UUID"
    assert isinstance(data["content_id"], str)
    assert data["channel"] in _CHANNELS
    cohort = data["cohort_month"]
    assert isinstance(cohort, str) and len(cohort) == 7 and cohort[4] == "-", \
        f"cohort_month must be YYYY-MM, got {cohort!r}"
    assert isinstance(data["retained_at_day_30"], bool)
    assert isinstance(data["retained_at_day_90"], bool)


def assert_billing_event(data: dict):
    """Append-only ledger entry: id + created_at, and NO updated_at/version
    (PRD section 2.5 — 'both `updated_at` and `version` are absent')."""
    assert is_valid_uuid(data.get("billing_event_id", "")), \
        "billing_event_id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    assert "updated_at" not in data, "append-only ledger entry must omit updated_at"
    assert "version" not in data, "append-only ledger entry must omit version"
    assert is_valid_uuid(data.get("account_id", "")), "account_id must be a UUID"
    assert is_valid_uuid(data.get("subscription_id", "")), \
        "subscription_id must be a UUID"
    assert data["event_type"] in _BILLING_EVENT_TYPES
    assert isinstance(data["amount_cents"], int)
    assert is_iso8601_timestamp(data.get("occurred_at_utc", ""))


# ---------------------------------------------------------------------------
# Domain invariant checkers
# ---------------------------------------------------------------------------

def assert_round_half_up(expected: int, numerator: int, denominator: int):
    """Assert `expected` equals round_half_up(numerator / denominator) in
    whole cents (PRD section 2.6 — round-half-up, 0 decimal places)."""
    assert denominator > 0
    # round-half-up for non-negative values: floor(x + 0.5)
    computed = (2 * numerator + denominator) // (2 * denominator)
    assert computed == expected, (
        f"round_half_up({numerator}/{denominator}) == {computed}, expected {expected}"
    )
