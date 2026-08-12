"""Payload factories — one per entity, input fields only."""

_COUNTER = {"n": 0}


def _seq() -> int:
    _COUNTER["n"] += 1
    return _COUNTER["n"]


def create_employee_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "employee_code": f"EMP{n:04d}",
        "full_name": f"Test Employee {n}",
        "department": "ENG",
        "job_level": 5,
        "hire_date": "2023-01-15",
        "performance_rating": "SOLID",
    }
    defaults.update(overrides)
    return defaults


def create_critical_role_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "role_title": f"Critical Role {n}",
        "department": "ENG",
        "criticality_tier": "TIER_2",
        "assessment_method": "WEIGHTED",
    }
    defaults.update(overrides)
    return defaults


def create_successor_payload(employee_id, expected_critical_role_version, **overrides) -> dict:
    defaults = {
        "employee_id": employee_id,
        "readiness_rating": "READY_1_2",
        "expected_critical_role_version": expected_critical_role_version,
    }
    defaults.update(overrides)
    return defaults


def create_development_plan_payload(**overrides) -> dict:
    defaults = {"target_readiness": "READY_NOW"}
    defaults.update(overrides)
    return defaults


def create_posting_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "title": f"Posting {n}",
        "planned_open_date": "2026-05-04",
        "planned_close_date": "2026-05-29",
    }
    defaults.update(overrides)
    return defaults


def create_calibration_session_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "name": f"CAL-{n:04d}",
        "department_scope": "ENG",
        "scheduled_start": "2026-06-08T09:00:00Z",
        "scheduled_end": "2026-06-08T12:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_calibration_entry_payload(employee_id, **overrides) -> dict:
    defaults = {"employee_id": employee_id, "proposed_rating": "SOLID"}
    defaults.update(overrides)
    return defaults


def create_hipo_cycle_payload(**overrides) -> dict:
    n = _seq()
    defaults = {"cycle_name": f"2026-C{n:04d}", "capacity": 5}
    defaults.update(overrides)
    return defaults


def create_retention_assessment_payload(**overrides) -> dict:
    defaults = {"assessment_method": "POINT_IN_TIME"}
    defaults.update(overrides)
    return defaults


def create_diversity_snapshot_payload(**overrides) -> dict:
    defaults = {"scope_type": "DEPARTMENT", "scope_ref": "ENG"}
    defaults.update(overrides)
    return defaults
