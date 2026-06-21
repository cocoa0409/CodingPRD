"""Entity assertions and domain invariant checkers.

Uses the framework's generic validators internally. Field names are PRD-exact.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """id / created_at / updated_at / version present and well-typed."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version is int >= 1"


def assert_venue(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["posture"] in ("OPEN", "WEATHER_HOLD", "CLOSED")
    assert isinstance(data["open_slot_count"], int) and data["open_slot_count"] >= 0


def assert_attraction(data: dict):
    _assert_common(data)
    assert data["kind"] in ("GO_KART", "MINI_GOLF", "ARCADE")
    assert isinstance(data["min_height_cm"], int) and data["min_height_cm"] >= 0
    assert data["status"] == "ACTIVE"


def assert_pricing_plan(data: dict):
    _assert_common(data)
    assert data["mode"] in ("PER_ROUND", "PER_HEAT", "WRISTBAND")
    assert isinstance(data["base_price_cents"], int)
    assert data["status"] == "ACTIVE"


def assert_heat(data: dict):
    _assert_common(data)
    assert data["status"] in ("SCHEDULED", "OPEN", "CLOSED", "CANCELLED")
    assert isinstance(data["lane_capacity"], int)
    assert isinstance(data["lanes_committed"], int) and data["lanes_committed"] >= 0
    assert isinstance(data["lanes_available"], int) and data["lanes_available"] >= 0
    assert_heat_capacity_invariant(data)


def assert_tee_session(data: dict):
    _assert_common(data)
    assert data["status"] in ("SCHEDULED", "OPEN", "CLOSED", "CANCELLED")
    assert isinstance(data["party_slot_capacity"], int)
    assert isinstance(data["players_committed"], int) and data["players_committed"] >= 0
    assert isinstance(data["players_available"], int) and data["players_available"] >= 0
    assert_tee_session_capacity_invariant(data)


def assert_guest(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["waiver_status"] in ("NONE", "SIGNED", "EXPIRED")


def assert_waiver(data: dict):
    """Waiver is immutable: carries only id + created_at (no updated_at/version)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data.get("guest_id", "")), "guest_id must be a valid UUID"


def assert_wallet(data: dict):
    _assert_common(data)
    assert isinstance(data["arcade_card_balance_cents"], int)
    assert data["arcade_card_balance_cents"] >= 0
    assert isinstance(data["total_loaded_cents"], int) and data["total_loaded_cents"] >= 0


def assert_combo_pass(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "EXHAUSTED")
    assert isinstance(data["total_credits"], int)
    assert isinstance(data["credits_redeemed"], int) and data["credits_redeemed"] >= 0
    assert isinstance(data["credits_remaining"], int) and data["credits_remaining"] >= 0
    assert_combo_pass_credit_invariant(data)


def assert_party_group(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "CONFIRMED", "CHECKED_IN", "COMPLETED", "CANCELLED")
    assert isinstance(data["units_consumed"], int) and data["units_consumed"] >= 0


def assert_booking(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "HOLD", "CONFIRMED", "WAITLISTED", "CHECKED_IN", "COMPLETED", "CANCELLED", "NO_SHOW"
    )
    assert data["slot_kind"] in ("HEAT", "TEE_SESSION")
    assert data["origin"] in ("RESERVATION", "WALK_IN")
    assert isinstance(data["party_size"], int) and data["party_size"] >= 1
    assert isinstance(data["gross_price_cents"], int)
    assert isinstance(data["credits_applied"], int) and data["credits_applied"] >= 0
    assert isinstance(data["cash_due_cents"], int) and data["cash_due_cents"] >= 0


# ─── Domain invariants ────────────────────────────────────────────────────────

def assert_heat_capacity_invariant(heat: dict):
    """lanes_committed + lanes_available == lane_capacity; available never negative."""
    assert heat["lanes_available"] >= 0, "lanes_available never negative"
    assert heat["lanes_committed"] + heat["lanes_available"] == heat["lane_capacity"], (
        f"lanes_committed ({heat['lanes_committed']}) + lanes_available "
        f"({heat['lanes_available']}) must equal lane_capacity ({heat['lane_capacity']})"
    )


def assert_tee_session_capacity_invariant(tee: dict):
    """players_committed + players_available == party_slot_capacity; never negative."""
    assert tee["players_available"] >= 0, "players_available never negative"
    assert tee["players_committed"] + tee["players_available"] == tee["party_slot_capacity"], (
        f"players_committed ({tee['players_committed']}) + players_available "
        f"({tee['players_available']}) must equal party_slot_capacity "
        f"({tee['party_slot_capacity']})"
    )


def assert_combo_pass_credit_invariant(pass_: dict):
    """credits_remaining == total_credits - credits_redeemed, floored at zero."""
    expected = max(0, pass_["total_credits"] - pass_["credits_redeemed"])
    assert pass_["credits_remaining"] == expected, (
        f"credits_remaining ({pass_['credits_remaining']}) must equal "
        f"total_credits - credits_redeemed floored at 0 ({expected})"
    )
