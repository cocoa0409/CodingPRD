"""Payload factories -- one per entity, carrying only client-supplied fields."""

import itertools

_email_counter = itertools.count(1)


def unique_email(prefix: str = "investigator") -> str:
    """Return an institutional email that has not been used in this process."""
    return f"{prefix}{next(_email_counter)}@uni.edu"


DEFAULTS = {
    "INVESTIGATOR_NAME": "Test Investigator",
    "HOME_DEPARTMENT": "Research Security Studies",
    "ORG_NAME": "Test Foreign Institute",
    "COUNTRY_CODE": "CN",
    "PROJECT_TITLE": "Test Research Project",
    "PERIOD_START": "2026-09-01T00:00:00Z",
    "PERIOD_END": "2028-08-31T00:00:00Z",
    "AWARD_AMOUNT_CENTS": 50_000_000,
    "CYCLE_LABEL": "2026-ANNUAL",
    "ITEM_START_DATE": "2024-09-01T00:00:00Z",
    "TRAVEL_DEPART_ON": "2026-09-01T00:00:00Z",
    "TRAVEL_RETURN_ON": "2026-09-10T00:00:00Z",
    "GRANT_VALID_FROM": "2026-09-01T00:00:00Z",
    "GRANT_VALID_UNTIL": "2026-12-01T00:00:00Z",
    "TRAINING_DUE_ON": "2026-12-31T00:00:00Z",
    "DISCOVERED_ON": "2026-07-20T00:00:00Z",
    "INCIDENT_SUMMARY": "Discovered during a routine records review.",
    "SUBAWARD_SCOPE": "Component fabrication and testing.",
    "SUBAWARD_AMOUNT_CENTS": 5_000_000,
}


def create_investigator_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["INVESTIGATOR_NAME"],
        "email": unique_email(),
        "appointment_type": "FACULTY",
        "home_department": DEFAULTS["HOME_DEPARTMENT"],
    }
    defaults.update(overrides)
    return defaults


def create_foreign_organization_payload(**overrides) -> dict:
    defaults = {
        "legal_name": DEFAULTS["ORG_NAME"],
        "country_code": DEFAULTS["COUNTRY_CODE"],
        "org_type": "INSTITUTE",
    }
    defaults.update(overrides)
    return defaults


def create_project_payload(**overrides) -> dict:
    defaults = {
        "title": DEFAULTS["PROJECT_TITLE"],
        "agency_code": "NSF",
        "sensitivity_level": "STANDARD",
        "award_amount_cents": DEFAULTS["AWARD_AMOUNT_CENTS"],
        "period_start": DEFAULTS["PERIOD_START"],
        "period_end": DEFAULTS["PERIOD_END"],
        "controlled_area_capacity": 0,
    }
    defaults.update(overrides)
    return defaults


def create_personnel_payload(investigator_id: str, **overrides) -> dict:
    defaults = {
        "investigator_id": investigator_id,
        "role_on_project": "PI",
        "committed_person_months": 1.00,
    }
    defaults.update(overrides)
    return defaults


def create_disclosure_payload(
    investigator_id: str, expected_investigator_version: int, **overrides
) -> dict:
    defaults = {
        "investigator_id": investigator_id,
        "cycle_label": DEFAULTS["CYCLE_LABEL"],
        "disclosure_type": "ANNUAL",
        "expected_investigator_version": expected_investigator_version,
    }
    defaults.update(overrides)
    return defaults


def create_disclosure_item_payload(foreign_organization_id: str, **overrides) -> dict:
    defaults = {
        "item_type": "FOREIGN_APPOINTMENT",
        "foreign_organization_id": foreign_organization_id,
        "start_date": DEFAULTS["ITEM_START_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_support_statement_payload(
    investigator_id: str, project_id: str, **overrides
) -> dict:
    defaults = {
        "investigator_id": investigator_id,
        "project_id": project_id,
        "agency_code": "NIH",
        "document_type": "CURRENT_AND_PENDING",
        "declared_person_months": 0.00,
        "declared_appointment_count": 0,
        "declared_support_count": 0,
    }
    defaults.update(overrides)
    return defaults


def create_travel_registration_payload(investigator_id: str, **overrides) -> dict:
    defaults = {
        "investigator_id": investigator_id,
        "destination_country_code": "JP",
        "depart_on": DEFAULTS["TRAVEL_DEPART_ON"],
        "return_on": DEFAULTS["TRAVEL_RETURN_ON"],
        "purpose": "CONFERENCE",
    }
    defaults.update(overrides)
    return defaults


def create_access_grant_payload(
    project_id: str, investigator_id: str, expected_project_version: int, **overrides
) -> dict:
    defaults = {
        "project_id": project_id,
        "investigator_id": investigator_id,
        "valid_from": DEFAULTS["GRANT_VALID_FROM"],
        "valid_until": DEFAULTS["GRANT_VALID_UNTIL"],
        "expected_project_version": expected_project_version,
    }
    defaults.update(overrides)
    return defaults


def create_security_incident_payload(investigator_id: str, **overrides) -> dict:
    defaults = {
        "investigator_id": investigator_id,
        "incident_type": "UNDISCLOSED_APPOINTMENT",
        "discovered_on": DEFAULTS["DISCOVERED_ON"],
        "summary": DEFAULTS["INCIDENT_SUMMARY"],
    }
    defaults.update(overrides)
    return defaults


def create_training_assignment_payload(investigator_id: str, **overrides) -> dict:
    defaults = {
        "investigator_id": investigator_id,
        "course_code": "RESEARCH_SECURITY_BASE",
        "due_on": DEFAULTS["TRAINING_DUE_ON"],
    }
    defaults.update(overrides)
    return defaults


def create_subaward_payload(project_id: str, organization_id: str, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "organization_id": organization_id,
        "scope": DEFAULTS["SUBAWARD_SCOPE"],
        "amount_cents": DEFAULTS["SUBAWARD_AMOUNT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def issue_plan_payload(**overrides) -> dict:
    defaults = {
        "action": "ISSUE",
        "plan_effort_cap_pct": 100,
        "plan_required_actions": ["REDUCE_OUTSIDE_EFFORT"],
        "plan_effective_from": "2026-08-01T00:00:00Z",
        "plan_expires_on": "2027-08-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults
