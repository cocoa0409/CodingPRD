"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
    assert_cost_precision,
)


def assert_shelter(data: dict):
    """Validate Shelter response structure against PRD contract."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["address"], str) and len(data["address"]) > 0
    assert isinstance(data["boarding_capacity"], int) and data["boarding_capacity"] >= 0
    assert isinstance(data["current_boarding_count"], int) and data["current_boarding_count"] >= 0
    assert isinstance(data["adoption_count"], int) and data["adoption_count"] >= 0
    assert isinstance(data["compliance_score"], (int, float))
    assert 0 <= data["compliance_score"] <= 100
    assert isinstance(data["revenue_balance"], (int, float))
    assert data["status"] in ["OPEN", "SUSPENDED"]


def assert_animal(data: dict):
    """Validate Animal response structure against PRD contract."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert is_valid_uuid(data.get("shelter_id", "")), "shelter_id must be valid UUID"
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["species"] in ["DOG", "CAT", "RABBIT", "BIRD", "OTHER"]
    assert isinstance(data["breed"], str)
    assert isinstance(data["age_months"], int)
    assert isinstance(data["weight_kg"], (int, float))
    assert data["temperament"] in ["CALM", "MODERATE", "ENERGETIC", "AGGRESSIVE"]
    assert isinstance(data["special_needs"], list)
    assert isinstance(data["vaccination_compliant"], bool)
    assert isinstance(data["adoption_eligible"], bool)
    assert isinstance(data["boarding_compatible_tags"], list)
    assert data["status"] in [
        "INTAKE", "AVAILABLE", "ADOPTION_PENDING", "ADOPTED", "BOARDING", "UNAVAILABLE"
    ]


def assert_vaccination_record(data: dict):
    """Validate VaccinationRecord response structure."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int)
    assert is_valid_uuid(data.get("animal_id", "")), "animal_id must be valid UUID"
    assert isinstance(data["vaccine_name"], str) and len(data["vaccine_name"]) > 0
    assert isinstance(data["administered_date"], str)
    assert isinstance(data["expiry_date"], str)
    assert isinstance(data["batch_number"], str)
    assert isinstance(data["veterinarian_name"], str)
    assert isinstance(data["is_valid"], bool)


def assert_adopter(data: dict):
    """Validate Adopter response structure."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int)
    assert is_valid_uuid(data.get("shelter_id", "")), "shelter_id must be valid UUID"
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str)
    assert isinstance(data["phone"], str)
    assert data["home_type"] in ["HOUSE", "APARTMENT", "FARM", "OTHER"]
    assert isinstance(data["has_yard"], bool)
    assert isinstance(data["has_other_pets"], bool)
    assert isinstance(data["other_pet_species"], list)
    assert isinstance(data["adoption_history_count"], int) and data["adoption_history_count"] >= 0
    assert isinstance(data["home_visit_passed"], bool)
    assert data["status"] in ["ACTIVE", "BLACKLISTED"]


def assert_adoption_application(data: dict):
    """Validate AdoptionApplication response structure."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int)
    assert is_valid_uuid(data.get("shelter_id", "")), "shelter_id must be valid UUID"
    assert is_valid_uuid(data.get("animal_id", "")), "animal_id must be valid UUID"
    assert is_valid_uuid(data.get("adopter_id", "")), "adopter_id must be valid UUID"
    assert isinstance(data["reason"], str)
    assert data["status"] in [
        "SUBMITTED", "UNDER_REVIEW", "HOME_VISIT_REQUIRED", "HOME_VISIT_SCHEDULED",
        "REVIEWED", "APPROVED", "REJECTED", "WITHDRAWN", "COMPLETED"
    ]


def assert_home_visit(data: dict):
    """Validate HomeVisit response structure."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int)
    assert is_valid_uuid(data.get("adopter_id", "")), "adopter_id must be valid UUID"
    assert data["status"] in ["SCHEDULED", "COMPLETED", "CANCELLED", "EXPIRED"]


def assert_boarding_reservation(data: dict):
    """Validate BoardingReservation response structure."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int)
    assert is_valid_uuid(data.get("shelter_id", "")), "shelter_id must be valid UUID"
    assert is_valid_uuid(data.get("animal_id", "")), "animal_id must be valid UUID"
    assert isinstance(data["owner_name"], str)
    assert isinstance(data["owner_contact"], str)
    assert isinstance(data["duration_days"], int) and data["duration_days"] >= 1
    assert data["status"] in ["REQUESTED", "CONFIRMED", "CHECKED_IN", "CHECKED_OUT", "CANCELLED"]


def assert_boarding_match(data: dict):
    """Validate BoardingMatch response structure (immutable, no version/updated_at)."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data.get("reservation_id", "")), "reservation_id must be valid UUID"
    assert is_valid_uuid(data.get("animal_id", "")), "animal_id must be valid UUID"
    assert is_valid_uuid(data.get("shelter_id", "")), "shelter_id must be valid UUID"
    assert isinstance(data["compatibility_score"], (int, float))
    assert 0 <= data["compatibility_score"] <= 100
    assert isinstance(data["boarding_zone"], str)
    assert data["boarding_zone"] in ["ISOLATION", "ACTIVE", "SMALL_ANIMAL", "GENERAL"]
    assert isinstance(data["conflict_flags"], list)


def assert_fee_invoice(data: dict):
    """Validate FeeInvoice response structure."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int)
    assert is_valid_uuid(data.get("shelter_id", "")), "shelter_id must be valid UUID"
    assert data["reference_type"] in ["ADOPTION", "BOARDING"]
    assert is_valid_uuid(data.get("reference_id", "")), "reference_id must be valid UUID"
    assert isinstance(data["line_items"], list)
    assert isinstance(data["subtotal"], (int, float))
    assert isinstance(data["tax_rate"], (int, float))
    assert isinstance(data["tax_amount"], (int, float))
    assert isinstance(data["discount_amount"], (int, float))
    assert isinstance(data["total_amount"], (int, float))
    assert isinstance(data["paid_amount"], (int, float))
    assert isinstance(data["refund_amount"], (int, float))
    assert isinstance(data["balance_due"], (int, float))
    assert data["status"] in ["DRAFT", "ISSUED", "PAID", "PARTIALLY_PAID", "REFUNDED", "VOID"]


def assert_compliance_hold(data: dict):
    """Validate ComplianceHold response structure."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int)
    assert is_valid_uuid(data.get("animal_id", "")), "animal_id must be valid UUID"
    assert data["hold_type"] in [
        "VACCINATION_OVERDUE", "HEALTH_CONCERN", "BEHAVIOR_INCIDENT", "QUARANTINE"
    ]
    assert isinstance(data["reason"], str)
    assert data["severity"] in ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    assert data["status"] in ["ACTIVE", "RESOLVED"]


def assert_fee_schedule(data: dict):
    """Validate FeeSchedule response structure."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int)
    assert is_valid_uuid(data.get("shelter_id", "")), "shelter_id must be valid UUID"
    assert data["fee_type"] in [
        "ADOPTION_BASE", "BOARDING_DAILY", "SPECIAL_NEEDS_SURCHARGE",
        "VACCINATION_FEE", "LOYALTY_DISCOUNT"
    ]
    assert data["species"] in ["DOG", "CAT", "RABBIT", "BIRD", "OTHER", "ALL"]
    assert isinstance(data["amount"], (int, float))
    assert isinstance(data["is_active"], bool)


def assert_monetary_precision(value, msg=""):
    """Assert a monetary value has at most 2 decimal places."""
    assert_cost_precision(value)


def assert_shelter_invariants(data: dict):
    """Shelter domain invariants that must hold after any operation."""
    assert data["current_boarding_count"] >= 0, "current_boarding_count must be >= 0"
    assert data["current_boarding_count"] <= data["boarding_capacity"], \
        "current_boarding_count must not exceed boarding_capacity"
    assert data["adoption_count"] >= 0, "adoption_count must be >= 0"
    assert 0 <= data["compliance_score"] <= 100, "compliance_score must be in [0, 100]"
    assert_cost_precision(data["revenue_balance"])


def assert_invoice_invariants(data: dict):
    """FeeInvoice domain invariants."""
    assert data["subtotal"] >= 0
    assert data["tax_amount"] >= 0
    assert data["discount_amount"] >= 0
    assert data["total_amount"] >= 0
    assert data["paid_amount"] >= 0
    assert data["refund_amount"] >= 0
    assert_cost_precision(data["subtotal"])
    assert_cost_precision(data["tax_amount"])
    assert_cost_precision(data["discount_amount"])
    assert_cost_precision(data["total_amount"])
    assert_cost_precision(data["paid_amount"])
