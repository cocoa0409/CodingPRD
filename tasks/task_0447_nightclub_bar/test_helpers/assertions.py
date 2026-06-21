"""Entity assertions and domain invariant checkers (Nightclub & Bar Service)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


_VERSIONED_COMMON = ("id", "created_at", "updated_at", "version")


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_venue(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["fire_code_capacity"], int) and data["fire_code_capacity"] >= 1
    assert isinstance(data["last_call_offset_minutes"], int) and data["last_call_offset_minutes"] >= 0
    assert isinstance(data["cover_base_cents"], int) and data["cover_base_cents"] >= 0
    assert 0 <= data["cover_surge_pct"] <= 2
    assert isinstance(data["max_alcohol_strikes"], int) and data["max_alcohol_strikes"] >= 1
    assert isinstance(data["occupancy_count"], int) and data["occupancy_count"] >= 0
    assert isinstance(data["tabs_open_count"], int) and data["tabs_open_count"] >= 0
    assert data["posture"] in ("OPEN", "AT_CAPACITY", "LAST_CALL", "CLOSED")


def assert_promoter(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["venue_id"])
    assert isinstance(data["name"], str)
    assert isinstance(data["comp_budget_cents"], int) and data["comp_budget_cents"] >= 0
    assert 0 <= data["guest_discount_pct"] <= 1
    assert isinstance(data["comp_committed_cents"], int) and data["comp_committed_cents"] >= 0
    assert isinstance(data["heads_credited"], int) and data["heads_credited"] >= 0


def assert_guest_list_entry(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["venue_id"])
    assert isinstance(data["guest_name"], str)
    assert isinstance(data["party_size"], int) and data["party_size"] >= 1
    assert isinstance(data["comp_value_cents"], int) and data["comp_value_cents"] >= 0
    assert data["status"] in ("CONFIRMED", "REDEEMED", "CANCELLED")


def assert_reservation(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["venue_id"])
    assert isinstance(data["table_label"], str)
    assert isinstance(data["party_size"], int) and data["party_size"] >= 1
    assert isinstance(data["spend_minimum_cents"], int) and data["spend_minimum_cents"] >= 0
    assert isinstance(data["deposit_cents"], int) and data["deposit_cents"] >= 0
    assert data["status"] in ("BOOKED", "SEATED", "SETTLED", "NO_SHOW", "CANCELLED")


def assert_tab(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["venue_id"])
    assert isinstance(data["patron_name"], str)
    assert isinstance(data["preauth_cents"], int) and data["preauth_cents"] >= 0
    assert 0 <= data["gratuity_pct"] <= 1
    assert isinstance(data["running_subtotal_cents"], int) and data["running_subtotal_cents"] >= 0
    assert isinstance(data["final_total_cents"], int) and data["final_total_cents"] >= 0
    assert isinstance(data["bac_strikes"], int) and data["bac_strikes"] >= 0
    assert data["status"] in ("OPEN", "RUNNING", "SETTLED", "VOIDED")


def assert_tab_item(data: dict):
    """TabItem is append-only: id + created_at only; NO updated_at, NO version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["name"], str)
    assert data["category"] in ("ALCOHOL", "FOOD", "NA_BEVERAGE", "SERVICE")
    assert isinstance(data["qty"], int) and data["qty"] >= 1
    assert isinstance(data["unit_price_cents"], int) and data["unit_price_cents"] >= 0
    assert isinstance(data["voided"], bool)


def assert_entry(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["venue_id"])
    assert is_valid_uuid(data["id_check_id"])
    assert isinstance(data["cover_paid_cents"], int) and data["cover_paid_cents"] >= 0
    assert data["status"] in ("INSIDE", "EXITED", "EJECTED")


def assert_id_check(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["venue_id"])
    assert isinstance(data["patron_name"], str)
    assert isinstance(data["computed_age_years"], int)
    assert data["outcome"] in ("PASS", "REFUSED_UNDERAGE", "REFUSED_EXPIRED_ID")


def assert_security_incident(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["venue_id"])
    assert data["severity"] in ("MINOR", "SERIOUS", "CRITICAL")
    assert data["action"] in ("WARNING", "EJECTION", "REFUSAL_SERVICE")
    assert isinstance(data["narrative"], str)
