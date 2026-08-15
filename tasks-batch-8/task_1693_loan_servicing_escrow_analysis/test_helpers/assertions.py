"""Entity assertions and domain invariant checkers (PRD §2.4, §2.7)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict):
    """Every persisted resource except ledger entries (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID: {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601: {data.get('created_at')!r}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"updated_at must be ISO 8601: {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_loan(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["loan_number"], str) and data["loan_number"]
    assert isinstance(data["borrower_name"], str)
    assert isinstance(data["principal_balance_cents"], int)
    assert isinstance(data["monthly_pi_cents"], int)
    assert isinstance(data["escrow_required"], bool)
    assert isinstance(data["closing_date"], str)
    assert data["status"] in ("ONBOARDING", "ACTIVE", "PAID_OFF", "TRANSFERRED_OUT")


def assert_escrow_account(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("loan_id", ""))
    assert data["account_status"] in ("SETUP", "ACTIVE", "SUSPENDED", "CLOSED")
    assert data["hold_status"] in ("NONE", "COMPLIANCE_HOLD")
    assert isinstance(data["balance_cents"], int)
    assert isinstance(data["target_cushion_cents"], int)


def assert_ledger_entry(data: dict):
    """Append-only ledger entry: id + created_at only, no updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    assert data["entry_type"] in (
        "DEPOSIT", "DISBURSEMENT", "DISBURSEMENT_RETURN", "ADVANCE_ISSUED",
        "ADVANCE_RECOVERY", "SURPLUS_REFUND", "FORCE_PLACEMENT_CHARGE",
        "FORCE_PLACEMENT_REFUND", "ERROR_CORRECTION",
    )
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["effective_date"], str)
    assert isinstance(data["running_balance_cents"], int)
    assert isinstance(data["escrow_account_id"], str)
    assert isinstance(data["source_entity_type"], str)
    assert isinstance(data["source_entity_id"], str)


def assert_line_item(data: dict):
    _assert_common_fields(data)
    assert data["expense_type"] in (
        "PROPERTY_TAX", "HAZARD_INSURANCE", "FLOOD_INSURANCE", "PMI",
    )
    assert isinstance(data["expected_annual_amount_cents"], int)
    assert data["installments_per_year"] in (1, 2, 4, 12)
    assert data["status"] in ("ACTIVE", "REMOVED")


def assert_payee(data: dict):
    _assert_common_fields(data)
    assert data["payee_type"] in ("TAX_AUTHORITY", "INSURANCE_CARRIER", "PMI_PROVIDER")
    assert isinstance(data["legal_name"], str)
    assert isinstance(data["created_by_user_id"], str)
    assert data["verification_status"] in (
        "PENDING_VERIFICATION", "VERIFIED", "REJECTED", "SUSPENDED", "EXPIRED",
    )


def assert_disbursement(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["status"] in (
        "SCHEDULED", "BLOCKED", "RELEASED", "CLEARED", "RETURNED", "CANCELLED",
    )
    assert isinstance(data["scheduled_by_user_id"], str)
    assert isinstance(data["late_release"], bool)


def assert_insurance_policy(data: dict):
    _assert_common_fields(data)
    assert data["policy_type"] in ("HAZARD", "FLOOD")
    assert data["status"] in (
        "ACTIVE", "LAPSED", "NOTICE_1_SENT", "NOTICE_2_SENT", "FORCE_PLACED",
        "REFUNDED", "CANCELLED", "EXPIRED_CLOSED",
    )
    assert isinstance(data["annual_premium_cents"], int)


def assert_tax_record(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["parcel_number"], str)
    assert isinstance(data["tax_year"], int)
    assert isinstance(data["installment_sequence"], int)
    assert isinstance(data["amount_due_cents"], int)
    assert data["penalty_method"] in ("SIMPLE", "COMPOUND")
    assert data["status"] in (
        "MONITORING", "DUE_SOON", "DELINQUENT", "PENALTY_ACCRUING",
        "REDEMPTION_RISK", "PAID_CURRENT", "PAID_DELINQUENT",
    )
    assert isinstance(data["accrued_penalty_cents"], int)


def assert_analysis_cycle(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["analysis_year"], int)
    assert data["method"] in ("PROSPECTIVE", "LEDGER_ACTUAL")
    assert data["status"] in (
        "DRAFT", "COMPUTED", "STATEMENT_ISSUED", "EFFECTIVE", "REOPENED",
        "SUPERSEDED", "VOIDED",
    )
    assert isinstance(data["projection_start_date"], str)
    assert isinstance(data["window_end_date"], str)


def assert_notice(data: dict):
    _assert_common_fields(data)
    assert data["notice_type"] in ("PAYMENT_CHANGE", "SHORTAGE", "DEFICIENCY", "SURPLUS")
    assert isinstance(data["old_monthly_escrow_cents"], int)
    assert isinstance(data["new_monthly_escrow_cents"], int)
    assert isinstance(data["effective_date"], str)
    assert isinstance(data["send_by_date"], str)
    assert data["status"] in ("DRAFT", "SENT", "ACKNOWLEDGED", "APPLIED", "VOIDED")


def assert_advance(data: dict):
    _assert_common_fields(data)
    assert data["reason"] in (
        "DISBURSEMENT_SHORTFALL", "FORCE_PLACEMENT_PREMIUM", "MANUAL_CORRECTION",
    )
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["recovered_cents"], int)
    assert isinstance(data["written_off_cents"], int)
    assert isinstance(data["outstanding_cents"], int)
    assert data["status"] in ("OUTSTANDING", "RECOVERING", "RECOVERED", "WRITTEN_OFF")


def assert_error_case(data: dict):
    _assert_common_fields(data)
    assert data["error_type"] in (
        "DISBURSEMENT_FAILURE", "DISBURSEMENT_AMOUNT_ERROR",
        "UNTIMELY_DISBURSEMENT", "FORCE_PLACEMENT_ERROR", "ANALYSIS_ERROR",
        "PAYMENT_APPLICATION_ERROR", "OTHER_COVERED",
    )
    assert data["status"] in (
        "RECEIVED", "ACKNOWLEDGED", "INVESTIGATING", "EXTENDED",
        "RESOLVED_CORRECTED", "RESOLVED_NO_ERROR", "DISMISSED_NOT_COVERED",
    )
    assert isinstance(data["ack_deadline"], str)
    assert isinstance(data["resolution_deadline"], str)


def assert_balance_conservation(account: dict, ledger_entries: list):
    """PRD §2.7 ledger conservation invariant: balance equals the sum of
    amount_cents over every ledger entry posted to the account."""
    total = sum(e["amount_cents"] for e in ledger_entries)
    assert account["balance_cents"] == total, (
        f"balance_cents {account['balance_cents']} != ledger sum {total}"
    )


def assert_advance_decomposition(advance: dict):
    """PRD §3.4 advance decomposition invariant:
    outstanding == amount - recovered - written_off."""
    expected = (advance["amount_cents"] - advance["recovered_cents"]
                - advance["written_off_cents"])
    assert advance["outstanding_cents"] == expected, (
        f"outstanding_cents {advance['outstanding_cents']} != "
        f"{advance['amount_cents']} - {advance['recovered_cents']} - "
        f"{advance['written_off_cents']}"
    )
