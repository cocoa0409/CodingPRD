"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp,
)


VALID_SHELTER_STATUSES = {"OPEN", "SUSPENDED"}
VALID_ANIMAL_STATUSES = {"AVAILABLE", "HELD", "ADOPTED", "BOARDING_ONLY", "RETIRED"}
VALID_SPECIES = {"DOG", "CAT", "RABBIT", "OTHER"}
VALID_SPECIAL_CARE = {"NONE", "MEDICAL", "BEHAVIORAL"}
VALID_VACCINE_TYPES = {"RABIES", "DISTEMPER", "PARVO", "BORDETELLA", "FELV"}
VALID_HOMEVISIT_STATUSES = {"SCHEDULED", "SUBMITTED", "PASSED", "FAILED", "CANCELLED"}
VALID_ADOPTER_HV_STATUSES = {"PENDING", "PASSED", "FAILED", "EXPIRED"}
VALID_APP_STATUSES = {"SUBMITTED", "UNDER_REVIEW", "HOME_VISIT_REQUIRED", "APPROVED", "REJECTED", "FINALIZED", "WITHDRAWN"}
VALID_RESERVATION_STATUSES = {"RESERVED", "ACTIVE", "COMPLETED", "SETTLED", "CANCELLED"}
VALID_SETTLEMENT_STATUSES = {"PENDING", "COMPLETED", "REFUNDED", "FAILED"}
VALID_SUBJECT_TYPES = {"ADOPTION", "BOARDING"}
VALID_PAYMENT_METHODS = {"CARD", "BANK_TRANSFER", "CASH"}


def _assert_common(data: dict):
    """Assert common_fields are present and correctly formatted."""
    assert "id" in data, f"id missing: {data}"
    assert is_valid_uuid(data["id"]), f"id must be a valid UUID, got {data['id']}"
    assert "created_at" in data, f"created_at missing: {data}"
    assert is_iso8601_timestamp(data["created_at"]), f"created_at bad format: {data['created_at']}"
    assert "updated_at" in data, f"updated_at missing: {data}"
    assert is_iso8601_timestamp(data["updated_at"]), f"updated_at bad format: {data['updated_at']}"
    assert "version" in data, f"version missing: {data}"
    assert isinstance(data["version"], int), f"version must be int, got {type(data['version'])}"
    assert data["version"] >= 1, f"version must be >= 1, got {data['version']}"


def assert_shelter(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["boarding_capacity"], int) and data["boarding_capacity"] >= 0
    assert isinstance(data["reserved_slots"], int) and data["reserved_slots"] >= 0
    assert isinstance(data["available_slots"], int) and data["available_slots"] >= 0
    assert data["available_slots"] == max(0, data["boarding_capacity"] - data["reserved_slots"]), (
        f"available_slots invariant broken: {data}"
    )
    assert isinstance(data["adoption_fee_base"], int)
    assert isinstance(data["boarding_rate_per_night"], int)
    assert data["status"] in VALID_SHELTER_STATUSES, f"bad shelter status {data['status']}"


def assert_animal(data: dict):
    _assert_common(data)
    assert isinstance(data["shelter_id"], str) and is_valid_uuid(data["shelter_id"])
    assert isinstance(data["name"], str) and data["name"]
    assert data["species"] in VALID_SPECIES, f"bad species {data['species']}"
    assert isinstance(data["age_months"], int) and data["age_months"] >= 0
    assert isinstance(data["temperament_tags"], list)
    assert data["special_care_level"] in VALID_SPECIAL_CARE, f"bad special_care_level {data['special_care_level']}"
    assert is_iso8601_timestamp(data["intake_date"]), f"intake_date bad format: {data['intake_date']}"
    assert data["status"] in VALID_ANIMAL_STATUSES, f"bad animal status {data['status']}"


def assert_vaccination(data: dict):
    assert is_valid_uuid(data["id"]), f"id must be UUID: {data['id']}"
    assert is_valid_uuid(data["animal_id"])
    assert data["vaccine_type"] in VALID_VACCINE_TYPES
    assert is_iso8601_timestamp(data["administered_date"])
    assert is_iso8601_timestamp(data["expires_date"])
    assert isinstance(data["lot_number"], str) and data["lot_number"]
    assert is_iso8601_timestamp(data["created_at"])


def assert_adopter(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["household_size"], int) and data["household_size"] >= 0
    assert isinstance(data["has_yard"], bool)
    assert data["home_visit_status"] in VALID_ADOPTER_HV_STATUSES, f"bad home_visit_status {data['home_visit_status']}"
    assert isinstance(data["disqualified"], bool)


def assert_home_visit(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["adopter_id"])
    assert is_iso8601_timestamp(data["scheduled_for"])
    assert isinstance(data["inspector_id"], str) and data["inspector_id"]
    assert data["status"] in VALID_HOMEVISIT_STATUSES, f"bad hv status {data['status']}"
    assert isinstance(data.get("yard_verified", False), bool)


def assert_adoption_application(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["adopter_id"])
    assert is_valid_uuid(data["animal_id"])
    assert is_valid_uuid(data["shelter_id"])
    assert data["status"] in VALID_APP_STATUSES, f"bad app status {data['status']}"


def assert_boarding_reservation(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["shelter_id"])
    assert is_valid_uuid(data["animal_id"])
    assert isinstance(data["owner_id"], str) and data["owner_id"]
    assert is_iso8601_timestamp(data["check_in_date"])
    assert is_iso8601_timestamp(data["check_out_date"])
    assert isinstance(data["nights"], int) and data["nights"] >= 1, f"nights must be >= 1, got {data.get('nights')}"
    assert isinstance(data["quoted_total"], int) and data["quoted_total"] >= 0
    assert data["status"] in VALID_RESERVATION_STATUSES


def assert_fee_settlement(data: dict):
    _assert_common(data)
    assert data["subject_type"] in VALID_SUBJECT_TYPES
    assert isinstance(data["subject_id"], str) and data["subject_id"]
    assert isinstance(data["amount"], int)
    assert data["method"] in VALID_PAYMENT_METHODS
    assert data["status"] in VALID_SETTLEMENT_STATUSES


def assert_shelter_slot_invariant(shelter: dict):
    """available_slots = max(0, boarding_capacity - reserved_slots) per PRD §3.7."""
    expected = max(0, shelter["boarding_capacity"] - shelter["reserved_slots"])
    assert shelter["available_slots"] == expected, (
        f"Shelter slot invariant broken: available_slots={shelter['available_slots']} "
        f"expected {expected} (capacity={shelter['boarding_capacity']}, reserved={shelter['reserved_slots']})"
    )
