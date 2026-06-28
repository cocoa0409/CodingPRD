"""Entity assertions and domain invariant checkers (PRD §2.4, §3).

These validate response structure and types against the PRD contract. Numeric
field VALUES that depend on PRD calculations are asserted in the test bodies
(from the design-index precomputed literals), not here.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """Every persisted resource carries id + created_at + updated_at + version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID with no type prefix"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version begins at 1 on creation"


def assert_menu_item(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["tier"] in ("MYERS", "NAD", "IMMUNITY")
    assert isinstance(data["base_price_cents"], int) and data["base_price_cents"] >= 0
    assert isinstance(data["requires_standing_order"], bool)
    assert isinstance(data["g6pd_sensitive"], bool)
    assert isinstance(data["active"], bool)


def assert_add_on(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["code"] in ("GLUTATHIONE", "B12", "ZOFRAN", "TORADOL", "VITC_HIGH")
    assert isinstance(data["price_cents"], int) and data["price_cents"] >= 0
    assert isinstance(data["active"], bool)


def assert_patient(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["open_adverse_event_count"], int)
    assert data["open_adverse_event_count"] >= 0


def assert_membership(data: dict):
    _assert_common(data)
    assert data["tier"] in ("NONE", "GOLD", "PLATINUM")
    assert data["covered_drip_tier"] in ("MYERS", "NAD", "IMMUNITY")
    assert isinstance(data["drip_credits_total"], int)
    assert isinstance(data["drip_credits_remaining"], int)
    assert isinstance(data["addon_credits_total"], int)
    assert isinstance(data["addon_credits_remaining"], int)
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    # Credit balances may never go below zero (PRD §3.11).
    assert data["drip_credits_remaining"] >= 0
    assert data["addon_credits_remaining"] >= 0


def assert_standing_order(data: dict):
    _assert_common(data)
    assert isinstance(data["medical_director_user_id"], str)
    assert data["covered_tier"] in ("MYERS", "NAD", "IMMUNITY")
    assert is_iso8601_timestamp(data["effective_from"])
    assert is_iso8601_timestamp(data["expires_at"])
    assert data["status"] in ("DRAFT", "ACTIVE", "EXPIRED", "REVOKED")


def assert_nurse(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["license_number"], str) and len(data["license_number"]) > 0
    assert data["status"] in ("AVAILABLE", "OFF_DUTY")


def assert_lounge(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["bay_count"], int) and data["bay_count"] >= 1
    assert isinstance(data["open_minute_of_day"], int)
    assert isinstance(data["close_minute_of_day"], int)


def assert_appointment(data: dict):
    _assert_common(data)
    assert isinstance(data["patient_id"], str)
    assert isinstance(data["menu_item_id"], str)
    assert isinstance(data["addon_ids"], list)
    assert data["location_type"] in ("LOUNGE", "MOBILE")
    assert data["status"] in (
        "REQUESTED", "SCREEN_PENDING", "REQUIRES_MD_REVIEW", "SCHEDULED",
        "DISPATCHED", "IN_PROGRESS", "COMPLETED", "DECLINED", "CANCELLED",
    )
    assert isinstance(data["drip_credit_used"], int)
    assert isinstance(data["addon_credits_used"], int)


def assert_intake_screening(data: dict):
    _assert_common(data)
    assert isinstance(data["appointment_id"], str)
    assert isinstance(data["author_user_id"], str)
    assert isinstance(data["contraindication_score"], int)
    assert data["outcome"] in ("CLEARED", "REQUIRES_MD_REVIEW", "BLOCKED")
    assert data["status"] in ("SUBMITTED", "SUPERSEDED")


def assert_consent(data: dict):
    _assert_common(data)
    assert isinstance(data["appointment_id"], str)
    assert isinstance(data["witness_user_id"], str)
    assert data["status"] in ("SIGNED", "REVOKED")


def assert_supply_lot(data: dict):
    _assert_common(data)
    assert data["item_kind"] in ("DRIP_BASE", "ADDON")
    assert isinstance(data["tier_or_code"], str)
    assert isinstance(data["units_total"], int) and data["units_total"] >= 1
    assert isinstance(data["units_reserved"], int) and data["units_reserved"] >= 0
    assert isinstance(data["units_consumed"], int) and data["units_consumed"] >= 0
    assert data["status"] in ("AVAILABLE", "EXHAUSTED", "EXPIRED", "QUARANTINED")
    # Conservation: reserved + consumed never exceeds total (PRD §2.9).
    assert data["units_reserved"] + data["units_consumed"] <= data["units_total"]


def assert_dispatch_route(data: dict):
    _assert_common(data)
    assert isinstance(data["nurse_id"], str)
    assert is_iso8601_timestamp(data["service_date"])
    assert isinstance(data["turnaround_minutes"], int) and data["turnaround_minutes"] >= 0
    assert isinstance(data["stop_count"], int) and data["stop_count"] >= 0
    assert data["status"] in ("PLANNING", "LOCKED", "CLOSED")


def assert_adverse_event(data: dict):
    _assert_common(data)
    assert isinstance(data["appointment_id"], str)
    assert isinstance(data["reported_by_user_id"], str)
    assert data["severity"] in ("MILD", "MODERATE", "SEVERE")
    assert data["status"] in ("REPORTED", "UNDER_REVIEW", "RESOLVED")
