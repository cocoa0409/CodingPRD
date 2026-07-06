"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_client(data: dict):
    _assert_common(data)
    assert isinstance(data["legal_name"], str) and len(data["legal_name"]) > 0
    assert data["entity_type"] in ["SOLE_PROP", "PARTNERSHIP", "S_CORP", "C_CORP", "LLC"]
    assert data["accounting_basis"] in ["CASH", "ACCRUAL"]
    assert data["status"] in ["ACTIVE", "ARCHIVED"]


def assert_engagement(data: dict):
    _assert_common(data)
    assert data["workflow_status"] in [
        "DRAFT", "SCOPING", "RECONSTRUCTION", "RECONCILIATION",
        "TAX_HANDOFF", "COMPLETED", "CANCELLED",
    ]
    assert data["billing_status"] in ["UNBILLED", "QUOTED", "PHASED", "SETTLED"]
    assert isinstance(data["scope_locked"], bool)
    assert isinstance(data["estimated_txn_volume"], int)
    assert isinstance(data["reconciled_account_count"], int)
    assert isinstance(data["total_account_count"], int)
    assert isinstance(data["open_blocking_exception_count"], int)
    assert isinstance(data["readiness_score"], int)
    assert 0 <= data["readiness_score"] <= 100, "readiness_score must be in [0, 100]"
    assert data["recon_status"] in ["PENDING", "IN_BALANCE", "OUT_OF_BALANCE"]


def assert_scope_estimate(data: dict):
    _assert_common(data)
    assert isinstance(data["monthly_txn_rate"], int)
    assert isinstance(data["txn_volume_estimate"], int)
    assert data["status"] in ["PROPOSED", "ACCEPTED", "SUPERSEDED"]


def assert_account(data: dict):
    _assert_common(data)
    assert isinstance(data["account_code"], str) and len(data["account_code"]) > 0
    assert data["account_type"] in ["ASSET", "LIABILITY", "EQUITY", "INCOME", "EXPENSE"]
    assert data["normal_side"] in ["DEBIT", "CREDIT"]
    assert isinstance(data["is_bank_account"], bool)
    assert isinstance(data["book_balance_cents"], int)
    assert data["status"] in ["DRAFT", "CATEGORIZED", "RECONCILED", "EXCLUDED"]


def assert_entry(data: dict):
    _assert_common(data)
    assert data["side"] in ["DEBIT", "CREDIT"]
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["cash_settled"], bool)
    assert data["status"] in ["DRAFT", "POSTED", "REVERSED"]


def assert_statement(data: dict):
    _assert_common(data)
    assert isinstance(data["ending_balance_cents"], int)
    assert data["status"] in ["IMPORTED", "RECONCILING", "RECONCILED"]


def assert_reconciliation_item(data: dict):
    _assert_common(data)
    assert data["match_kind"] in ["EXACT", "TOLERANCE"]
    assert data["status"] in ["MATCHED", "DISPUTED", "UNMATCHED"]


def assert_phase(data: dict):
    _assert_common(data)
    assert isinstance(data["phase_index"], int)
    assert isinstance(data["weight_bp"], int)
    assert data["status"] in ["PLANNED", "BILLABLE", "INVOICED", "PAID"]


def assert_phase_invoice(data: dict):
    _assert_common(data)
    assert isinstance(data["amount_cents"], int)
    assert data["status"] in ["ISSUED", "PAID", "VOID"]


def assert_tax_package(data: dict):
    _assert_common(data)
    assert data["basis"] in ["CASH", "ACCRUAL"]
    assert isinstance(data["net_book_income_cents"], int)
    assert data["status"] in ["BUILT", "HANDED_OFF", "AMENDED"]


def assert_service_plan(data: dict):
    _assert_common(data)
    assert isinstance(data["monthly_fee_cents"], int)
    assert data["status"] in ["PENDING", "ACTIVE", "CANCELLED"]


def assert_exception(data: dict):
    _assert_common(data)
    assert data["kind"] in ["MISSING_DOC", "UNCATEGORIZED", "UNRECONCILED_DIFF", "DUPLICATE"]
    assert data["severity"] in ["NORMAL", "BLOCKING"]
    assert data["status"] in ["OPEN", "WAITING_DOCS", "RESOLVED", "WAIVED"]
