"""Payload factories — one per entity, input fields only (PRD 4)."""
from typing import Any, Dict


def create_district_payload(**overrides) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {"name": "D1"}
    defaults.update(overrides)
    return defaults


def create_school_payload(district_id: str, **overrides) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "district_id": district_id,
        "name": "S1",
        "coverage_budget_total_cents": 1_000_000,
    }
    defaults.update(overrides)
    return defaults


def create_staff_member_payload(school_id: str, **overrides) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "school_id": school_id,
        "full_name": "Teach One",
        "subject": "MATH",
        "grade_band": "HIGH",
    }
    defaults.update(overrides)
    return defaults


def create_substitute_payload(**overrides) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "full_name": "Sub A",
        "base_daily_rate_cents": 20_000,
    }
    defaults.update(overrides)
    return defaults


def create_qualification_payload(substitute_id: str, **overrides) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "substitute_id": substitute_id,
        "subject": "MATH",
        "grade_band": "HIGH",
    }
    defaults.update(overrides)
    return defaults


def create_clearance_payload(substitute_id: str, **overrides) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "substitute_id": substitute_id,
        "clearance_type": "BACKGROUND_CHECK",
        "expires_on": "2027-12-31",
    }
    defaults.update(overrides)
    return defaults


def create_mark_payload(school_id: str, substitute_id: str, **overrides) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "school_id": school_id,
        "substitute_id": substitute_id,
        "mark_type": "PREFERRED",
    }
    defaults.update(overrides)
    return defaults


def create_absence_payload(staff_member_id: str, **overrides) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "staff_member_id": staff_member_id,
        "start_date": "2026-08-03",
        "end_date": "2026-08-03",
        "absence_type": "SICK",
        "required_subject": "MATH",
        "required_grade_band": "HIGH",
    }
    defaults.update(overrides)
    return defaults


def create_dispatch_batch_payload(district_id: str, **overrides) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {"district_id": district_id}
    defaults.update(overrides)
    return defaults


def create_assignment_payload(absence_id: str, substitute_id: str, **overrides) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "absence_id": absence_id,
        "substitute_id": substitute_id,
    }
    defaults.update(overrides)
    return defaults


def create_coverage_payload(absence_id: str, staff_member_id: str, **overrides) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "absence_id": absence_id,
        "staff_member_id": staff_member_id,
        "coverage_date": "2026-08-03",
        "periods": 2,
    }
    defaults.update(overrides)
    return defaults


def create_timesheet_payload(assignment_id: str, work_date: str, **overrides) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "assignment_id": assignment_id,
        "work_date": work_date,
        "hours_worked": 8.0,
    }
    defaults.update(overrides)
    return defaults


def create_payroll_period_payload(district_id: str, **overrides) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "district_id": district_id,
        "period_start": "2026-08-03",
        "period_end": "2026-08-07",
    }
    defaults.update(overrides)
    return defaults


def create_performance_flag_payload(substitute_id: str, school_id: str, **overrides) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "substitute_id": substitute_id,
        "school_id": school_id,
        "flag_type": "QUALITY",
        "severity": "MINOR",
    }
    defaults.update(overrides)
    return defaults
