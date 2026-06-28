"""Entity assertions and domain invariant checkers.

Each assert_{entity}() validates the response structure against the PRD contract.
Append-only entities (Inspection, Feeding) must NOT carry updated_at / version.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

_HEALTH = ["HEALTHY", "TREATMENT", "QUARANTINE", "DEADOUT"]
_QUEEN = ["QUEENRIGHT", "QUEENLESS", "REQUEENING"]


def _common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_apiary(data: dict):
    _common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["state_code"], str)
    assert data["registration_status"] in [
        "UNREGISTERED", "PENDING", "ACTIVE", "EXPIRED"]
    assert isinstance(data["active_colony_count"], int)
    assert data["active_colony_count"] >= 0
    assert isinstance(data["max_yard_colonies"], int)
    assert data["max_yard_colonies"] >= 1


def assert_state_registration(data: dict):
    _common(data)
    assert is_valid_uuid(data["apiary_id"])
    assert isinstance(data["registration_number"], str)
    assert data["status"] in ["PENDING", "ACTIVE", "EXPIRED", "REVOKED"]


def assert_hive(data: dict):
    _common(data)
    assert is_valid_uuid(data["apiary_id"])
    assert isinstance(data["tag"], str) and len(data["tag"]) > 0
    assert data["health_status"] in _HEALTH
    assert data["queen_status"] in _QUEEN
    assert isinstance(data["brood_frames"], int) and data["brood_frames"] >= 0
    assert isinstance(data["honey_frames"], int) and data["honey_frames"] >= 0
    assert isinstance(data["inspection_strength"], int)
    assert 0 <= data["inspection_strength"] <= 100


def assert_inspection(data: dict):
    # Append-only: id + created_at only; no updated_at / version.
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    assert is_valid_uuid(data["hive_id"])
    assert isinstance(data["treatment_recommended"], bool)


def assert_inspection_is_append_only(data: dict):
    """Inspection carries no version field (PRD §2.4)."""
    assert "version" not in data, "Inspection must not carry a version field"


def assert_treatment(data: dict):
    _common(data)
    assert is_valid_uuid(data["hive_id"])
    assert data["product"] in ["APIVAR", "FORMIC_PRO", "OXALIC_ACID"]
    assert data["status"] in ["ACTIVE", "COMPLETED", "VOIDED"]


def assert_honey_lot(data: dict):
    _common(data)
    assert is_valid_uuid(data["apiary_id"])
    assert isinstance(data["lot_code"], str)
    assert data["floral_source"] in [
        "WILDFLOWER", "ALMOND", "CLOVER", "ORANGE_BLOSSOM"]
    assert data["status"] in ["DRAFT", "BLOCKED", "EXTRACTED", "SOLD", "VOIDED"]
    assert data["gross_weight_kg"] >= 0
    assert data["provisional_yield_kg"] >= 0


def assert_harvest(data: dict):
    _common(data)
    assert is_valid_uuid(data["lot_id"])
    assert is_valid_uuid(data["hive_id"])
    assert data["status"] in ["RECORDED", "VOID"]


def assert_contract(data: dict):
    _common(data)
    assert isinstance(data["grower_name"], str)
    assert data["status"] in [
        "DRAFT", "SIGNED", "PLACED", "UNDERSTAFFED",
        "FULFILLED", "DISPUTED", "CANCELLED"]
    assert isinstance(data["placed_strong_hives"], int)
    assert isinstance(data["projected_payout_cents"], int)


def assert_placement(data: dict):
    _common(data)
    assert is_valid_uuid(data["contract_id"])
    assert is_valid_uuid(data["hive_id"])
    assert data["status"] in ["PROPOSED", "CONFIRMED", "REMOVED", "CANCELLED"]


def assert_sale(data: dict):
    _common(data)
    assert is_valid_uuid(data["apiary_id"])
    assert is_valid_uuid(data["source_hive_id"])
    assert data["product_type"] in ["QUEEN", "NUC"]
    assert data["status"] in ["RESERVED", "SHIPPED", "VOIDED"]


def assert_requeen_schedule(data: dict):
    _common(data)
    assert is_valid_uuid(data["hive_id"])
    assert data["status"] in ["SCHEDULED", "COMPLETED", "CANCELLED"]


def assert_feeding(data: dict):
    # Append-only: id + created_at only.
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    assert is_valid_uuid(data["hive_id"])


# ─── Domain invariant checkers ──────────────────────────────────────────
def assert_colony_count_invariant(apiary: dict, expected: int):
    """PRD §2.9: active_colony_count == count of non-DEADOUT hives in the yard."""
    assert apiary["active_colony_count"] == expected, (
        f"Expected active_colony_count {expected}, got "
        f"{apiary['active_colony_count']}")
    assert apiary["active_colony_count"] >= 0
