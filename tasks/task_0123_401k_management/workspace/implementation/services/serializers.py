"""Serializers — convert entity dicts to API-shaped dicts.

Each serializer returns a fresh dict so callers may mutate without aliasing.
"""

from copy import deepcopy


PLAN_FIELDS = [
    "id", "plan_name", "plan_year", "match_formula_type", "tiered_brackets",
    "vesting_schedule_type", "cliff_years", "graded_percentages", "rmd_age",
    "current_vesting_epoch", "status",
    "created_at", "updated_at", "version",
]


PARTICIPANT_FIELDS = [
    "id", "plan_id", "employee_external_id", "date_of_birth", "hire_date",
    "annual_compensation_cents", "elected_deferral_pct",
    "deferral_suspended_until",
    "vested_pct_snapshot", "vesting_epoch_at_snapshot",
    "cumulative_employee_contribution_cents",
    "cumulative_employer_match_cents",
    "total_account_balance_cents",
    "status",
    "created_at", "updated_at", "version",
]


CONTRIBUTION_FIELDS = [
    "id", "plan_id", "participant_id", "pay_period_end", "gross_pay_cents",
    "employee_amount_cents", "employer_match_cents", "status", "created_at",
]


VESTING_SNAPSHOT_FIELDS = [
    "id", "plan_id", "participant_id", "vesting_epoch",
    "service_years_completed", "vested_pct", "vested_balance_cents",
    "created_at",
]


LOAN_FIELDS = [
    "id", "plan_id", "participant_id", "requested_amount_cents",
    "approved_amount_cents", "term_months", "monthly_payment_cents",
    "outstanding_principal_cents", "payments_made", "origination_date",
    "next_due_date", "status",
    "created_at", "updated_at", "version",
]


LOAN_REPAYMENT_FIELDS = [
    "id", "plan_id", "participant_id", "loan_id", "payment_amount_cents",
    "principal_cents", "posted_on", "status", "created_at",
]


HARDSHIP_FIELDS = [
    "id", "plan_id", "participant_id", "requested_amount_cents",
    "hardship_reason_code", "approved_amount_cents",
    "vested_balance_cents_at_request", "status",
    "created_at", "updated_at", "version",
]


RMD_FIELDS = [
    "id", "plan_id", "participant_id", "rmd_year",
    "prior_year_end_balance_cents", "distribution_period_factor",
    "required_amount_cents", "due_date", "distributed_amount_cents", "status",
    "created_at", "updated_at", "version",
]


PLAN_CLOCK_FIELDS = ["id", "plan_id", "current_date", "created_at"]


def _project(entity: dict, fields: list) -> dict:
    return {k: deepcopy(entity.get(k)) for k in fields}


def plan_view(p: dict) -> dict:
    return _project(p, PLAN_FIELDS)


def participant_view(p: dict) -> dict:
    return _project(p, PARTICIPANT_FIELDS)


def contribution_view(c: dict) -> dict:
    return _project(c, CONTRIBUTION_FIELDS)


def vesting_snapshot_view(v: dict) -> dict:
    return _project(v, VESTING_SNAPSHOT_FIELDS)


def loan_view(l: dict) -> dict:
    return _project(l, LOAN_FIELDS)


def loan_repayment_view(r: dict) -> dict:
    return _project(r, LOAN_REPAYMENT_FIELDS)


def hardship_view(h: dict) -> dict:
    return _project(h, HARDSHIP_FIELDS)


def rmd_view(r: dict) -> dict:
    return _project(r, RMD_FIELDS)


def plan_clock_view(c: dict) -> dict:
    return _project(c, PLAN_CLOCK_FIELDS)
