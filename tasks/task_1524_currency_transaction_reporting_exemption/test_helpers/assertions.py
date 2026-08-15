"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
)


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be int >= 1, got {data.get('version')!r}"
    )


def assert_branch(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["branch_code"], str) and data["branch_code"]
    assert data["status"] in ("ACTIVE", "INACTIVE")


def assert_customer(data: dict):
    _assert_common(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert data["customer_type"] in (
        "INDIVIDUAL", "BUSINESS_NONLISTED", "BUSINESS_LISTED",
        "BANK", "GOVERNMENT_AGENCY", "PAYROLL_CUSTOMER",
    )
    assert data["status"] in ("ACTIVE", "SUSPENDED", "CLOSED")
    assert isinstance(data.get("structuring_referral_count"), int)


def assert_cash_transaction(data: dict):
    _assert_common(data)
    assert data["direction"] in ("CASH_IN", "CASH_OUT")
    assert isinstance(data["amount_cents"], int)
    assert data["status"] in ("POSTED", "VOIDED")
    assert isinstance(data["business_date"], str)


def assert_instrument_sale(data: dict):
    _assert_common(data)
    assert data["instrument_type"] in ("CASHIERS_CHECK", "MONEY_ORDER", "TRAVELERS_CHECK")
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["fee_cents"], int)
    assert isinstance(data["record_required"], bool)
    assert data["status"] in ("RECORDED", "VOIDED")


def assert_daily_aggregation(data: dict):
    _assert_common(data)
    for k in (
        "total_cash_in_cents", "total_cash_out_cents",
        "transaction_count", "instrument_sale_count", "instrument_fee_total_cents",
    ):
        assert isinstance(data[k], int), f"{k} must be int"
    for k in ("raw_reportable_in", "raw_reportable_out", "covered_in", "covered_out", "ctr_required"):
        assert isinstance(data[k], bool), f"{k} must be bool"


def assert_ctr(data: dict):
    _assert_common(data)
    assert data["filing_type"] in ("INITIAL", "CORRECTION")
    assert data["status"] in (
        "DRAFT", "VALIDATED", "FILED", "ACKNOWLEDGED",
        "AMENDMENT_REQUIRED", "SUPERSEDED", "VOIDED",
    )
    assert isinstance(data["snapshot_cash_in_cents"], int)
    assert isinstance(data["snapshot_cash_out_cents"], int)
    assert isinstance(data["due_date_efile"], str)
    assert isinstance(data["due_date_paper"], str)


def assert_exemption_designation(data: dict):
    _assert_common(data)
    assert data["phase"] in ("PHASE_I", "PHASE_II")
    assert data["status"] in (
        "PENDING_REVIEW", "ACTIVE", "REVIEW_DUE", "DENIED", "REVOKED",
    )
    assert isinstance(data["covers_cash_in"], bool)
    assert isinstance(data["covers_cash_out"], bool)


def assert_structuring_alert(data: dict):
    _assert_common(data)
    assert data["detection_source"] in ("AUTO", "MANUAL")
    assert data["status"] in ("OPEN", "UNDER_REVIEW", "REFERRED", "DISMISSED")
    assert isinstance(data["window_start_date"], str)
    assert isinstance(data["window_end_date"], str)
    assert isinstance(data["risk_score"], int)


def assert_examination_case(data: dict):
    _assert_common(data)
    assert data["regulator"] in ("FINCEN", "OCC", "FDIC", "STATE")
    assert isinstance(data["case_number"], str) and data["case_number"]
    assert data["status"] in ("OPEN", "FIELDWORK", "FINDINGS_ISSUED", "CLOSED")


def assert_examination_finding(data: dict):
    _assert_common(data)
    assert data["severity"] in ("OBSERVATION", "DEFICIENCY", "VIOLATION")
    assert data["target_type"] in (
        "CTR", "EXEMPTION_DESIGNATION", "STRUCTURING_ALERT",
        "MONETARY_INSTRUMENT_SALE", "CASH_TRANSACTION",
    )
    assert data["status"] in ("OPEN", "REMEDIATED", "VERIFIED")


def assert_audit_event(data: dict):
    """AuditEvent is append-only: id + created_at only; NO updated_at, NO version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert "updated_at" not in data, "AuditEvent must not carry updated_at"
    assert "version" not in data, "AuditEvent must not carry version"
    assert isinstance(data["sequence_no"], int) and data["sequence_no"] >= 1
    assert isinstance(data["prev_hash"], str) and len(data["prev_hash"]) == 64
    assert isinstance(data["event_hash"], str) and len(data["event_hash"]) == 64
