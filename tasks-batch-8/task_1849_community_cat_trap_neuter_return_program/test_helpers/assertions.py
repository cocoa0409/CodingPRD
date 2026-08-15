"""Entity assertions and domain invariant checkers (PRD §2.5, §2.6, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict):
    """Primary resources carry id, created_at, updated_at, version (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_caretaker(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["phone"], str)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["certified_tnr"], bool)
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_colony(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["address"], str)
    assert is_valid_uuid(data.get("caretaker_id", ""))
    assert isinstance(data["estimated_population"], int) and data["estimated_population"] >= 1
    assert data["status"] in ("REGISTERED", "DISSOLVED")
    assert data["monitoring_status"] in ("ACTIVE", "WATCH", "STABLE")
    assert isinstance(data["sterilized_pct"], (int, float))
    assert 0 <= data["sterilized_pct"] <= 1


def assert_cat(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("colony_id", ""))
    assert isinstance(data["intake_tag"], str) and len(data["intake_tag"]) > 0
    assert data["sex"] in ("MALE", "FEMALE", "UNKNOWN")
    assert isinstance(data["approximate_age_months"], int) and data["approximate_age_months"] >= 0
    assert isinstance(data["is_kitten"], bool)
    assert isinstance(data["ear_tipped"], bool)
    assert isinstance(data["vaccinated_rabies"], bool)
    assert data["status"] in (
        "AT_LARGE", "TRAPPED", "AT_CLINIC", "POST_SURGERY", "RETURNED",
        "COLONY_STERILIZED", "IN_FOSTER", "ADOPTION_PIPELINE", "ADOPTED", "DECEASED",
    )
    assert data.get("pathway") in (None, "RETURN_TO_FIELD", "ADOPTION")


def assert_partner_clinic(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["voucher_reimbursement_cents"], int)
    assert data["voucher_reimbursement_cents"] > 0
    assert isinstance(data["accepts_vouchers"], bool)
    assert data["status"] in ("ACTIVE", "INACTIVE")


def assert_clinic_day(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("clinic_id", ""))
    assert isinstance(data["base_capacity"], int) and data["base_capacity"] >= 1
    assert isinstance(data["surge_capacity"], int) and data["surge_capacity"] >= 0
    assert isinstance(data["booked_count"], int) and data["booked_count"] >= 0
    assert data["status"] in ("SCHEDULED", "COMPLETED", "CANCELLED")


def assert_clinic_slot(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("clinic_day_id", ""))
    assert isinstance(data["slot_index"], int) and data["slot_index"] >= 1
    assert data["status"] in ("OPEN", "BOOKED", "USED", "RELEASED")


def assert_appointment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("cat_id", ""))
    assert is_valid_uuid(data.get("clinic_slot_id", ""))
    assert data["status"] in ("SCHEDULED", "TRAPPED", "NO_SHOW", "COMPLETED", "CANCELLED")


def assert_surgery_record(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("appointment_id", ""))
    assert isinstance(data["surgeon_initials"], str)
    assert isinstance(data["ear_tipped"], bool)
    assert isinstance(data["rabies_vaccinated"], bool)
    assert data["outcome"] in ("STERILIZED", "ALREADY_STERILE", "DIED_IN_SURGERY")


def assert_voucher(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("caretaker_id", ""))
    assert isinstance(data["face_value_cents"], int) and data["face_value_cents"] > 0
    assert data["funding_source"] in ("MUNICIPAL_GRANT", "DONATION_FUND")
    assert data["status"] in ("ISSUED", "COMMITTED", "REDEEMED", "VOIDED", "EXPIRED")


def assert_complaint(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("colony_id", ""))
    assert isinstance(data["complainant_name"], str)
    assert data["category"] in (
        "NOISE", "ODOR", "PROPERTY_DAMAGE", "WILDLIFE_CONFLICT", "OVERPOPULATION",
    )
    assert data["severity"] in ("STANDARD", "HIGH")
    assert data["status"] in ("OPEN", "IN_MEDIATION", "RESOLVED", "ESCALATED")


def assert_foster_home(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["volunteer_name"], str) and len(data["volunteer_name"]) > 0
    assert isinstance(data["capacity_kittens"], int) and data["capacity_kittens"] >= 1
    assert isinstance(data["current_kittens"], int) and data["current_kittens"] >= 0
    assert data["status"] in ("ACTIVE", "PAUSED")


def assert_foster_placement(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("cat_id", ""))
    assert is_valid_uuid(data.get("foster_home_id", ""))
    assert data["status"] in ("ACTIVE", "ENDED_ADOPTION", "ENDED_RETURNED")


def assert_population_survey(data: dict):
    """Append-only: id + created_at only; no updated_at, no version (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    assert "version" not in data, "PopulationSurvey must not carry version"
    assert "updated_at" not in data, "PopulationSurvey must not carry updated_at"
    assert is_valid_uuid(data.get("colony_id", ""))
    assert isinstance(data["observed_count"], int) and data["observed_count"] >= 0
    assert isinstance(data["eartipped_count"], int) and data["eartipped_count"] >= 0
