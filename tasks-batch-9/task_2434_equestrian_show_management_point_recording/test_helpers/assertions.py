"""Entity-shape and ledger-invariant assertions.

Every resource type exposes the four common properties `id`, `created_at`,
`updated_at` and `version` (PRD §2.5), so each entity assertion checks those
first and then the resource-specific fields.
"""
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def assert_common_fields(data: Dict[str, Any]) -> None:
    """`id` (UUID), `created_at`/`updated_at` (ISO-8601 UTC), `version` (int >= 1)."""
    assert is_valid_uuid(data["id"]), f"id is not a UUID: {data.get('id')!r}"
    assert is_iso8601_timestamp(data["created_at"]), f"bad created_at: {data.get('created_at')!r}"
    assert is_iso8601_timestamp(data["updated_at"]), f"bad updated_at: {data.get('updated_at')!r}"
    assert isinstance(data["version"], int) and data["version"] >= 1, (
        f"version must be an integer starting at 1: {data.get('version')!r}"
    )


def _require(data: Dict[str, Any], fields: List[str]) -> None:
    missing = [f for f in fields if f not in data]
    assert not missing, f"missing fields {missing} in {sorted(data.keys())}"


def assert_show(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    _require(data, [
        "name", "federation_show_id", "venue", "competition_level", "start_utc", "end_utc",
        "entry_close_utc", "license_status", "revision_count", "prize_money_pool_cents",
        "allocated_prize_cents", "unallocated_prize_cents", "stall_capacity",
        "reserved_stall_count", "available_stall_count", "stall_fee_cents",
        "division_share_bp_total", "welfare_strike_count",
    ])


def assert_ring(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    _require(data, [
        "show_id", "name", "surface_type", "footing_condition_score", "status",
        "turnover_buffer_minutes", "warmup_capacity_horses", "slot_count",
        "scheduled_minutes_total",
    ])


def assert_division(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    _require(data, [
        "show_id", "name", "discipline", "age_group", "min_jump_height_cm",
        "max_jump_height_cm", "division_share_bp", "status", "jumpoff_enabled",
        "division_allotment_cents",
    ])


def assert_class(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    _require(data, [
        "division_id", "class_number", "name", "jump_height_cm", "entry_fee_cents",
        "class_share_bp", "max_entries", "qualifier_for_class_id", "status",
        "entry_count", "confirmed_entry_count", "estimated_minutes", "actual_minutes",
        "class_purse_cents", "awarded_prize_cents", "placed_count", "point_eligible",
    ])


def assert_ring_slot(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    _require(data, [
        "ring_id", "class_id", "slot_type", "start_utc", "duration_minutes", "end_utc",
        "warmup_start_utc", "order_index", "status",
    ])


def assert_official(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    _require(data, [
        "federation_official_id", "full_name", "license_roles", "license_level",
        "licensed_disciplines", "license_expires_on", "affiliated_trainer_name",
        "assigned_minutes",
    ])


def assert_official_assignment(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    _require(data, ["official_id", "slot_id", "official_role", "status"])


def assert_rider(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    _require(data, [
        "federation_member_number", "full_name", "membership_expires_on", "trainer_name",
        "membership_status", "national_points_total", "regional_points_total",
    ])


def assert_horse(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    _require(data, [
        "federation_registration_number", "name", "owner_name", "coggins_drawn_on",
        "coggins_expires_on", "eligibility_status",
    ])


def assert_entry(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    _require(data, [
        "show_id", "rider_id", "horse_id", "verification_status", "settlement_status",
        "requested_stall_count", "assigned_stall_count", "class_fee_cents_total",
        "stall_fee_cents", "preliminary_subtotal_cents", "office_fee_cents",
        "total_due_cents", "refunded_cents",
    ])


def assert_class_entry(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    _require(data, [
        "entry_id", "class_id", "status", "placing", "round_seconds", "prize_cents",
        "points_national", "points_regional",
    ])


def assert_point_submission(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    _require(data, [
        "class_id", "submitted_by_user_id", "national_body_reference",
        "regional_body_reference", "national_points_total", "regional_points_total",
        "status",
    ])


def assert_compliance_case(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    _require(data, [
        "entry_id", "opened_by_official_id", "case_type", "sample_code",
        "welfare_rule_code", "finding", "status",
    ])


def assert_coverage_shift(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    _require(data, [
        "show_id", "coverage_type", "provider_name", "start_utc", "end_utc", "status",
    ])


# --- conserved-quantity invariants (PRD §2.10) -------------------------------

def assert_stall_ledger_invariant(show: Dict[str, Any]) -> None:
    """`reserved_stall_count + available_stall_count == stall_capacity` at all times."""
    assert show["reserved_stall_count"] + show["available_stall_count"] == show["stall_capacity"], (
        f"stall ledger drift: reserved={show['reserved_stall_count']} "
        f"available={show['available_stall_count']} capacity={show['stall_capacity']}"
    )


def assert_prize_ledger_invariant(show: Dict[str, Any]) -> None:
    """`allocated_prize_cents + unallocated_prize_cents == prize_money_pool_cents`."""
    assert (
        show["allocated_prize_cents"] + show["unallocated_prize_cents"]
        == show["prize_money_pool_cents"]
    ), (
        f"prize ledger drift: allocated={show['allocated_prize_cents']} "
        f"unallocated={show['unallocated_prize_cents']} pool={show['prize_money_pool_cents']}"
    )


def assert_show_ledgers(show: Dict[str, Any]) -> None:
    assert_stall_ledger_invariant(show)
    assert_prize_ledger_invariant(show)


def assert_unchanged(before: Dict[str, Any], after: Dict[str, Any],
                     fields: Optional[List[str]] = None) -> None:
    """Assert the listed fields (default: all of `before`) did not move."""
    for field in (fields if fields is not None else list(before.keys())):
        assert before[field] == after[field], (
            f"{field} moved: {before[field]!r} -> {after[field]!r}"
        )
