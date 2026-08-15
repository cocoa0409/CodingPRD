"""Payload factories — one per entity, input fields only (PRD §3, §4)."""


def create_study_payload(**overrides) -> dict:
    defaults = {
        "name": "Study",
        "analysis_period_start": "2024-01-01",
        "analysis_period_end": "2024-12-31",
        "protected_classes": ["GENDER"],
    }
    defaults.update(overrides)
    return defaults


def create_snapshot_payload(study_id, **overrides) -> dict:
    defaults = {
        "study_id": study_id,
        "employee_ref": "E1",
        "gender_class": "MALE",
        "ethnicity_class": "WHITE",
        "age_band": "UNDER_40",
        "job_family": "ENG",
        "job_level": 5,
        "location_code": "CA",
        "fte_factor": 1.0,
        "base_salary_cents": 10000000,
        "bonus_cents": 0,
        "hire_date": "2020-01-01",
    }
    defaults.update(overrides)
    return defaults


def create_group_payload(study_id, **overrides) -> dict:
    defaults = {
        "study_id": study_id,
        "name": "G1",
        "job_family": "ENG",
        "min_job_level": 5,
        "max_job_level": 5,
        "location_code": "CA",
    }
    defaults.update(overrides)
    return defaults


def create_model_run_payload(comparator_group_id, expected_group_version, **overrides) -> dict:
    defaults = {
        "comparator_group_id": comparator_group_id,
        "methodology": "COHORT_MEDIAN",
        "expected_group_version": expected_group_version,
    }
    defaults.update(overrides)
    return defaults


def create_plan_payload(study_id, **overrides) -> dict:
    defaults = {
        "study_id": study_id,
        "total_budget_cents": 2700000,
    }
    defaults.update(overrides)
    return defaults


def create_adjustment_payload(plan_id, gap_finding_id, employee_snapshot_id, **overrides) -> dict:
    defaults = {
        "plan_id": plan_id,
        "gap_finding_id": gap_finding_id,
        "employee_snapshot_id": employee_snapshot_id,
        "proposed_increase_cents": 100000,
        "effective_date": "2026-09-01",
    }
    defaults.update(overrides)
    return defaults


def create_filing_payload(study_id, **overrides) -> dict:
    defaults = {
        "study_id": study_id,
        "report_type": "EEO_WORKFORCE_COMP",
        "reporting_year": 2025,
        "due_date": "2026-12-31",
    }
    defaults.update(overrides)
    return defaults


def create_jurisdiction_rule_payload(**overrides) -> dict:
    defaults = {
        "jurisdiction_code": "CA",
    }
    defaults.update(overrides)
    return defaults


def create_posting_payload(jurisdiction_rule_id, **overrides) -> dict:
    # min_salary_cents / max_salary_cents are optional and nullable (PRD §3.5);
    # they stay absent unless the caller supplies them.
    defaults = {
        "jurisdiction_rule_id": jurisdiction_rule_id,
        "job_posting_ref": "POST-1",
        "title": "Engineer",
    }
    defaults.update(overrides)
    return defaults


def create_pipeline_analysis_payload(study_id, **overrides) -> dict:
    defaults = {
        "study_id": study_id,
        "stage": "INTERVIEW",
        "cohort_period_start": "2026-01-01",
        "cohort_period_end": "2026-03-31",
        "records": [
            {"class_label": "MAJORITY", "count_in": 100, "count_passed": 80},
            {"class_label": "MINORITY", "count_in": 100, "count_passed": 64},
        ],
    }
    defaults.update(overrides)
    return defaults


def create_monitoring_cycle_payload(study_id, **overrides) -> dict:
    defaults = {
        "study_id": study_id,
        "window_start": "2026-09-02",
        "window_end": "2026-12-01",
        "due_date": "2026-12-15",
    }
    defaults.update(overrides)
    return defaults
