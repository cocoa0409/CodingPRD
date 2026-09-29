"""Payload factories — one per write endpoint, input fields only.

Every factory supplies the required inputs and lets the caller override any of
them (or add an optional one) through ``**overrides``.  Passing ``None`` for a
key keeps the key in the payload with a null value, which is what schema-band
tests need; use ``drop_keys`` to omit a required field entirely.
"""

import itertools
from typing import Any, Dict, Iterable

_counter = itertools.count(1)


def unique_suffix() -> str:
    """Monotonic suffix so codes and emails stay unique inside one test."""
    return str(next(_counter))


def _build(defaults: Dict[str, Any], overrides: Dict[str, Any],
           drop_keys: Iterable[str] = ()) -> Dict[str, Any]:
    payload = dict(defaults)
    payload.update(overrides)
    for key in drop_keys:
        payload.pop(key, None)
    return payload


# ---------------------------------------------------------------------------
# Catalogue
# ---------------------------------------------------------------------------

def create_plan_payload(drop_keys: Iterable[str] = (), **overrides) -> Dict[str, Any]:
    """Required: code, name, monthly_price_cents, unit_cogs_cents, margin_floor_pct."""
    suffix = unique_suffix()
    defaults = {
        "code": f"PLAN_{suffix}",
        "name": f"Plan {suffix}",
        "monthly_price_cents": 4999,
        "unit_cogs_cents": 2100,
        "margin_floor_pct": 0.4200,
    }
    return _build(defaults, overrides, drop_keys)


def create_save_offer_template_payload(drop_keys: Iterable[str] = (),
                                       **overrides) -> Dict[str, Any]:
    """Required: code, name, offer_type, priority_rank."""
    suffix = unique_suffix()
    defaults = {
        "code": f"TPL_{suffix}",
        "name": f"Template {suffix}",
        "offer_type": "DISCOUNT",
        "priority_rank": 10,
    }
    return _build(defaults, overrides, drop_keys)


# ---------------------------------------------------------------------------
# Subscribers and payment instruments
# ---------------------------------------------------------------------------

def create_subscriber_payload(drop_keys: Iterable[str] = (), **overrides) -> Dict[str, Any]:
    """Required: email, acquisition_channel."""
    suffix = unique_suffix()
    defaults = {
        "email": f"subscriber{suffix}@example.com",
        "acquisition_channel": "SEARCH",
    }
    return _build(defaults, overrides, drop_keys)


def update_subscriber_payload(do_not_contact: bool = True, **overrides) -> Dict[str, Any]:
    """Required: do_not_contact."""
    return _build({"do_not_contact": do_not_contact}, overrides)


def create_payment_method_payload(subscriber_id: str, drop_keys: Iterable[str] = (),
                                  **overrides) -> Dict[str, Any]:
    """Required: subscriber_id, card_last4, exp_month, exp_year, network."""
    defaults = {
        "subscriber_id": subscriber_id,
        "card_last4": "4242",
        "exp_month": 12,
        "exp_year": 2030,
        "network": "VISA",
    }
    return _build(defaults, overrides, drop_keys)


def updater_result_payload(outcome: str = "UPDATED", **overrides) -> Dict[str, Any]:
    """Required: outcome. Optional: new_card_last4, new_exp_month, new_exp_year."""
    return _build({"outcome": outcome}, overrides)


# ---------------------------------------------------------------------------
# Subscriptions and modifications
# ---------------------------------------------------------------------------

def create_subscription_payload(subscriber_id: str, plan_id: str, payment_method_id: str,
                                drop_keys: Iterable[str] = (), **overrides) -> Dict[str, Any]:
    """Required: subscriber_id, plan_id, payment_method_id, frequency_weeks,
    disclosure_acknowledged. Optional: addons, winback_target_id."""
    defaults = {
        "subscriber_id": subscriber_id,
        "plan_id": plan_id,
        "payment_method_id": payment_method_id,
        "frequency_weeks": 4,
        "disclosure_acknowledged": True,
    }
    return _build(defaults, overrides, drop_keys)


def create_modification_payload(mod_type: str, expected_subscription_version: int,
                                drop_keys: Iterable[str] = (), **overrides) -> Dict[str, Any]:
    """Required: mod_type, expected_subscription_version."""
    defaults = {
        "mod_type": mod_type,
        "expected_subscription_version": expected_subscription_version,
    }
    return _build(defaults, overrides, drop_keys)


def reverse_modification_payload(**overrides) -> Dict[str, Any]:
    """All inputs optional: reason_note."""
    return dict(overrides)


# ---------------------------------------------------------------------------
# Compliance notices
# ---------------------------------------------------------------------------

def schedule_notice_payload(notice_type: str, scheduled_for: str,
                            drop_keys: Iterable[str] = (), **overrides) -> Dict[str, Any]:
    """Required: notice_type, scheduled_for. Optional: channel, body_ref."""
    defaults = {"notice_type": notice_type, "scheduled_for": scheduled_for}
    return _build(defaults, overrides, drop_keys)


# ---------------------------------------------------------------------------
# Collections
# ---------------------------------------------------------------------------

def simulate_payment_payload(invoice_id: str, outcome: str,
                             drop_keys: Iterable[str] = (), **overrides) -> Dict[str, Any]:
    """Required: invoice_id, outcome. Optional: decline_code."""
    defaults = {"invoice_id": invoice_id, "outcome": outcome}
    return _build(defaults, overrides, drop_keys)


# ---------------------------------------------------------------------------
# Cancellation conversation
# ---------------------------------------------------------------------------

def create_cancellation_session_payload(subscription_id: str,
                                        drop_keys: Iterable[str] = (),
                                        **overrides) -> Dict[str, Any]:
    """Required: subscription_id, entry_channel."""
    defaults = {"subscription_id": subscription_id, "entry_channel": "WEB_SELF_SERVE"}
    return _build(defaults, overrides, drop_keys)


def capture_reason_payload(reason_code: str, drop_keys: Iterable[str] = (),
                           **overrides) -> Dict[str, Any]:
    """Required: reason_code. Optional: reason_detail."""
    return _build({"reason_code": reason_code}, overrides, drop_keys)


def complete_cancellation_payload(confirm: bool = True, **overrides) -> Dict[str, Any]:
    """Required: confirm."""
    return _build({"confirm": confirm}, overrides)


def decline_grant_payload(**overrides) -> Dict[str, Any]:
    """All inputs optional: decline_note."""
    return dict(overrides)


def margin_exception_payload(decision: str, **overrides) -> Dict[str, Any]:
    """Required: decision. Optional: justification."""
    return _build({"decision": decision}, overrides)


# ---------------------------------------------------------------------------
# Win-back
# ---------------------------------------------------------------------------

def create_winback_campaign_payload(drop_keys: Iterable[str] = (), **overrides) -> Dict[str, Any]:
    """Required: code, name, min_days_since_lapse, max_days_since_lapse,
    offer_discount_pct."""
    suffix = unique_suffix()
    defaults = {
        "code": f"WB_{suffix}",
        "name": f"Campaign {suffix}",
        "min_days_since_lapse": 0,
        "max_days_since_lapse": 90,
        "offer_discount_pct": 0.2000,
    }
    return _build(defaults, overrides, drop_keys)


def create_winback_target_payload(subscriber_id: str, expected_campaign_version: int,
                                  drop_keys: Iterable[str] = (), **overrides) -> Dict[str, Any]:
    """Required: subscriber_id, expected_campaign_version."""
    defaults = {
        "subscriber_id": subscriber_id,
        "expected_campaign_version": expected_campaign_version,
    }
    return _build(defaults, overrides, drop_keys)


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------

def create_cohort_snapshot_payload(cohort_month: str, ltv_variant: str = "REALIZED",
                                   drop_keys: Iterable[str] = (), **overrides) -> Dict[str, Any]:
    """Required: cohort_month, ltv_variant. Optional: acquisition_channel,
    plan_code, tenure_bucket."""
    defaults = {"cohort_month": cohort_month, "ltv_variant": ltv_variant}
    return _build(defaults, overrides, drop_keys)
