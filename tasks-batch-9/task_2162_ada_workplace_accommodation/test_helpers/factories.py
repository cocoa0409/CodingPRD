"""Payload factories - one per resource, input fields only."""

import itertools

from .constants import TEST_DEFAULTS

_seq = itertools.count(1)


def next_suffix() -> str:
    """A short unique suffix so business keys never collide inside one test."""
    return f"{next(_seq):03d}"


def create_job_profile_payload(**overrides) -> dict:
    payload = {
        "job_code": f"JP-{next_suffix()}",
        "title": "Warehouse Operator",
        "department_code": "OPS",
        "department_annual_budget_cents": TEST_DEFAULTS["DEPARTMENT_BUDGET_CENTS"],
        "employer_annual_budget_cents": TEST_DEFAULTS["EMPLOYER_BUDGET_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_essential_function_payload(**overrides) -> dict:
    payload = {
        "function_code": f"EF-{next_suffix()}",
        "description": "Lift 50 lb totes to shoulder height",
        "criticality_weight": TEST_DEFAULTS["CRITICALITY_WEIGHT"],
        "frequency_per_week": TEST_DEFAULTS["FREQUENCY_PER_WEEK"],
        "is_essential": True,
        "marginal_reassignable": False,
    }
    payload.update(overrides)
    return payload


def publish_profile_payload(**overrides) -> dict:
    payload = {"profile_version_label": TEST_DEFAULTS["PROFILE_VERSION_LABEL"]}
    payload.update(overrides)
    return payload


def create_employee_payload(job_profile_id: str, **overrides) -> dict:
    payload = {
        "employee_number": f"E-{next_suffix()}",
        "full_name": "Dana Ruiz",
        "department_code": "OPS",
        "job_title": "Warehouse Operator",
        "hire_date": "2023-04-01",
        "job_profile_id": job_profile_id,
        "is_people_manager": False,
        "annual_salary_cents": TEST_DEFAULTS["ANNUAL_SALARY_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_accommodation_request_payload(employee_id: str, **overrides) -> dict:
    payload = {
        "employee_id": employee_id,
        "request_channel": "WRITTEN",
        "requested_accommodation_text": "Lift assist device for tote handling",
        "disability_obvious": True,
    }
    payload.update(overrides)
    return payload


def create_medical_doc_request_payload(expected_request_version: int, **overrides) -> dict:
    payload = {
        "scope_fields_requested": ["functional_limitations", "work_restrictions"],
        "due_date": "2026-08-17T00:00:00Z",
        "is_second_opinion": False,
        "expected_request_version": expected_request_version,
    }
    payload.update(overrides)
    return payload


def create_function_analysis_payload(essential_function_id: str, **overrides) -> dict:
    payload = {
        "essential_function_id": essential_function_id,
        "can_perform_unaided": False,
        "limitation_severity": 3,
        "proposed_treatment": "PERFORM_WITH_AID",
    }
    payload.update(overrides)
    return payload


def create_option_payload(coverage_function_ids=None, **overrides) -> dict:
    payload = {
        "option_code": f"OPT-{next_suffix()}",
        "category": "EQUIPMENT",
        "one_time_cost_cents": TEST_DEFAULTS["CHEAP_ONE_TIME_CENTS"],
        "recurring_monthly_cost_cents": 0,
        "implementation_days": 10,
        "coverage_function_ids": list(coverage_function_ids or []),
    }
    payload.update(overrides)
    return payload


def create_hardship_assessment_payload(expected_option_version: int, **overrides) -> dict:
    payload = {
        "assessment_basis": "SITE_LOCAL",
        "expected_option_version": expected_option_version,
    }
    payload.update(overrides)
    return payload


def create_trial_period_payload(request_id: str, option_id: str, **overrides) -> dict:
    payload = {
        "request_id": request_id,
        "option_id": option_id,
        "start_date": "2026-09-01",
        "end_date": "2026-11-30",
        "checkin_cadence_days": 14,
        "scoring_mode": "LATEST_WEIGHTED",
    }
    payload.update(overrides)
    return payload


def create_effectiveness_review_payload(**overrides) -> dict:
    payload = {
        "employee_rating": 8,
        "manager_rating": 8,
        "objective_metric_pct": 80,
    }
    payload.update(overrides)
    return payload


def create_absence_record_payload(employee_id: str, **overrides) -> dict:
    payload = {
        "employee_id": employee_id,
        "record_type": "FMLA_CONTINUOUS",
        "start_date": "2026-08-25",
        "end_date": "2026-10-31",
        "weekly_intermittent_days": 0,
        "restriction_severity": 0,
        "modified_duty_available": False,
    }
    payload.update(overrides)
    return payload


def create_medical_disclosure_payload(**overrides) -> dict:
    payload = {
        "disclosed_to_role": "AccommodationCoordinator",
        "disclosed_to_user_id": "COORD-1",
        "disclosure_purpose": "FUNCTION_ANALYSIS",
        "fields_disclosed": ["work_restrictions"],
    }
    payload.update(overrides)
    return payload


def deny_payload(**overrides) -> dict:
    payload = {
        "decision": "DENY",
        "denial_basis": "NOT_QUALIFIED",
        "rationale_text": "No accommodation on the table clears the essential duties.",
    }
    payload.update(overrides)
    return payload


def grant_payload(selected_option_id: str, decision: str = "GRANT_PERMANENT", **overrides) -> dict:
    payload = {"decision": decision, "selected_option_id": selected_option_id}
    payload.update(overrides)
    return payload
