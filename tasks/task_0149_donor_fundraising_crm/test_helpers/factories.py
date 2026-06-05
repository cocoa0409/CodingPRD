"""Payload factories — one per entity, input fields only.

Each factory produces a minimal valid request body and accepts **overrides for
the fields a test needs to control. Computed/server-managed fields are never
included.
"""
import itertools

from .constants import DEFAULT_STARTS_ON, DEFAULT_ENDS_ON

# Monotonic counter so factory-minted emails / codes / names are unique within
# a single test process (the server DB is reset per test, but uniqueness within
# one test still matters).
_seq = itertools.count(1)


def _next() -> int:
    return next(_seq)


def create_household_payload(**overrides) -> dict:
    """Household: name (required) + optional soft_credit_policy, primary_donor_id."""
    payload = {"name": f"Household {_next()}"}
    payload.update(overrides)
    return payload


def create_donor_payload(**overrides) -> dict:
    """Donor: full_name + email (required); optional household_id, employer_id,
    lapse_threshold_days."""
    n = _next()
    payload = {"full_name": f"Donor {n}", "email": f"donor{n}@example.com"}
    payload.update(overrides)
    return payload


def create_employer_payload(**overrides) -> dict:
    """Employer: name (required); ratio/floor/caps optional with PRD defaults."""
    payload = {
        "name": f"Employer {_next()}",
        "match_ratio": 1.0,
        "min_gift_cents": 2500,
        "max_match_cents": 1000000,
        "annual_match_cap_cents": 5000000,
    }
    payload.update(overrides)
    return payload


def create_campaign_payload(**overrides) -> dict:
    """Campaign: name, goal_cents, starts_on, ends_on (all required)."""
    payload = {
        "name": f"Campaign {_next()}",
        "goal_cents": 1000000,
        "starts_on": DEFAULT_STARTS_ON,
        "ends_on": DEFAULT_ENDS_ON,
    }
    payload.update(overrides)
    return payload


def create_appeal_payload(campaign_id, **overrides) -> dict:
    """Appeal: campaign_id, channel, code (required); expected_response_rate optional."""
    payload = {
        "campaign_id": campaign_id,
        "channel": "EMAIL",
        "code": f"AP{_next()}",
    }
    payload.update(overrides)
    return payload


def create_pledge_payload(donor_id, campaign_id, **overrides) -> dict:
    """Pledge: donor_id, campaign_id, total_amount_cents, installment_count,
    frequency (required); schedule_basis optional."""
    payload = {
        "donor_id": donor_id,
        "campaign_id": campaign_id,
        "total_amount_cents": 10000,
        "installment_count": 2,
        "frequency": "MONTHLY",
        "schedule_basis": "FRONT_LOADED",
    }
    payload.update(overrides)
    return payload


def create_gift_payload(donor_id, campaign_id, **overrides) -> dict:
    """Gift: donor_id, campaign_id, amount_cents (required); appeal_id, pledge_id,
    payment_method, benefit_value_cents optional."""
    payload = {
        "donor_id": donor_id,
        "campaign_id": campaign_id,
        "amount_cents": 5000,
    }
    payload.update(overrides)
    return payload


def create_match_claim_payload(gift_id, **overrides) -> dict:
    """MatchClaim: gift_id (the only input field)."""
    payload = {"gift_id": gift_id}
    payload.update(overrides)
    return payload


def create_planned_gift_payload(donor_id, **overrides) -> dict:
    """PlannedGift: donor_id, vehicle, expected_amount_cents (required)."""
    payload = {
        "donor_id": donor_id,
        "vehicle": "BEQUEST",
        "expected_amount_cents": 500000,
    }
    payload.update(overrides)
    return payload


def create_segment_payload(**overrides) -> dict:
    """Segment: name (required); min_lifetime_cents, giving_status_in,
    lifecycle_status_in optional."""
    payload = {"name": f"Segment {_next()}"}
    payload.update(overrides)
    return payload
