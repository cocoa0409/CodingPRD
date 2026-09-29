"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .types import (
    ChangeoverOrderStatus,
    DockSlotReservationStatus,
    EquipmentAssetStatus,
    EquipmentIssueStatus,
    EventBookingStatus,
    HoldChallengeStatus,
    IceDeckStatus,
    IceSheetStatus,
    LaborCallStatus,
)


def _assert_common_bookkeeping(data: dict, label: str):
    """id + created_at + updated_at + version, per PRD §2.4."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{label}.created_at must be an ISO 8601 UTC timestamp"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"{label}.updated_at must be an ISO 8601 UTC timestamp"
    assert isinstance(data.get("version"), int), f"{label}.version must be an integer"
    assert data["version"] >= 1, f"{label}.version starts at 1"


def assert_venue(data: dict):
    _assert_common_bookkeeping(data, "venue")
    assert isinstance(data["name"], str) and 1 <= len(data["name"]) <= 120
    assert float(data["rigging_capacity_kg"]) > 0
    assert 1 <= data["dock_count"] <= 8
    assert data["max_bowl_seats"] > 0
    assert 1 <= data["crew_headcount_cap"] <= 200
    assert 0 <= data["min_turnaround_buffer_minutes"] <= 240
    assert 0 <= data["dock_buffer_minutes"] <= 180
    assert 18 <= data["overnight_shift_start_local_hour"] <= 23
    assert data["ice_deck_status"] in [s.value for s in IceDeckStatus]
    assert float(data["rigging_committed_load_kg"]) >= 0
    assert data["open_hold_count"] >= 0
    assert data["changeover_debt_minutes"] >= 0


def assert_configuration_profile(data: dict):
    """A configuration profile carries only id and created_at (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "profile.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert "updated_at" not in data, "configuration profile has no updated_at field"
    assert "version" not in data, "configuration profile has no version field"
    assert data["code"] in [
        "ICE_HOCKEY",
        "COURT_BASKETBALL",
        "CONCERT_END_STAGE",
        "CONCERT_IN_ROUND",
        "FAMILY_SHOW",
    ]
    assert isinstance(data["requires_ice"], bool)
    assert isinstance(data["ice_cover_required"], bool)
    assert data["seating_mode"] in ["FULL_BOWL", "RETRACTABLE_IN", "CURTAINED_HALF"]
    assert data["nominal_seats"] > 0
    assert 30 <= data["base_changeover_minutes"] <= 1440
    assert 1 <= data["crew_size_required"] <= 200
    assert 0 <= data["floor_protection_panels_required"] <= 2000
    assert float(data["dehumidification_required_lph"]) >= 0
    assert 0 <= data["rigging_points_required"] <= 400


def assert_anchor_tenant(data: dict):
    _assert_common_bookkeeping(data, "tenant")
    assert data["hold_priority_tier"] in ["TIER_1", "TIER_2", "TIER_3"]
    assert 1 <= data["guaranteed_holds_per_season"] <= 60
    assert data["holds_consumed"] >= 0
    assert data["challenge_credits"] >= 0


def assert_event_booking(data: dict):
    _assert_common_bookkeeping(data, "booking")
    assert data["status"] in [s.value for s in EventBookingStatus]
    assert isinstance(data["title"], str) and 1 <= len(data["title"]) <= 160
    assert data["event_end_utc"] > data["event_start_utc"]
    assert data["expected_attendance"] >= 0
    assert float(data["rigging_load_kg"]) >= 0
    assert data["displacement_penalty_cents"] >= 0
    if data.get("hold_tier") is not None:
        assert data["hold_tier"] in ["TIER_1", "TIER_2", "TIER_3", "OPEN"]


def assert_hold_challenge(data: dict):
    _assert_common_bookkeeping(data, "challenge")
    assert data["status"] in [s.value for s in HoldChallengeStatus]
    assert -3 <= data["priority_delta"] <= 3


def assert_changeover_order(data: dict):
    _assert_common_bookkeeping(data, "order")
    assert data["status"] in [s.value for s in ChangeoverOrderStatus]
    assert data["floor_stage"] in ["NOT_STARTED", "STRIKING", "LAYING", "FLOOR_COMPLETE"]
    assert data["seating_stage"] in [
        "NOT_STARTED",
        "RETRACTING",
        "CURTAINING",
        "SEATING_COMPLETE",
    ]
    assert data["infra_stage"] in [
        "NOT_STARTED",
        "UTILITY_SET",
        "NETWORK_SET",
        "BROADCAST_READY",
    ]
    assert isinstance(data["overnight_shift"], bool)
    assert data["window_minutes"] >= 0
    assert data["planned_turnaround_minutes"] >= 0
    assert data["overrun_minutes"] >= 0
    assert data["rework_count"] >= 0


def assert_ice_sheet(data: dict):
    _assert_common_bookkeeping(data, "ice_sheet")
    assert data["status"] in [s.value for s in IceSheetStatus]
    assert float(data["dehumidification_lph_applied"]) >= 0
    assert float(data["required_dehumidification_lph"]) >= 0
    assert 18 <= float(data["sheet_thickness_mm"]) <= 45
    assert data["cover_cycles"] >= 0
    assert float(data["cover_hours_accumulated"]) >= 0
    assert 0 <= float(data["condensation_risk_score"]) <= 100


def assert_dock_slot_reservation(data: dict):
    _assert_common_bookkeeping(data, "reservation")
    assert data["status"] in [s.value for s in DockSlotReservationStatus]
    assert data["purpose"] in ["LOAD_IN", "LOAD_OUT"]
    assert 1 <= data["truck_count"] <= 60
    assert data["window_end_utc"] > data["window_start_utc"]


def assert_labor_call(data: dict):
    _assert_common_bookkeeping(data, "labor_call")
    assert data["status"] in [s.value for s in LaborCallStatus]
    assert data["craft"] in [
        "STAGEHAND",
        "RIGGER",
        "ICE_TECH",
        "ELECTRICIAN",
        "CONVERSION_CREW",
    ]
    assert 1 <= data["headcount"] <= 200
    assert data["call_end_utc"] > data["call_start_utc"]
    assert 0 <= float(data["guaranteed_hours"]) <= 12
    assert isinstance(data["overnight"], bool)
    assert isinstance(data["estimated_cost_cents"], int)
    assert data["estimated_cost_cents"] >= 0


def assert_equipment_asset(data: dict):
    _assert_common_bookkeeping(data, "asset")
    assert data["status"] in [s.value for s in EquipmentAssetStatus]
    assert 1 <= data["units_total"] <= 500
    assert 1 <= data["service_interval_cycles"] <= 200
    assert data["units_available"] >= 0
    assert data["units_out_of_service"] >= 0
    assert data["cycles_since_service"] >= 0
    assert isinstance(data["service_due"], bool)


def assert_equipment_issue(data: dict):
    _assert_common_bookkeeping(data, "issue")
    assert data["status"] in [s.value for s in EquipmentIssueStatus]
    assert data["units_issued"] >= 1
    assert data["damaged_units"] >= 0
    assert data["damaged_units"] <= data["units_issued"]


# --------------------------------------------------------------------------
# Domain invariant checkers
# --------------------------------------------------------------------------
def assert_equipment_pool_conserved(asset: dict, outstanding_issued_units: int):
    """available + outstanding issued + out-of-service == units_total (PRD §3.9)."""
    total = (
        asset["units_available"]
        + outstanding_issued_units
        + asset["units_out_of_service"]
    )
    assert total == asset["units_total"], (
        f"Expected units_available {asset['units_available']} + issued "
        f"{outstanding_issued_units} + out_of_service {asset['units_out_of_service']} "
        f"== units_total {asset['units_total']}, got {total}"
    )


def assert_no_version_field(data: dict):
    assert "version" not in data, "this resource must not expose a version field"
    assert "updated_at" not in data, "this resource must not expose an updated_at field"


def assert_iso_millis(value: str, expected: str):
    """Compare an ISO 8601 UTC instant carrying three fractional digits."""
    assert value == expected, f"Expected timestamp {expected}, got {value}"


def assert_blocking_reasons_ordered(reasons, declared_order):
    """blocking_reasons appear in the fixed PRD order (PRD §3.8)."""
    positions = [declared_order.index(r) for r in reasons]
    assert positions == sorted(positions), (
        f"blocking_reasons {reasons} are not in the declared order {declared_order}"
    )
