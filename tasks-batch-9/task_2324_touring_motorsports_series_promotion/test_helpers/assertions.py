"""Shape checkers and domain invariant checkers.

The ``assert_<entity>`` helpers verify that a payload carries the documented
fields with plausible types, including the common-field split: every resource
carries ``id`` and ``created_at``, and all of them except the immutable
inspection record also carry ``updated_at`` and ``version``.

The remaining helpers assert the invariants the PRD states must hold at all
times: the conserved seat pool, the conserved marketing budget, the readiness
posture derivation, the order money breakdown, the settlement waterfall identity
and the readiness score formula.
"""

from __future__ import annotations

import math
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from . import constants as C

# ---------------------------------------------------------------------------
# Rounding helpers
# ---------------------------------------------------------------------------


def round_half_up_cents(value: float) -> int:
    """Round a monetary product to whole cents using round-half-up."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_2dp(value: float) -> float:
    """Round a rate figure to exactly two decimal places using round-half-up."""
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Common field checks
# ---------------------------------------------------------------------------


def assert_common_fields(row: Dict[str, Any]) -> None:
    """Assert the mutable-resource common fields: id, timestamps and version."""
    assert "id" in row, "missing id"
    assert is_valid_uuid(row["id"]), f"id is not a UUID: {row['id']}"
    assert is_iso8601_timestamp(
        row["created_at"]
    ), f"created_at is not ISO 8601 UTC: {row.get('created_at')}"
    assert is_iso8601_timestamp(
        row["updated_at"]
    ), f"updated_at is not ISO 8601 UTC: {row.get('updated_at')}"
    assert isinstance(row["version"], int), "version must be an integer"
    assert row["version"] >= 1, "version starts at 1"


def assert_immutable_common_fields(row: Dict[str, Any]) -> None:
    """Assert the audit-record common fields: id and created_at only."""
    assert "id" in row, "missing id"
    assert is_valid_uuid(row["id"]), f"id is not a UUID: {row['id']}"
    assert is_iso8601_timestamp(
        row["created_at"]
    ), f"created_at is not ISO 8601 UTC: {row.get('created_at')}"
    assert "updated_at" not in row, "an immutable audit record has no updated_at"
    assert "version" not in row, "an immutable audit record has no version"


def _assert_fields(row: Dict[str, Any], names: List[str]) -> None:
    for name in names:
        assert name in row, f"missing field: {name}"


def _assert_ints(row: Dict[str, Any], names: List[str]) -> None:
    for name in names:
        assert isinstance(
            row[name], int
        ), f"{name} must be an integer number of cents/count, got {row[name]!r}"


def _assert_enum(row: Dict[str, Any], name: str, allowed: List[str]) -> None:
    assert row[name] in allowed, f"{name} must be one of {allowed}, got {row[name]!r}"


def _assert_nullable_timestamp(row: Dict[str, Any], name: str) -> None:
    value = row.get(name)
    if value is not None:
        assert is_iso8601_timestamp(value), f"{name} is not ISO 8601 UTC: {value}"


# ---------------------------------------------------------------------------
# Entity shape checkers
# ---------------------------------------------------------------------------


def assert_season(row: Dict[str, Any]) -> None:
    """Assert a season carries its calendar window, ledger and counters."""
    assert_common_fields(row)
    _assert_fields(
        row,
        [
            "name",
            "year",
            "season_start_date",
            "season_end_date",
            "market_rotation_cooldown_days",
            "total_marketing_budget_cents",
            "marketing_allocated_cents",
            "marketing_unallocated_cents",
            "booking_count",
            "settled_stop_count",
            "season_net_cents",
            "status",
        ],
    )
    _assert_ints(
        row,
        [
            "year",
            "market_rotation_cooldown_days",
            "total_marketing_budget_cents",
            "marketing_allocated_cents",
            "marketing_unallocated_cents",
            "booking_count",
            "settled_stop_count",
            "season_net_cents",
        ],
    )
    _assert_enum(row, "status", C.SEASON_STATUSES)
    assert_marketing_budget_conserved(row)


def assert_venue(row: Dict[str, Any]) -> None:
    """Assert a venue carries its capacity, floor, bays and turnaround."""
    assert_common_fields(row)
    _assert_fields(
        row,
        [
            "name",
            "market_code",
            "city",
            "state_code",
            "seat_capacity",
            "floor_type",
            "catch_fence_max_height_ft",
            "medical_bay_count",
            "load_in_hours_required",
            "staging_bay_count",
            "turnaround_hours",
        ],
    )
    _assert_ints(
        row,
        [
            "seat_capacity",
            "catch_fence_max_height_ft",
            "medical_bay_count",
            "load_in_hours_required",
            "staging_bay_count",
            "turnaround_hours",
        ],
    )
    _assert_enum(row, "floor_type", C.VENUE_FLOOR_TYPES)
    assert row["seat_capacity"] >= 1, "seat_capacity must be at least 1"


def assert_venue_booking(row: Dict[str, Any]) -> None:
    """Assert a booking carries its terms, occupancy window and negotiation state."""
    assert_common_fields(row)
    _assert_fields(
        row,
        [
            "season_id",
            "venue_id",
            "tour_date",
            "rental_base_cents",
            "revenue_share_pct",
            "per_ticket_facility_fee_cents",
            "load_in_start_utc",
            "tear_down_end_utc",
            "state",
            "negotiation_round",
            "terms_source",
        ],
    )
    _assert_ints(
        row,
        ["rental_base_cents", "per_ticket_facility_fee_cents", "negotiation_round"],
    )
    _assert_enum(row, "state", C.BOOKING_STATES)
    _assert_enum(row, "terms_source", C.TERMS_SOURCES)
    assert 0 <= row["revenue_share_pct"] <= 1, "revenue_share_pct must lie in [0, 1]"
    assert is_iso8601_timestamp(row["load_in_start_utc"])
    assert is_iso8601_timestamp(row["tear_down_end_utc"])
    _assert_nullable_timestamp(row, "confirmed_at")


def assert_tour_stop(row: Dict[str, Any]) -> None:
    """Assert a stop carries both state dimensions, the posture and its roll-ups."""
    assert_common_fields(row)
    _assert_fields(
        row,
        [
            "season_id",
            "venue_booking_id",
            "market_code",
            "event_date",
            "show_window_minutes",
            "pit_party_price_cents",
            "pit_party_capacity",
            "pit_party_sold_count",
            "sales_state",
            "safety_state",
            "readiness_posture",
            "expected_attendance",
            "competition_segment_count",
            "run_order_end_offset_minutes",
            "tickets_sold_count",
            "gross_ticket_revenue_cents",
            "addon_revenue_cents",
            "facility_fee_collected_cents",
            "marketing_spend_committed_cents",
            "sponsorship_committed_cents",
            "held_hospitality_seat_count",
            "haul_distance_miles",
        ],
    )
    _assert_ints(
        row,
        [
            "show_window_minutes",
            "pit_party_price_cents",
            "pit_party_capacity",
            "pit_party_sold_count",
            "expected_attendance",
            "competition_segment_count",
            "run_order_end_offset_minutes",
            "tickets_sold_count",
            "gross_ticket_revenue_cents",
            "addon_revenue_cents",
            "facility_fee_collected_cents",
            "marketing_spend_committed_cents",
            "sponsorship_committed_cents",
            "held_hospitality_seat_count",
            "haul_distance_miles",
        ],
    )
    _assert_enum(row, "sales_state", C.SALES_STATES)
    _assert_enum(row, "safety_state", C.SAFETY_STATES)
    _assert_enum(row, "readiness_posture", C.READINESS_POSTURES)
    _assert_nullable_timestamp(row, "doors_open_utc")
    _assert_nullable_timestamp(row, "show_start_utc")


def assert_competitor(row: Dict[str, Any]) -> None:
    """Assert a competitor carries its team identity, class and entry count."""
    assert_common_fields(row)
    _assert_fields(
        row,
        ["team_name", "driver_name", "home_market_code", "vehicle_class", "entry_count"],
    )
    _assert_ints(row, ["entry_count"])
    _assert_enum(row, "vehicle_class", C.VEHICLE_CLASSES)


def assert_vehicle_entry(row: Dict[str, Any]) -> None:
    """Assert an entry carries its bay, tech status and readiness score."""
    assert_common_fields(row)
    _assert_fields(
        row,
        [
            "competitor_id",
            "tour_stop_id",
            "vehicle_number",
            "vehicle_weight_lbs",
            "haul_distance_miles",
            "scheduled_arrival_utc",
            "logistics_state",
            "tech_status",
            "tech_attempt_count",
            "failed_attempt_count",
            "readiness_score",
            "readiness_variant",
            "branding_slots_committed",
        ],
    )
    _assert_ints(
        row,
        [
            "vehicle_weight_lbs",
            "haul_distance_miles",
            "tech_attempt_count",
            "failed_attempt_count",
            "readiness_score",
            "branding_slots_committed",
        ],
    )
    _assert_enum(row, "logistics_state", C.LOGISTICS_STATES)
    _assert_enum(row, "tech_status", C.TECH_STATUSES)
    _assert_enum(row, "readiness_variant", C.READINESS_VARIANTS)
    _assert_nullable_timestamp(row, "actual_arrival_utc")
    assert is_iso8601_timestamp(row["scheduled_arrival_utc"])
    assert (
        C.READINESS_SCORE_MIN <= row["readiness_score"] <= C.READINESS_SCORE_MAX
    ), "readiness_score must be clamped into 0..100"
    if row["logistics_state"] == "WITHDRAWN":
        assert (
            row.get("staging_bay_index") is None
        ), "a withdrawn entry releases its staging bay"
    assert (
        row["failed_attempt_count"] <= row["tech_attempt_count"]
    ), "failed attempts cannot exceed total attempts"


def assert_tech_inspection(row: Dict[str, Any]) -> None:
    """Assert an inspection is an immutable audit record with its attempt number."""
    assert_immutable_common_fields(row)
    _assert_fields(
        row,
        ["vehicle_entry_id", "attempt_no", "result", "defect_severity", "inspected_by_user_id"],
    )
    _assert_ints(row, ["attempt_no"])
    _assert_enum(row, "result", C.INSPECTION_RESULTS)
    _assert_enum(row, "defect_severity", C.DEFECT_SEVERITIES)
    assert 1 <= row["attempt_no"] <= C.MAX_TECH_ATTEMPTS, "attempt_no is 1-based and capped"


def assert_show_segment(row: Dict[str, Any]) -> None:
    """Assert a segment carries its position, duration and timeline offsets."""
    assert_common_fields(row)
    _assert_fields(
        row,
        [
            "tour_stop_id",
            "segment_type",
            "title",
            "run_order_position",
            "duration_minutes",
            "start_offset_minutes",
            "end_offset_minutes",
            "reset_gap_minutes",
        ],
    )
    _assert_ints(
        row,
        [
            "run_order_position",
            "duration_minutes",
            "start_offset_minutes",
            "end_offset_minutes",
            "reset_gap_minutes",
        ],
    )
    _assert_enum(row, "segment_type", C.SEGMENT_TYPES)
    assert row["run_order_position"] >= 1, "run_order_position is 1-based"
    assert row["duration_minutes"] >= 1, "duration_minutes must be at least 1"
    assert (
        row["end_offset_minutes"] == row["start_offset_minutes"] + row["duration_minutes"]
    ), "a segment occupies exactly its duration on the timeline"
    assert row["reset_gap_minutes"] in (
        0,
        C.FLOOR_RESET_MINUTES,
    ), "reset_gap_minutes is either zero or the floor reset"


def assert_ticket_tier(row: Dict[str, Any]) -> None:
    """Assert a tier carries its price card and its conserved seat pool."""
    assert_common_fields(row)
    _assert_fields(
        row,
        [
            "tour_stop_id",
            "tier_code",
            "price_cents",
            "allotment",
            "reserved_seat_count",
            "sold_seat_count",
            "held_seat_count",
            "available_seat_count",
            "group_min_qty",
            "group_discount_pct",
            "on_sale_start_utc",
            "on_sale_end_utc",
        ],
    )
    _assert_ints(
        row,
        [
            "price_cents",
            "allotment",
            "reserved_seat_count",
            "sold_seat_count",
            "held_seat_count",
            "available_seat_count",
            "group_min_qty",
        ],
    )
    assert 0 <= row["group_discount_pct"] <= 1, "group_discount_pct must lie in [0, 1]"
    assert row["group_min_qty"] >= 1, "group_min_qty must be at least 1"
    assert row["allotment"] >= 1, "allotment must be at least 1"
    assert is_iso8601_timestamp(row["on_sale_start_utc"])
    assert is_iso8601_timestamp(row["on_sale_end_utc"])
    assert_seat_pool_conserved(row)


def assert_ticket_order(row: Dict[str, Any]) -> None:
    """Assert an order carries its status and its frozen money breakdown."""
    assert_common_fields(row)
    _assert_fields(
        row,
        [
            "tour_stop_id",
            "ticket_tier_id",
            "purchaser_name",
            "purchaser_email",
            "qty",
            "is_group",
            "pit_party_addon_qty",
            "status",
            "line_subtotal_cents",
            "group_discount_cents",
            "addon_subtotal_cents",
            "addon_discount_cents",
            "facility_fee_cents",
            "total_cents",
        ],
    )
    _assert_ints(
        row,
        [
            "qty",
            "pit_party_addon_qty",
            "line_subtotal_cents",
            "group_discount_cents",
            "addon_subtotal_cents",
            "addon_discount_cents",
            "facility_fee_cents",
            "total_cents",
        ],
    )
    assert isinstance(row["is_group"], bool), "is_group must be a boolean"
    _assert_enum(row, "status", C.ORDER_STATUSES)
    _assert_nullable_timestamp(row, "paid_at")
    _assert_nullable_timestamp(row, "refunded_at")
    if row.get("void_reason") is not None:
        _assert_enum(row, "void_reason", C.VOID_REASONS)
    assert row["qty"] >= 1, "qty must be at least 1"
    assert_order_total(row)


def assert_sponsor(row: Dict[str, Any]) -> None:
    """Assert a sponsor carries its category and its exclusivity claim."""
    assert_common_fields(row)
    _assert_fields(row, ["company_name", "category", "contact_email", "exclusive_category"])
    _assert_enum(row, "category", C.SPONSOR_CATEGORIES)
    assert isinstance(
        row["exclusive_category"], bool
    ), "exclusive_category must be a boolean"


def assert_sponsorship_activation(row: Dict[str, Any]) -> None:
    """Assert an activation carries its package, state and recognized fee."""
    assert_common_fields(row)
    _assert_fields(
        row,
        [
            "sponsor_id",
            "tour_stop_id",
            "fee_cents",
            "vehicle_branding_slots",
            "signage_units",
            "hospitality_seat_count",
            "state",
            "recognized_fee_cents",
        ],
    )
    _assert_ints(
        row,
        [
            "fee_cents",
            "vehicle_branding_slots",
            "signage_units",
            "hospitality_seat_count",
            "recognized_fee_cents",
        ],
    )
    _assert_enum(row, "state", C.ACTIVATION_STATES)
    _assert_nullable_timestamp(row, "obligations_fulfilled_at")
    assert (
        row["vehicle_branding_slots"] <= C.MAX_BRANDING_SLOTS_PER_VEHICLE
    ), "one vehicle carries at most four branding slots"


def assert_safety_plan(row: Dict[str, Any]) -> None:
    """Assert a plan carries provisioned and required figures side by side."""
    assert_common_fields(row)
    _assert_fields(
        row,
        [
            "tour_stop_id",
            "state",
            "barrier_linear_feet",
            "catch_fence_height_ft",
            "medical_als_staff_count",
            "medical_bls_staff_count",
            "ambulance_count",
            "emergency_access_lanes",
            "required_als_staff_count",
            "required_bls_staff_count",
            "required_ambulance_count",
            "required_catch_fence_height_ft",
            "required_emergency_access_lanes",
            "required_barrier_linear_feet",
            "safety_cost_cents",
            "return_count",
        ],
    )
    _assert_ints(
        row,
        [
            "barrier_linear_feet",
            "catch_fence_height_ft",
            "medical_als_staff_count",
            "medical_bls_staff_count",
            "ambulance_count",
            "emergency_access_lanes",
            "required_als_staff_count",
            "required_bls_staff_count",
            "required_ambulance_count",
            "required_catch_fence_height_ft",
            "required_emergency_access_lanes",
            "required_barrier_linear_feet",
            "safety_cost_cents",
            "return_count",
        ],
    )
    _assert_enum(row, "state", C.SAFETY_PLAN_STATES)
    assert_safety_cost(row)


def assert_marketing_allocation(row: Dict[str, Any]) -> None:
    """Assert an allocation carries its channel, amount and commitment state."""
    assert_common_fields(row)
    _assert_fields(row, ["tour_stop_id", "channel", "amount_cents", "state"])
    _assert_ints(row, ["amount_cents"])
    _assert_enum(row, "channel", C.MARKETING_CHANNELS)
    _assert_enum(row, "state", C.MARKETING_STATES)
    _assert_nullable_timestamp(row, "released_at")
    assert row["amount_cents"] >= 1, "amount_cents must be at least 1"
    if row["state"] == "COMMITTED":
        assert row.get("released_at") is None, "a committed allocation has no released_at"
    else:
        assert row.get("released_at") is not None, "a released allocation stamps released_at"


def assert_event_settlement(row: Dict[str, Any]) -> None:
    """Assert a settlement carries its variant, waterfall buckets and margin."""
    assert_common_fields(row)
    _assert_fields(
        row,
        [
            "tour_stop_id",
            "state",
            "variant",
            "ticket_revenue_cents",
            "addon_revenue_cents",
            "facility_fee_cents",
            "sponsorship_revenue_cents",
            "marketing_spend_cents",
            "safety_cost_cents",
            "purse_cents",
            "rental_due_pre_credit_cents",
            "coop_credit_pct",
            "coop_credit_cents",
            "venue_due_cents",
            "collected_cash_cents",
            "net_to_promoter_cents",
            "payout_venue_cents",
            "payout_safety_cents",
            "payout_marketing_cents",
            "payout_purse_cents",
            "promoter_remainder_cents",
            "shortfall_cents",
            "profitability_margin_pct",
            "dispute_count",
        ],
    )
    _assert_ints(
        row,
        [
            "ticket_revenue_cents",
            "addon_revenue_cents",
            "facility_fee_cents",
            "sponsorship_revenue_cents",
            "marketing_spend_cents",
            "safety_cost_cents",
            "purse_cents",
            "rental_due_pre_credit_cents",
            "coop_credit_cents",
            "venue_due_cents",
            "collected_cash_cents",
            "net_to_promoter_cents",
            "payout_venue_cents",
            "payout_safety_cents",
            "payout_marketing_cents",
            "payout_purse_cents",
            "promoter_remainder_cents",
            "shortfall_cents",
            "dispute_count",
        ],
    )
    _assert_enum(row, "state", C.SETTLEMENT_STATES)
    _assert_enum(row, "variant", C.SETTLEMENT_VARIANTS)
    assert_settlement_waterfall(row)


def assert_market_report(payload: Dict[str, Any]) -> None:
    """Assert a market report carries its rows and its season-wide totals."""
    _assert_fields(
        payload,
        [
            "season_id",
            "market_rows",
            "total_net_cents",
            "settled_stop_count",
            "unsettled_stop_count",
        ],
    )
    assert isinstance(payload["market_rows"], list), "market_rows must be an array"
    _assert_ints(payload, ["total_net_cents", "settled_stop_count", "unsettled_stop_count"])
    running_net = 0
    for market_row in payload["market_rows"]:
        _assert_fields(
            market_row,
            [
                "market_code",
                "stop_count",
                "collected_cash_cents",
                "net_to_promoter_cents",
                "margin_pct",
            ],
        )
        _assert_ints(
            market_row, ["stop_count", "collected_cash_cents", "net_to_promoter_cents"]
        )
        running_net += market_row["net_to_promoter_cents"]
    assert (
        payload["total_net_cents"] == running_net
    ), "total_net_cents must sum the rows' net figures"
    assert_market_rows_ordered(payload["market_rows"])


# ---------------------------------------------------------------------------
# Conserved pools
# ---------------------------------------------------------------------------


def assert_seat_pool_conserved(tier: Dict[str, Any]) -> None:
    """A tier's allotment always equals available + reserved + sold + held."""
    total = (
        tier["available_seat_count"]
        + tier["reserved_seat_count"]
        + tier["sold_seat_count"]
        + tier["held_seat_count"]
    )
    assert tier["allotment"] == total, (
        "seat pool not conserved: allotment "
        f"{tier['allotment']} != available {tier['available_seat_count']} + reserved "
        f"{tier['reserved_seat_count']} + sold {tier['sold_seat_count']} + held "
        f"{tier['held_seat_count']}"
    )


def assert_marketing_budget_conserved(season: Dict[str, Any]) -> None:
    """A season's total budget always equals allocated + unallocated."""
    total = season["marketing_allocated_cents"] + season["marketing_unallocated_cents"]
    assert season["total_marketing_budget_cents"] == total, (
        "marketing budget not conserved: total "
        f"{season['total_marketing_budget_cents']} != allocated "
        f"{season['marketing_allocated_cents']} + unallocated "
        f"{season['marketing_unallocated_cents']}"
    )


# ---------------------------------------------------------------------------
# Readiness posture
# ---------------------------------------------------------------------------


def expected_readiness_posture(
    stop: Dict[str, Any], any_live_entry_tech_held: bool = False
) -> str:
    """The posture the stop's own fields imply, given whether an entry is held."""
    if stop["safety_state"] == "SAFETY_SUSPENDED" or stop["sales_state"] == "CANCELLED":
        return "FROZEN"
    if (
        stop["safety_state"] != "SAFETY_CERTIFIED"
        or stop["competition_segment_count"] == 0
        or any_live_entry_tech_held
        or stop["marketing_spend_committed_cents"] == 0
        or stop.get("show_start_utc") is None
    ):
        return "RESTRICTED"
    return "OPEN"


def assert_readiness_posture(
    stop: Dict[str, Any],
    expected: str,
    any_live_entry_tech_held: bool = False,
) -> None:
    """Assert the stop's posture equals ``expected`` and matches the derivation."""
    assert stop["readiness_posture"] == expected, (
        f"expected posture {expected}, got {stop['readiness_posture']} "
        f"(sales_state={stop['sales_state']}, safety_state={stop['safety_state']})"
    )
    derived = expected_readiness_posture(stop, any_live_entry_tech_held)
    assert stop["readiness_posture"] == derived, (
        f"posture {stop['readiness_posture']} disagrees with the derivation {derived}"
    )


def assert_stop_frozen(stop: Dict[str, Any]) -> None:
    """Assert the stop sits at the posture that rejects every mutation."""
    assert stop["readiness_posture"] == "FROZEN", (
        f"expected a frozen stop, got {stop['readiness_posture']}"
    )


# ---------------------------------------------------------------------------
# Order money
# ---------------------------------------------------------------------------


def expected_order_amounts(
    price_cents: int,
    qty: int,
    per_ticket_facility_fee_cents: int,
    pit_party_price_cents: int = 0,
    pit_party_addon_qty: int = 0,
    is_group: bool = False,
    group_min_qty: int = C.DEFAULT_GROUP_MIN_QTY,
    group_discount_pct: float = C.DEFAULT_GROUP_DISCOUNT_PCT,
) -> Dict[str, int]:
    """The six frozen money figures an order should carry, each rounded on its own line."""
    line_subtotal = price_cents * qty
    group_discount = (
        round_half_up_cents(line_subtotal * group_discount_pct)
        if is_group and qty >= group_min_qty
        else 0
    )
    addon_subtotal = pit_party_price_cents * pit_party_addon_qty
    addon_discount = (
        round_half_up_cents(addon_subtotal * C.PIT_PARTY_BUNDLE_DISCOUNT_PCT)
        if pit_party_addon_qty > 0 and pit_party_addon_qty == qty
        else 0
    )
    facility_fee = per_ticket_facility_fee_cents * qty
    return {
        "line_subtotal_cents": line_subtotal,
        "group_discount_cents": group_discount,
        "addon_subtotal_cents": addon_subtotal,
        "addon_discount_cents": addon_discount,
        "facility_fee_cents": facility_fee,
        "total_cents": (
            line_subtotal - group_discount + addon_subtotal - addon_discount + facility_fee
        ),
    }


def assert_order_total(order: Dict[str, Any]) -> None:
    """Assert an order's total is the sum of its five component lines."""
    expected = (
        order["line_subtotal_cents"]
        - order["group_discount_cents"]
        + order["addon_subtotal_cents"]
        - order["addon_discount_cents"]
        + order["facility_fee_cents"]
    )
    assert order["total_cents"] == expected, (
        f"total_cents {order['total_cents']} does not equal the component sum {expected}"
    )


def assert_order_amounts(order: Dict[str, Any], expected: Dict[str, int]) -> None:
    """Assert every money line of an order matches the expected breakdown."""
    for field, value in expected.items():
        assert order[field] == value, f"{field}: expected {value}, got {order[field]}"


# ---------------------------------------------------------------------------
# Safety provisioning
# ---------------------------------------------------------------------------


def expected_safety_requirements(
    expected_attendance: int,
    live_entry_count: int,
    heavy_rig_present: bool,
    floor_type: str,
) -> Dict[str, int]:
    """The six requirement floors implied by attendance, entries and the floor."""
    als = 1
    if expected_attendance >= C.SAFETY_ATTENDANCE_STEP:
        als += 1
    if live_entry_count >= C.SAFETY_ENTRY_COUNT_ALS_STEP:
        als += 1
    bls = max(
        C.SAFETY_BLS_MIN,
        math.ceil(expected_attendance / C.SAFETY_BLS_ATTENDANCE_DIVISOR),
    )
    if floor_type == "CONCRETE":
        bls += 1
    ambulances = max(
        C.SAFETY_AMBULANCE_MIN,
        math.ceil(live_entry_count / C.SAFETY_AMBULANCE_ENTRY_DIVISOR),
    )
    fence = (
        C.SAFETY_FENCE_HEIGHT_HEAVY_FT
        if heavy_rig_present
        else C.SAFETY_FENCE_HEIGHT_LIGHT_FT
    )
    lanes = C.SAFETY_LANES_MIN + (
        1 if expected_attendance >= C.SAFETY_ATTENDANCE_STEP else 0
    )
    barrier = max(
        C.SAFETY_BARRIER_MIN_FT,
        C.SAFETY_BARRIER_BASE_FT + C.SAFETY_BARRIER_PER_ENTRY_FT * live_entry_count,
    )
    return {
        "required_als_staff_count": als,
        "required_bls_staff_count": bls,
        "required_ambulance_count": ambulances,
        "required_catch_fence_height_ft": fence,
        "required_emergency_access_lanes": lanes,
        "required_barrier_linear_feet": barrier,
    }


def assert_safety_requirements(plan: Dict[str, Any], expected: Dict[str, int]) -> None:
    """Assert every requirement floor on the plan matches the expected figure."""
    for field, value in expected.items():
        assert plan[field] == value, f"{field}: expected {value}, got {plan[field]}"


def expected_safety_cost_cents(
    als_count: int, bls_count: int, ambulance_count: int, barrier_linear_feet: int
) -> int:
    """The provisioning bill implied by what the plan actually provisioned."""
    return (
        als_count * C.ALS_STAFF_COST_CENTS
        + bls_count * C.BLS_STAFF_COST_CENTS
        + ambulance_count * C.AMBULANCE_COST_CENTS
        + barrier_linear_feet * C.BARRIER_COST_PER_FOOT_CENTS
    )


def assert_safety_cost(plan: Dict[str, Any]) -> None:
    """Assert the plan's cost is the sum of its four priced provisioning lines."""
    expected = expected_safety_cost_cents(
        plan["medical_als_staff_count"],
        plan["medical_bls_staff_count"],
        plan["ambulance_count"],
        plan["barrier_linear_feet"],
    )
    assert plan["safety_cost_cents"] == expected, (
        f"safety_cost_cents {plan['safety_cost_cents']} does not equal the "
        f"provisioning bill {expected}"
    )


def assert_plan_provisioning_adequate(plan: Dict[str, Any]) -> None:
    """Assert the plan provisions at least every requirement floor it carries."""
    pairs = [
        ("medical_als_staff_count", "required_als_staff_count"),
        ("medical_bls_staff_count", "required_bls_staff_count"),
        ("ambulance_count", "required_ambulance_count"),
        ("catch_fence_height_ft", "required_catch_fence_height_ft"),
        ("emergency_access_lanes", "required_emergency_access_lanes"),
        ("barrier_linear_feet", "required_barrier_linear_feet"),
    ]
    for provisioned, required in pairs:
        assert plan[provisioned] >= plan[required], (
            f"{provisioned} {plan[provisioned]} falls below {required} {plan[required]}"
        )


# ---------------------------------------------------------------------------
# Readiness score
# ---------------------------------------------------------------------------


def expected_readiness_score(
    haul_distance_miles: int,
    schedule_penalty_applies: bool,
    failed_attempt_count: int = 0,
    latest_result_conditional: bool = False,
) -> int:
    """The clamped readiness score implied by haul, schedule and inspections."""
    score = C.READINESS_BASE_SCORE
    score -= (
        haul_distance_miles // C.READINESS_HAUL_BLOCK_MILES
    ) * C.READINESS_HAUL_PENALTY_PER_BLOCK
    if schedule_penalty_applies:
        score -= C.READINESS_SCHEDULE_PENALTY
    score -= failed_attempt_count * C.READINESS_FAILED_ATTEMPT_PENALTY
    if latest_result_conditional:
        score -= C.READINESS_CONDITIONAL_PENALTY
    return max(C.READINESS_SCORE_MIN, min(C.READINESS_SCORE_MAX, score))


def assert_readiness_score(entry: Dict[str, Any], expected: int, variant: str) -> None:
    """Assert the entry's score and the variant that produced it."""
    assert entry["readiness_score"] == expected, (
        f"readiness_score: expected {expected}, got {entry['readiness_score']}"
    )
    assert entry["readiness_variant"] == variant, (
        f"readiness_variant: expected {variant}, got {entry['readiness_variant']}"
    )


# ---------------------------------------------------------------------------
# Staging bays
# ---------------------------------------------------------------------------


def expected_staging_bay_index(
    vehicle_weight_lbs: int, occupied_bays: List[int], staging_bay_count: int
) -> Optional[int]:
    """The bay the selector should choose, or ``None`` when the pool is empty."""
    free = [
        index
        for index in range(1, staging_bay_count + 1)
        if index not in set(occupied_bays)
    ]
    if not free:
        return None
    return max(free) if vehicle_weight_lbs >= C.HEAVY_VEHICLE_LBS else min(free)


def assert_staging_bay_index(entry: Dict[str, Any], expected: int) -> None:
    """Assert the entry took the bay the weight-based selector implies."""
    assert entry["staging_bay_index"] == expected, (
        f"staging_bay_index: expected {expected}, got {entry['staging_bay_index']}"
    )


# ---------------------------------------------------------------------------
# Settlement
# ---------------------------------------------------------------------------


def expected_coop_credit_pct(rental_due_pre_credit_cents: int) -> float:
    """The co-op rate keyed on the pre-credit rental total, inclusive boundaries."""
    for threshold, pct in C.MARKETING_COOP_TIERS:
        if rental_due_pre_credit_cents >= threshold:
            return pct
    return C.MARKETING_COOP_DEFAULT_PCT


def expected_payout_waterfall(
    collected_cash_cents: int,
    venue_due_cents: int,
    safety_cost_cents: int,
    marketing_spend_cents: int,
    purse_cents: int,
) -> Dict[str, int]:
    """The four funded buckets, the promoter remainder and the shortfall."""
    remainder = collected_cash_cents
    payout_venue = min(remainder, venue_due_cents)
    remainder -= payout_venue
    payout_safety = min(remainder, safety_cost_cents)
    remainder -= payout_safety
    payout_marketing = min(remainder, marketing_spend_cents)
    remainder -= payout_marketing
    payout_purse = min(remainder, purse_cents)
    remainder -= payout_purse
    shortfall = (
        (venue_due_cents - payout_venue)
        + (safety_cost_cents - payout_safety)
        + (marketing_spend_cents - payout_marketing)
        + (purse_cents - payout_purse)
    )
    return {
        "payout_venue_cents": payout_venue,
        "payout_safety_cents": payout_safety,
        "payout_marketing_cents": payout_marketing,
        "payout_purse_cents": payout_purse,
        "promoter_remainder_cents": remainder,
        "shortfall_cents": shortfall,
    }


def assert_settlement_waterfall(settlement: Dict[str, Any]) -> None:
    """Assert the buckets, the remainder and the net-to-promoter identity."""
    expected = expected_payout_waterfall(
        settlement["collected_cash_cents"],
        settlement["venue_due_cents"],
        settlement["safety_cost_cents"],
        settlement["marketing_spend_cents"],
        settlement["purse_cents"],
    )
    for field, value in expected.items():
        assert settlement[field] == value, (
            f"{field}: expected {value}, got {settlement[field]}"
        )
    assert settlement["promoter_remainder_cents"] >= 0, (
        "promoter_remainder_cents is never negative by construction"
    )
    assert (
        settlement["net_to_promoter_cents"]
        == settlement["promoter_remainder_cents"] - settlement["shortfall_cents"]
    ), (
        "waterfall identity broken: net_to_promoter_cents "
        f"{settlement['net_to_promoter_cents']} != promoter_remainder_cents "
        f"{settlement['promoter_remainder_cents']} - shortfall_cents "
        f"{settlement['shortfall_cents']}"
    )
    assert (
        settlement["collected_cash_cents"]
        == settlement["ticket_revenue_cents"]
        + settlement["addon_revenue_cents"]
        + settlement["facility_fee_cents"]
        + settlement["sponsorship_revenue_cents"]
    ), "collected_cash_cents must sum the four revenue lines"
    assert (
        settlement["venue_due_cents"]
        == settlement["rental_due_pre_credit_cents"] - settlement["coop_credit_cents"]
    ), "venue_due_cents must be the pre-credit total less the co-op credit"
    assert settlement["coop_credit_pct"] == expected_coop_credit_pct(
        settlement["rental_due_pre_credit_cents"]
    ), "coop_credit_pct must be keyed on the pre-credit rental total"


def assert_profitability_margin(settlement: Dict[str, Any]) -> None:
    """Assert the margin is net over collected cash, to two decimal places."""
    if settlement["collected_cash_cents"] > 0:
        expected = round_half_up_2dp(
            settlement["net_to_promoter_cents"]
            / settlement["collected_cash_cents"]
            * 100
        )
    else:
        expected = 0.00
    assert settlement["profitability_margin_pct"] == expected, (
        f"profitability_margin_pct: expected {expected}, got "
        f"{settlement['profitability_margin_pct']}"
    )


def assert_market_rows_ordered(market_rows: List[Dict[str, Any]]) -> None:
    """Assert market rows run by net descending, then market code ascending."""
    keys = [(-row["net_to_promoter_cents"], row["market_code"]) for row in market_rows]
    assert keys == sorted(keys), (
        "market_rows must be ordered by net_to_promoter_cents descending with "
        "market_code ascending as the tie-break"
    )


# ---------------------------------------------------------------------------
# Interval semantics
# ---------------------------------------------------------------------------


def expected_haul_buffer_hours(haul_distance_miles: int) -> int:
    """Driving hours rounded up plus the mandatory rest, for the transport chain."""
    return math.ceil(haul_distance_miles / C.HAUL_AVG_MPH) + C.HAUL_REST_HOURS


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


def assert_sorted_by(rows: List[Dict[str, Any]], field: str) -> None:
    """Assert the rows run ascending by ``field``."""
    values = [row[field] for row in rows]
    assert values == sorted(values), f"rows are not sorted ascending by {field}"


def assert_pagination_meta(
    meta: Dict[str, Any], limit: int, offset: int, total_count: int
) -> None:
    """Assert the pagination block reports the window and the has_more flag."""
    assert meta["limit"] == limit, f"limit: expected {limit}, got {meta['limit']}"
    assert meta["offset"] == offset, f"offset: expected {offset}, got {meta['offset']}"
    assert meta["total_count"] == total_count, (
        f"total_count: expected {total_count}, got {meta['total_count']}"
    )
    assert meta["has_more"] == (offset + limit < total_count), (
        f"has_more disagrees with the window: {meta}"
    )
