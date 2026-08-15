"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data, entity_name):
    assert is_valid_uuid(str(data.get("id", ""))), \
        f"{entity_name}.id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(str(data.get("created_at", ""))), \
        f"{entity_name}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(str(data.get("updated_at", ""))), \
        f"{entity_name}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"{entity_name}.version must be a positive int, " \
        f"got {data.get('version')!r}"


def _assert_append_only_fields(data, entity_name):
    """RevenueLedgerEntry and PeriodClose carry only id + created_at."""
    assert is_valid_uuid(str(data.get("id", ""))) or (
        entity_name == "PeriodClose" and isinstance(data.get("id"), str)
    ), f"{entity_name}.id must be present"
    assert is_iso8601_timestamp(str(data.get("created_at", ""))), \
        f"{entity_name}.created_at must be ISO 8601"
    assert "updated_at" not in data, \
        f"{entity_name} must not expose updated_at"
    assert "version" not in data, \
        f"{entity_name} must not expose version"


def assert_security(data: dict):
    _assert_common_fields(data, "Security")
    assert isinstance(data.get("symbol"), str) and len(data["symbol"]) > 0
    assert data.get("asset_class") in ("EQUITY", "GOV_BOND", "CORP_BOND")
    assert isinstance(data.get("price_cents"), int)
    assert data.get("haircut_bps") in (200, 600, 1000)
    assert data.get("status") in ("LENDABLE", "HALTED")


def assert_beneficial_owner(data: dict):
    _assert_common_fields(data, "BeneficialOwner")
    assert isinstance(data.get("display_name"), str)
    assert isinstance(data.get("revenue_share_bps"), int)
    assert isinstance(data.get("indemnification_opt_in"), bool)
    assert data.get("status") in ("ACTIVE", "SUSPENDED", "OFFBOARDED")


def assert_borrower(data: dict):
    _assert_common_fields(data, "Borrower")
    assert isinstance(data.get("display_name"), str)
    assert isinstance(data.get("credit_limit_cents"), int)
    assert isinstance(data.get("effective_limit_cents"), int)
    assert isinstance(data.get("utilization_cents"), int)
    assert isinstance(data.get("utilization_bps"), int)
    assert data.get("status") in ("ACTIVE", "SUSPENDED", "DEFAULTED")


def assert_lendable_position(data: dict):
    _assert_common_fields(data, "LendablePosition")
    assert isinstance(data.get("owner_id"), str)
    assert isinstance(data.get("security_id"), str)
    assert isinstance(data.get("quantity_total"), int)
    assert data["quantity_total"] > 0
    assert isinstance(data.get("min_fee_bps"), int)
    assert isinstance(data.get("quantity_reserved"), int)
    assert isinstance(data.get("quantity_on_loan"), int)
    assert isinstance(data.get("quantity_available"), int)
    assert data.get("status") in ("OPEN", "SUSPENDED")


def assert_borrow_request(data: dict):
    _assert_common_fields(data, "BorrowRequest")
    assert isinstance(data.get("borrower_id"), str)
    assert isinstance(data.get("security_id"), str)
    assert isinstance(data.get("quantity"), int) and data["quantity"] > 0
    assert isinstance(data.get("max_rate_bps"), int)
    assert data.get("collateral_type") in ("CASH", "SECURITIES")
    assert isinstance(data.get("needed_by_date"), str)
    assert data.get("status") in (
        "SUBMITTED", "MATCHED", "LOANED", "CANCELLED", "EXPIRED")


def assert_loan(data: dict):
    _assert_common_fields(data, "Loan")
    assert isinstance(data.get("position_id"), str)
    assert isinstance(data.get("owner_id"), str)
    assert isinstance(data.get("borrower_id"), str)
    assert isinstance(data.get("security_id"), str)
    assert isinstance(data.get("quantity"), int) and data["quantity"] > 0
    assert isinstance(data.get("outstanding_quantity"), int)
    assert data.get("collateral_type") in ("CASH", "SECURITIES")
    assert isinstance(data.get("rate_bps"), int)
    assert data.get("status") in (
        "PROPOSED", "COUNTERED", "BOOKED", "RECALLED", "SETTLED",
        "DEFAULTED", "CANCELLED")
    assert data.get("margin_status") in ("CURRENT", "CALL_OPEN")


def assert_collateral_pledge(data: dict):
    _assert_common_fields(data, "CollateralPledge")
    assert isinstance(data.get("loan_id"), str)
    assert data.get("pledge_type") in ("CASH", "SECURITY")
    assert isinstance(data.get("marked_value_cents"), int)
    assert data.get("status") in (
        "ACTIVE", "RELEASED", "SUBSTITUTED", "SEIZED")


def assert_margin_call(data: dict):
    _assert_common_fields(data, "MarginCall")
    assert isinstance(data.get("loan_id"), str)
    assert isinstance(data.get("amount_due_cents"), int)
    assert isinstance(data.get("issued_date"), str)
    assert isinstance(data.get("due_date"), str)
    assert data.get("status") in ("OPEN", "CURED", "ESCALATED", "DEFAULTED")


def assert_recall(data: dict):
    _assert_common_fields(data, "Recall")
    assert isinstance(data.get("loan_id"), str)
    assert isinstance(data.get("owner_id"), str)
    assert isinstance(data.get("quantity"), int) and data["quantity"] > 0
    assert data.get("reason") in (
        "SALE", "CORPORATE_ACTION", "VOTE", "PORTFOLIO_REBALANCE")
    assert isinstance(data.get("issue_date"), str)
    assert isinstance(data.get("deadline_date"), str)
    assert isinstance(data.get("delivered_quantity"), int)
    assert isinstance(data.get("extended_once"), bool)
    assert isinstance(data.get("fail_fee_cents"), int)
    assert data.get("status") in (
        "ISSUED", "EXTENDED", "COMPLETED", "FAILED", "BOUGHT_IN",
        "CANCELLED")


def assert_reinvestment_tranche(data: dict):
    _assert_common_fields(data, "ReinvestmentTranche")
    assert isinstance(data.get("loan_id"), str)
    assert data.get("instrument_type") in ("MMF", "REPO", "TIME_DEPOSIT")
    assert isinstance(data.get("principal_cents"), int)
    assert data["principal_cents"] > 0
    assert isinstance(data.get("stated_yield_bps"), int)
    assert isinstance(data.get("current_nav_cents"), int)
    assert data.get("status") in ("INVESTED", "UNWOUND")


def assert_ledger_entry(data: dict):
    """Append-only ledger entry: id + created_at only, no version."""
    _assert_append_only_fields(data, "RevenueLedgerEntry")
    assert isinstance(data.get("owner_id"), str)
    assert data.get("entry_type") in (
        "FEE_ACCRUAL_PROVISIONAL", "FEE_ACCRUAL_FINAL", "FEE_TRUE_UP",
        "REBATE_ACCRUAL", "REINVEST_INCOME_PROVISIONAL",
        "REINVEST_INCOME_FINAL", "FAIL_FEE", "BUY_IN_CHARGE",
        "COLLATERAL_SEIZURE", "INDEMNITY_CREDIT", "REVENUE_SPLIT_OWNER",
        "REVENUE_SPLIT_AGENT")
    assert isinstance(data.get("amount_cents"), int)
    assert isinstance(data.get("accrual_date"), str)
    assert isinstance(data.get("period"), str)
    assert "note" in data


def assert_limit_override(data: dict):
    _assert_common_fields(data, "LimitOverride")
    assert isinstance(data.get("borrower_id"), str)
    assert isinstance(data.get("new_limit_cents"), int)
    assert isinstance(data.get("effective_from"), str)
    assert isinstance(data.get("expires_at"), str)
    assert data.get("status") in (
        "REQUESTED", "APPROVED", "REJECTED", "EXPIRED")


def assert_regulatory_report(data: dict):
    _assert_common_fields(data, "RegulatoryReport")
    assert isinstance(data.get("period"), str)
    assert data.get("report_type") in (
        "MONTHLY_LOAN_ACTIVITY", "FAILS_AND_BUYINS", "COLLATERAL_SUMMARY")
    assert data.get("status") in ("DRAFT", "FINALIZED", "FILED")


def assert_period_close(data: dict):
    """Append-only close record: id + created_at only, no version."""
    _assert_append_only_fields(data, "PeriodClose")
    assert isinstance(data.get("period"), str)
    assert isinstance(data.get("loans_finalized_count"), int)
    assert data.get("status") == "CLOSED"


def assert_position_bucket_conservation(position: dict):
    """quantity_total == reserved + on_loan + available at all times."""
    total = position["quantity_total"]
    r = position["quantity_reserved"]
    o = position["quantity_on_loan"]
    a = position["quantity_available"]
    assert r + o + a == total, (
        f"Bucket conservation violated: {r} + {o} + {a} != {total}")
