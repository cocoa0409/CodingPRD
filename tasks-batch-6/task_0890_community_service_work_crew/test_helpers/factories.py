"""Payload factories — one per entity, input fields only.

Only fields the client supplies (``source: input``) appear here. System- and
computed-source fields are omitted so tests never send server-owned values.
"""
from .constants import (
    DEFAULT_POLICY_EFFECTIVE, DEFAULT_POLICY_EXPIRY, DEFAULT_DEADLINE,
)


def create_participant_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Pat Doe",
        "date_of_birth": "1990-01-01T00:00:00Z",
        "contact_email": "pat@example.org",
    }
    defaults.update(overrides)
    return defaults


def create_site_payload(**overrides) -> dict:
    defaults = {
        "name": "Green Park",
        "agency_type": "NONPROFIT",
        "address": "1 Main St",
        "capacity_slots": 5,
    }
    defaults.update(overrides)
    return defaults


def create_insurance_policy_payload(site_id: str, **overrides) -> dict:
    defaults = {
        "site_id": site_id,
        "carrier": "Acme",
        "coverage_amount_cents": 1_000_000,
        "effective_date": DEFAULT_POLICY_EFFECTIVE,
        "expiry_date": DEFAULT_POLICY_EXPIRY,
    }
    defaults.update(overrides)
    return defaults


def create_supervisor_payload(site_id: str, **overrides) -> dict:
    defaults = {
        "site_id": site_id,
        "full_name": "Sam Sup",
        "max_concurrent_participants": 5,
    }
    defaults.update(overrides)
    return defaults


def create_referral_payload(participant_id: str, **overrides) -> dict:
    defaults = {
        "participant_id": participant_id,
        "court_case_number": "CR-1",
        "offense_class": "MISDEMEANOR",
        "hours_ordered": 40,
        "deadline_date": DEFAULT_DEADLINE,
        "indigency_status": "NONE",
    }
    defaults.update(overrides)
    return defaults


def create_placement_payload(referral_id: str, site_id: str, supervisor_id: str,
                             **overrides) -> dict:
    defaults = {
        "referral_id": referral_id,
        "site_id": site_id,
        "supervisor_id": supervisor_id,
    }
    defaults.update(overrides)
    return defaults


def create_work_session_payload(placement_id: str, scheduled_start: str,
                                scheduled_end: str, **overrides) -> dict:
    defaults = {
        "placement_id": placement_id,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
    }
    defaults.update(overrides)
    return defaults


def create_fee_conversion_payload(referral_id: str, hours_to_convert: float,
                                  expected_referral_version: int, **overrides) -> dict:
    defaults = {
        "referral_id": referral_id,
        "hours_to_convert": hours_to_convert,
        "expected_referral_version": expected_referral_version,
    }
    defaults.update(overrides)
    return defaults


def create_compliance_action_payload(referral_id: str, action_type: str,
                                     reason: str = "reason", **overrides) -> dict:
    defaults = {
        "referral_id": referral_id,
        "action_type": action_type,
        "reason": reason,
    }
    defaults.update(overrides)
    return defaults
