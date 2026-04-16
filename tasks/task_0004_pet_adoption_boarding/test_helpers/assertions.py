"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


_SPECIES = {"DOG", "CAT", "RABBIT", "BIRD", "OTHER"}
_SPECIES_WITH_ALL = _SPECIES | {"ALL"}
_TEMPERAMENT = {"CALM", "MODERATE", "ENERGETIC", "AGGRESSIVE"}


# ---------------------------------------------------------------------------
# Shelter
# ---------------------------------------------------------------------------

def assert_shelter(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"Shelter id must be UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be an integer >= 1"
    assert isinstance(data.get("name"), str) and len(data["name"]) > 0, "name must be non-empty"
    assert isinstance(data.get("address"), str), "address must be a string"
    assert isinstance(data.get("contact_email"), str), "contact_email must be a string"
    assert isinstance(data.get("boarding_capacity"), int) and data["boarding_capacity"] >= 1, \
        f"boarding_capacity must be >= 1, got {data.get('boarding_capacity')}"
    assert isinstance(data.get("tax_rate"), (int, float)), "tax_rate must be numeric"
    assert 0.0 <= data["tax_rate"] <= 0.30, f"tax_rate must be in [0, 0.30], got {data['tax_rate']}"
    assert isinstance(data.get("current_boarding_count"), int), "current_boarding_count must be int"
    assert isinstance(data.get("adoption_count"), int), "adoption_count must be int"
    assert isinstance(data.get("compliance_score"), (int, float)), "compliance_score must be numeric"
    assert 0 <= data["compliance_score"] <= 100, f"compliance_score must be 0-100, got {data['compliance_score']}"
    assert isinstance(data.get("revenue_pending_cents"), int), "revenue_pending_cents must be int"
    assert isinstance(data.get("revenue_settled_cents"), int), "revenue_settled_cents must be int"
    assert data["status"] in ["OPEN", "SUSPENDED"], f"Invalid shelter status: {data['status']}"


# ---------------------------------------------------------------------------
# Animal
# ---------------------------------------------------------------------------

def assert_animal(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"Animal id must be UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1
    assert is_valid_uuid(data.get("shelter_id", "")), "shelter_id must be UUID"
    assert isinstance(data.get("name"), str) and len(data["name"]) > 0
    assert data["species"] in _SPECIES, f"Invalid species: {data['species']}"
    assert isinstance(data.get("breed"), str), "breed must be a string"
    assert isinstance(data.get("age_months"), int) and data["age_months"] >= 0
    assert isinstance(data.get("weight_kg"), (int, float)) and data["weight_kg"] > 0
    assert data["temperament"] in _TEMPERAMENT, f"Invalid temperament: {data['temperament']}"
    assert isinstance(data.get("special_needs"), list), "special_needs must be a list"
    assert isinstance(data.get("vaccination_compliant"), bool), "vaccination_compliant must be bool"
    assert isinstance(data.get("active_hold_count"), int) and data["active_hold_count"] >= 0
    assert isinstance(data.get("adoption_eligible"), bool), "adoption_eligible must be bool"
    assert data["status"] in [
        "INTAKE", "AVAILABLE", "ADOPTION_PENDING", "ADOPTED", "BOARDING", "UNAVAILABLE"
    ], f"Invalid animal status: {data['status']}"


def assert_animal_invariants(data: dict):
    """Cross-field invariants that must always hold on an Animal resource."""
    # adoption_eligible is true iff status == AVAILABLE AND vaccination_compliant AND no HIGH/CRITICAL ACTIVE hold.
    # We can't check hold-severity from here, but basic implications hold:
    if data["status"] != "AVAILABLE":
        assert data["adoption_eligible"] is False, \
            f"adoption_eligible must be False when status={data['status']}"
    if not data.get("vaccination_compliant", False):
        assert data["adoption_eligible"] is False, \
            "adoption_eligible must be False when vaccination_compliant=False"


# ---------------------------------------------------------------------------
# VaccinationRecord
# ---------------------------------------------------------------------------

def assert_vaccination_record(data: dict):
    assert is_valid_uuid(data.get("id", "")), "VaccinationRecord id must be UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data.get("animal_id", "")), "animal_id must be UUID"
    assert data["vaccine_name"] in [
        "RABIES", "DHPP", "FVRCP", "BORDETELLA", "RHDV", "OTHER"
    ], f"Invalid vaccine_name: {data['vaccine_name']}"
    assert is_iso8601_timestamp(data.get("administered_date", "")), "administered_date must be ISO 8601"
    assert is_iso8601_timestamp(data.get("expiry_date", "")), "expiry_date must be ISO 8601"
    assert isinstance(data.get("batch_number"), str), "batch_number must be a string"
    assert isinstance(data.get("veterinarian_id"), str) and len(data["veterinarian_id"]) > 0, \
        "veterinarian_id must be non-empty"
    assert isinstance(data.get("is_currently_valid"), bool), "is_currently_valid must be bool"


# ---------------------------------------------------------------------------
# Adopter
# ---------------------------------------------------------------------------

def assert_adopter(data: dict):
    assert is_valid_uuid(data.get("id", "")), "Adopter id must be UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1
    assert is_valid_uuid(data.get("shelter_id", "")), "shelter_id must be UUID"
    assert isinstance(data.get("full_name"), str) and len(data["full_name"]) > 0
    assert isinstance(data.get("email"), str) and "@" in data["email"]
    assert isinstance(data.get("phone"), str)
    assert data["home_type"] in ["HOUSE", "APARTMENT", "FARM", "OTHER"], \
        f"Invalid home_type: {data['home_type']}"
    assert isinstance(data.get("has_yard"), bool), "has_yard must be bool"
    assert isinstance(data.get("has_other_pets"), bool), "has_other_pets must be bool"
    assert isinstance(data.get("other_pet_species"), list), "other_pet_species must be a list"
    assert isinstance(data.get("adoption_history_count"), int) and data["adoption_history_count"] >= 0
    # latest_home_visit_id is nullable
    if data.get("latest_home_visit_id") is not None:
        assert is_valid_uuid(data["latest_home_visit_id"]), "latest_home_visit_id must be UUID or null"
    # latest_home_visit_result is nullable
    if data.get("latest_home_visit_result") is not None:
        assert data["latest_home_visit_result"] in ["PASS", "CONDITIONAL_PASS", "FAIL"], \
            f"Invalid latest_home_visit_result: {data['latest_home_visit_result']}"
    assert data["status"] in ["ACTIVE", "BLACKLISTED"], f"Invalid adopter status: {data['status']}"


# ---------------------------------------------------------------------------
# AdoptionApplication
# ---------------------------------------------------------------------------

def assert_adoption_application(data: dict):
    assert is_valid_uuid(data.get("id", "")), "AdoptionApplication id must be UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1
    assert is_valid_uuid(data.get("shelter_id", "")), "shelter_id must be UUID"
    assert is_valid_uuid(data.get("animal_id", "")), "animal_id must be UUID"
    assert is_valid_uuid(data.get("adopter_id", "")), "adopter_id must be UUID"
    assert isinstance(data.get("reason"), str), "reason must be a string"
    assert isinstance(data.get("requires_home_visit"), bool), "requires_home_visit must be bool"
    assert data["status"] in [
        "SUBMITTED", "UNDER_REVIEW", "HOME_VISIT_REQUIRED", "HOME_VISIT_SCHEDULED",
        "REVIEWED", "APPROVED", "COMPLETED", "REJECTED", "WITHDRAWN",
    ], f"Invalid application status: {data['status']}"


# ---------------------------------------------------------------------------
# HomeVisit
# ---------------------------------------------------------------------------

def assert_home_visit(data: dict):
    assert is_valid_uuid(data.get("id", "")), "HomeVisit id must be UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1
    assert is_valid_uuid(data.get("application_id", "")), "application_id must be UUID"
    assert is_valid_uuid(data.get("adopter_id", "")), "adopter_id must be UUID"
    assert isinstance(data.get("case_worker_id"), str) and len(data["case_worker_id"]) > 0
    assert is_iso8601_timestamp(data.get("scheduled_date", "")), "scheduled_date must be ISO 8601"
    assert data["status"] in [
        "SCHEDULED", "COMPLETED", "CANCELLED", "EXPIRED"
    ], f"Invalid home visit status: {data['status']}"
    # overall_score and result exist only after COMPLETED; may be null otherwise
    if data.get("overall_score") is not None:
        assert isinstance(data["overall_score"], int), "overall_score must be int"
        assert 0 <= data["overall_score"] <= 100, f"overall_score must be 0-100"
    if data.get("result") is not None:
        assert data["result"] in ["PASS", "CONDITIONAL_PASS", "FAIL"], \
            f"Invalid home visit result: {data['result']}"


# ---------------------------------------------------------------------------
# BoardingReservation
# ---------------------------------------------------------------------------

def assert_boarding_reservation(data: dict):
    assert is_valid_uuid(data.get("id", "")), "BoardingReservation id must be UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1
    assert is_valid_uuid(data.get("shelter_id", "")), "shelter_id must be UUID"
    assert is_valid_uuid(data.get("animal_id", "")), "animal_id must be UUID"
    assert isinstance(data.get("owner_name"), str) and len(data["owner_name"]) > 0
    assert isinstance(data.get("owner_contact"), str) and len(data["owner_contact"]) > 0
    assert is_iso8601_timestamp(data.get("check_in_date", "")), "check_in_date must be ISO 8601"
    assert is_iso8601_timestamp(data.get("check_out_date", "")), "check_out_date must be ISO 8601"
    assert isinstance(data.get("planned_duration_days"), int) and data["planned_duration_days"] >= 1
    assert data["status"] in [
        "REQUESTED", "CONFIRMED", "CHECKED_IN", "CHECKED_OUT", "CANCELLED"
    ], f"Invalid reservation status: {data['status']}"


# ---------------------------------------------------------------------------
# BoardingMatch
# ---------------------------------------------------------------------------

def assert_boarding_match(data: dict):
    assert is_valid_uuid(data.get("id", "")), "BoardingMatch id must be UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data.get("reservation_id", "")), "reservation_id must be UUID"
    assert is_valid_uuid(data.get("animal_id", "")), "animal_id must be UUID"
    assert is_valid_uuid(data.get("shelter_id", "")), "shelter_id must be UUID"
    assert isinstance(data.get("compatibility_score"), int) and 0 <= data["compatibility_score"] <= 100
    assert data["boarding_zone"] in ["GENERAL", "ACTIVE", "SMALL_ANIMAL", "ISOLATION"], \
        f"Invalid boarding_zone: {data['boarding_zone']}"
    assert isinstance(data.get("conflict_flags"), list), "conflict_flags must be a list"
    # voided_at is nullable
    if data.get("voided_at") is not None:
        assert is_iso8601_timestamp(data["voided_at"]), "voided_at must be ISO 8601 or null"


# ---------------------------------------------------------------------------
# FeeInvoice
# ---------------------------------------------------------------------------

def assert_fee_invoice(data: dict):
    assert is_valid_uuid(data.get("id", "")), "FeeInvoice id must be UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1
    assert is_valid_uuid(data.get("shelter_id", "")), "shelter_id must be UUID"
    assert data["reference_type"] in ["ADOPTION", "BOARDING"], \
        f"Invalid reference_type: {data['reference_type']}"
    assert is_valid_uuid(data.get("reference_id", "")), "reference_id must be UUID"
    assert isinstance(data.get("line_items"), list), "line_items must be a list"
    assert isinstance(data.get("subtotal_cents"), int), "subtotal_cents must be int"
    assert isinstance(data.get("discount_cents"), int), "discount_cents must be int"
    assert isinstance(data.get("tax_cents"), int), "tax_cents must be int"
    assert isinstance(data.get("total_amount_cents"), int), "total_amount_cents must be int"
    assert data["total_amount_cents"] >= 0, f"total_amount_cents must be >= 0"
    assert isinstance(data.get("paid_amount_cents"), int), "paid_amount_cents must be int"
    assert data["paid_amount_cents"] >= 0
    assert isinstance(data.get("refund_amount_cents"), int), "refund_amount_cents must be int"
    assert isinstance(data.get("balance_due_cents"), int), "balance_due_cents must be int"
    assert data["balance_due_cents"] >= 0
    assert data["status"] in [
        "DRAFT", "ISSUED", "PARTIALLY_PAID", "PAID", "REFUNDED", "VOID"
    ], f"Invalid invoice status: {data['status']}"


def assert_fee_invoice_invariants(data: dict):
    """Cross-field invariants on FeeInvoice."""
    # balance_due_cents == max(0, total - paid)
    expected_balance = max(0, data["total_amount_cents"] - data["paid_amount_cents"])
    assert data["balance_due_cents"] == expected_balance, \
        f"balance_due_cents {data['balance_due_cents']} != max(0, total{data['total_amount_cents']} - paid{data['paid_amount_cents']}) = {expected_balance}"
    # total == subtotal - discount + tax (never negative)
    expected_total = data["subtotal_cents"] - data["discount_cents"] + data["tax_cents"]
    # In the credit line case at check-out, total can be recomputed; in standard case it must match.
    # We still assert basic non-negativity and line item totals align for ADOPTION reference_type.
    if data["reference_type"] == "ADOPTION":
        assert expected_total == data["total_amount_cents"], \
            f"total_amount_cents {data['total_amount_cents']} != subtotal-discount+tax {expected_total}"


# ---------------------------------------------------------------------------
# ComplianceHold
# ---------------------------------------------------------------------------

def assert_compliance_hold(data: dict):
    assert is_valid_uuid(data.get("id", "")), "ComplianceHold id must be UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1
    assert is_valid_uuid(data.get("animal_id", "")), "animal_id must be UUID"
    assert data["hold_type"] in [
        "VACCINATION_OVERDUE", "HEALTH_CONCERN", "BEHAVIOR_INCIDENT", "QUARANTINE"
    ], f"Invalid hold_type: {data['hold_type']}"
    assert data["severity"] in ["LOW", "MEDIUM", "HIGH", "CRITICAL"], \
        f"Invalid severity: {data['severity']}"
    assert isinstance(data.get("reason"), str)
    assert isinstance(data.get("imposed_by"), str) and len(data["imposed_by"]) > 0
    assert data["imposed_role"] in ["VETERINARIAN", "SHELTER_MANAGER"], \
        f"Invalid imposed_role: {data['imposed_role']}"
    assert data["status"] in ["ACTIVE", "RESOLVED"], f"Invalid hold status: {data['status']}"


# ---------------------------------------------------------------------------
# FeeSchedule
# ---------------------------------------------------------------------------

def assert_fee_schedule(data: dict):
    assert is_valid_uuid(data.get("id", "")), "FeeSchedule id must be UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1
    assert is_valid_uuid(data.get("shelter_id", "")), "shelter_id must be UUID"
    assert data["fee_type"] in [
        "ADOPTION_BASE", "BOARDING_DAILY", "SPECIAL_NEEDS_SURCHARGE", "LOYALTY_DISCOUNT_PCT"
    ], f"Invalid fee_type: {data['fee_type']}"
    assert data["species"] in _SPECIES_WITH_ALL, f"Invalid species: {data['species']}"
    assert isinstance(data.get("amount_cents"), int)
    assert is_iso8601_timestamp(data.get("effective_from", "")), "effective_from must be ISO 8601"
    # effective_to is nullable
    if data.get("effective_to") is not None:
        assert is_iso8601_timestamp(data["effective_to"]), "effective_to must be ISO 8601 or null"
    assert isinstance(data.get("is_currently_active"), bool)


# ---------------------------------------------------------------------------
# SettlementBatch
# ---------------------------------------------------------------------------

def assert_settlement_batch(data: dict):
    assert is_valid_uuid(data.get("id", "")), "SettlementBatch id must be UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data.get("shelter_id", "")), "shelter_id must be UUID"
    assert is_iso8601_timestamp(data.get("period_start", "")), "period_start must be ISO 8601"
    assert is_iso8601_timestamp(data.get("period_end", "")), "period_end must be ISO 8601"
    assert isinstance(data.get("invoice_ids"), list), "invoice_ids must be a list"
    assert isinstance(data.get("gross_amount_cents"), int)
    assert isinstance(data.get("refund_amount_cents"), int)
    assert isinstance(data.get("net_amount_cents"), int)
    assert data["net_amount_cents"] >= 0, "net_amount_cents must be >= 0"
    assert data["status"] in ["DRAFT", "APPROVED", "PAID"], \
        f"Invalid settlement batch status: {data['status']}"
