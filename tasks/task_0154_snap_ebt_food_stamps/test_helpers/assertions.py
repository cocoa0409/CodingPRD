"""Entity assertions and domain invariant checkers for SNAP/EBT."""
import re

from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
)

# Enum value sets (from PRD §2.11)
HOUSEHOLD_CERT_STATUSES = {None, "PENDING", "APPROVED", "DENIED", "CLOSED"}
MEMBER_STATUSES = {"ACTIVE", "REMOVED"}
ABAWD_STATUSES = {"NOT_ABAWD", "ABAWD_EXEMPT", "ABAWD_WAIVED", "ABAWD_SUBJECT"}
APPLICATION_STATES = {
    "DRAFT", "SUBMITTED", "PENDING_INTERVIEW", "INTERVIEW_DONE",
    "APPROVED", "DENIED", "CLOSED",
}
DENIAL_REASONS = {None, "INCOME_OVER_LIMIT", "INCOMPLETE_INFO", "IDENTITY_FAILURE", "OTHER"}
CARD_STATUSES = {"ISSUED", "ACTIVE", "SUSPENDED", "REPLACED", "CLOSED"}
LEDGER_ENTRY_TYPES = {"REGULAR_ALLOTMENT", "EMERGENCY_ALLOTMENT", "PURCHASE", "REFUND", "ADJUSTMENT"}
TRANSACTION_STATUSES = {"PENDING", "APPROVED", "DECLINED", "REVERSED"}
DECLINE_REASONS = {None, "INSUFFICIENT_FUNDS", "CARD_NOT_ACTIVE", "MERCHANT_NOT_AUTHORIZED", "ALL_ITEMS_INELIGIBLE"}
ITEM_CATEGORIES = {
    "STAPLE", "PRODUCE", "DAIRY", "MEAT", "BREAD",
    "COLD_PREPARED", "HOT_PREPARED", "NON_FOOD", "ALCOHOL", "TOBACCO",
}
MERCHANT_AUTH_STATUSES = {"AUTHORIZED", "SUSPENDED", "REVOKED"}
FRAUD_CASE_STATES = {"OPEN", "UNDER_REVIEW", "SUBSTANTIATED", "UNFOUNDED", "APPEAL_PENDING", "CLOSED"}
FRAUD_TRIGGER_REASONS = {"TRAFFICKING_PATTERN", "DUPLICATE_BENEFITS", "IDENTITY_MISMATCH", "MANUAL_REPORT"}
WAIVER_STATES = {"REQUESTED", "APPROVED", "REJECTED", "EXPIRED"}
WAIVER_KINDS = {"WORK_TRAINING_ENROLLED", "MEDICALLY_UNFIT", "CAREGIVER", "AREA_HIGH_UNEMPLOYMENT"}
WAIVER_DECISION_REASONS = {None, "INSUFFICIENT_DOCS", "INELIGIBLE_CATEGORY", "OTHER"}
EA_STATES = {"DRAFT", "DECLARED", "DISBURSED", "CANCELLED"}
STATE_CODES = {"CA", "TX", "NY", "FL", "IL", "PA", "OH", "GA", "NC", "MI"}


CASE_NUMBER_PATTERN = re.compile(r"^SNAP-\d{4}-\d{6}$")
BENEFIT_MONTH_PATTERN = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def assert_household(data: dict) -> None:
    """Validate the shape and constraints of a Household entity."""
    assert is_valid_uuid(data["id"]), f"Household id is not a valid UUID: {data['id']}"
    assert CASE_NUMBER_PATTERN.match(data["case_number"]), (
        f"Invalid case_number format: {data['case_number']}"
    )
    assert data["state_code"] in STATE_CODES, f"Invalid state_code: {data['state_code']}"
    assert isinstance(data["address_zip"], str) and len(data["address_zip"]) == 5 and data["address_zip"].isdigit(), (
        f"Invalid address_zip: {data['address_zip']}"
    )
    assert isinstance(data["household_size"], int) and data["household_size"] >= 0
    assert isinstance(data["gross_monthly_income_cents"], int) and data["gross_monthly_income_cents"] >= 0
    assert isinstance(data["net_monthly_income_cents"], int) and data["net_monthly_income_cents"] >= 0
    assert isinstance(data["monthly_allotment_cents"], int) and data["monthly_allotment_cents"] >= 0
    assert data.get("certification_status") in HOUSEHOLD_CERT_STATUSES
    assert isinstance(data["dependent_care_expense_cents"], int) and data["dependent_care_expense_cents"] >= 0
    assert isinstance(data["shelter_expense_cents"], int) and data["shelter_expense_cents"] >= 0
    assert isinstance(data["has_elderly_or_disabled"], bool)
    assert is_iso8601_timestamp(data["created_at"]), f"Invalid created_at: {data['created_at']}"
    assert is_iso8601_timestamp(data["updated_at"]), f"Invalid updated_at: {data['updated_at']}"
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_member(data: dict) -> None:
    """Validate the shape and constraints of a Member entity."""
    assert is_valid_uuid(data["id"]), f"Member id is not a valid UUID: {data['id']}"
    assert is_valid_uuid(data["household_id"]), f"Invalid household_id: {data['household_id']}"
    assert isinstance(data["full_name"], str) and 1 <= len(data["full_name"]) <= 100
    assert isinstance(data["date_of_birth"], str) and len(data["date_of_birth"]) > 0
    assert isinstance(data["is_disabled"], bool)
    assert isinstance(data["is_pregnant"], bool)
    assert isinstance(data["earned_income_cents"], int) and data["earned_income_cents"] >= 0
    assert isinstance(data["unearned_income_cents"], int) and data["unearned_income_cents"] >= 0
    assert data["abawd_status"] in ABAWD_STATUSES
    assert isinstance(data["abawd_countable_months_used"], int)
    assert 0 <= data["abawd_countable_months_used"] <= 3
    assert data["status"] in MEMBER_STATUSES
    assert is_iso8601_timestamp(data["created_at"])
    assert is_iso8601_timestamp(data["updated_at"])
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_application(data: dict) -> None:
    """Validate the shape and constraints of an Application entity."""
    assert is_valid_uuid(data["id"])
    assert is_valid_uuid(data["household_id"])
    assert data["state"] in APPLICATION_STATES
    assert data.get("denial_reason") in DENIAL_REASONS
    assert is_iso8601_timestamp(data["created_at"])
    assert is_iso8601_timestamp(data["updated_at"])
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_ebt_card(data: dict) -> None:
    """Validate the shape and constraints of an EbtCard entity."""
    assert is_valid_uuid(data["id"])
    assert is_valid_uuid(data["household_id"])
    assert isinstance(data["card_number_last4"], str)
    assert len(data["card_number_last4"]) == 4 and data["card_number_last4"].isdigit()
    assert data["status"] in CARD_STATUSES
    assert is_iso8601_timestamp(data["issued_at"])
    assert isinstance(data["balance_cents"], int) and data["balance_cents"] >= 0
    assert is_iso8601_timestamp(data["created_at"])
    assert is_iso8601_timestamp(data["updated_at"])
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_benefit_ledger_entry(data: dict) -> None:
    """Validate the shape and constraints of a BenefitLedger entry.

    BenefitLedger is append-only: only id + created_at, no updated_at/version.
    """
    assert is_valid_uuid(data["id"])
    assert is_valid_uuid(data["household_id"])
    assert is_valid_uuid(data["card_id"])
    assert data["entry_type"] in LEDGER_ENTRY_TYPES
    assert isinstance(data["amount_cents"], int)
    assert BENEFIT_MONTH_PATTERN.match(data["benefit_month"]), (
        f"Invalid benefit_month: {data['benefit_month']}"
    )
    assert is_iso8601_timestamp(data["created_at"])


def assert_transaction(data: dict) -> None:
    """Validate the shape and constraints of a Transaction entity.

    Transaction is append-only: only id + created_at, no updated_at/version.
    """
    assert is_valid_uuid(data["id"])
    assert is_valid_uuid(data["card_id"])
    assert is_valid_uuid(data["merchant_id"])
    assert isinstance(data["requested_amount_cents"], int) and data["requested_amount_cents"] >= 1
    assert isinstance(data["eligible_amount_cents"], int) and data["eligible_amount_cents"] >= 0
    assert isinstance(data["ineligible_amount_cents"], int) and data["ineligible_amount_cents"] >= 0
    assert data["status"] in TRANSACTION_STATUSES
    assert data.get("decline_reason") in DECLINE_REASONS
    assert isinstance(data["line_items"], list)
    assert 1 <= len(data["line_items"]) <= 50
    for li in data["line_items"]:
        assert li["item_category"] in ITEM_CATEGORIES
        assert isinstance(li["unit_price_cents"], int) and li["unit_price_cents"] > 0
        assert isinstance(li["quantity"], int) and li["quantity"] > 0
    assert is_iso8601_timestamp(data["created_at"])


def assert_merchant(data: dict) -> None:
    """Validate the shape and constraints of a Merchant entity."""
    assert is_valid_uuid(data["id"])
    assert isinstance(data["name"], str) and 1 <= len(data["name"]) <= 100
    assert data["snap_authorization_status"] in MERCHANT_AUTH_STATUSES
    assert is_iso8601_timestamp(data["authorization_expires_at"])
    assert isinstance(data["hot_food_pilot"], bool)
    assert is_iso8601_timestamp(data["created_at"])
    assert is_iso8601_timestamp(data["updated_at"])
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_fraud_case(data: dict) -> None:
    """Validate the shape and constraints of a FraudCase entity."""
    assert is_valid_uuid(data["id"])
    assert is_valid_uuid(data["household_id"])
    assert data["state"] in FRAUD_CASE_STATES
    assert data["trigger_reason"] in FRAUD_TRIGGER_REASONS
    assert isinstance(data["suspicious_score"], (int, float))
    assert 0.0 <= data["suspicious_score"] <= 1.0
    # Should be rounded to two decimal places
    score = float(data["suspicious_score"])
    assert abs(score - round(score, 2)) < 1e-9, (
        f"suspicious_score not rounded to 2 decimals: {data['suspicious_score']}"
    )
    assert is_iso8601_timestamp(data["opened_at"])
    assert is_iso8601_timestamp(data["created_at"])
    assert is_iso8601_timestamp(data["updated_at"])
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_abawd_waiver(data: dict) -> None:
    """Validate the shape and constraints of an AbawdWaiver entity."""
    assert is_valid_uuid(data["id"])
    assert is_valid_uuid(data["member_id"])
    assert data["waiver_kind"] in WAIVER_KINDS
    assert data["state"] in WAIVER_STATES
    assert is_iso8601_timestamp(data["effective_from"])
    assert is_iso8601_timestamp(data["effective_to"])
    assert data.get("decision_reason") in WAIVER_DECISION_REASONS
    assert is_iso8601_timestamp(data["created_at"])
    assert is_iso8601_timestamp(data["updated_at"])
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_emergency_allotment(data: dict) -> None:
    """Validate the shape and constraints of an EmergencyAllotment entity."""
    assert is_valid_uuid(data["id"])
    assert data["state_code"] in STATE_CODES
    assert BENEFIT_MONTH_PATTERN.match(data["benefit_month"])
    assert data["state"] in EA_STATES
    assert isinstance(data["max_allotment_table_version"], int) and data["max_allotment_table_version"] >= 1
    assert is_iso8601_timestamp(data["created_at"])
    assert is_iso8601_timestamp(data["updated_at"])
    assert isinstance(data["version"], int) and data["version"] >= 1


# ---------------------------------------------------------------------------
# Domain invariant checkers
# ---------------------------------------------------------------------------

def assert_card_balance_matches_ledger(card: dict, ledger_entries: list) -> None:
    """PRD §2.9 invariant: card.balance_cents == sum(amount_cents) over its ledger entries."""
    ledger_sum = sum(int(e["amount_cents"]) for e in ledger_entries)
    assert card["balance_cents"] == ledger_sum, (
        f"Card balance_cents={card['balance_cents']} but ledger sum={ledger_sum}"
    )


def assert_no_active_application(household_data: dict) -> None:
    """Verify a household has no APPROVED certification at this moment."""
    assert household_data.get("certification_status") != "APPROVED"


def assert_envelope_success_object(envelope: dict) -> None:
    """Validate the standard PRD §2.2 success envelope shape on a JSON body."""
    assert "meta" in envelope
    assert "response_type" in envelope
    assert "data" in envelope
    meta = envelope["meta"]
    assert isinstance(meta.get("api_request_id"), str) and meta["api_request_id"].startswith("req_")
    assert is_iso8601_timestamp(meta.get("api_request_timestamp", ""))
