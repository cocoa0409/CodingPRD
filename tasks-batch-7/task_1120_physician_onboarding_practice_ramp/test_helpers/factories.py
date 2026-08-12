"""Payload factories — one per creatable entity, input fields only."""

import itertools

_counter = itertools.count(1)


def _uniq_email() -> str:
    return f"physician{next(_counter)}@example.com"


def create_physician_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Dr. Test",
        "specialty": "FAMILY_MEDICINE",
        "email": _uniq_email(),
        "hire_type": "EXPERIENCED",
    }
    defaults.update(overrides)
    return defaults


def create_case_payload(physician_id: str, **overrides) -> dict:
    defaults = {
        "physician_id": physician_id,
        "target_start_date": "2027-06-01",
    }
    defaults.update(overrides)
    return defaults


def create_offer_payload(onboarding_case_id: str, expected_onboarding_case_version: int, **overrides) -> dict:
    defaults = {
        "onboarding_case_id": onboarding_case_id,
        "expected_onboarding_case_version": expected_onboarding_case_version,
        "base_salary_cents": 25000000,
        "signing_bonus_cents": 2000000,
        "guarantee_monthly_cents": 2000000,
        "guarantee_term_months": 12,
        "panel_capacity": 1000,
        "proposed_start_date": "2027-06-01",
        "expires_at": "2026-08-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_credential_item_payload(onboarding_case_id: str, item_type: str, **overrides) -> dict:
    defaults = {
        "onboarding_case_id": onboarding_case_id,
        "item_type": item_type,
        "document_ref": f"doc-{item_type.lower()}",
    }
    if item_type in ("STATE_LICENSE", "DEA_REGISTRATION"):
        defaults["expires_on"] = "2028-06-01"
    if item_type in ("PAYER_ENROLLMENT_MEDICARE", "PAYER_ENROLLMENT_COMMERCIAL"):
        defaults["payer_code"] = "MCR" if item_type == "PAYER_ENROLLMENT_MEDICARE" else "AETNA"
    defaults.update(overrides)
    return defaults


def create_schedule_template_payload(onboarding_case_id: str, **overrides) -> dict:
    defaults = {
        "onboarding_case_id": onboarding_case_id,
        "weekday": 1,
        "start_minute": 480,
        "end_minute": 960,
        "block_type": "CLINIC",
    }
    defaults.update(overrides)
    return defaults


def create_campaign_payload(onboarding_case_id: str, **overrides) -> dict:
    defaults = {
        "onboarding_case_id": onboarding_case_id,
        "name": "Outreach",
        "budget_cents": 1000000,
    }
    defaults.update(overrides)
    return defaults


def create_campaign_event_payload(campaign_id: str, **overrides) -> dict:
    defaults = {
        "campaign_id": campaign_id,
        "event_type": "COMMUNITY_TALK",
        "start_date": "2027-04-05",
        "end_date": "2027-04-05",
        "cost_cents": 100000,
        "venue": "Library",
    }
    defaults.update(overrides)
    return defaults


def create_mentorship_payload(onboarding_case_id: str, mentor_physician_id: str,
                              expected_onboarding_case_version: int, **overrides) -> dict:
    defaults = {
        "onboarding_case_id": onboarding_case_id,
        "mentor_physician_id": mentor_physician_id,
        "expected_onboarding_case_version": expected_onboarding_case_version,
    }
    defaults.update(overrides)
    return defaults


def create_check_in_payload(day_marker: str, sentiment: str, **overrides) -> dict:
    defaults = {
        "day_marker": day_marker,
        "sentiment": sentiment,
    }
    defaults.update(overrides)
    return defaults


def create_snapshot_payload(onboarding_case_id: str, variant: str, **overrides) -> dict:
    defaults = {
        "onboarding_case_id": onboarding_case_id,
        "variant": variant,
    }
    defaults.update(overrides)
    return defaults
