"""Entity assertions and domain invariant checkers (PRD §2.2, §2.4, §3)."""
from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp,
)


# ---------------------------------------------------------------------------
# Common-field helpers
# ---------------------------------------------------------------------------
def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be an integer >= 1, got {data.get('version')!r}"


def _assert_immutable_common(data: dict):
    """Immutable records (health records, weather assessments, ledger entries)
    carry only id and created_at (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


# ---------------------------------------------------------------------------
# Per-entity assertions
# ---------------------------------------------------------------------------
def assert_customer(data: dict):
    _assert_common(data)
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["customer_type"] in ["PRIVATE", "SCHOOL", "LIBRARY"]


def assert_venue(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("customer_id", "")), "customer_id must be a UUID"
    assert data["venue_type"] in ["INDOOR", "OUTDOOR", "MIXED"]
    assert isinstance(data["water_access"], bool)
    assert data["surface_type"] in ["GRASS", "PAVEMENT", "INDOOR_FLOOR"]
    assert data["travel_zone"] in ["ZONE_A", "ZONE_B", "ZONE_C"]
    assert isinstance(data["distance_miles"], int) and data["distance_miles"] >= 0
    assert isinstance(data["max_guest_capacity"], int) and data["max_guest_capacity"] > 0
    assert isinstance(data["requires_animal_permit"], bool)
    assert isinstance(data["requires_handwash_stations"], bool)


def assert_animal(data: dict):
    _assert_common(data)
    assert data["species"] in ["GOAT", "SHEEP", "PONY", "RABBIT", "CHICKEN", "REPTILE"]
    assert data["weight_class"] in ["SMALL", "MEDIUM", "LARGE"]
    assert isinstance(data["temperament_tier"], int) and 1 <= data["temperament_tier"] <= 3
    assert isinstance(data["base_event_fee_cents"], int) and data["base_event_fee_cents"] >= 0
    assert isinstance(data["rest_buffer_hours"], int) and data["rest_buffer_hours"] >= 0
    assert data["status"] in ["AVAILABLE", "QUARANTINE", "RETIRED"]


def assert_health_record(data: dict):
    _assert_immutable_common(data)
    assert is_valid_uuid(data.get("animal_id", "")), "animal_id must be a UUID"
    assert data["result"] in ["PASS", "FAIL"]
    assert "updated_at" not in data, "immutable records carry no updated_at (PRD §2.4)"
    assert "version" not in data, "immutable records carry no version (PRD §2.4)"


def assert_handler(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["certifications"], list)
    for cert in data["certifications"]:
        assert cert in ["REPTILE_CERTIFIED", "PONY_RIDE_CERTIFIED", "FIRST_AID"]
    assert data["status"] in ["ACTIVE", "INACTIVE"]
    assert isinstance(data["scheduled_minutes_total"], int) \
        and data["scheduled_minutes_total"] >= 0


def assert_booking(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("customer_id", "")), "customer_id must be a UUID"
    assert is_valid_uuid(data.get("venue_id", "")), "venue_id must be a UUID"
    assert data["status"] in [
        "DRAFT", "QUOTED", "CONFIRMED", "WEATHER_HOLD", "EN_ROUTE", "ON_SITE_SETUP",
        "IN_PROGRESS", "COMPLETED", "INVOICED",
        "CANCELLED_CUSTOMER", "CANCELLED_WEATHER", "CANCELLED_COMPLIANCE",
    ]
    assert data["payment_status"] in [
        "UNPAID", "DEPOSIT_PAID", "PAID_IN_FULL",
        "REFUND_PARTIAL", "REFUND_FULL", "FORFEITED",
    ]
    assert data["booking_type"] in ["PRIVATE_PARTY", "SCHOOL_PROGRAM", "LIBRARY_PROGRAM"]
    assert isinstance(data["guest_count"], int) and data["guest_count"] >= 0
    assert isinstance(data["child_guest_count"], int) and data["child_guest_count"] >= 0
    assert isinstance(data["planned_handwash_stations"], int)
    assert isinstance(data["quote_fresh"], bool)
    assert isinstance(data["total_paid_cents"], int) and data["total_paid_cents"] >= 0


def assert_booking_animal(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("booking_id", "")), "booking_id must be a UUID"
    assert is_valid_uuid(data.get("animal_id", "")), "animal_id must be a UUID"
    assert data["role"] in ["PETTING_ZOO", "PONY_RIDE", "REPTILE_SHOW"]
    assert data["status"] in ["PROPOSED", "CONFIRMED", "REMOVED"]


def assert_staff_assignment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("booking_id", "")), "booking_id must be a UUID"
    assert is_valid_uuid(data.get("handler_id", "")), "handler_id must be a UUID"
    assert data["role"] in ["LEAD", "ASSISTANT"]
    assert data["status"] in ["ASSIGNED", "RELEASED", "COMPLETED"]


def assert_addon_request(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("booking_id", "")), "booking_id must be a UUID"
    assert data["addon_type"] in ["PONY_RIDE", "REPTILE_SHOW"]
    assert isinstance(data["duration_minutes"], int) and data["duration_minutes"] > 0
    assert data["status"] in ["REQUESTED", "APPROVED", "DENIED", "REMOVED"]


def assert_permit(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("booking_id", "")), "booking_id must be a UUID"
    assert data["permit_type"] in ["ANIMAL_EXHIBITION", "HEALTH_DEPT", "FIRE_SAFETY"]
    assert isinstance(data["jurisdiction"], str) and len(data["jurisdiction"]) > 0
    assert data["status"] in ["DRAFT", "SUBMITTED", "ISSUED", "DENIED"]


def assert_waiver(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("booking_id", "")), "booking_id must be a UUID"
    assert isinstance(data["required_signatures"], int) and data["required_signatures"] >= 0
    assert isinstance(data["signed_count"], int) and data["signed_count"] >= 0
    assert data["signed_count"] <= data["required_signatures"], \
        "signed_count may never exceed required_signatures"
    assert data["status"] in ["PENDING", "PARTIAL", "COMPLETE"]


def assert_insurance_certificate(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("customer_id", "")), "customer_id must be a UUID"
    assert isinstance(data["provider"], str) and len(data["provider"]) > 0
    assert isinstance(data["policy_number"], str) and len(data["policy_number"]) > 0
    assert isinstance(data["coverage_amount_cents"], int)
    assert data["status"] in ["SUBMITTED", "VERIFIED", "REJECTED"]


def assert_weather_assessment(data: dict):
    _assert_immutable_common(data)
    assert is_valid_uuid(data.get("booking_id", "")), "booking_id must be a UUID"
    assert isinstance(data["forecast_temp_f"], int)
    assert isinstance(data["forecast_precip_pct"], int) \
        and 0 <= data["forecast_precip_pct"] <= 100
    assert isinstance(data["wind_mph"], int)
    assert data["verdict"] in ["PROCEED", "HOLD_RECOMMENDED", "MANDATORY_HOLD"]
    assert "updated_at" not in data, "immutable records carry no updated_at (PRD §2.4)"
    assert "version" not in data, "immutable records carry no version (PRD §2.4)"


def assert_ledger_entry(data: dict):
    _assert_immutable_common(data)
    assert is_valid_uuid(data.get("booking_id", "")), "booking_id must be a UUID"
    assert data["entry_type"] in ["PAYMENT", "REFUND", "FORFEIT", "PENALTY", "CHARGE"]
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0
    assert "updated_at" not in data, "immutable records carry no updated_at (PRD §2.4)"
    assert "version" not in data, "immutable records carry no version (PRD §2.4)"


# ---------------------------------------------------------------------------
# Ledger domain helpers (PRD §2.10)
# ---------------------------------------------------------------------------
def entries_of_type(entries: list, entry_type: str) -> list:
    return [e for e in entries if e.get("entry_type") == entry_type]


def sum_of_type(entries: list, entry_type: str) -> int:
    return sum(e["amount_cents"] for e in entries_of_type(entries, entry_type))


def assert_booking_money_invariants(booking: dict):
    """Invariants that must hold for any booking carrying money (PRD §2.5, §2.10)."""
    assert isinstance(booking["total_paid_cents"], int) and booking["total_paid_cents"] >= 0
    if booking.get("deposit_amount_cents") is not None:
        assert isinstance(booking["deposit_amount_cents"], int)
        assert booking["deposit_amount_cents"] >= 0
    if booking.get("quoted_total_cents") is not None:
        assert isinstance(booking["quoted_total_cents"], int)
    if booking.get("final_total_cents") is not None:
        assert isinstance(booking["final_total_cents"], int)
