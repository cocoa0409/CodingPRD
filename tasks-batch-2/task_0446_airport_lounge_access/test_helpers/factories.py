"""Payload factories — one per entity, input fields only.

Field names are PRD-exact. Required vs optional follows the PRD: factories supply
all required input fields by default and let tests override via **overrides.
"""

DEFAULTS = {
    "PLAN_TIER": "PRESTIGE",
    "INCLUDED_VISITS": 10,
    "INCLUDED_GUEST_VISITS": 5,
    "OVERAGE_CHARGE_CENTS": 5000,
    "GUEST_CHARGE_CENTS": 2500,
    "MIN_CARD_STATUS": "BASIC",
    "ANNUAL_FEE_CENTS": 0,
    "LOUNGE_NAME": "Test Lounge",
    "AIRPORT_CODE": "SFO",
    "CAPACITY": 50,
    "SETTLEMENT_RATE_CENTS": 1200,
    "GUEST_FEE_CENTS": 1000,
    "DAY_PASS_PRICE_CENTS": 4000,
    "MEMBER_NAME": "Test Member",
    "CARD_STATUS": "BASIC",
    "FARE_CLASS": "ECONOMY",
    "CARD_VALID_UNTIL": "2027-01-01T00:00:00Z",
    "SUITE_LABEL": "Suite A",
}


def create_plan_payload(**overrides) -> dict:
    """POST /membership-plans. Required: tier, included_visits_per_year,
    included_guest_visits_per_year, overage_charge_cents, guest_charge_cents,
    min_card_status, annual_fee_cents."""
    payload = {
        "tier": DEFAULTS["PLAN_TIER"],
        "included_visits_per_year": DEFAULTS["INCLUDED_VISITS"],
        "included_guest_visits_per_year": DEFAULTS["INCLUDED_GUEST_VISITS"],
        "overage_charge_cents": DEFAULTS["OVERAGE_CHARGE_CENTS"],
        "guest_charge_cents": DEFAULTS["GUEST_CHARGE_CENTS"],
        "min_card_status": DEFAULTS["MIN_CARD_STATUS"],
        "annual_fee_cents": DEFAULTS["ANNUAL_FEE_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_lounge_payload(**overrides) -> dict:
    """POST /lounges. Required: name, airport_code, capacity, settlement_rate_cents,
    guest_fee_cents, day_pass_price_cents."""
    payload = {
        "name": DEFAULTS["LOUNGE_NAME"],
        "airport_code": DEFAULTS["AIRPORT_CODE"],
        "capacity": DEFAULTS["CAPACITY"],
        "settlement_rate_cents": DEFAULTS["SETTLEMENT_RATE_CENTS"],
        "guest_fee_cents": DEFAULTS["GUEST_FEE_CENTS"],
        "day_pass_price_cents": DEFAULTS["DAY_PASS_PRICE_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_member_payload(plan_id: str, **overrides) -> dict:
    """POST /memberships. Required: plan_id, full_name."""
    payload = {
        "plan_id": plan_id,
        "full_name": DEFAULTS["MEMBER_NAME"],
    }
    payload.update(overrides)
    return payload


def create_card_payload(member_id: str, **overrides) -> dict:
    """POST /eligibility-cards. Required: member_id, card_status, fare_class,
    valid_until."""
    payload = {
        "member_id": member_id,
        "card_status": DEFAULTS["CARD_STATUS"],
        "fare_class": DEFAULTS["FARE_CLASS"],
        "valid_until": DEFAULTS["CARD_VALID_UNTIL"],
    }
    payload.update(overrides)
    return payload


def create_visit_payload(lounge_id: str, expected_lounge_version: int, **overrides) -> dict:
    """POST /visits. Required: lounge_id, expected_lounge_version. Optional:
    member_id, day_pass_id, guest_count (default 0), guest_names."""
    payload = {
        "lounge_id": lounge_id,
        "expected_lounge_version": expected_lounge_version,
    }
    payload.update(overrides)
    return payload


def create_day_pass_payload(expected_lounge_version: int, **overrides) -> dict:
    """POST /lounges/{lounge_id}/day-passes. Required: expected_lounge_version.
    Optional: member_id, buyer_name."""
    payload = {
        "expected_lounge_version": expected_lounge_version,
    }
    payload.update(overrides)
    return payload


def close_lounge_payload(expected_lounge_version: int, **overrides) -> dict:
    """POST /lounges/{lounge_id}/close. Required: expected_lounge_version."""
    payload = {
        "expected_lounge_version": expected_lounge_version,
    }
    payload.update(overrides)
    return payload


def create_shower_suite_payload(lounge_id: str, **overrides) -> dict:
    """POST /shower-suites. Required: lounge_id, label. Optional: turnover_minutes
    (default 0)."""
    payload = {
        "lounge_id": lounge_id,
        "label": DEFAULTS["SUITE_LABEL"],
    }
    payload.update(overrides)
    return payload


def create_shower_reservation_payload(
    shower_suite_id: str, visit_id: str, start_at: str, end_at: str, **overrides
) -> dict:
    """POST /shower-reservations. Required: shower_suite_id, visit_id, start_at,
    end_at."""
    payload = {
        "shower_suite_id": shower_suite_id,
        "visit_id": visit_id,
        "start_at": start_at,
        "end_at": end_at,
    }
    payload.update(overrides)
    return payload
