"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

OWNER_STATUSES = ["ACTIVE", "DELINQUENT"]
PET_STATUSES = ["ACTIVE", "DECEASED"]
SPECIES = ["DOG", "CAT"]
VACCINE_TYPES = ["RABIES", "DHPP", "FVRCP"]
KENNEL_STATUSES = ["OPEN", "SUSPENDED"]
LICENSE_KINDS = ["INDIVIDUAL", "KENNEL"]
LICENSE_STATUSES = [
    "DRAFT", "SUBMITTED", "UNDER_REVIEW", "NEEDS_VACCINATION_PROOF",
    "APPROVED", "ACTIVE", "GRACE", "EXPIRED", "REJECTED", "REVOKED",
]
TAG_STATUSES = ["ISSUED", "SUPERSEDED", "VOID"]
DDC_SEVERITIES = ["BITE", "ATTACK", "NUISANCE"]
DDC_STATUSES = [
    "REPORTED", "INVESTIGATING", "DESIGNATED", "APPEALED", "OVERTURNED", "DISMISSED",
]
REPORT_TYPES = ["LOST", "FOUND"]
LOST_FOUND_STATUSES = ["OPEN", "MATCHED", "RESOLVED", "CLOSED"]


def _assert_common_full(data: dict):
    """id + created_at + updated_at + version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_common_immutable(data: dict):
    """Immutable records carry only id + created_at (PRD §2.4) — no version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "immutable record must not carry a version field"
    assert "updated_at" not in data, "immutable record must not carry updated_at"


def assert_owner(data: dict):
    _assert_common_full(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert data["status"] in OWNER_STATUSES, f"unexpected owner status {data['status']}"
    assert isinstance(data["active_license_count"], int)
    assert data["active_license_count"] >= 0
    assert isinstance(data["outstanding_penalty_cents"], int)
    assert data["outstanding_penalty_cents"] >= 0


def assert_pet(data: dict):
    _assert_common_full(data)
    assert data["species"] in SPECIES
    assert isinstance(data["is_altered"], bool)
    assert isinstance(data["is_dangerous"], bool)
    assert data["status"] in PET_STATUSES


def assert_vaccination_record(data: dict):
    _assert_common_immutable(data)
    assert data["vaccine_type"] in VACCINE_TYPES


def assert_kennel(data: dict):
    _assert_common_full(data)
    assert isinstance(data["slot_capacity"], int) and data["slot_capacity"] >= 1
    assert isinstance(data["occupied_slots"], int) and data["occupied_slots"] >= 0
    assert data["status"] in KENNEL_STATUSES


def assert_license(data: dict):
    _assert_common_full(data)
    assert data["license_kind"] in LICENSE_KINDS
    assert data["term_years"] in (1, 3)
    assert data["status"] in LICENSE_STATUSES
    assert isinstance(data["provisional_fee_cents"], int)
    assert isinstance(data["final_fee_cents"], int)
    assert isinstance(data["late_penalty_cents"], int)
    assert isinstance(data["penalty_paid"], bool)


def assert_tag(data: dict):
    _assert_common_full(data)
    assert data["status"] in TAG_STATUSES


def assert_dangerous_dog_case(data: dict):
    _assert_common_full(data)
    assert data["severity"] in DDC_SEVERITIES
    assert data["status"] in DDC_STATUSES
    assert isinstance(data["surcharge_cents"], int)


def assert_lost_found_report(data: dict):
    _assert_common_full(data)
    assert data["report_type"] in REPORT_TYPES
    assert data["species"] in SPECIES
    assert data["status"] in LOST_FOUND_STATUSES
    assert isinstance(data["match_score"], int)
