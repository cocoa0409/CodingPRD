"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
)


_HOUSEHOLD_REQUIRED = (
    "primary_parent_name", "family_size", "annual_income_cents", "address_state",
    "direct_certification_flag",
)
_MEAL_APPLICATION_STATUSES = {
    "DRAFT", "SUBMITTED", "UNDER_REVIEW", "APPROVED", "DENIED", "APPEALED", "WITHDRAWN",
}
_ELIGIBILITY_LIFECYCLES = {"ACTIVE", "SUPERSEDED", "EXPIRED", "REVOKED"}
_ELIGIBILITY_VERIFICATIONS = {"UNVERIFIED", "VERIFIED", "DEFERRED"}
_ELIGIBILITY_SOURCES = {"APPLICATION", "DIRECT_CERTIFICATION", "AUTO_RENEWAL"}
_ELIGIBILITY_TIERS = {"FREE", "REDUCED", "PAID"}
_SERVICE_TX_STATUSES = {"PENDING", "SETTLED", "REJECTED", "REFUNDED", "DISPUTED"}
_LEDGER_ENTRY_TYPES = {"TOPUP", "MEAL_CHARGE", "MEAL_REFUND", "ADJUSTMENT"}
_ALLERGY_SEVERITIES = {"MILD", "MODERATE", "SEVERE_ANAPHYLACTIC"}
_REIMBURSEMENT_STATUSES = {"DRAFT", "SUBMITTED", "FINALIZED", "REJECTED"}
_ACCOUNTING_BASES = {"CASH", "ACCRUAL"}


def _assert_common_fields(data: dict, entity_label: str) -> None:
    """Verify id + created_at + updated_at + version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"{entity_label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_label}.created_at must be ISO 8601 UTC"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity_label}.updated_at must be ISO 8601 UTC"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity_label}.version must be a positive integer (got {data.get('version')!r})"
    )


def _assert_append_only_fields(data: dict, entity_label: str) -> None:
    """LedgerEntry carries ONLY id + created_at (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"{entity_label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_label}.created_at must be ISO 8601 UTC"
    )


def assert_household(data: dict) -> None:
    _assert_common_fields(data, "Household")
    assert isinstance(data["primary_parent_name"], str)
    assert isinstance(data["family_size"], int) and 1 <= data["family_size"] <= 20
    assert isinstance(data["annual_income_cents"], int) and data["annual_income_cents"] >= 0
    assert isinstance(data["address_state"], str) and len(data["address_state"]) == 2
    assert isinstance(data["direct_certification_flag"], bool)


def assert_student(data: dict) -> None:
    _assert_common_fields(data, "Student")
    assert is_valid_uuid(data["household_id"])
    assert isinstance(data["full_name"], str)
    assert isinstance(data["school_code"], str)
    assert isinstance(data["grade_level"], int) and 0 <= data["grade_level"] <= 12


def assert_allergy_profile(data: dict) -> None:
    _assert_common_fields(data, "AllergyProfile")
    assert is_valid_uuid(data["student_id"])
    assert isinstance(data["allergens"], list)
    assert data["severity"] in _ALLERGY_SEVERITIES


def assert_meal_application(data: dict) -> None:
    _assert_common_fields(data, "MealApplication")
    assert is_valid_uuid(data["household_id"])
    assert data["status"] in _MEAL_APPLICATION_STATUSES
    assert isinstance(data["school_year"], str)


def assert_eligibility_determination(data: dict) -> None:
    _assert_common_fields(data, "EligibilityDetermination")
    assert is_valid_uuid(data["household_id"])
    assert data["source"] in _ELIGIBILITY_SOURCES
    assert data["tier"] in _ELIGIBILITY_TIERS
    assert data["lifecycle_status"] in _ELIGIBILITY_LIFECYCLES
    assert data["verification_status"] in _ELIGIBILITY_VERIFICATIONS
    assert is_iso8601_timestamp(data["valid_from_utc"])
    assert is_iso8601_timestamp(data["valid_to_utc"])


def assert_menu_item(data: dict) -> None:
    _assert_common_fields(data, "MenuItem")
    assert isinstance(data["school_code"], str)
    assert isinstance(data["name"], str)
    for f in (
        "list_price_cents",
        "federal_reimbursement_free_cents",
        "federal_reimbursement_reduced_cents",
        "federal_reimbursement_paid_cents",
        "calories",
    ):
        assert isinstance(data[f], int) and data[f] >= 0, f"{f} must be non-negative integer"
    assert isinstance(data["allergens_present"], list)


def assert_parent_account(data: dict) -> None:
    _assert_common_fields(data, "ParentAccount")
    assert is_valid_uuid(data["household_id"])
    assert isinstance(data["balance_cents"], int)


def assert_ledger_entry(data: dict) -> None:
    _assert_append_only_fields(data, "LedgerEntry")
    assert is_valid_uuid(data["parent_account_id"])
    assert data["entry_type"] in _LEDGER_ENTRY_TYPES
    assert isinstance(data["amount_cents"], int)
    # PRD §2.4: LedgerEntry has neither updated_at nor version.
    assert "updated_at" not in data or data.get("updated_at") is None, (
        "LedgerEntry must not carry updated_at"
    )
    assert "version" not in data or data.get("version") is None, (
        "LedgerEntry must not carry version"
    )


def assert_service_transaction(data: dict) -> None:
    _assert_common_fields(data, "ServiceTransaction")
    assert is_valid_uuid(data["student_id"])
    assert is_valid_uuid(data["menu_item_id"])
    assert data["status"] in _SERVICE_TX_STATUSES
    assert isinstance(data["paid_charge_cents"], int) and data["paid_charge_cents"] >= 0
    assert isinstance(data["federal_reimbursement_cents"], int)


def assert_reimbursement_claim(data: dict) -> None:
    _assert_common_fields(data, "ReimbursementClaim")
    assert isinstance(data["school_code"], str)
    assert is_iso8601_timestamp(data["period_start_utc"])
    assert is_iso8601_timestamp(data["period_end_utc"])
    assert data["status"] in _REIMBURSEMENT_STATUSES
    assert data["accounting_basis"] in _ACCOUNTING_BASES
