"""Payload factories — one per entity, request-input fields only."""
import itertools

from .constants import TEST_DEFAULTS

_license_counter = itertools.count(1)


def unique_license_number(prefix: str = "P") -> str:
    return f"{prefix}-{9000 + next(_license_counter)}"


def project_payload(**overrides) -> dict:
    payload = {
        "license_number": overrides.pop("license_number", unique_license_number()),
        "project_name": TEST_DEFAULTS["PROJECT_NAME"],
        "installed_capacity_mw": TEST_DEFAULTS["INSTALLED_CAPACITY_MW"],
        "base_annual_generation_mwh": TEST_DEFAULTS["BASE_ANNUAL_GENERATION_MWH"],
        "license_expiration_date": TEST_DEFAULTS["LICENSE_EXPIRATION_DATE"],
    }
    payload.update(overrides)
    return payload


def dam_payload(project_id: str, **overrides) -> dict:
    payload = {
        "project_id": project_id,
        "dam_code": "D1",
        "hazard_class": "HIGH",
        "inspection_interval_months": 12,
    }
    payload.update(overrides)
    return payload


def site_payload(project_id: str, **overrides) -> dict:
    payload = {
        "project_id": project_id,
        "site_code": TEST_DEFAULTS["SITE_CODE"],
        "river_mile": TEST_DEFAULTS["RIVER_MILE"],
    }
    payload.update(overrides)
    return payload


def study_plan_payload(project_id: str, **overrides) -> dict:
    payload = {"project_id": project_id, "plan_title": TEST_DEFAULTS["PLAN_TITLE"]}
    payload.update(overrides)
    return payload


def study_payload(study_plan_id: str, site_id: str, **overrides) -> dict:
    payload = {
        "study_plan_id": study_plan_id,
        "site_id": site_id,
        "resource_category": "FISH_PASSAGE",
        "study_title": "Upstream passage assessment",
        "fieldwork_window_start": "2026-09-01",
        "fieldwork_window_end": "2026-10-01",
    }
    payload.update(overrides)
    return payload


def comment_payload(study_plan_id: str, party_id: str, **overrides) -> dict:
    payload = {
        "study_plan_id": study_plan_id,
        "party_id": party_id,
        "resource_category": "FISH_PASSAGE",
        "comment_text": "Add a spring outmigration survey.",
    }
    payload.update(overrides)
    return payload


def party_payload(project_id: str, **overrides) -> dict:
    payload = {
        "project_id": project_id,
        "party_name": "State Fish Agency",
        "party_type": "AGENCY",
    }
    payload.update(overrides)
    return payload


def settlement_payload(project_id: str, expected_project_version: int, **overrides) -> dict:
    payload = {
        "project_id": project_id,
        "title": "Comprehensive settlement",
        "expected_project_version": expected_project_version,
    }
    payload.update(overrides)
    return payload


def signature_payload(settlement_id: str, party_id: str, **overrides) -> dict:
    payload = {
        "settlement_id": settlement_id,
        "party_id": party_id,
        "position": "SUPPORT",
    }
    payload.update(overrides)
    return payload


def water_quality_certification_payload(project_id: str, **overrides) -> dict:
    payload = {
        "project_id": project_id,
        "certifying_agency_name": TEST_DEFAULTS["CERTIFYING_AGENCY_NAME"],
    }
    payload.update(overrides)
    return payload


def measure_payload(project_id: str, **overrides) -> dict:
    payload = {
        "project_id": project_id,
        "measure_name": "Minimum flow release",
        "resource_category": "WATER_QUALITY",
        "source": "LICENSEE_PROPOSED",
        "capital_cost_usd": 600000.00,
        "annual_om_cost_usd": 20000.00,
        "construction_start_year": 2026,
        "implementation_months": 6,
        "flow_release_cfs": 40,
        "gross_head_ft": 60,
        "release_days": 120,
    }
    payload.update(overrides)
    return payload


def condition_payload(**overrides) -> dict:
    """One element of the `conditions` array on a certification decision."""
    payload = {
        "measure_name": "Minimum flow release",
        "resource_category": "WATER_QUALITY",
        "capital_cost_usd": 600000.00,
        "annual_om_cost_usd": 20000.00,
        "construction_start_year": 2026,
        "implementation_months": 6,
        "flow_release_cfs": 40,
        "gross_head_ft": 60,
        "release_days": 120,
    }
    payload.update(overrides)
    return payload


def application_payload(project_id: str, expected_project_version: int, **overrides) -> dict:
    payload = {
        "project_id": project_id,
        "application_type": "ORIGINAL_RELICENSE",
        "expected_project_version": expected_project_version,
    }
    payload.update(overrides)
    return payload


def annual_report_payload(report_basis: str, period_year: int, **overrides) -> dict:
    payload = {"report_basis": report_basis, "period_year": period_year}
    payload.update(overrides)
    return payload


def schedule_payload(activity_window_start: str, activity_window_end: str, **overrides) -> dict:
    payload = {
        "activity_window_start": activity_window_start,
        "activity_window_end": activity_window_end,
    }
    payload.update(overrides)
    return payload
