"""Entity assertions and domain invariant checkers (PRD §2, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _common(data: dict, versioned: bool = True):
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID with no type prefix"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    if versioned:
        assert is_iso8601_timestamp(data.get("updated_at", "")), \
            "updated_at must be ISO 8601"
        assert isinstance(data.get("version"), int) and data["version"] >= 1, \
            "version must be an integer >= 1"


def assert_course(data: dict):
    _common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert 1 <= data["difficulty_level"] <= 5
    assert isinstance(data["base_price_cents"], int)


def assert_time_slot(data: dict):
    _common(data)
    assert data["status"] in ("SCHEDULED", "OPEN", "CLOSED", "COMPLETED")
    assert data["remaining_capacity"] >= 0
    assert data["booked_count"] >= 0
    assert data["remaining_capacity"] == max(0, data["capacity"] - data["booked_count"])


def assert_participant(data: dict):
    _common(data)
    assert data["waiver_status"] in ("NONE", "SIGNED", "EXPIRED")
    assert isinstance(data["age_years"], int)


def assert_season_pass(data: dict):
    _common(data)
    assert data["status"] in ("ACTIVE", "SUPERSEDED")
    assert data["uses_remaining"] >= 0
    assert data["uses_remaining"] == max(
        0, data["total_uses"] - data["uses_committed"] - data["uses_settled"])


def assert_group(data: dict):
    _common(data)
    assert data["status"] in ("OPEN", "CANCELLED")
    assert data["member_count"] >= 0
    assert data["insurance_total_cents"] >= 0


def assert_booking(data: dict):
    _common(data)
    assert data["status"] in ("CONFIRMED", "CHECKED_IN", "BRIEFED", "COMPLETED",
                              "CANCELLED", "RAINCHECKED", "NO_SHOW", "REDEEMED")
    assert isinstance(data["price_cents"], int) and data["price_cents"] >= 0
    assert data["raincheck_credit_cents"] >= 0


def assert_gear_item(data: dict):
    _common(data)
    assert data["status"] in ("AVAILABLE", "CHECKED_OUT")


def assert_gear_checkout(data: dict):
    _common(data)
    assert data["status"] in ("OUT", "RETURNED")


def assert_incident_report(data: dict):
    # Append-only: id + created_at only, no version / updated_at (PRD §2.4, §3.9).
    _common(data, versioned=False)
    assert "version" not in data, "IncidentReport must not carry a version"
    assert "updated_at" not in data, "IncidentReport must not carry updated_at"
    assert data["severity"] in ("MINOR", "MODERATE", "SEVERE")
