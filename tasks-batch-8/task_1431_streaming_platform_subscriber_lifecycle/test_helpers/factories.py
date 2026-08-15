"""Payload factories — one per entity, input fields only (PRD section 4)."""
import itertools

from .constants import TEST_DEFAULTS

_counter = itertools.count(1)


def _n() -> int:
    return next(_counter)


# --- Plans ---

def create_plan_payload(**overrides) -> dict:
    i = _n()
    defaults = {
        "plan_code": f"{TEST_DEFAULTS['PLAN_CODE']}{i}",
        "display_name": f"{TEST_DEFAULTS['PLAN_DISPLAY_NAME']} {i}",
        "tier": TEST_DEFAULTS["PLAN_TIER"],
        "monthly_price_cents": TEST_DEFAULTS["PLAN_MONTHLY_PRICE_CENTS"],
        "trial_days": TEST_DEFAULTS["PLAN_TRIAL_DAYS"],
        "max_profiles": TEST_DEFAULTS["PLAN_MAX_PROFILES"],
        "max_households": TEST_DEFAULTS["PLAN_MAX_HOUSEHOLDS"],
    }
    defaults.update(overrides)
    return defaults


# --- Accounts ---

def create_account_payload(**overrides) -> dict:
    i = _n()
    defaults = {
        "email": f"user{i}@example.com",
        "full_name": f"Test User {i}",
        "country_code": TEST_DEFAULTS["ACCOUNT_COUNTRY_CODE"],
    }
    defaults.update(overrides)
    return defaults


# --- Profiles ---

def create_profile_payload(account_id, **overrides) -> dict:
    i = _n()
    defaults = {
        "account_id": account_id,
        "display_name": f"Profile {i}",
        "is_kids": False,
        "household_id": TEST_DEFAULTS["PROFILE_HOUSEHOLD_ID"],
    }
    defaults.update(overrides)
    return defaults


# --- Subscriptions ---

def create_subscription_payload(account_id, plan_id, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "plan_id": plan_id,
    }
    defaults.update(overrides)
    return defaults


def cancel_subscription_payload(**overrides) -> dict:
    defaults = {"cancel_reason": "USER_REQUESTED"}
    defaults.update(overrides)
    return defaults


def pause_subscription_payload(**overrides) -> dict:
    defaults = {"duration_months": 1}
    defaults.update(overrides)
    return defaults


def change_plan_payload(target_plan_id, expected_subscription_version, **overrides) -> dict:
    defaults = {
        "target_plan_id": target_plan_id,
        "expected_subscription_version": expected_subscription_version,
    }
    defaults.update(overrides)
    return defaults


# --- Save offers ---

def create_save_offer_payload(subscription_id, **overrides) -> dict:
    defaults = {
        "subscription_id": subscription_id,
        "offer_type": "PAUSE_1M",
    }
    defaults.update(overrides)
    return defaults


# --- Billing events ---

def create_billing_event_payload(account_id, subscription_id, **overrides) -> dict:
    i = _n()
    defaults = {
        "account_id": account_id,
        "subscription_id": subscription_id,
        "event_type": "CHARGE_FAILED",
        "amount_cents": TEST_DEFAULTS["PLAN_MONTHLY_PRICE_CENTS"],
        "external_reference": f"ref-{i}",
        "notes": f"manual event {i}",
    }
    defaults.update(overrides)
    return defaults


# --- Price change notices ---

def create_price_change_notice_payload(plan_id, **overrides) -> dict:
    defaults = {
        "plan_id": plan_id,
        "old_price_cents": 3000,
        "new_price_cents": 4000,
        "effective_at_utc": "2026-09-15T00:00:00Z",
        "grandfather_period_months": 0,
    }
    defaults.update(overrides)
    return defaults


# --- Win-back campaigns ---

def create_winback_campaign_payload(**overrides) -> dict:
    i = _n()
    defaults = {
        "campaign_code": f"WB{i}",
        "discount_pct": 50,
        "duration_months": 3,
        "min_days_since_cancel": 30,
        "max_days_since_cancel": 365,
        "eligible_cancel_reasons": ["USER_REQUESTED"],
    }
    defaults.update(overrides)
    return defaults


def winback_enroll_payload(winback_campaign_id, expected_subscription_version,
                           **overrides) -> dict:
    defaults = {
        "winback_campaign_id": winback_campaign_id,
        "expected_subscription_version": expected_subscription_version,
    }
    defaults.update(overrides)
    return defaults


# --- Partner billing records ---

def create_partner_billing_record_payload(account_id, **overrides) -> dict:
    i = _n()
    defaults = {
        "partner_code": "APPLE",
        "account_id": account_id,
        "partner_subscription_ref": f"pref-{i}",
        "expected_amount_cents": 10000,
        "period_start_utc": "2026-08-01T00:00:00Z",
        "period_end_utc": "2026-08-31T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults
