"""Entity assertions and domain invariant checkers.

Field names are exactly as the PRD declares them; all monetary fields are
integer cents.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """Common fields every entity in this domain carries: id, created_at,
    updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_client(data: dict):
    _assert_common(data)
    assert isinstance(data["legal_name"], str) and len(data["legal_name"]) > 0
    assert data["onboarding_status"] in [
        "LEAD", "KICKOFF_SCHEDULED", "LEDGER_SETUP", "ONBOARDED"]
    assert data["engagement_status"] in [
        "PROSPECT", "ACTIVE", "PAUSED", "OFFBOARDED"]
    assert data["retainer_tier"] in ["ESSENTIALS", "GROWTH", "CFO"]
    assert isinstance(data["included_txn_count"], int)
    assert isinstance(data["catchup_active"], bool)
    assert isinstance(data["covenant_floor_cents"], int)
    assert isinstance(data["open_close_count"], int)


def assert_ledger_account(data: dict):
    _assert_common(data)
    assert isinstance(data["account_code"], str)
    assert data["account_type"] in ["ASSET", "LIABILITY", "EQUITY", "REVENUE", "EXPENSE"]
    assert data["status"] in ["ACTIVE", "ARCHIVED"]


def assert_catchup_project(data: dict):
    _assert_common(data)
    assert data["status"] in [
        "DRAFT", "SCOPED", "IN_PROGRESS", "CLIENT_REVIEW",
        "REVISION", "COMPLETED", "CANCELLED"]
    assert isinstance(data["revision_rounds"], int)
    assert isinstance(data["quoted_fee_cents"], int)


def assert_monthly_close(data: dict):
    _assert_common(data)
    assert data["status"] in [
        "OPEN", "IN_PROGRESS", "READY_FOR_REVIEW", "FINALIZED", "REOPENED"]
    assert data["review_status"] in [
        "NOT_STARTED", "UNDER_REVIEW", "APPROVED", "CHANGES_REQUESTED"]
    assert isinstance(data["period_year"], int)
    assert 1 <= data["period_month"] <= 12
    assert isinstance(data["completion_pct"], (int, float))
    assert isinstance(data["provisional_completion_pct"], (int, float))


def assert_close_task(data: dict):
    _assert_common(data)
    assert data["status"] in ["PENDING", "IN_REVIEW", "DONE", "WAIVED", "BLOCKED"]
    assert isinstance(data["weight"], int) and data["weight"] >= 1


def assert_ar_invoice(data: dict):
    _assert_common(data)
    assert data["status"] in ["OPEN", "DISPUTED", "PAID", "WRITTEN_OFF"]
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["paid_amount_cents"], int)


def assert_ap_bill(data: dict):
    _assert_common(data)
    assert data["status"] in ["ENTERED", "APPROVED", "SCHEDULED", "PAID", "VOID"]
    assert isinstance(data["amount_cents"], int)


def assert_payroll_run(data: dict):
    _assert_common(data)
    assert data["status"] in ["DRAFT", "ALLOCATED", "POSTED", "REVERSED"]
    assert isinstance(data["total_employer_cost_cents"], int)


def assert_payroll_allocation(data: dict):
    _assert_common(data)
    assert isinstance(data["dept_gross_cents"], int)
    assert isinstance(data["allocated_cents"], int)


def assert_cash_flow_forecast(data: dict):
    _assert_common(data)
    assert data["status"] in ["DRAFT", "APPROVED", "SUPERSEDED"]
    assert isinstance(data["opening_balance_cents"], int)
    assert isinstance(data["ending_balance_cents"], int)
    assert isinstance(data["min_projected_balance_cents"], int)


def assert_forecast_line(data: dict):
    _assert_common(data)
    assert data["direction"] in ["INFLOW", "OUTFLOW"]
    assert isinstance(data["amount_cents"], int)


def assert_tax_handoff(data: dict):
    _assert_common(data)
    assert data["status"] in [
        "PREPARING", "BOOKS_REVIEW", "ADVISORY_REVIEW", "READY", "DELIVERED", "RETURNED"]
    assert isinstance(data["books_signoff"], bool)
    assert isinstance(data["advisory_signoff"], bool)


def assert_retainer_invoice(data: dict):
    _assert_common(data)
    assert data["status"] in ["ISSUED", "PAID", "VOID"]
    assert isinstance(data["base_fee_cents"], int)
    assert isinstance(data["overage_cents"], int)
    assert isinstance(data["surcharge_cents"], int)
    assert isinstance(data["total_cents"], int)


def assert_retainer_invoice_total_consistent(data: dict):
    """total_cents is the sum of base_fee_cents, overage_cents, surcharge_cents
    (PRD §3.8)."""
    assert data["total_cents"] == (
        data["base_fee_cents"] + data["overage_cents"] + data["surcharge_cents"]
    ), "total_cents must equal base_fee_cents + overage_cents + surcharge_cents"
