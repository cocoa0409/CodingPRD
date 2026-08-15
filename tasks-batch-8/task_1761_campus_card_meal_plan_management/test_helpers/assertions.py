"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AccessDecision,
    AccessEvent,
    AccountStatus,
    AccountType,
    CardLifecycleStatus,
    ChangeRequestStatus,
    DenyReason,
    DisputeStatus,
    FrozenReason,
    GrantStatus,
    HolderStatus,
    HolderType,
    HousingStatus,
    LedgerEntryType,
    MealPlanStatus,
    MerchantCategory,
    MerchantStatus,
    PhotoStatus,
    ProrationMode,
    RefundStatus,
    RefundVariant,
    ReviewStatus,
    SecurityLevel,
    SettlementStatus,
    SuspendedReason,
    TenderType,
    TermStatus,
    TransactionStatus,
    VoidReason,
    EnrollmentStatus,
    CommissionMode,
)


def _enum_values(enum_cls):
    return [member.value for member in enum_cls]


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be an integer >= 1, got {data.get('version')!r}"


def _assert_event_fields(data: dict):
    # Immutable event records carry only id + created_at, never updated_at/version.
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert "updated_at" not in data, "immutable event records must not carry updated_at"
    assert "version" not in data, "immutable event records must not carry version"


def assert_card_holder(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["university_id"], str) and data["university_id"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert data["holder_type"] in _enum_values(HolderType)
    assert data["housing_status"] in _enum_values(HousingStatus)
    assert data["status"] in _enum_values(HolderStatus)
    assert isinstance(data["fraud_strike_count"], int)
    assert isinstance(data["fraud_flag"], bool)


def assert_campus_card(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["holder_id"])
    assert isinstance(data["card_number"], str) and len(data["card_number"]) > 0
    assert data["lifecycle_status"] in _enum_values(CardLifecycleStatus)
    assert data["photo_status"] in _enum_values(PhotoStatus)
    assert isinstance(data["is_provisional"], bool)
    assert isinstance(data["replacement_fee_cents"], int)
    assert isinstance(data["lost_or_stolen_report_count"], int)
    assert is_iso8601_timestamp(data["expires_at"])


def assert_photo_submission(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["card_id"])
    assert isinstance(data["image_ref"], str) and data["image_ref"]
    assert data["review_status"] in _enum_values(ReviewStatus)
    assert isinstance(data["submission_sequence"], int) and data["submission_sequence"] >= 1


def assert_term(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["term_code"], str) and data["term_code"]
    assert isinstance(data["name"], str)
    assert is_iso8601_timestamp(data["start_date"])
    assert is_iso8601_timestamp(data["end_date"])
    assert is_iso8601_timestamp(data["add_drop_deadline"])
    assert isinstance(data["total_weeks"], int) and data["total_weeks"] >= 1
    assert data["proration_mode"] in _enum_values(ProrationMode)
    assert isinstance(data["current_week_index"], int) and data["current_week_index"] >= 0
    assert data["status"] in _enum_values(TermStatus)


def assert_meal_plan(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["plan_code"], str) and data["plan_code"]
    assert isinstance(data["weekly_swipe_allowance"], int)
    assert isinstance(data["is_unlimited_swipes"], bool)
    assert isinstance(data["dining_dollar_allocation_cents"], int)
    assert isinstance(data["price_cents"], int) and data["price_cents"] > 0
    assert isinstance(data["requires_on_campus_housing"], bool)
    assert isinstance(data["eligible_holder_types"], list) and data["eligible_holder_types"]
    assert data["status"] in _enum_values(MealPlanStatus)


def assert_enrollment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["holder_id"])
    assert is_valid_uuid(data["plan_id"])
    assert is_valid_uuid(data["term_id"])
    assert data["status"] in _enum_values(EnrollmentStatus)
    assert isinstance(data["swipes_used_this_week"], int)


def assert_change_request(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["enrollment_id"])
    assert is_valid_uuid(data["new_plan_id"])
    assert data["status"] in _enum_values(ChangeRequestStatus)
    if data.get("void_reason") is not None:
        assert data["void_reason"] in _enum_values(VoidReason)


def assert_account(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["holder_id"])
    assert data["account_type"] in _enum_values(AccountType)
    assert data["status"] in _enum_values(AccountStatus)
    assert isinstance(data["balance_cents"], int)
    if data.get("frozen_reason") is not None:
        assert data["frozen_reason"] in _enum_values(FrozenReason)


def assert_ledger_entry(data: dict):
    _assert_event_fields(data)
    assert is_valid_uuid(data["account_id"])
    assert data["entry_type"] in _enum_values(LedgerEntryType)
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert isinstance(data["entry_sequence"], int) and data["entry_sequence"] >= 1
    assert isinstance(data["running_balance_cents"], int)


def assert_transaction(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["card_id"])
    assert data["tender_type"] in _enum_values(TenderType)
    assert isinstance(data["amount_cents"], int)
    assert data["status"] in _enum_values(TransactionStatus)


def assert_dispute(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["transaction_id"])
    assert is_valid_uuid(data["filed_by_holder_id"])
    assert data["status"] in _enum_values(DisputeStatus)
    assert isinstance(data["provisional_credit_cents"], int)


def assert_refund_request(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["account_id"])
    assert is_valid_uuid(data["requested_by_holder_id"])
    assert data["refund_variant"] in _enum_values(RefundVariant)
    assert isinstance(data["amount_cents"], int)
    assert data["status"] in _enum_values(RefundStatus)


def assert_door_zone(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["zone_code"], str) and data["zone_code"]
    assert isinstance(data["building"], str)
    assert data["security_level"] in _enum_values(SecurityLevel)
    assert isinstance(data["access_windows"], list) and data["access_windows"]
    assert data["status"] in ("ACTIVE", "DECOMMISSIONED")


def assert_access_grant(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["card_id"])
    assert is_valid_uuid(data["zone_id"])
    assert data["clearance"] in _enum_values(SecurityLevel)
    assert data["status"] in _enum_values(GrantStatus)
    if data.get("suspended_reason") is not None:
        assert data["suspended_reason"] in _enum_values(SuspendedReason)


def assert_access_event(data: dict):
    _assert_event_fields(data)
    assert is_valid_uuid(data["card_id"])
    assert is_valid_uuid(data["zone_id"])
    assert data["decision"] in _enum_values(AccessDecision)
    if data.get("deny_reason") is not None:
        assert data["deny_reason"] in _enum_values(DenyReason)
    assert is_iso8601_timestamp(data["attempted_at"])


def assert_merchant(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["merchant_code"], str) and data["merchant_code"]
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert data["category"] in _enum_values(MerchantCategory)
    assert isinstance(data["commission_bps"], int) and 0 <= data["commission_bps"] <= 2000
    assert data["commission_mode"] in _enum_values(CommissionMode)
    assert data["status"] in _enum_values(MerchantStatus)


def assert_settlement(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["merchant_id"])
    assert is_valid_uuid(data["term_id"])
    assert is_iso8601_timestamp(data["period_start"])
    assert is_iso8601_timestamp(data["period_end"])
    assert data["status"] in _enum_values(SettlementStatus)


def assert_account_balance_matches_ledger(account: dict, entries: list):
    """Domain invariant: balance_cents == signed ledger sum replayed in order."""
    credits = {"FUND", "ALLOCATION_GRANT", "PRORATION_CREDIT",
               "PROVISIONAL_CREDIT", "ADJUSTMENT_CREDIT", "PURCHASE_REVERSAL"}
    signed = sum(
        e["amount_cents"] if e["entry_type"] in credits else -e["amount_cents"]
        for e in entries
    )
    assert account["balance_cents"] == signed, (
        f"balance_cents {account['balance_cents']} != signed ledger sum {signed}"
    )
