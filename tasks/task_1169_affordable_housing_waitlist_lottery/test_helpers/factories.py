"""Payload factories — one per creatable resource, input fields only (PRD §3)."""
from .constants import (
    DEFAULT_AMI_LIMIT_CENTS, DEFAULT_CERT_INCOME_SOURCE,
    DEFAULT_HOUSEHOLD_SIZE, DEFAULT_MARKETING_CHANNELS,
    DEFAULT_NOTICE_RESPONSE_DAYS, DEFAULT_SELF_REPORTED_INCOME_CENTS,
    DEFAULT_TARGET_AMI_TIER, WINDOW_CLOSE, WINDOW_OPEN,
)


def create_property_payload(**overrides) -> dict:
    defaults = {
        "name": "Maple Court",
        "address_line": "1 Main St",
        "city": "Springfield",
        "state_code": "IL",
    }
    defaults.update(overrides)
    return defaults


def create_unit_payload(property_id, **overrides) -> dict:
    defaults = {
        "property_id": property_id,
        "unit_number": "101",
        "bedroom_count": "ONE_BR",
        "ami_tier": "AMI_50",
    }
    defaults.update(overrides)
    return defaults


def create_occupancy_standard_payload(property_id, **overrides) -> dict:
    defaults = {
        "property_id": property_id,
        "bedroom_count": "ONE_BR",
        "min_occupants": 1,
        "max_occupants": 3,
    }
    defaults.update(overrides)
    return defaults


def create_ami_limit_payload(property_id, **overrides) -> dict:
    defaults = {
        "property_id": property_id,
        "household_size": DEFAULT_HOUSEHOLD_SIZE,
        "ami_tier": DEFAULT_TARGET_AMI_TIER,
        "annual_limit_cents": DEFAULT_AMI_LIMIT_CENTS,
    }
    defaults.update(overrides)
    return defaults


def create_campaign_payload(property_id, **overrides) -> dict:
    defaults = {
        "property_id": property_id,
        "name": "June 2026",
        "application_open_at": WINDOW_OPEN,
        "application_close_at": WINDOW_CLOSE,
        "marketing_channels": list(DEFAULT_MARKETING_CHANNELS),
        "marketing_plan_summary": "press and web outreach",
        "target_ami_tier": DEFAULT_TARGET_AMI_TIER,
    }
    defaults.update(overrides)
    return defaults


def create_applicant_payload(**overrides) -> dict:
    defaults = {"full_name": "Test Applicant", "email": "applicant@example.com"}
    defaults.update(overrides)
    return defaults


def create_application_payload(applicant_id, campaign_id, **overrides) -> dict:
    defaults = {
        "applicant_id": applicant_id,
        "campaign_id": campaign_id,
        "household_size": DEFAULT_HOUSEHOLD_SIZE,
        "self_reported_annual_income_cents":
            DEFAULT_SELF_REPORTED_INCOME_CENTS,
    }
    defaults.update(overrides)
    return defaults


def create_preference_claim_payload(application_id, **overrides) -> dict:
    defaults = {
        "application_id": application_id,
        "category": "LOCAL_RESIDENT",
        "evidence_ref": "lease-2025",
    }
    defaults.update(overrides)
    return defaults


def create_lottery_run_payload(campaign_id, expected_campaign_version,
                               **overrides) -> dict:
    defaults = {
        "campaign_id": campaign_id,
        "seed": "SEED-1",
        "expected_campaign_version": expected_campaign_version,
    }
    defaults.update(overrides)
    return defaults


def create_purge_run_payload(campaign_id, expected_campaign_version,
                             **overrides) -> dict:
    defaults = {
        "campaign_id": campaign_id,
        "notice_response_days": DEFAULT_NOTICE_RESPONSE_DAYS,
        "expected_campaign_version": expected_campaign_version,
    }
    defaults.update(overrides)
    return defaults


def create_compliance_report_payload(campaign_id, **overrides) -> dict:
    defaults = {
        "campaign_id": campaign_id,
        "period_start": "2026-04-01T00:00:00Z",
        "period_end": "2026-06-30T00:00:00Z",
        "period_mode": "CALENDAR_QUARTER",
    }
    defaults.update(overrides)
    return defaults


def income_source(**overrides) -> dict:
    defaults = dict(DEFAULT_CERT_INCOME_SOURCE)
    defaults.update(overrides)
    return defaults
