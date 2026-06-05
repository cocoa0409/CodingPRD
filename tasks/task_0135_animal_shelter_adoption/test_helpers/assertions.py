"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
)

LIFECYCLE_STATES = [
    "INTAKE_PENDING", "IN_CUSTODY", "AVAILABLE", "FOSTERED",
    "ADOPTED", "RECLAIMED", "EUTHANIZED",
]
MEDICAL_STATES = ["UNEXAMINED", "EXAM_PENDING", "NEEDS_TREATMENT", "CLEARED"]


def _assert_common(data: dict) -> None:
    """id + created_at + updated_at + version for mutable entities."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1 and increments"


def assert_shelter(data: dict) -> None:
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["stray_hold_days"], int) and data["stray_hold_days"] >= 0
    assert isinstance(data["promo_active"], bool)
    assert isinstance(data["collected_fee_cents"], int)
    assert isinstance(data["dog_daily_board_cents"], int)
    assert isinstance(data["cat_daily_board_cents"], int)


def assert_kennel(data: dict) -> None:
    _assert_common(data)
    assert isinstance(data["label"], str) and len(data["label"]) > 0
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert isinstance(data["occupied_count"], int) and data["occupied_count"] >= 0
    assert data["status"] in ("OPEN", "FULL")


def assert_animal(data: dict) -> None:
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["species"] in ("DOG", "CAT")
    assert isinstance(data["age_months"], int) and data["age_months"] >= 0
    assert data["lifecycle_status"] in LIFECYCLE_STATES
    assert data["medical_status"] in MEDICAL_STATES
    assert isinstance(data["microchipped"], bool)
    # stray_hold_release_at is null before intake, ISO 8601 after.
    if data.get("stray_hold_release_at") is not None:
        assert is_iso8601_timestamp(data["stray_hold_release_at"])


def assert_intake_record(data: dict) -> None:
    _assert_common(data)
    assert is_valid_uuid(data["animal_id"])
    assert data["source"] in ("STRAY", "SURRENDER", "TRANSFER")
    assert is_iso8601_timestamp(data["intake_at"])
    assert is_iso8601_timestamp(data["stray_hold_release_at"])


def assert_kennel_assignment(data: dict) -> None:
    _assert_common(data)
    assert is_valid_uuid(data["kennel_id"])
    assert is_valid_uuid(data["animal_id"])
    assert is_iso8601_timestamp(data["start_at"])
    assert data["status"] in ("ACTIVE", "RELEASED")
    if data["status"] == "ACTIVE":
        assert data.get("end_at") is None
        assert data.get("actual_board_cents") is None
    else:
        assert is_iso8601_timestamp(data["end_at"])
        assert isinstance(data["actual_board_cents"], int)


def assert_medical_record(data: dict) -> None:
    _assert_common(data)
    assert is_valid_uuid(data["animal_id"])
    assert data["record_type"] in ("EXAM", "SPAY_NEUTER", "VACCINATION")


def assert_microchip(data: dict) -> None:
    """Microchip is immutable: id + created_at only, NO version, NO updated_at."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data["animal_id"])
    assert isinstance(data["chip_number"], str) and len(data["chip_number"]) > 0
    assert "version" not in data, "Microchip is immutable and must not carry version"
    assert "updated_at" not in data, "Microchip is immutable and must not carry updated_at"


def assert_owner_claim(data: dict) -> None:
    _assert_common(data)
    assert is_valid_uuid(data["animal_id"])
    assert isinstance(data["claimant_name"], str) and len(data["claimant_name"]) > 0
    assert data["status"] in ("PENDING", "APPROVED", "DENIED")


def assert_adopter_account(data: dict) -> None:
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str) and len(data["email"]) > 0


def assert_adoption_application(data: dict) -> None:
    _assert_common(data)
    assert is_valid_uuid(data["animal_id"])
    assert is_valid_uuid(data["adopter_id"])
    assert data["status"] in ("SUBMITTED", "APPROVED", "REJECTED", "FINALIZED", "REFUNDED")
    assert isinstance(data["estimated_fee_cents"], int)
    assert isinstance(data["refunded"], bool)


def assert_foster_home(data: dict) -> None:
    _assert_common(data)
    assert isinstance(data["contact_name"], str) and len(data["contact_name"]) > 0
    assert isinstance(data["max_concurrent"], int) and data["max_concurrent"] >= 1
    assert isinstance(data["cooldown_days"], int) and data["cooldown_days"] >= 0
    assert isinstance(data["active_placement_count"], int) and data["active_placement_count"] >= 0


def assert_foster_placement(data: dict) -> None:
    _assert_common(data)
    assert is_valid_uuid(data["foster_home_id"])
    assert is_valid_uuid(data["animal_id"])
    assert is_iso8601_timestamp(data["start_at"])
    assert data["status"] in ("ACTIVE", "RETURNED")


def assert_euthanasia_decision(data: dict) -> None:
    _assert_common(data)
    assert is_valid_uuid(data["animal_id"])
    assert data["reason"] in ("MEDICAL_UNTREATABLE", "BEHAVIORAL", "COURT_ORDER")
    assert data["status"] in ("REQUESTED", "APPROVED", "REJECTED", "EXECUTED")


# ─── Domain invariant checkers ────────────────────────

def assert_kennel_occupancy_invariant(kennel: dict) -> None:
    """occupied_count within [0, capacity]; status derived from the two."""
    assert 0 <= kennel["occupied_count"] <= kennel["capacity"], (
        f"occupied_count {kennel['occupied_count']} out of [0, {kennel['capacity']}]"
    )
    if kennel["occupied_count"] == kennel["capacity"]:
        assert kennel["status"] == "FULL", "status must be FULL at capacity"
    else:
        assert kennel["status"] == "OPEN", "status must be OPEN below capacity"


def assert_foster_home_occupancy_invariant(home: dict) -> None:
    """active_placement_count within [0, max_concurrent]."""
    assert 0 <= home["active_placement_count"] <= home["max_concurrent"], (
        f"active_placement_count {home['active_placement_count']} "
        f"out of [0, {home['max_concurrent']}]"
    )
