"""Payload factories — one per entity, input fields only (PRD §3)."""
import uuid as _uuid

from .constants import TEST_DEFAULTS


def _uniq(tag: str) -> str:
    return f"{tag}-{_uuid.uuid4().hex[:8]}"


def create_plan_payload(**overrides) -> dict:
    defaults = {
        "plan_name": TEST_DEFAULTS["PLAN_NAME"],
        "school_year": TEST_DEFAULTS["SCHOOL_YEAR"],
        "total_budget_cents": TEST_DEFAULTS["TOTAL_BUDGET_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_building_payload(plan_id, **overrides) -> dict:
    defaults = {
        "plan_id": plan_id,
        "name": TEST_DEFAULTS["BUILDING_NAME"],
        "building_code": _uniq(TEST_DEFAULTS["BUILDING_CODE"]),
        "hardship_factor": TEST_DEFAULTS["HARDSHIP_FACTOR"],
    }
    defaults.update(overrides)
    return defaults


def create_student_payload(plan_id, building_id, **overrides) -> dict:
    defaults = {
        "plan_id": plan_id,
        "building_id": building_id,
        "student_ref": _uniq("STU"),
        "iep_service_level": "TRANSITIONAL",
        "iep_minutes_per_week": TEST_DEFAULTS["IEP_MINUTES"],
        "required_qualification": "NONE",
    }
    defaults.update(overrides)
    return defaults


def create_para_payload(plan_id, home_building_id, **overrides) -> dict:
    defaults = {
        "plan_id": plan_id,
        "home_building_id": home_building_id,
        "full_name": TEST_DEFAULTS["PARA_NAME"],
        "email": f"{_uniq('para')}@district.test",
        "base_hourly_wage_cents": TEST_DEFAULTS["PARA_WAGE_CENTS"],
        "contracted_max_weekly_minutes": TEST_DEFAULTS["PARA_CAP_MINUTES"],
        "hire_date": TEST_DEFAULTS["HIRE_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_qualification_payload(qualification, completed_on, **overrides) -> dict:
    defaults = {
        "qualification": qualification,
        "completed_on": completed_on,
    }
    defaults.update(overrides)
    return defaults


def create_change_order_payload(student_id, change_type, reason, **overrides) -> dict:
    defaults = {
        "student_id": student_id,
        "change_type": change_type,
        "reason": reason,
    }
    defaults.update(overrides)
    return defaults


def create_assignment_payload(plan_id, student_id, para_id, building_id,
                              expected_plan_version, **overrides) -> dict:
    defaults = {
        "plan_id": plan_id,
        "student_id": student_id,
        "para_id": para_id,
        "building_id": building_id,
        "start_date": TEST_DEFAULTS["START_DATE"],
        "end_date": TEST_DEFAULTS["END_DATE"],
        "days_of_week": list(TEST_DEFAULTS["WEEKDAYS"]),
        "daily_start_minute": TEST_DEFAULTS["DAY_START_MINUTE"],
        "daily_end_minute": TEST_DEFAULTS["DAY_END_MINUTE"],
        "expected_plan_version": expected_plan_version,
    }
    defaults.update(overrides)
    return defaults


def create_coverage_plan_payload(plan_id, building_id, coverage_date, **overrides) -> dict:
    defaults = {
        "plan_id": plan_id,
        "building_id": building_id,
        "coverage_date": coverage_date,
    }
    defaults.update(overrides)
    return defaults


def create_absence_payload(assignment_id, absence_date, expected_coverage_plan_version,
                           reason="illness", **overrides) -> dict:
    defaults = {
        "assignment_id": assignment_id,
        "absence_date": absence_date,
        "expected_coverage_plan_version": expected_coverage_plan_version,
        "reason": reason,
    }
    defaults.update(overrides)
    return defaults


def create_timesheet_payload(assignment_id, work_date, start_minute, end_minute, **overrides) -> dict:
    defaults = {
        "assignment_id": assignment_id,
        "work_date": work_date,
        "start_minute": start_minute,
        "end_minute": end_minute,
    }
    defaults.update(overrides)
    return defaults


def create_evaluation_payload(plan_id, para_id, **overrides) -> dict:
    defaults = {
        "plan_id": plan_id,
        "para_id": para_id,
        "period_start": "2026-03-01",
        "period_end": "2026-04-30",
        "professionalism_score": 4,
        "instructional_support_score": 4,
        "comments": "solid contribution",
    }
    defaults.update(overrides)
    return defaults


def create_formula_payload(plan_id, **overrides) -> dict:
    defaults = {
        "plan_id": plan_id,
        "base_grant_cents": 100_000,
        "per_minute_rate_cents": 5,
        "weight_one_to_one": 1.0,
        "weight_shared_support": 0.6,
        "weight_transitional": 0.4,
        "period_weeks": 1,
    }
    defaults.update(overrides)
    return defaults


def compute_allocations_payload(formula_id, period_label, **overrides) -> dict:
    defaults = {
        "formula_id": formula_id,
        "period_label": period_label,
    }
    defaults.update(overrides)
    return defaults
