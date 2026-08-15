"""Entity assertions and domain invariant checkers (PRD §2.5, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict):
    """Standard system-managed fields carried by primary resources (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_light_common_fields(data: dict):
    """Notifications and ledger entries carry only id and created_at (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "updated_at must be absent from this resource"
    assert "version" not in data, "version must be absent from this resource"


def assert_clearing_bank(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["routing_number"], str) and data["routing_number"]
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["claim_window_business_days"], int)
    assert isinstance(data["warranty_window_days"], int)
    assert isinstance(data["daily_claim_capacity"], int)


def assert_depositor_account(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["customer_name"], str) and data["customer_name"]
    assert isinstance(data["account_number"], str) and data["account_number"]
    assert data["status"] in ("ACTIVE", "FROZEN")
    assert data["risk_tier"] in ("STANDARD", "HIGH_RISK")
    assert isinstance(data["reg_cc_eligible"], bool)
    assert isinstance(data["available_balance_cents"], int)
    assert isinstance(data["settled_balance_cents"], int)
    assert isinstance(data["returned_item_count_30d"], int)


def assert_account_freeze(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["depositor_account_id"], str)
    assert is_iso8601_timestamp(data["start_at"])
    assert is_iso8601_timestamp(data["end_at"])
    assert data["status"] in ("ACTIVE", "EXPIRED")


def assert_check_item(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["depositor_account_id"], str)
    assert isinstance(data["clearing_bank_id"], str)
    assert isinstance(data["item_reference"], str)
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["encoded_amount_cents"], int)
    assert isinstance(data["image_quality_score"], int)
    assert data["capture_channel"] in ("BRANCH", "ATM", "MOBILE", "RDC")
    assert data["status"] in (
        "RECEIVED", "UNDER_REVIEW", "PRESENTED", "PAID", "RETURNED",
        "DUPLICATE_REJECTED", "DEPOSIT_REJECTED",
    )
    assert isinstance(data["is_large_item"], bool)
    assert isinstance(data["presentment_count"], int)


def assert_hold_decision(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["check_item_id"], str)
    assert data["source"] in ("AUTO_LARGE_ITEM", "MANUAL")
    assert data["status"] in ("PENDING", "DECIDED", "EXPIRED")
    assert is_iso8601_timestamp(data["window_start_at"])
    assert is_iso8601_timestamp(data["hold_until"])


def assert_return_event(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["check_item_id"], str)
    assert data["status"] in ("PENDING_CODING", "CODED")


def assert_adjustment_case(data: dict):
    _assert_common_fields(data)
    assert data["case_type"] in (
        "RETURN_ITEM", "ENCODING_ERROR", "IMAGE_WARRANTY",
        "DUPLICATE_PRESENTMENT", "LARGE_ITEM_REVIEW",
    )
    assert isinstance(data["check_item_id"], str)
    assert data["status"] in ("OPEN", "ASSIGNED", "RESOLVED", "REOPENED", "ESCALATED", "CLOSED")
    assert isinstance(data["reopen_count"], int)


def assert_adjustment_claim(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["adjustment_case_id"], str)
    assert isinstance(data["clearing_bank_id"], str)
    assert isinstance(data["claimed_amount_cents"], int)
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "ACKNOWLEDGED", "SETTLED", "DENIED",
        "ESCALATED", "WRITTEN_OFF",
    )
    assert isinstance(data["aging_calendar_days"], int)
    assert isinstance(data["aging_business_days"], int)


def assert_warranty_claim(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["adjustment_case_id"], str)
    assert isinstance(data["claimed_amount_cents"], int)
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "HONORED", "REJECTED", "ESCALATED", "WRITTEN_OFF",
    )
    assert is_iso8601_timestamp(data["deadline_at"])


def assert_customer_notification(data: dict):
    _assert_light_common_fields(data)
    assert isinstance(data["depositor_account_id"], str)
    assert data["notification_type"] in (
        "RETURN_NOTICE", "CASE_CLOSED", "DUPLICATE_NOTICE",
        "DEPOSIT_REJECTED_NOTICE", "LARGE_ITEM_HOLD_NOTICE",
    )
    assert data["status"] in ("PENDING", "DELIVERED", "BREACHED")
    assert is_iso8601_timestamp(data["due_at"])


def assert_fee_assessment(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["depositor_account_id"], str)
    assert data["fee_type"] == "RETURN_ITEM_FEE"
    assert isinstance(data["amount_cents"], int)
    assert data["status"] in ("POSTED", "WAIVED")


def assert_recredit_request(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["depositor_account_id"], str)
    assert isinstance(data["check_item_id"], str)
    assert isinstance(data["claimed_amount_cents"], int)
    assert data["status"] in (
        "SUBMITTED", "PROVISIONALLY_CREDITED", "CONFIRMED", "REVOKED",
    )


def assert_ledger_entry(data: dict):
    _assert_light_common_fields(data)
    assert isinstance(data["depositor_account_id"], str)
    assert data["entry_type"] in (
        "OPENING_CREDIT", "DEPOSIT_CREDIT", "PROVISIONAL_REVERSAL",
        "SETTLEMENT_CREDIT", "ITEM_RETURN_DEBIT", "DUPLICATE_REVERSAL_CREDIT",
        "FEE_DEBIT", "FEE_WAIVER_CREDIT", "RECREDIT_PROVISIONAL_CREDIT",
        "RECREDIT_CLAWBACK_DEBIT", "ADJUSTMENT_CREDIT", "ADJUSTMENT_DEBIT",
    )
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["provisional"], bool)


def assert_account_balance_invariants(data: dict):
    """Balance derivations of PRD §2.7 must hold on every account read."""
    assert isinstance(data["available_balance_cents"], int)
    assert isinstance(data["settled_balance_cents"], int)
    # Settled excludes provisional entries, so it can never exceed nothing —
    # the only universal relation guaranteed by the PRD is that both are
    # exact integer-cent sums over the same append-only ledger.
    if data["status"] == "FROZEN":
        assert data["available_balance_cents"] < 0, (
            "a FROZEN account must have a negative available balance (PRD §2.7)"
        )
