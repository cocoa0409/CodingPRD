"""Payload factories — one per resource, input fields only."""

from .constants import TEST_DEFAULTS


def create_organization_payload(**overrides) -> dict:
    defaults = {
        "name": "Riverside Health Foundation",
        "ein": "12-3456789",
        "contact_email": "ops@riverside.org",
    }
    defaults.update(overrides)
    return defaults


def create_campaign_payload(organization_id: str, **overrides) -> dict:
    defaults = {
        "organization_id": organization_id,
        "title": "Autumn Walk 2026",
        "goal_amount_cents": TEST_DEFAULTS["CAMPAIGN_GOAL_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_event_payload(campaign_id: str, **overrides) -> dict:
    defaults = {
        "campaign_id": campaign_id,
        "name": "Autumn 10K Walk",
        "starts_at": TEST_DEFAULTS["EVENT_STARTS_AT"],
        "ends_at": TEST_DEFAULTS["EVENT_ENDS_AT"],
        "early_bird_ends_at": TEST_DEFAULTS["EARLY_BIRD_ENDS_AT"],
        "registration_fee_cents": TEST_DEFAULTS["EVENT_FEE_CENTS"],
        "capacity": TEST_DEFAULTS["EVENT_CAPACITY"],
    }
    defaults.update(overrides)
    return defaults


def create_team_payload(campaign_id: str, **overrides) -> dict:
    defaults = {
        "campaign_id": campaign_id,
        "name": "Team Alpha",
        "goal_amount_cents": TEST_DEFAULTS["TEAM_GOAL_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_participant_payload(campaign_id: str, **overrides) -> dict:
    defaults = {
        "campaign_id": campaign_id,
        "display_name": "Alice Reyes",
    }
    defaults.update(overrides)
    return defaults


def create_registration_payload(participant_id: str, event_id: str, **overrides) -> dict:
    defaults = {
        "participant_id": participant_id,
        "event_id": event_id,
    }
    defaults.update(overrides)
    return defaults


def create_donor_payload(**overrides) -> dict:
    defaults = {
        "display_name": "Dana Cole",
        "email": "dana@example.com",
    }
    defaults.update(overrides)
    return defaults


def create_donation_payload(
    campaign_id: str,
    donor_id: str,
    designation_type: str,
    designation_id: str,
    amount_cents: int,
    **overrides,
) -> dict:
    defaults = {
        "campaign_id": campaign_id,
        "donor_id": donor_id,
        "designation_type": designation_type,
        "designation_id": designation_id,
        "amount_cents": amount_cents,
    }
    defaults.update(overrides)
    return defaults


def create_match_pool_payload(campaign_id: str, **overrides) -> dict:
    defaults = {
        "campaign_id": campaign_id,
        "sponsor_name": "Northline Bank",
        "pool_amount_cents": 50000,
        "match_ratio": 0.5,
        "per_donation_cap_cents": 5000,
        "min_donation_cents": 0,
        "starts_at": TEST_DEFAULTS["POOL_STARTS_AT"],
        "ends_at": TEST_DEFAULTS["POOL_ENDS_AT"],
    }
    defaults.update(overrides)
    return defaults


def create_incentive_tier_payload(campaign_id: str, **overrides) -> dict:
    defaults = {
        "campaign_id": campaign_id,
        "name": "Bronze Shirt",
        "threshold_cents": 5000,
        "reward_description": "Event shirt",
    }
    defaults.update(overrides)
    return defaults


def create_payout_payload(amount_cents: int, expected_campaign_version: int, **overrides) -> dict:
    defaults = {
        "amount_cents": amount_cents,
        "expected_campaign_version": expected_campaign_version,
    }
    defaults.update(overrides)
    return defaults
