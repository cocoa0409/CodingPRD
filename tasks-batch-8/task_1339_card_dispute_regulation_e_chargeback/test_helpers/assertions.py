"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


_COMMON_STATUSES = {}


def _assert_common_fields(data: dict):
    """Primary resources carry id, created_at, updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_immutable_fields(data: dict):
    """Notifications and ledger entries carry only id + created_at."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert "updated_at" not in data, "immutable records must not expose updated_at"
    assert "version" not in data, "immutable records must not expose version"


def assert_card_account(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["cardholder_name"], str) and data["cardholder_name"]
    assert isinstance(data["balance_cents"], int)
    assert isinstance(data["provisional_outstanding_cents"], int)
    assert data["provisional_outstanding_cents"] >= 0
    assert data["status"] in ("ACTIVE", "RESTRICTED")
    assert is_iso8601_timestamp(data.get("opened_at", ""))


def assert_card_transaction(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("card_account_id", ""))
    assert isinstance(data["merchant_name"], str) and data["merchant_name"]
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["transaction_type"] in (
        "POS_PIN", "POS_SIGNATURE", "ATM_WITHDRAWAL", "ECOMMERCE", "RECURRING",
    )
    assert data["network"] in ("VISA", "MASTERCARD")
    assert is_iso8601_timestamp(data.get("posted_at", ""))
    assert data["status"] in (
        "POSTED", "DISPUTED", "CHARGED_BACK", "RE_PRESENTED", "SETTLED",
    )


def assert_dispute_case(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("card_transaction_id", ""))
    assert is_valid_uuid(data.get("card_account_id", ""))
    assert data["error_type"] in (
        "UNAUTHORIZED", "INCORRECT_AMOUNT", "DUPLICATE_CHARGE",
        "SERVICE_NOT_RECEIVED", "CANCELLED_RECURRING",
    )
    assert isinstance(data["claim_amount_cents"], int) and data["claim_amount_cents"] > 0
    assert isinstance(data["claimed_report_delay_days"], int)
    assert data["status"] in (
        "RECEIVED", "CLASSIFIED", "CHARGEBACK_FILED", "REPRESENTMENT_REVIEW",
        "REVERSAL_PENDING", "RESOLVED_CARDHOLDER_FAVOR",
        "RESOLVED_MERCHANT_FAVOR", "WITHDRAWN",
    )
    assert is_iso8601_timestamp(data.get("received_at", ""))


def assert_provisional_credit(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("dispute_case_id", ""))
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0
    assert data["status"] in ("GRANTED", "REVERSED", "REINSTATED", "FINALIZED")
    assert isinstance(data["granted_late"], bool)
    assert is_iso8601_timestamp(data.get("granted_at", ""))


def assert_chargeback(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("dispute_case_id", ""))
    assert is_valid_uuid(data.get("card_transaction_id", ""))
    assert data["reason_code"] in (
        "V10_4", "V10_5", "V13_1", "V13_3", "M4837", "M4870", "M4853", "M4855",
    )
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["network"] in ("VISA", "MASTERCARD")
    assert isinstance(data["fees_total_cents"], int) and data["fees_total_cents"] >= 0
    assert data["stage_entered"] in ("NONE", "PRE_COMPLIANCE", "ARBITRATION")
    assert data["status"] in (
        "FILED", "REPRESENTED", "SECOND_PRESENTED", "CLOSED_WON",
        "CLOSED_LOST", "CANCELLED", "WITHDRAWN",
    )


def assert_representment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("chargeback_id", ""))
    assert isinstance(data["merchant_ref"], str) and data["merchant_ref"]
    assert isinstance(data["evidence_documents"], list)
    assert len(data["evidence_documents"]) >= 1
    assert data["status"] in ("PENDING_REVIEW", "ACCEPTED", "REJECTED")


def assert_notification(data: dict):
    _assert_immutable_fields(data)
    assert is_valid_uuid(data.get("dispute_case_id", ""))
    assert data["type"] in (
        "PROVISIONAL_CREDIT_ADVICE", "REVERSAL_NOTICE", "RESOLUTION_LETTER",
    )
    assert is_iso8601_timestamp(data.get("sent_at", ""))


def assert_loss_recovery(data: dict):
    _assert_immutable_fields(data)
    assert is_valid_uuid(data.get("dispute_case_id", ""))
    assert data["type"] in ("LOSS_RECOGNIZED", "RECOVERY_RECEIVED")
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["source"] in ("AUTO", "MANUAL")


def assert_claim_conservation(case_data: dict):
    """cardholder_keeps_cents + final_liability_cents == claim_amount_cents."""
    total = case_data["cardholder_keeps_cents"] + case_data["final_liability_cents"]
    assert total == case_data["claim_amount_cents"], (
        f"claim conservation violated: keeps {case_data['cardholder_keeps_cents']} "
        f"+ liability {case_data['final_liability_cents']} "
        f"!= claim {case_data['claim_amount_cents']}"
    )


def assert_account_ledger_invariants(account_data: dict):
    """provisional_outstanding_cents never negative; balance is integer cents."""
    assert account_data["provisional_outstanding_cents"] >= 0
    assert isinstance(account_data["balance_cents"], int)
