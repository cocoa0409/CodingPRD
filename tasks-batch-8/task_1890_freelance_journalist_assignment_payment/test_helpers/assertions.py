"""Entity assertions and domain invariant checkers (PRD sections 2.2-2.4, 3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict, entity: str):
    """PRD section 2.4: every persisted entity carries id, created_at,
    updated_at and an integer version (LedgerEntry excepted)."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{entity}.created_at must be ISO 8601 UTC"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"{entity}.updated_at must be ISO 8601 UTC"
    assert isinstance(data.get("version"), int), \
        f"{entity}.version must be an integer"


def assert_contributor(data: dict):
    _assert_common_fields(data, "Contributor")
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert data["tax_residency"] in ("DOMESTIC_US", "FOREIGN")
    assert data["status"] in ("ACTIVE", "SUSPENDED", "TERMINATED")
    assert isinstance(data["ytd_gross_cents"], int)
    assert isinstance(data["reportable_threshold_crossed"], bool)
    assert isinstance(data["backup_withholding_flag"], bool)


def assert_rate_agreement(data: dict):
    _assert_common_fields(data, "RateAgreement")
    assert data["pricing_mode"] in ("PER_WORD", "FLAT")
    assert data["rights_default"] in ("FIRST", "ONE_TIME", "ALL")
    assert data["status"] in ("ACTIVE", "SUPERSEDED", "REVOKED")
    assert 1 <= data["kill_fee_pct_num"] <= 100


def assert_assignment(data: dict):
    _assert_common_fields(data, "Assignment")
    assert data["editorial_status"] in (
        "DRAFT", "OFFERED", "ACCEPTED", "IN_PROGRESS", "SUBMITTED",
        "UNDER_VERIFICATION", "ACCEPTED_FOR_PUBLICATION", "KILLED",
        "REJECTED_AFTER_FLAG")
    assert data["payment_status"] in (
        "UNINVOICED", "INVOICED", "PAYABLE", "PAID", "VOID")
    assert isinstance(data["commissioned_word_count"], int)
    assert isinstance(data["agreed_fee_cents"], int)
    assert isinstance(data["verification_cleared"], bool)
    assert isinstance(data["late_flag"], bool)


def assert_expense_claim(data: dict):
    _assert_common_fields(data, "ExpenseClaim")
    assert data["category"] in ("TRAVEL", "MEALS", "EQUIPMENT", "OTHER")
    assert data["status"] in (
        "PRE_APPROVAL_REQUESTED", "APPROVED", "REJECTED", "SUBMITTED",
        "REIMBURSABLE", "DENIED", "PAID")
    assert isinstance(data["requested_cents"], int)


def assert_verification_report(data: dict):
    _assert_common_fields(data, "VerificationReport")
    assert data["checker_kind"] in ("PLAGIARISM", "AI_CONTENT")
    assert data["status"] in (
        "PENDING", "CLEARED", "FLAGGED", "CONFIRMED_VIOLATION", "DISMISSED")
    assert 0 <= data["similarity_score_bps"] <= 10000
    assert 0 <= data["ai_probability_bps"] <= 10000


def assert_rights_purchase(data: dict):
    _assert_common_fields(data, "RightsPurchase")
    assert data["rights_kind"] in ("FIRST", "ONE_TIME", "ALL")
    assert data["status"] in ("ACTIVE", "REVERTED")
    assert isinstance(data["reuse_count"], int)
    assert isinstance(data["reuse_fee_cents_total"], int)
    assert isinstance(data["buyout_uplift_cents"], int)


def assert_tax_document(data: dict):
    _assert_common_fields(data, "TaxDocument")
    assert data["doc_kind"] in ("W9", "W8BEN")
    assert data["status"] in ("SUBMITTED", "VERIFIED", "REJECTED", "EXPIRED")
    assert isinstance(data["tin_last4"], str) and len(data["tin_last4"]) == 4
    assert is_iso8601_timestamp(data.get("submitted_at", ""))
    assert is_iso8601_timestamp(data.get("expires_at", ""))


def assert_invoice(data: dict):
    _assert_common_fields(data, "Invoice")
    assert data["status"] in (
        "SUBMITTED", "VERIFIED", "APPROVED", "BATCHED", "PAID", "REJECTED",
        "VOID")
    assert isinstance(data["fee_claim_cents"], int)
    assert isinstance(data["expense_claim_cents"], int)


def assert_payment_batch(data: dict):
    _assert_common_fields(data, "PaymentBatch")
    assert data["status"] in ("OPEN", "LOCKED", "RELEASED", "CANCELLED")
    assert isinstance(data["total_gross_cents"], int)
    assert isinstance(data["total_withholding_cents"], int)
    assert isinstance(data["total_net_cents"], int)


def assert_ledger_entry(data: dict):
    """PRD section 2.4: LedgerEntry carries id and created_at only;
    updated_at and version are absent because postings are immutable."""
    assert is_valid_uuid(data.get("id", "")), "LedgerEntry.id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "LedgerEntry.created_at must be ISO 8601 UTC"
    assert "updated_at" not in data, "LedgerEntry must not carry updated_at"
    assert "version" not in data, "LedgerEntry must not carry version"
    assert data["entry_kind"] in (
        "FEE_CREDIT", "EXPENSE_CREDIT", "WITHHOLDING_DEBIT", "LATE_FEE_CREDIT",
        "REUSE_ROYALTY_CREDIT")
    assert isinstance(data["amount_cents"], int)
    assert is_iso8601_timestamp(data.get("posted_at", "")), \
        "LedgerEntry.posted_at must be ISO 8601 UTC"


def assert_invoice_money_invariants(invoice: dict):
    """Verified-invoice money identities (PRD section 3.8)."""
    assert invoice["gross_cents"] == (
        invoice["fee_claim_cents"] + invoice["expense_claim_cents"]), \
        "gross_cents must equal fee_claim_cents + expense_claim_cents"
    assert invoice["net_payable_cents"] == (
        invoice["gross_cents"] - invoice["withholding_cents"]), \
        "net_payable_cents must equal gross_cents - withholding_cents"
    assert invoice["withholding_cents"] >= 0
