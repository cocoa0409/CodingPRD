"""Payload factories — one per creatable resource, input fields only (PRD §3)."""
from .constants import (
    ACADEMIC_YEAR,
    EVENT_END_2H,
    EVENT_START,
    FEDERAL_DEADLINE,
    STATE_GRANT_DEADLINE,
    TEST_DEFAULTS,
)


def create_campaign_payload(**overrides) -> dict:
    defaults = {
        "name": "Campaign 2027",
        "academic_year": ACADEMIC_YEAR,
        "state_grant_deadline": STATE_GRANT_DEADLINE,
        "federal_deadline": FEDERAL_DEADLINE,
        "total_budget_cents": TEST_DEFAULTS["TOTAL_BUDGET_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_school_payload(campaign_id, **overrides) -> dict:
    defaults = {
        "campaign_id": campaign_id,
        "name": "North High School",
        "district_code": "D01",
        "school_code": "SC01",
    }
    defaults.update(overrides)
    return defaults


def create_staff_profile_payload(campaign_id, **overrides) -> dict:
    defaults = {
        "campaign_id": campaign_id,
        "full_name": "Volunteer Vic",
        "capabilities": ["EVENT_STAFF"],
        "languages": ["en"],
    }
    defaults.update(overrides)
    return defaults


def create_senior_record_payload(school_id, **overrides) -> dict:
    defaults = {
        "school_id": school_id,
        "student_ref": "S1",
        "full_name": "Ana Lee",
        "dob": "2009-03-04",
        "home_language": "en",
    }
    defaults.update(overrides)
    return defaults


def create_aid_record_payload(campaign_id, **overrides) -> dict:
    defaults = {
        "campaign_id": campaign_id,
        "external_ref": "EXT1",
        "full_name": "Ana Lee",
        "dob": "2009-03-04",
        "school_code": "SC01",
        "district_code": "D01",
        "initial_status": "SUBMITTED",
        "effective_date": "2027-01-10",
    }
    defaults.update(overrides)
    return defaults


def create_status_event_payload(**overrides) -> dict:
    defaults = {
        "fafsa_status": "SUBMITTED",
        "effective_date": "2027-02-01",
    }
    defaults.update(overrides)
    return defaults


def create_match_link_payload(senior_record_id, aid_record_id, expected_version) -> dict:
    return {
        "senior_record_id": senior_record_id,
        "aid_record_id": aid_record_id,
        "expected_senior_record_version": expected_version,
    }


def create_consent_payload(senior_record_id, **overrides) -> dict:
    defaults = {
        "senior_record_id": senior_record_id,
        "scopes": ["STATUS_DETAIL"],
        "granted_by": "PARENT",
    }
    defaults.update(overrides)
    return defaults


def create_event_payload(school_id, **overrides) -> dict:
    defaults = {
        "school_id": school_id,
        "title": "FAFSA Night",
        "start_time": EVENT_START,
        "end_time": EVENT_END_2H,
        "capacity": TEST_DEFAULTS["EVENT_CAPACITY"],
        "cost_estimate_cents": TEST_DEFAULTS["EVENT_COST_CENTS"],
        "required_expert_count": 0,
        "supported_languages": [],
    }
    defaults.update(overrides)
    return defaults


def create_staff_assignment_payload(event_id, staff_profile_id, **overrides) -> dict:
    defaults = {
        "event_id": event_id,
        "staff_profile_id": staff_profile_id,
        "assigned_role": "VOLUNTEER",
    }
    defaults.update(overrides)
    return defaults


def create_event_registration_payload(event_id, senior_record_id) -> dict:
    return {"event_id": event_id, "senior_record_id": senior_record_id}


def create_support_case_payload(senior_record_id, **overrides) -> dict:
    defaults = {
        "senior_record_id": senior_record_id,
        "case_type": "SPECIAL_CIRCUMSTANCE",
    }
    defaults.update(overrides)
    return defaults


def create_completion_report_payload(campaign_id, **overrides) -> dict:
    defaults = {
        "campaign_id": campaign_id,
        "variant": "SUBMISSION_BASED",
    }
    defaults.update(overrides)
    return defaults
