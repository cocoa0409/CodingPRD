"""Domain assertions, rounding helpers and invariant checkers."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional, Sequence

import pytest

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import (
    ADMIN_FEE_PCT_TIER_1,
    ADMIN_FEE_PCT_TIER_2,
    ADMIN_FEE_PCT_TIER_3,
    ADMIN_FEE_TIER_1_LIMIT_CENTS,
    ADMIN_FEE_TIER_2_LIMIT_CENTS,
    BEST_BALL_ALLOWANCE_PCT,
    MAX_COURSE_HANDICAP,
    MIN_COURSE_HANDICAP,
    SCRAMBLE_WEIGHTS,
    SLOPE_DIVISOR,
    STROKE_PLAY_ALLOWANCE_PCT,
    TEAM_ALLOWANCE_AGGREGATE_MULTIPLIER,
    TOKEN_GSV_CAP_CENTS,
    TOKEN_GSV_PCT,
)
from .types import (
    ALLOCATION_COMMITTED_STATUSES,
    ALLOCATION_FULFILLED_STATUSES,
    ALLOCATION_RESERVED_STATUSES,
)

# ======================================================= rounding helpers ===


def round_half_up(value: float, decimals: int = 0) -> float:
    """Round away from zero on an exact .5 boundary, to ``decimals`` places."""
    quant = Decimal(1).scaleb(-decimals)
    result = Decimal(str(value)).quantize(quant, rounding=ROUND_HALF_UP)
    return int(result) if decimals == 0 else float(result)


def round_cents(value: float) -> int:
    """Round a monetary quantity half up to whole cents."""
    return int(round_half_up(value, 0))


# =================================================== calculation mirrors ====


def course_handicap(
    index: float, slope_rating: float, course_rating: float, par: int
) -> int:
    """Index -> whole-stroke course handicap, rounded then floored then capped."""
    raw = index * slope_rating / SLOPE_DIVISOR + (course_rating - par)
    rounded = int(round_half_up(raw, 0))
    return max(MIN_COURSE_HANDICAP, min(MAX_COURSE_HANDICAP, rounded))


def scramble_team_handicap(course_handicaps: Sequence[int]) -> float:
    ordered = sorted(course_handicaps)
    total = sum(ch * w for ch, w in zip(ordered, SCRAMBLE_WEIGHTS))
    return round_half_up(total, 1)


def _allowance_team_handicap(course_handicaps: Sequence[int], pct: float) -> float:
    ordered = sorted(course_handicaps)
    allowances = [int(round_half_up(ch * pct, 0)) for ch in ordered]
    return round_half_up(sum(allowances) * TEAM_ALLOWANCE_AGGREGATE_MULTIPLIER, 1)


def best_ball_team_handicap(course_handicaps: Sequence[int]) -> float:
    return _allowance_team_handicap(course_handicaps, BEST_BALL_ALLOWANCE_PCT)


def stroke_play_team_handicap(course_handicaps: Sequence[int]) -> float:
    return _allowance_team_handicap(course_handicaps, STROKE_PLAY_ALLOWANCE_PCT)


def admin_fee_pct_for(net_before_fee_cents: int) -> float:
    """Fee rate selected from the before-fee figure, never from the after-fee net."""
    if net_before_fee_cents <= 0:
        return 0
    if net_before_fee_cents < ADMIN_FEE_TIER_1_LIMIT_CENTS:
        return ADMIN_FEE_PCT_TIER_1
    if net_before_fee_cents < ADMIN_FEE_TIER_2_LIMIT_CENTS:
        return ADMIN_FEE_PCT_TIER_2
    return ADMIN_FEE_PCT_TIER_3


def token_benefit_ceiling(payment_cents: int) -> int:
    """The smaller of 1300 cents and two percent of the payment, rounded half up."""
    return min(TOKEN_GSV_CAP_CENTS, round_cents(TOKEN_GSV_PCT * payment_cents))


# ==================================================== timestamp handling =====


def parse_utc(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant, tolerating 0-9 fractional digits."""
    assert isinstance(value, str), f"expected an ISO 8601 string, got {value!r}"
    text = value.strip()
    assert text.endswith("Z"), f"timestamp must be UTC with a trailing Z: {value!r}"
    body = text[:-1]
    if "." in body:
        head, frac = body.split(".", 1)
        frac = (frac + "000000")[:6]
        body = f"{head}.{frac}"
    return datetime.fromisoformat(body).replace(tzinfo=timezone.utc)


def assert_instant_equals(actual: Optional[str], expected: str) -> None:
    """Compare two UTC instants regardless of fractional-second width."""
    assert actual is not None, f"expected the instant {expected}, got null"
    assert parse_utc(actual) == parse_utc(expected), (
        f"expected the instant {expected}, got {actual}"
    )


def shift_minutes(value: str, minutes: int) -> str:
    """Advance an instant, rendered back with three fractional digits."""
    moved = parse_utc(value) + timedelta(minutes=minutes)
    return moved.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moved.microsecond // 1000:03d}Z"


def shift_days(value: str, days: int) -> str:
    moved = parse_utc(value) + timedelta(days=days)
    return moved.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moved.microsecond // 1000:03d}Z"


# ================================================= common-field assertions ===


def assert_system_fields(row: Dict[str, Any]) -> None:
    """The four system-managed properties carried by ten of the eleven families."""
    assert is_valid_uuid(row["id"]), f"id is not a UUID: {row.get('id')!r}"
    assert is_iso8601_timestamp(row["created_at"]), f"bad created_at: {row.get('created_at')!r}"
    assert is_iso8601_timestamp(row["updated_at"]), f"bad updated_at: {row.get('updated_at')!r}"
    assert isinstance(row["version"], int) and not isinstance(row["version"], bool)
    assert row["version"] >= 1, f"version must start at 1, got {row['version']}"


def assert_append_only_fields(row: Dict[str, Any]) -> None:
    """A charitable receipt carries only ``id`` and ``created_at``."""
    assert is_valid_uuid(row["id"]), f"id is not a UUID: {row.get('id')!r}"
    assert is_iso8601_timestamp(row["created_at"]), f"bad created_at: {row.get('created_at')!r}"
    assert "updated_at" not in row, "a charitable receipt carries no updated_at field"
    assert "version" not in row, "a charitable receipt carries no version field"


def assert_money_integer(row: Dict[str, Any], *fields: str) -> None:
    """Money is carried in whole integer cents, never as a string."""
    for field in fields:
        value = row.get(field)
        assert isinstance(value, int) and not isinstance(value, bool), (
            f"{field} must be an integer number of cents, got {value!r}"
        )


def assert_version_advanced(new_row: Dict[str, Any], old_version: int, by: int = 1) -> None:
    assert new_row["version"] == old_version + by, (
        f"expected version {old_version + by}, got {new_row['version']}"
    )


def assert_version_unchanged(row: Dict[str, Any], expected_version: int) -> None:
    assert row["version"] == expected_version, (
        f"a rejected write must not advance the version: expected "
        f"{expected_version}, got {row['version']}"
    )


# ==================================================== per-entity shape checks ===


def assert_outing(row: Dict[str, Any], **expected: Any) -> Dict[str, Any]:
    assert_system_fields(row)
    for field in (
        "name",
        "beneficiary_name",
        "format",
        "start_format",
        "scheduled_date",
        "wave_a_start",
        "wave_a_end",
        "field_capacity_teams",
        "prize_pool_cents",
        "play_status",
        "finance_status",
        "proceeds_variant",
    ):
        assert field in row, f"outing is missing {field}"
    assert_money_integer(
        row,
        "prize_pool_cents",
        "gross_revenue_cents",
        "refunded_cents",
        "course_charge_cents",
        "fnb_shortfall_cents",
        "insurance_cost_cents",
        "prize_cost_cents",
        "fulfillment_credit_cents",
        "direct_costs_cents",
        "net_proceeds_before_fee_cents",
        "admin_fee_cents",
        "net_proceeds_cents",
        "unclaimed_prize_cents",
        "receipted_deductible_total_cents",
        "beneficiary_remittance_cents",
    )
    _assert_fields(row, "outing", expected)
    return row


def assert_contract(row: Dict[str, Any], **expected: Any) -> Dict[str, Any]:
    assert_system_fields(row)
    for field in ("outing_id", "course_name", "rate_per_player_cents", "status"):
        assert field in row, f"course contract is missing {field}"
    assert_money_integer(
        row,
        "rate_per_player_cents",
        "fnb_minimum_cents",
        "fnb_per_player_cents",
        "rain_credit_cents",
        "settled_charge_cents",
    )
    _assert_fields(row, "course contract", expected)
    return row


def assert_package_tier(row: Dict[str, Any], **expected: Any) -> Dict[str, Any]:
    assert_system_fields(row)
    for field in ("outing_id", "code", "kind", "price_cents", "player_slots", "sold_count"):
        assert field in row, f"package tier is missing {field}"
    assert_money_integer(row, "price_cents", "gsv_cents")
    assert 0 <= row["player_slots"] <= 4, "player_slots lies between 0 and 4 inclusive"
    _assert_fields(row, "package tier", expected)
    return row


def assert_registration(row: Dict[str, Any], **expected: Any) -> Dict[str, Any]:
    assert_system_fields(row)
    for field in ("outing_id", "package_tier_id", "buyer_name", "player_count", "status"):
        assert field in row, f"registration is missing {field}"
    assert_money_integer(
        row,
        "amount_paid_cents",
        "amount_refunded_cents",
        "late_cancel_fee_cents",
        "fulfillment_credit_cents",
    )
    _assert_fields(row, "registration", expected)
    return row


def assert_player(row: Dict[str, Any], **expected: Any) -> Dict[str, Any]:
    assert_system_fields(row)
    for field in ("registration_id", "full_name", "handicap_index", "amateur_status"):
        assert field in row, f"player is missing {field}"
    _assert_fields(row, "player", expected)
    return row


def assert_team(row: Dict[str, Any], **expected: Any) -> Dict[str, Any]:
    assert_system_fields(row)
    for field in ("outing_id", "team_name", "player_count", "handicap_variant"):
        assert field in row, f"team is missing {field}"
    assert_money_integer(row, "prize_award_cents")
    _assert_fields(row, "team", expected)
    return row


def assert_sponsorship_asset(row: Dict[str, Any], **expected: Any) -> Dict[str, Any]:
    assert_system_fields(row)
    for field in (
        "outing_id",
        "asset_type",
        "label",
        "capacity",
        "exclusive",
        "list_price_cents",
        "reserved_count",
        "committed_count",
        "fulfilled_count",
        "remaining_capacity",
        "status",
    ):
        assert field in row, f"sponsorship asset is missing {field}"
    assert_money_integer(row, "list_price_cents")
    _assert_fields(row, "sponsorship asset", expected)
    return row


def assert_sponsor_allocation(row: Dict[str, Any], **expected: Any) -> Dict[str, Any]:
    assert_system_fields(row)
    for field in ("registration_id", "sponsorship_asset_id", "source", "status"):
        assert field in row, f"sponsor allocation is missing {field}"
    assert_money_integer(row, "upsell_price_cents", "fulfillment_credit_cents")
    _assert_fields(row, "sponsor allocation", expected)
    return row


def assert_contest(row: Dict[str, Any], **expected: Any) -> Dict[str, Any]:
    assert_system_fields(row)
    for field in (
        "outing_id",
        "contest_type",
        "hole_number",
        "prize_value_cents",
        "status",
        "insurance_status",
        "requires_insurance",
        "claim_denial_reason",
    ):
        assert field in row, f"contest is missing {field}"
    assert_money_integer(
        row,
        "prize_value_cents",
        "insurance_premium_cents",
        "insurance_coverage_cap_cents",
        "awarded_value_cents",
        "insurance_recovery_cents",
        "contest_payout_cents",
    )
    _assert_fields(row, "contest", expected)
    return row


def assert_fundraising_item(row: Dict[str, Any], **expected: Any) -> Dict[str, Any]:
    assert_system_fields(row)
    for field in ("outing_id", "item_type", "description", "status"):
        assert field in row, f"fundraising item is missing {field}"
    assert_money_integer(row, "fmv_cents", "ask_cents", "bid_cents", "collected_cents")
    _assert_fields(row, "fundraising item", expected)
    return row


def assert_charitable_receipt(row: Dict[str, Any], **expected: Any) -> Dict[str, Any]:
    assert_append_only_fields(row)
    for field in (
        "outing_id",
        "receipt_kind",
        "receipt_number",
        "payment_cents",
        "gsv_cents",
        "deductible_amount_cents",
        "issued_by_user_id",
        "issued_at",
    ):
        assert field in row, f"charitable receipt is missing {field}"
    assert_money_integer(row, "payment_cents", "gsv_cents", "deductible_amount_cents")
    _assert_fields(row, "charitable receipt", expected)
    return row


def _assert_fields(row: Dict[str, Any], label: str, expected: Dict[str, Any]) -> None:
    for field, want in expected.items():
        assert field in row, f"{label} is missing {field}"
        got = row[field]
        if isinstance(want, float):
            assert got == pytest.approx(want, abs=0.01), (
                f"{label}.{field}: expected {want}, got {got}"
            )
        else:
            assert got == want, f"{label}.{field}: expected {want!r}, got {got!r}"


# ===================================================== domain invariants =====


def assert_inventory_conservation(asset: Dict[str, Any]) -> None:
    """capacity == remaining_capacity + reserved + committed + fulfilled.

    A withdrawn unit reads ``remaining_capacity`` 0 regardless of its counters,
    so the identity is asserted on the live form of the unit only.
    """
    occupied = asset["reserved_count"] + asset["committed_count"] + asset["fulfilled_count"]
    if asset["status"] == "WITHDRAWN":
        assert asset["remaining_capacity"] == 0, (
            "a withdrawn unit reads remaining_capacity 0"
        )
        return
    assert asset["capacity"] == asset["remaining_capacity"] + occupied, (
        f"conservation broken: capacity {asset['capacity']} != remaining "
        f"{asset['remaining_capacity']} + reserved {asset['reserved_count']} + "
        f"committed {asset['committed_count']} + fulfilled {asset['fulfilled_count']}"
    )


def expected_asset_posture(asset: Dict[str, Any]) -> str:
    """The derived inventory posture of a unit that was not withdrawn manually."""
    reserved = asset["reserved_count"]
    committed = asset["committed_count"]
    fulfilled = asset["fulfilled_count"]
    if reserved + committed + fulfilled == 0:
        return "AVAILABLE"
    if committed > 0:
        return "COMMITTED"
    if reserved > 0:
        return "RESERVED"
    return "FULFILLED"


def assert_asset_posture_derived(asset: Dict[str, Any]) -> None:
    if asset["status"] == "WITHDRAWN":
        return
    assert asset["status"] == expected_asset_posture(asset), (
        f"posture {asset['status']} does not follow from the counters "
        f"({asset['reserved_count']}, {asset['committed_count']}, {asset['fulfilled_count']})"
    )


def occupancy_of(allocation_status: str) -> str:
    """Which of the three counters an allocation status occupies."""
    if allocation_status in ALLOCATION_RESERVED_STATUSES:
        return "reserved_count"
    if allocation_status in ALLOCATION_COMMITTED_STATUSES:
        return "committed_count"
    if allocation_status in ALLOCATION_FULFILLED_STATUSES:
        return "fulfilled_count"
    return "none"


def assert_outing_slot_aggregate(outing: Dict[str, Any], assets: List[Dict[str, Any]]) -> None:
    """The outing-level counter is the sum of the three counters over its assets."""
    total = sum(
        a["reserved_count"] + a["committed_count"] + a["fulfilled_count"] for a in assets
    )
    assert outing["reserved_asset_slot_count"] == total, (
        f"reserved_asset_slot_count {outing['reserved_asset_slot_count']} != {total}"
    )


def assert_direct_costs(outing: Dict[str, Any], rain_credit_cents: int = 0) -> None:
    """Direct costs are the four cost components less the rain credit.

    The outing's own ``fulfillment_credit_cents`` joins the sum only under the
    final treatment, so the caller supplies the contract's rain credit because
    that figure lives on the contract rather than on the outing.
    """
    expected = (
        outing["course_charge_cents"]
        + outing["fnb_shortfall_cents"]
        + outing["insurance_cost_cents"]
        + outing["prize_cost_cents"]
        - rain_credit_cents
    )
    if outing["proceeds_variant"] == "FINAL":
        expected += outing["fulfillment_credit_cents"]
    assert outing["direct_costs_cents"] == expected, (
        f"direct_costs_cents {outing['direct_costs_cents']} != {expected}"
    )


def assert_rollup_chain(outing: Dict[str, Any]) -> None:
    """Re-derive the arithmetic links of the rollup from the reported components."""
    assert outing["net_proceeds_before_fee_cents"] == (
        outing["gross_revenue_cents"] - outing["refunded_cents"] - outing["direct_costs_cents"]
    ), "net before fee must be gross less refunds less direct costs"
    assert outing["admin_fee_pct"] == pytest.approx(
        admin_fee_pct_for(outing["net_proceeds_before_fee_cents"]), abs=0.0001
    ), "the fee rate is selected from the before-fee figure"
    assert outing["admin_fee_cents"] == round_cents(
        outing["admin_fee_pct"] * outing["gross_revenue_cents"]
    ), "the fee base is gross revenue, rounded half up exactly once"
    assert outing["net_proceeds_cents"] == (
        outing["net_proceeds_before_fee_cents"] - outing["admin_fee_cents"]
    ), "net proceeds is the before-fee figure less the fee"


def assert_receipt_ledger(outing: Dict[str, Any], receipts: List[Dict[str, Any]]) -> None:
    """The outing total is the signed sum over every receipt, reversals included."""
    signed = sum(r["deductible_amount_cents"] for r in receipts)
    assert outing["receipted_deductible_total_cents"] == signed, (
        f"receipted_deductible_total_cents {outing['receipted_deductible_total_cents']} "
        f"!= signed sum {signed}"
    )


def assert_receipt_numbers_sequential(receipts: List[Dict[str, Any]]) -> None:
    """Per-outing receipt numbers run GR-0001, GR-0002, ... in created_at order."""
    for index, receipt in enumerate(receipts, start=1):
        assert receipt["receipt_number"] == f"GR-{index:04d}", (
            f"receipt {index} reads {receipt['receipt_number']}, expected GR-{index:04d}"
        )


def assert_ranking_total_order(teams: List[Dict[str, Any]]) -> None:
    """Every team receives a distinct rank position numbered from 1."""
    ranks = sorted(t["rank_position"] for t in teams)
    assert ranks == list(range(1, len(teams) + 1)), (
        f"ranking is not a total order over the field: {ranks}"
    )


def assert_slot_occupancy(team: Dict[str, Any], tee_time: str, interval_minutes: int) -> None:
    """Occupancy runs from the tee time to its exclusive end one interval later."""
    assert_instant_equals(team["slot_occupancy_start"], tee_time)
    assert_instant_equals(team["slot_occupancy_end"], shift_minutes(tee_time, interval_minutes))
