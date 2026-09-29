"""Payload factories — one per write endpoint, input fields only."""

from typing import Any, Dict, List, Optional

DEFAULTS = {
    "PLAN_NAME": "Digital Basic",
    "GROUP_NAME": "Univ Library",
    "ADMIN_EMAIL": "admin@campus.test",
    "EMAIL_DOMAIN": "campus.test",
    "READER_EMAIL": "reader@example.test",
    "HEADLINE": "Council approves budget",
    "SECTION": "politics",
    "RULE_NAME": "Default meter rule",
}


# --------------------------------------------------------------------------
# Offer plans and the price ladder
# --------------------------------------------------------------------------


def create_offer_plan_payload(**overrides) -> Dict[str, Any]:
    """A DIGITAL_ONLY ladder: cycle 1 at the intro price, cycle 2 onward standard."""
    payload: Dict[str, Any] = {
        "name": DEFAULTS["PLAN_NAME"],
        "bundle_type": "DIGITAL_ONLY",
        "intro_price_cents": 499,
        "intro_cycles": 1,
        "standard_from_cycle": 2,
        "standard_price_cents": 1499,
        "cycle_days": 30,
    }
    payload.update(overrides)
    return payload


def create_print_digital_plan_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "name": "Print Plus",
        "bundle_type": "PRINT_DIGITAL",
        "intro_price_cents": 999,
        "intro_cycles": 1,
        "standard_from_cycle": 2,
        "standard_price_cents": 1899,
        "cycle_days": 30,
        "print_component_cents": 900,
        "print_delivery_days": ["SUN"],
        "print_deliveries_per_cycle": 4,
    }
    payload.update(overrides)
    return payload


def create_institutional_plan_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "name": "Campus Seats",
        "bundle_type": "INSTITUTIONAL_SEAT",
        "intro_price_cents": 5000,
        "intro_cycles": 1,
        "standard_from_cycle": 2,
        "standard_price_cents": 5000,
        "cycle_days": 30,
        "per_seat_price_cents": 400,
    }
    payload.update(overrides)
    return payload


def schedule_price_change_payload(
    expected_offer_plan_version: int,
    pending_price_cents: int = 1799,
    pending_effective_on: str = "2026-10-15",
    grandfather_policy: str = "NONE",
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "pending_price_cents": pending_price_cents,
        "pending_effective_on": pending_effective_on,
        "grandfather_policy": grandfather_policy,
        "expected_offer_plan_version": expected_offer_plan_version,
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Paywall rules, articles and access decisions
# --------------------------------------------------------------------------


def create_paywall_rule_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "name": DEFAULTS["RULE_NAME"],
        "action": "METER",
        "priority": 10,
    }
    payload.update(overrides)
    return payload


def create_article_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "headline": DEFAULTS["HEADLINE"],
        "content_type": "NEWS",
        "section": DEFAULTS["SECTION"],
    }
    payload.update(overrides)
    return payload


def access_decision_payload(reader_id: str, article_id: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"reader_id": reader_id, "article_id": article_id}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Readers, cards and events
# --------------------------------------------------------------------------


def create_reader_payload(**overrides) -> Dict[str, Any]:
    """An anonymous device row — every field on the reader is optional."""
    payload: Dict[str, Any] = {}
    payload.update(overrides)
    return payload


def create_registered_reader_payload(
    email: str = DEFAULTS["READER_EMAIL"], **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"email": email, "is_registered": True}
    payload.update(overrides)
    return payload


def replace_card_payload(
    card_last4: str = "9876",
    card_exp_month: int = 5,
    card_exp_year: int = 2028,
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "card_last4": card_last4,
        "card_exp_month": card_exp_month,
        "card_exp_year": card_exp_year,
    }
    payload.update(overrides)
    return payload


def create_reader_event_payload(event_type: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"event_type": event_type}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Subscriptions, invoices and payment attempts
# --------------------------------------------------------------------------


def create_subscription_payload(
    reader_id: str,
    offer_plan_id: str,
    expected_offer_plan_version: int,
    group_account_id: Optional[str] = None,
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "reader_id": reader_id,
        "offer_plan_id": offer_plan_id,
        "expected_offer_plan_version": expected_offer_plan_version,
    }
    if group_account_id is not None:
        payload["group_account_id"] = group_account_id
    payload.update(overrides)
    return payload


def create_payment_attempt_payload(
    outcome: str, amount_cents: int, decline_code: Optional[str] = None, **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"outcome": outcome, "amount_cents": amount_cents}
    if decline_code is not None:
        payload["decline_code"] = decline_code
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Holds
# --------------------------------------------------------------------------


def create_hold_payload(
    hold_type: str, start_date: str, end_date: str, **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "hold_type": hold_type,
        "start_date": start_date,
        "end_date": end_date,
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Cancellation flow and save offers
# --------------------------------------------------------------------------


def create_cancellation_request_payload(
    reason_code: str = "PRICE", **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"reason_code": reason_code}
    payload.update(overrides)
    return payload


def create_save_offer_payload(
    offer_type: str = "RETENTION_DISCOUNT", **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"offer_type": offer_type}
    if offer_type == "RETENTION_DISCOUNT":
        payload["discount_pct"] = 0.25
        payload["duration_cycles"] = 3
    elif offer_type == "DOWNGRADE":
        payload["duration_cycles"] = 3
    elif offer_type == "PAUSE":
        payload["pause_days"] = 30
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Institutional access
# --------------------------------------------------------------------------


def create_group_account_payload(
    offer_plan_id: str, seat_capacity: int = 3, **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "name": DEFAULTS["GROUP_NAME"],
        "admin_email": DEFAULTS["ADMIN_EMAIL"],
        "allowed_email_domain": DEFAULTS["EMAIL_DOMAIN"],
        "seat_capacity": seat_capacity,
        "offer_plan_id": offer_plan_id,
    }
    payload.update(overrides)
    return payload


def create_seat_payload(
    reader_id: str,
    starts_on: str,
    expected_group_account_version: int,
    ends_on: Optional[str] = None,
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "reader_id": reader_id,
        "starts_on": starts_on,
        "expected_group_account_version": expected_group_account_version,
    }
    if ends_on is not None:
        payload["ends_on"] = ends_on
    payload.update(overrides)
    return payload


def step_up_schedule(*entries: tuple) -> List[Dict[str, int]]:
    """Build a step-up array from (from_cycle, price_cents) pairs."""
    return [{"from_cycle": fc, "price_cents": pc} for fc, pc in entries]
