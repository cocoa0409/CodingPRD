"""Entity assertions and domain invariant checkers."""
from typing import List, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict):
    """Fields carried by every mutable entity: id, created_at, updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), f"version must be an int, got {data.get('version')!r}"


def _assert_append_only_fields(data: dict):
    """Immutable records carry id and created_at only — no updated_at, no version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert "updated_at" not in data, "immutable records must not carry updated_at"
    assert "version" not in data, "immutable records must not carry version"


def assert_household_employer(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["primary_state_code"], str) and len(data["primary_state_code"]) == 2
    assert isinstance(data["fein"], str) and len(data["fein"]) == 9
    assert data["pay_frequency"] in ("WEEKLY", "BIWEEKLY", "SEMIMONTHLY", "MONTHLY")
    assert isinstance(data["prior_year_schedule_h_cents"], int)
    assert data["status"] in ("ONBOARDING", "ACTIVE", "SUSPENDED")
    assert data["compliance_posture"] in ("CLEAR", "ATTENTION", "RESTRICTED")


def assert_state_rule_pack(data: dict):
    _assert_append_only_fields(data)
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert data["min_pay_frequency"] in ("WEEKLY", "BIWEEKLY", "SEMIMONTHLY", "MONTHLY")
    assert isinstance(data["weekly_ot_threshold_minutes"], int)
    assert isinstance(data["daily_ot_threshold_minutes"], int)
    assert isinstance(data["daily_dt_threshold_minutes"], int)
    assert isinstance(data["live_in_weekly_ot_eligible"], bool)
    assert isinstance(data["live_in_daily_ot_eligible"], bool)
    assert isinstance(data["min_wage_cents"], int)
    assert isinstance(data["workers_comp_required"], bool)
    assert isinstance(data["new_hire_report_days"], int)
    assert isinstance(data["pay_stub_required"], bool)


def assert_state_registration(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["employer_id"], str)
    assert isinstance(data["state_code"], str)
    assert data["agency"] in ("SIT_WITHHOLDING", "SUTA", "NEW_HIRE_DIRECTORY")
    assert data["status"] in ("DRAFT", "SUBMITTED", "ACTIVE")


def assert_domestic_worker(data: dict):
    _assert_common_fields(data)
    assert data["employer_id"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["work_state_code"], str)
    assert isinstance(data["hire_date"], str)
    assert data["work_arrangement"] in ("LIVE_IN", "LIVE_OUT")
    assert data["classification"] in ("UNDETERMINED", "EMPLOYEE", "CONTRACTOR")
    assert data["status"] in ("ONBOARDING", "CLASSIFIED", "ACTIVE", "TERMINATED")
    assert isinstance(data["cash_wages_ytd_cents"], int)
    assert isinstance(data["fica_covered"], bool)
    assert isinstance(data["ss_wages_paid_ytd_cents"], int)
    assert isinstance(data["futa_wages_ytd_cents"], int)
    assert isinstance(data["ytd_approved_minutes"], int)
    assert isinstance(data["accrued_leave_minutes"], int)
    assert isinstance(data["used_leave_minutes"], int)
    assert isinstance(data["available_leave_minutes"], int)


def assert_employment_agreement(data: dict):
    _assert_common_fields(data)
    assert data["worker_id"]
    assert isinstance(data["hourly_rate_cents"], int)
    assert data["pay_method"] in ("HOURLY", "GUARANTEED_SALARY_FWW")
    assert isinstance(data["guaranteed_minutes_per_week"], int)
    assert isinstance(data["fit_withholding_cents_per_period"], int)
    assert isinstance(data["effective_from"], str)
    assert data["status"] in ("ACTIVE", "SUPERSEDED", "TERMINATED")


def assert_timesheet(data: dict):
    _assert_common_fields(data)
    assert data["worker_id"]
    assert isinstance(data["period_start"], str)
    assert isinstance(data["period_end"], str)
    assert isinstance(data["entries"], list)
    assert isinstance(data["total_worked_minutes"], int)
    assert data["status"] in ("DRAFT", "SUBMITTED", "APPROVED", "LOCKED")


def assert_pay_run(data: dict):
    _assert_common_fields(data)
    assert data["employer_id"]
    assert isinstance(data["period_start"], str)
    assert isinstance(data["period_end"], str)
    assert isinstance(data["pay_date"], str)
    assert data["status"] in ("OPEN", "CALCULATED", "FINALIZED")
    assert data["recalc_status"] in ("CURRENT", "STALE")
    assert isinstance(data["total_gross_cents"], int)
    assert isinstance(data["total_net_cents"], int)
    assert isinstance(data["total_employer_tax_cents"], int)


def assert_paycheck(data: dict):
    _assert_common_fields(data)
    assert data["pay_run_id"]
    assert data["worker_id"]
    assert data["basis"] in ("GUARANTEE_FALLBACK", "TIMESHEET")
    assert isinstance(data["basis_stale"], bool)
    assert data["pay_method"] in ("HOURLY", "GUARANTEED_SALARY_FWW")
    assert isinstance(data["regular_minutes"], int)
    assert isinstance(data["overtime_minutes"], int)
    assert isinstance(data["double_minutes"], int)
    assert isinstance(data["guarantee_top_up_minutes"], int)
    assert isinstance(data["provisional_gross_cents"], int)
    assert isinstance(data["gross_cents"], int)
    assert isinstance(data["withholding_lines"], list)
    assert isinstance(data["employer_tax_lines"], list)
    assert isinstance(data["net_pay_cents"], int)
    assert data["status"] in ("CALCULATED", "ISSUED", "VOIDED")
    assert data["deposit_status"] in ("PENDING", "SENT", "REVERSAL_PENDING")
    assert data["stub_status"] in ("PENDING", "DELIVERED", "NOT_REQUIRED")


def assert_leave_request(data: dict):
    _assert_common_fields(data)
    assert data["worker_id"]
    assert isinstance(data["start_date"], str)
    assert isinstance(data["end_date"], str)
    assert isinstance(data["requested_minutes"], int)
    assert data["status"] in ("REQUESTED", "APPROVED", "DENIED", "CANCELLED")


def assert_tax_liability_account(data: dict):
    _assert_common_fields(data)
    assert data["employer_id"]
    assert isinstance(data["tax_year"], int)
    assert data["tax_type"] in ("FICA_EE", "FICA_ER", "FUTA_ER", "SIT_EE", "SUTA_ER")
    assert isinstance(data["accrued_cents"], int)
    assert isinstance(data["projected_annual_cents"], int)
    assert isinstance(data["deposited_cents"], int)
    assert isinstance(data["penalty_cents"], int)
    assert isinstance(data["balance_cents"], int)


def assert_tax_deposit(data: dict):
    _assert_append_only_fields(data)
    assert data["employer_id"]
    assert isinstance(data["tax_year"], int)
    assert data["quarter"] in (1, 2, 3, 4)
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["remitted_on"], str)
    assert isinstance(data["required_amount_cents"], int)
    assert isinstance(data["due_date"], str)
    assert isinstance(data["late_days"], int)
    assert isinstance(data["penalty_cents"], int)
    assert isinstance(data["unapplied_cents"], int)


def assert_quarterly_filing(data: dict):
    _assert_common_fields(data)
    assert data["employer_id"]
    assert isinstance(data["tax_year"], int)
    assert data["quarter"] in (1, 2, 3, 4)
    assert data["status"] in ("OPEN", "PREPARED", "SUBMITTED", "REJECTED", "ACCEPTED")
    assert isinstance(data["total_cash_wages_cents"], int)
    assert isinstance(data["futa_applies"], bool)
    assert isinstance(data["futa_due_cents"], int)
    assert isinstance(data["suta_due_cents"], int)
    assert isinstance(data["estimated_federal_payment_cents"], int)


def assert_workers_comp_policy(data: dict):
    _assert_common_fields(data)
    assert data["employer_id"]
    assert isinstance(data["state_code"], str)
    assert isinstance(data["policy_number"], str)
    assert isinstance(data["coverage_start"], str)
    assert isinstance(data["coverage_end"], str)
    assert data["status"] in ("QUOTED", "BOUND", "ACTIVE", "LAPSED", "EXPIRED")


def assert_year_end_package(data: dict):
    _assert_common_fields(data)
    assert data["employer_id"]
    assert isinstance(data["tax_year"], int)
    assert data["status"] in ("DRAFT", "FINALIZED")


def line_amount(lines: List[dict], tax_type: str) -> Optional[int]:
    """Return the amount_cents of the line with the given tax_type, or None if omitted."""
    for line in lines:
        if line.get("tax_type") == tax_type:
            return line.get("amount_cents")
    return None


def assert_worker_leave_invariants(worker: dict):
    """available == accrued - used must hold on every worker read."""
    assert worker["available_leave_minutes"] == (
        worker["accrued_leave_minutes"] - worker["used_leave_minutes"]
    ), (
        f"available_leave_minutes {worker['available_leave_minutes']} != "
        f"accrued {worker['accrued_leave_minutes']} - used {worker['used_leave_minutes']}"
    )


def assert_account_balance_invariant(account: dict):
    """balance_cents == accrued_cents + penalty_cents - deposited_cents."""
    assert account["balance_cents"] == (
        account["accrued_cents"] + account["penalty_cents"] - account["deposited_cents"]
    ), (
        f"balance_cents {account['balance_cents']} != accrued {account['accrued_cents']} "
        f"+ penalty {account['penalty_cents']} - deposited {account['deposited_cents']}"
    )
