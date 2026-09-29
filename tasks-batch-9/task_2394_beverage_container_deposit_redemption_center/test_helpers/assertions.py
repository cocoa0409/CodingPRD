"""Domain assertion helpers.

These express contract statements once so the test bodies stay readable: the
common-field contract, the two journals' narrower field contract, the rounding
disciplines, the liability projection and the derived-counter families.
"""

from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import (
    HANDLING_FEE_TIER_1_CENTS,
    HANDLING_FEE_TIER_1_LIMIT,
    HANDLING_FEE_TIER_2_CENTS,
    HANDLING_FEE_TIER_2_LIMIT,
    HANDLING_FEE_TIER_3_CENTS,
    LIABILITY_NEUTRAL_ENTRY_TYPES,
)

# ─── Numeric helpers ─────────────────────────────────────────────────────────


def round_half_up(value: float, places: int = 0) -> float:
    """Round half away from zero, the only rounding mode this API uses."""
    quant = Decimal(1).scaleb(-places)
    result = Decimal(str(value)).quantize(quant, rounding=ROUND_HALF_UP)
    return float(result) if places > 0 else float(int(result))


def round_half_up_to_cents(value: float) -> int:
    """Round a fractional cent figure to a whole cent, half away from zero."""
    return int(Decimal(str(value)).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def expected_shrink(capped_count: int) -> int:
    """Two per cent of the capped count rounded up to the next whole container."""
    scaled = Decimal(str(capped_count)) * Decimal("0.02")
    return int(scaled.quantize(Decimal(1), rounding=ROUND_CEILING))


def expected_handling_fee_cents(containers_redeemed_count: int) -> int:
    """Marginal handling reimbursement over the three declared tiers."""
    tier_one = HANDLING_FEE_TIER_1_CENTS * min(
        containers_redeemed_count, HANDLING_FEE_TIER_1_LIMIT
    )
    tier_two = HANDLING_FEE_TIER_2_CENTS * max(
        min(containers_redeemed_count, HANDLING_FEE_TIER_2_LIMIT)
        - HANDLING_FEE_TIER_1_LIMIT,
        0,
    )
    tier_three = HANDLING_FEE_TIER_3_CENTS * max(
        containers_redeemed_count - HANDLING_FEE_TIER_2_LIMIT, 0
    )
    return tier_one + tier_two + tier_three


def expected_euclidean_distance_miles(
    x_a: float, y_a: float, x_b: float, y_b: float
) -> float:
    """Planar distance rounded to 2 decimal places, as the radius test demands."""
    squared = (float(x_a) - float(x_b)) ** 2 + (float(y_a) - float(y_b)) ** 2
    return round_half_up(squared ** 0.5, 2)


# ─── Field-shape assertions ──────────────────────────────────────────────────


def assert_common_fields(resource: Dict[str, Any]) -> None:
    """Every mutable resource carries id, created_at, updated_at and version."""
    assert is_valid_uuid(resource["id"]), f"id is not a bare UUID: {resource['id']!r}"
    assert is_iso8601_timestamp(
        resource["created_at"]
    ), f"created_at is not ISO 8601: {resource['created_at']!r}"
    assert is_iso8601_timestamp(
        resource["updated_at"]
    ), f"updated_at is not ISO 8601: {resource['updated_at']!r}"
    assert isinstance(resource["version"], int), "version must be an integer"
    assert resource["version"] >= 1, "version starts at 1 on creation"


def assert_journal_fields(entry: Dict[str, Any]) -> None:
    """A journal line carries only id and created_at — no updated_at, no version."""
    assert is_valid_uuid(entry["id"]), f"id is not a bare UUID: {entry['id']!r}"
    assert is_iso8601_timestamp(
        entry["created_at"]
    ), f"created_at is not ISO 8601: {entry['created_at']!r}"
    assert "updated_at" not in entry, "a journal line must not carry updated_at"
    assert "version" not in entry, "a journal line must not carry version"


def assert_stamped_at(value: Optional[str], expected_instant: str) -> None:
    """A stamped instant equals the logical clock in force, to the second.

    Stamped timestamps render with three fractional digits, so the comparison
    is made against the second-resolution prefix of the expected instant.
    """
    assert value is not None, f"expected an instant of {expected_instant}, got null"
    assert is_iso8601_timestamp(value), f"not an ISO 8601 instant: {value!r}"
    prefix = expected_instant.rstrip("Z").split(".")[0]
    assert value.startswith(prefix), f"expected {expected_instant}, got {value}"


def assert_created_at_ascending(rows: List[Dict[str, Any]]) -> None:
    """List results are ordered by created_at ascending."""
    stamps = [row["created_at"] for row in rows]
    assert stamps == sorted(stamps), f"rows are not in created_at ascending order: {stamps}"


# ─── Rounding disciplines ────────────────────────────────────────────────────


def assert_ratio_precision(value: float) -> None:
    """Ratios are rounded to 4 decimal places before any threshold comparison."""
    assert value == round_half_up(value, 4), (
        f"ratio {value} carries more than 4 decimal places"
    )


def assert_distance_precision(value: float) -> None:
    """Distances are rounded to 2 decimal places before the radius comparison."""
    assert value == round_half_up(value, 2), (
        f"distance {value} carries more than 2 decimal places"
    )


def assert_weight_precision(value: float) -> None:
    """Weights are rounded to 2 decimal places."""
    assert value == round_half_up(value, 2), (
        f"weight {value} carries more than 2 decimal places"
    )


# ─── Resource-family assertions ──────────────────────────────────────────────


def assert_coverage(
    product: Dict[str, Any],
    coverage_status: str,
    coverage_reason: str,
    deposit_cents: int,
) -> None:
    assert product["coverage_status"] == coverage_status
    assert product["coverage_reason"] == coverage_reason
    assert product["deposit_cents"] == deposit_cents


def assert_center_pool(
    center: Dict[str, Any],
    accepted_container_count: Optional[int] = None,
    batched_container_count: Optional[int] = None,
    unbatched_container_count: Optional[int] = None,
    withheld_visit_count: Optional[int] = None,
) -> None:
    """Check the centre's container-pool projections that were supplied."""
    if accepted_container_count is not None:
        assert center["accepted_container_count"] == accepted_container_count
    if batched_container_count is not None:
        assert center["batched_container_count"] == batched_container_count
    if unbatched_container_count is not None:
        assert center["unbatched_container_count"] == unbatched_container_count
    if withheld_visit_count is not None:
        assert center["withheld_visit_count"] == withheld_visit_count
    assert (
        center["unbatched_container_count"]
        == center["accepted_container_count"] - center["batched_container_count"]
    ), "unbatched pool must equal accepted minus batched"


def assert_visit_valuation(
    visit: Dict[str, Any],
    visit_limit_applied: int,
    capped_count: int,
    shrink_adjustment_count: int,
    payable_count: int,
    refused_over_limit_count: int,
    payout_cents: int,
) -> None:
    assert visit["visit_limit_applied"] == visit_limit_applied
    assert visit["capped_count"] == capped_count
    assert visit["shrink_adjustment_count"] == shrink_adjustment_count
    assert visit["payable_count"] == payable_count
    assert visit["refused_over_limit_count"] == refused_over_limit_count
    assert visit["payout_cents"] == payout_cents
    assert (
        visit["payable_count"] == visit["capped_count"] - visit["shrink_adjustment_count"]
    ), "payable_count must equal capped_count less the shrink deduction"
    assert (
        visit["refused_over_limit_count"]
        == visit["raw_accepted_count"] - visit["capped_count"]
    ), "refused_over_limit_count must equal raw accepted less capped"


def assert_fraud_posture(
    visit: Dict[str, Any],
    fraud_hold: bool,
    withhold_reason: Optional[str],
    payout_status: str,
) -> None:
    assert visit["fraud_hold"] is fraud_hold
    assert visit["withhold_reason"] == withhold_reason
    assert visit["payout_status"] == payout_status


def assert_account_standing(
    account: Dict[str, Any],
    status: str,
    fraud_strikes: int,
    last_strike_reason: Optional[str],
) -> None:
    assert account["status"] == status
    assert account["fraud_strikes"] == fraud_strikes
    assert account["last_strike_reason"] == last_strike_reason


def assert_lot_settlement(
    lot: Dict[str, Any], paid_quantity: int, reconciliation_flag: str
) -> None:
    assert lot["paid_quantity"] == paid_quantity
    assert lot["reconciliation_flag"] == reconciliation_flag


def assert_bag_drop_valuation(
    bag: Dict[str, Any],
    counted_lines: int,
    counted_total: int,
    gross_final_cents: int,
    final_credit_cents: int,
    adjustment_cents: int,
    variance_pct: float,
    variance_flag: bool,
) -> None:
    assert bag["counted_lines"] == counted_lines
    assert bag["counted_total"] == counted_total
    assert bag["gross_final_cents"] == gross_final_cents
    assert bag["final_credit_cents"] == final_credit_cents
    assert bag["adjustment_cents"] == adjustment_cents
    assert bag["variance_pct"] == variance_pct
    assert bag["variance_flag"] is variance_flag


def assert_credit_entry(
    entry: Dict[str, Any],
    entry_type: str,
    amount_cents: int,
    balance_after_cents: int,
    source_kind: str,
    source_ref_id: Optional[str] = None,
) -> None:
    assert_journal_fields(entry)
    assert entry["entry_type"] == entry_type
    assert entry["amount_cents"] == amount_cents
    assert entry["balance_after_cents"] == balance_after_cents
    assert entry["source_kind"] == source_kind
    if source_ref_id is not None:
        assert entry["source_ref_id"] == source_ref_id


def assert_ledger_entry(
    entry: Dict[str, Any],
    entry_type: str,
    amount_cents: int,
    container_count: int,
    source_kind: str,
    liability_after_cents: Optional[int] = None,
    source_ref_id: Optional[str] = None,
) -> None:
    assert_journal_fields(entry)
    assert entry["entry_type"] == entry_type
    assert entry["amount_cents"] == amount_cents
    assert entry["container_count"] == container_count
    assert entry["source_kind"] == source_kind
    if liability_after_cents is not None:
        assert entry["liability_after_cents"] == liability_after_cents
    if source_ref_id is not None:
        assert entry["source_ref_id"] == source_ref_id


def assert_liability_projection(entries: List[Dict[str, Any]]) -> int:
    """Replay the ledger from zero and check every liability_after_cents.

    Handling-fee and material-revenue lines contribute nothing to the running
    total; every other line contributes its amount_cents. Returns the final
    running liability.
    """
    assert_created_at_ascending(entries)
    running = 0
    for entry in entries:
        if entry["entry_type"] not in LIABILITY_NEUTRAL_ENTRY_TYPES:
            running += entry["amount_cents"]
        assert entry["liability_after_cents"] == running, (
            f"liability_after_cents on the {entry['entry_type']} line should be "
            f"{running}, got {entry['liability_after_cents']}"
        )
    return running


def assert_period_settlement(
    period: Dict[str, Any],
    handling_fee_cents: int,
    gross_unredeemed_cents: int,
    admin_shortfall_cents: int,
    sweep_to_funding_cents: int,
    unredeemed_deposit_cents: int,
    funding_balance_cents: int,
    funding_status: str,
) -> None:
    assert period["handling_fee_cents"] == handling_fee_cents
    assert period["gross_unredeemed_cents"] == gross_unredeemed_cents
    assert period["admin_shortfall_cents"] == admin_shortfall_cents
    assert period["sweep_to_funding_cents"] == sweep_to_funding_cents
    assert period["unredeemed_deposit_cents"] == unredeemed_deposit_cents
    assert period["funding_balance_cents"] == funding_balance_cents
    assert period["funding_status"] == funding_status


def assert_machine_state(
    machine: Dict[str, Any],
    status: str,
    jam_count_today: Optional[int] = None,
    open_session_count: Optional[int] = None,
    bin_filled_count: Optional[int] = None,
) -> None:
    assert machine["status"] == status
    if jam_count_today is not None:
        assert machine["jam_count_today"] == jam_count_today
    if open_session_count is not None:
        assert machine["open_session_count"] == open_session_count
    if bin_filled_count is not None:
        assert machine["bin_filled_count"] == bin_filled_count
