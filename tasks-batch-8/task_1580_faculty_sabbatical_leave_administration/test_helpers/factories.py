"""Payload factories — one per entity, input fields only."""

_counter = {"n": 0}


def _next() -> int:
    _counter["n"] += 1
    return _counter["n"]


def create_department_payload(**overrides) -> dict:
    defaults = {
        "name": f"Department {_next()}",
        "replacement_pool": 160000.00,
    }
    defaults.update(overrides)
    return defaults


def create_faculty_payload(department_id: str, **overrides) -> dict:
    n = _next()
    defaults = {
        "employee_number": f"EMP{n:05d}",
        "full_name": f"Faculty Member {n}",
        "department_id": department_id,
        "academic_rank": "ASSOCIATE_PROFESSOR",
        "hire_date": "2020-08-01T00:00:00Z",
        "annual_base_salary": 120000.00,
    }
    defaults.update(overrides)
    return defaults


def create_cycle_payload(**overrides) -> dict:
    defaults = {
        "name": f"AY2027 Sabbaticals {_next()}",
        "academic_year": "2027-2028",
        "award_quota": 2,
    }
    defaults.update(overrides)
    return defaults


def create_application_payload(
    leave_type: str = "SABBATICAL",
    cycle_id=None,
    requested_duration_semesters: int = 1,
    requested_salary_pct: int = 100,
    proposed_start_date: str = "2027-01-01T00:00:00Z",
    proposed_end_date: str = "2027-07-01T00:00:00Z",
    **overrides,
) -> dict:
    payload = {
        "leave_type": leave_type,
        "requested_duration_semesters": requested_duration_semesters,
        "requested_salary_pct": requested_salary_pct,
        "proposed_start_date": proposed_start_date,
        "proposed_end_date": proposed_end_date,
    }
    if cycle_id is not None:
        payload["cycle_id"] = cycle_id
    payload.update(overrides)
    return payload


def create_review_payload(
    application_id: str,
    scholarly_merit: float = 80,
    curriculum_benefit: float = 90,
    feasibility: float = 70,
    **overrides,
) -> dict:
    payload = {
        "application_id": application_id,
        "scholarly_merit": scholarly_merit,
        "curriculum_benefit": curriculum_benefit,
        "feasibility": feasibility,
    }
    payload.update(overrides)
    return payload


def create_coverage_plan_payload(
    application_id: str,
    courses_to_cover: int,
    expected_application_version: int,
    supersedes_plan_id=None,
    **overrides,
) -> dict:
    payload = {
        "application_id": application_id,
        "courses_to_cover": courses_to_cover,
        "expected_application_version": expected_application_version,
    }
    if supersedes_plan_id is not None:
        payload["supersedes_plan_id"] = supersedes_plan_id
    payload.update(overrides)
    return payload


def create_fellowship_payload(
    application_id: str,
    amount: float = 5000.00,
    window_start_date: str = "2027-03-01T00:00:00Z",
    window_end_date: str = "2027-07-01T00:00:00Z",
    **overrides,
) -> dict:
    payload = {
        "application_id": application_id,
        "name": f"Fellowship {_next()}",
        "amount": amount,
        "window_start_date": window_start_date,
        "window_end_date": window_end_date,
    }
    payload.update(overrides)
    return payload


def create_payment_payload(amount: float, expected_repayment_version: int, **overrides) -> dict:
    payload = {
        "amount": amount,
        "expected_repayment_version": expected_repayment_version,
    }
    payload.update(overrides)
    return payload


def create_accrual_ledger_entry_payload(
    faculty_id: str, credits_delta: int, affects_lifetime: bool = False, **overrides
) -> dict:
    payload = {
        "faculty_id": faculty_id,
        "entry_type": "ADJUST",
        "credits_delta": credits_delta,
        "affects_lifetime": affects_lifetime,
    }
    payload.update(overrides)
    return payload
