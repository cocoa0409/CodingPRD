"""Payload factories — one per entity, input fields only."""

DEFAULT_SALARY_CENTS = 10000
DEFAULT_HIRE_DATE = "2026-01-05"
DEFAULT_GRANT_VALID_FROM = "2026-08-01"
DEFAULT_GRANT_VALID_UNTIL = "2027-08-01"


def create_data_field_payload(**overrides) -> dict:
    defaults = {
        "field_key": "assignment.salary_cents",
        "display_name": "Salary",
        "sensitivity": "INTERNAL",
        "history_policy": "CORRECTABLE",
        "owner_team": "comp",
    }
    defaults.update(overrides)
    return defaults


def create_dq_rule_payload(**overrides) -> dict:
    defaults = {
        "rule_type": "RANGE",
        "severity": "WARNING",
        "param_min": 5000,
        "param_max": 20000,
    }
    defaults.update(overrides)
    return defaults


def create_position_payload(**overrides) -> dict:
    defaults = {
        "title": "Eng",
        "department": "ENG",
        "headcount_budget": 5,
    }
    defaults.update(overrides)
    return defaults


def create_worker_payload(**overrides) -> dict:
    defaults = {
        "legal_name": "Test Worker",
        "worker_number": "W1",
        "hire_date": DEFAULT_HIRE_DATE,
        "initial_salary_cents": DEFAULT_SALARY_CENTS,
    }
    defaults.update(overrides)
    return defaults


def create_worker_change_request_payload(**overrides) -> dict:
    defaults = {
        "target_type": "WORKER_FIELD",
        "new_value": "12000",
        "effective_date": "2026-09-01",
    }
    defaults.update(overrides)
    return defaults


def create_position_change_request_payload(**overrides) -> dict:
    defaults = {
        "target_type": "POSITION_FIELD",
        "new_value": "Staff Engineer",
        "effective_date": "2026-09-01",
    }
    defaults.update(overrides)
    return defaults


def create_batch_payload(**overrides) -> dict:
    defaults = {"name": "reorg"}
    defaults.update(overrides)
    return defaults


def create_batch_line_payload(**overrides) -> dict:
    defaults = {
        "line_index": 1,
        "new_value": "SF",
        "effective_date": "2026-09-01",
    }
    defaults.update(overrides)
    return defaults


def create_grant_payload(**overrides) -> dict:
    defaults = {
        "role_code": "CHANGE_APPROVER",
        "valid_from": DEFAULT_GRANT_VALID_FROM,
        "valid_until": DEFAULT_GRANT_VALID_UNTIL,
    }
    defaults.update(overrides)
    return defaults
