"""Entity assertions and domain invariant checkers.

All field names are PRD-exact. Append-only records (WeightRecord, TraceEvent)
are asserted to carry id + created_at and NOT version / updated_at.
"""
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
)

LIFE_STATES = ["ACTIVE", "SUSPENDED", "SOLD", "DEAD", "CULLED"]
CLEARANCE_STATES = ["CLEAR", "WITHHELD"]


def _common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), "created_at must be ISO 8601"


def _common_versioned(data: dict):
    _common(data)
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_herd(data: dict):
    _common_versioned(data)
    assert isinstance(data["name"], str) and 1 <= len(data["name"]) <= 120
    assert data["species"] in ("CATTLE", "SHEEP", "GOAT")
    assert isinstance(data["premises_id"], str) and len(data["premises_id"]) >= 1
    assert isinstance(data["active_animal_count"], int)
    assert isinstance(data["total_au_load"], (int, float))
    assert isinstance(data["mortality_rate_pct"], (int, float))


def assert_pasture(data: dict):
    _common_versioned(data)
    assert data["kind"] in ("PASTURE", "PEN")
    assert data["capacity_au"] > 0
    assert data["current_au_load"] >= 0


def assert_drug_product(data: dict):
    _common_versioned(data)
    assert data["category"] in ("VACCINE", "ANTIBIOTIC", "ANTIPARASITIC", "HORMONE")
    assert isinstance(data["route_withdrawals"], dict)


def assert_feed_ration(data: dict):
    _common_versioned(data)
    assert data["target_dmi_kg"] > 0
    assert isinstance(data["ingredients"], list) and len(data["ingredients"]) >= 1
    assert data["status"] in ("ACTIVE", "ARCHIVED")


def assert_animal(data: dict):
    _common_versioned(data)
    assert isinstance(data["ear_tag"], str) and 1 <= len(data["ear_tag"]) <= 32
    assert data["sex"] in ("MALE", "FEMALE", "STEER")
    assert data["life_status"] in LIFE_STATES
    assert data["meat_clearance_status"] in CLEARANCE_STATES
    assert data["birth_weight_kg"] > 0
    assert isinstance(data["latest_weight_kg"], (int, float))


def assert_breeding_record(data: dict):
    _common_versioned(data)
    assert data["status"] in (
        "OPEN",
        "BRED",
        "CONFIRMED_PREGNANT",
        "CALVED",
        "FAILED",
    )


def assert_health_treatment(data: dict):
    _common_versioned(data)
    assert data["route"] in (
        "INJECTION_IM",
        "INJECTION_SC",
        "ORAL",
        "TOPICAL_POUR_ON",
        "INTRAMAMMARY",
    )
    assert data["status"] in ("WITHDRAWAL_ACTIVE", "CLEARED", "VOIDED")
    assert data["dose_count"] >= 1


def assert_movement_record(data: dict):
    _common_versioned(data)
    assert data["status"] in ("PLANNED", "APPLIED", "REVERTED")


def assert_sale_lot(data: dict):
    _common_versioned(data)
    assert data["channel"] in ("AUCTION", "PRIVATE_TREATY")
    assert data["status"] in ("OPEN", "SOLD", "WITHDRAWN")
    assert isinstance(data["head_count"], int)


def assert_weight_ticket(data: dict):
    _common_versioned(data)
    assert data["gross_weight_kg"] > 0


def assert_mortality_record(data: dict):
    _common_versioned(data)
    assert data["cause"] in ("DISEASE", "PREDATION", "ACCIDENT", "CALVING", "UNKNOWN")
    assert data["status"] in ("RECORDED", "VOIDED")


def assert_weight_record(data: dict):
    """WeightRecord is append-only history: id + created_at, NO version / updated_at."""
    _common(data)
    assert data["weight_kg"] > 0
    assert "version" not in data, "WeightRecord must not carry a version field"
    assert "updated_at" not in data, "WeightRecord must not carry updated_at"


def assert_trace_event(data: dict):
    """TraceEvent is append-only history: id + created_at, NO version / updated_at."""
    _common(data)
    assert data["event_type"] in (
        "BIRTH",
        "MOVEMENT",
        "TREATMENT",
        "SALE",
        "MORTALITY",
        "CULL",
        "SUSPEND",
        "REINSTATE",
    )
    assert "version" not in data, "TraceEvent must not carry a version field"
    assert "updated_at" not in data, "TraceEvent must not carry updated_at"
