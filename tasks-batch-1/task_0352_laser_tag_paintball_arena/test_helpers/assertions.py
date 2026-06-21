"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """Common-field discipline shared by every entity (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_arena(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["status"] in ("OPEN", "CLOSED")
    assert isinstance(data["marker_pool_total"], int) and data["marker_pool_total"] >= 0
    assert isinstance(data["vest_pool_total"], int) and data["vest_pool_total"] >= 0
    assert isinstance(data["marker_available_count"], int)
    assert isinstance(data["vest_available_count"], int)
    assert isinstance(data["deposit_held_cents"], int)
    assert isinstance(data["deposit_refunded_cents"], int)
    assert isinstance(data["deposit_forfeited_cents"], int)


def assert_arena_ledger_invariants(data: dict):
    """Deposit-ledger conservation invariants (PRD §2.7)."""
    assert data["deposit_held_cents"] >= 0
    assert data["deposit_refunded_cents"] >= 0
    assert data["deposit_forfeited_cents"] >= 0
    assert data["marker_available_count"] >= 0
    assert data["vest_available_count"] >= 0


def assert_field(data: dict):
    _assert_common(data)
    assert isinstance(data["arena_id"], str)
    assert data["game_mode"] in ("LASER_TAG", "PAINTBALL")
    assert isinstance(data["capacity_max"], int) and data["capacity_max"] >= 1
    assert isinstance(data["turnaround_minutes"], int) and data["turnaround_minutes"] >= 0
    assert isinstance(data["reserved_headcount"], int) and data["reserved_headcount"] >= 0
    assert data["status"] in ("ACTIVE", "CLOSED")


def assert_party_package(data: dict):
    _assert_common(data)
    assert isinstance(data["included_players"], int) and data["included_players"] >= 1
    assert isinstance(data["extra_player_fee_cents"], int) and data["extra_player_fee_cents"] >= 0
    assert isinstance(data["base_fee_cents"], int) and data["base_fee_cents"] >= 0
    assert isinstance(data["active"], bool)
    assert 0 <= data["discount_pct"] < 1


def assert_booking(data: dict):
    _assert_common(data)
    assert data["booking_type"] in ("RESERVATION", "WALK_IN")
    assert isinstance(data["party_size"], int) and data["party_size"] >= 1
    assert data["status"] in (
        "HELD", "CONFIRMED", "CHECKED_IN", "COMPLETED", "NO_SHOW", "CANCELLED"
    )
    assert is_iso8601_timestamp(data["window_start"])
    assert is_iso8601_timestamp(data["window_end"])
    assert isinstance(data["minors_present"], bool)
    assert isinstance(data["referee_required"], bool)


def assert_waiver_profile(data: dict):
    _assert_common(data)
    assert isinstance(data["participant_name"], str)
    assert isinstance(data["age_years"], int)
    assert isinstance(data["is_minor"], bool)
    assert data["status"] in ("DRAFT", "SIGNED", "VOID")


def assert_equipment_unit(data: dict):
    _assert_common(data)
    assert data["unit_type"] in ("MARKER", "VEST")
    assert data["condition_grade"] in ("A", "B", "C")
    assert isinstance(data["deposit_cents"], int) and data["deposit_cents"] >= 0
    assert data["status"] in ("AVAILABLE", "RESERVED", "CHECKED_OUT", "MAINTENANCE")


def assert_rental(data: dict):
    _assert_common(data)
    assert isinstance(data["deposit_hold_cents"], int) and data["deposit_hold_cents"] >= 0
    assert data["status"] in ("HELD", "CHECKED_OUT", "RETURNED", "RELEASED")


def assert_rental_settlement_invariant(data: dict):
    """Settled deposit always sums back to the held amount (PRD §3.4)."""
    assert data["deposit_refund_cents"] + data["deposit_forfeit_cents"] == data["deposit_hold_cents"]
    assert data["deposit_refund_cents"] >= 0
    assert data["deposit_forfeit_cents"] >= 0


def assert_add_on_order(data: dict):
    _assert_common(data)
    assert isinstance(data["ammo_balls"], int) and data["ammo_balls"] >= 0
    assert isinstance(data["co2_tanks"], int) and data["co2_tanks"] >= 0
    assert isinstance(data["misc_cents"], int) and data["misc_cents"] >= 0
    assert isinstance(data["quote_total_cents"], int)
    assert data["status"] in ("QUOTED", "SETTLED", "VOID")


def assert_referee(data: dict):
    _assert_common(data)
    assert isinstance(data["certified_paintball"], bool)
    assert data["status"] in ("AVAILABLE", "ON_DUTY", "OFF_SHIFT")


def assert_referee_assignment(data: dict):
    _assert_common(data)
    assert data["status"] in ("ASSIGNED", "RELEASED")


def assert_league(data: dict):
    _assert_common(data)
    assert isinstance(data["total_rounds"], int) and data["total_rounds"] >= 1
    assert isinstance(data["current_round"], int) and data["current_round"] >= 0
    assert data["status"] in ("DRAFT", "OPEN", "ROUND_LOCKED", "FINALIZED")
    assert isinstance(data["win_points"], int) and data["win_points"] >= 0
    assert isinstance(data["draw_points"], int) and data["draw_points"] >= 0


def assert_league_match(data: dict):
    _assert_common(data)
    assert isinstance(data["home_team"], str)
    assert isinstance(data["away_team"], str)
    assert data["status"] in ("SCHEDULED", "RESULT_RECORDED", "VOID")
