"""Payload factories — one per entity, input fields only (PRD §3/§4)."""

_counter = {"n": 0}


def _uniq(prefix: str) -> str:
    _counter["n"] += 1
    return f"{prefix}-{_counter['n']}"


def create_program_payload(**overrides) -> dict:
    defaults = {
        "fiscal_year": 2027,
        "merit_budget_cents": 50_000_000,
        "refresh_budget_cents": 2_000_000,
        "pricing_as_of_date": "2026-08-01",
    }
    defaults.update(overrides)
    return defaults


def create_job_family_payload(**overrides) -> dict:
    defaults = {"code": _uniq("FAM"), "name": "Engineering"}
    defaults.update(overrides)
    return defaults


def create_job_level_payload(**overrides) -> dict:
    defaults = {
        "level_code": _uniq("L"),
        "title": "Engineer",
        "rank_order": _counter["n"],
    }
    defaults.update(overrides)
    return defaults


def create_geo_zone_payload(**overrides) -> dict:
    defaults = {
        "zone_code": _uniq("ZONE"),
        "name": "US National",
        "differential_ratio": 1.000000,
    }
    defaults.update(overrides)
    return defaults


def create_job_profile_payload(job_family_id: str, job_level_id: str, **overrides) -> dict:
    defaults = {
        "job_family_id": job_family_id,
        "job_level_id": job_level_id,
        "title": _uniq("Job"),
        "summary": "Job description summary",
        "salary_basis_weekly_cents": 200_000,
        "duties_test_passed": True,
    }
    defaults.update(overrides)
    return defaults


def create_market_survey_payload(**overrides) -> dict:
    defaults = {
        "name": _uniq("Survey"),
        "publisher": "Publisher",
        "survey_year": 2026,
        "effective_date": "2026-08-01",
    }
    defaults.update(overrides)
    return defaults


def create_market_cut_payload(
    market_survey_id: str, job_profile_id: str, geo_zone_id: str, **overrides
) -> dict:
    defaults = {
        "market_survey_id": market_survey_id,
        "job_profile_id": job_profile_id,
        "geo_zone_id": geo_zone_id,
        "p50_cents": 10_000_000,
        "sample_size": 20,
        "effective_date": "2026-08-01",
    }
    defaults.update(overrides)
    return defaults


def create_progression_policy_payload(
    job_family_id: str, from_level_id: str, to_level_id: str, **overrides
) -> dict:
    defaults = {
        "job_family_id": job_family_id,
        "from_level_id": from_level_id,
        "to_level_id": to_level_id,
        "min_midpoint_progression_pct": 0.1200,
        "max_overlap_pct": 0.2500,
    }
    defaults.update(overrides)
    return defaults


def create_pay_band_payload(
    comp_program_id: str, job_family_id: str, job_level_id: str, geo_zone_id: str,
    **overrides,
) -> dict:
    defaults = {
        "comp_program_id": comp_program_id,
        "job_family_id": job_family_id,
        "job_level_id": job_level_id,
        "geo_zone_id": geo_zone_id,
        "target_percentile": "P50",
        "spread_pct": 0.3000,
    }
    defaults.update(overrides)
    return defaults


def create_department_payload(**overrides) -> dict:
    defaults = {
        "name": _uniq("Dept"),
        "code": _uniq("D"),
        "adjustment_pool_cents": 5_000_000,
    }
    defaults.update(overrides)
    return defaults


def create_employee_payload(
    department_id: str, job_profile_id: str, geo_zone_id: str, **overrides
) -> dict:
    defaults = {
        "employee_ref": _uniq("E"),
        "department_id": department_id,
        "job_profile_id": job_profile_id,
        "geo_zone_id": geo_zone_id,
        "base_salary_cents": 10_000_000,
        "hire_date": "2020-01-15",
    }
    defaults.update(overrides)
    return defaults


def create_mapping_decision_payload(employee_id: str, to_job_profile_id: str, **overrides) -> dict:
    defaults = {"employee_id": employee_id, "to_job_profile_id": to_job_profile_id}
    defaults.update(overrides)
    return defaults


def create_exception_request_payload(
    employee_id: str, pay_band_id: str, **overrides
) -> dict:
    defaults = {
        "employee_id": employee_id,
        "pay_band_id": pay_band_id,
        "type": "OFF_CYCLE_INCREASE",
        "requested_salary_cents": 11_000_000,
        "justification": "retention",
    }
    defaults.update(overrides)
    return defaults


def create_refresh_cycle_payload(comp_program_id: str, **overrides) -> dict:
    defaults = {
        "comp_program_id": comp_program_id,
        "planned_window_start": "2027-01-01",
        "planned_window_end": "2027-03-01",
        "effective_date": "2027-01-01",
    }
    defaults.update(overrides)
    return defaults
