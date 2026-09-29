"""Domain assertion helpers.

These wrap the recurring shape checks the PRD pins in §2.2 (envelope), §2.5
(common fields and identifier format), §2.6 (money and percentage precision)
and §2.3 (pagination meta).
"""

from typing import Any, Dict, Iterable, List, Optional

import pytest
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import COMMON_FIELDS, IMMUTABLE_COMMON_FIELDS

# Money and percentage tolerance — PRD §2.6 pins whole cents and two decimals.
CENT = 0
PCT_TOLERANCE = 0.01


def assert_common_fields(row: Dict[str, Any], expected_version: Optional[int] = None):
    """Assert the PRD §2.5 common-field inventory on a versioned entity."""
    for field in COMMON_FIELDS:
        assert field in row, f"missing common field '{field}': {row}"
    assert is_valid_uuid(row["id"]), f"id must be a bare UUID, got {row['id']!r}"
    assert is_iso8601_timestamp(row["created_at"]), row["created_at"]
    assert is_iso8601_timestamp(row["updated_at"]), row["updated_at"]
    assert isinstance(row["version"], int) and row["version"] >= 1
    if expected_version is not None:
        assert row["version"] == expected_version, (
            f"expected version {expected_version}, got {row['version']}"
        )


def assert_immutable_common_fields(row: Dict[str, Any]):
    """Assert the ClaimAssessment carve-out from PRD §2.5: id and created_at only."""
    for field in IMMUTABLE_COMMON_FIELDS:
        assert field in row, f"missing common field '{field}': {row}"
    assert is_valid_uuid(row["id"]), f"id must be a bare UUID, got {row['id']!r}"
    assert is_iso8601_timestamp(row["created_at"]), row["created_at"]
    assert "updated_at" not in row, "ClaimAssessment must not carry updated_at"
    assert "version" not in row, "ClaimAssessment must not carry version"


def assert_timestamp_millis(value: str):
    """PRD §2.5: timestamps are ISO-8601 UTC with exactly three fraction digits."""
    assert isinstance(value, str), value
    assert value.endswith("Z"), f"timestamp must end in Z: {value}"
    assert "." in value, f"timestamp must carry milliseconds: {value}"
    fraction = value.split(".")[1][:-1]
    assert len(fraction) == 3, f"expected 3 fractional digits, got {value}"


def assert_money_cents(value: Any):
    """PRD §2.6: every money amount is a whole number of cents."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"money must be an integer number of cents, got {value!r}"
    )


def assert_pct(value: Any, expected: float):
    """PRD §2.6: percentages carrying two decimals."""
    assert value == pytest.approx(expected, abs=PCT_TOLERANCE), (
        f"expected {expected}, got {value}"
    )


def assert_multiplier(value: Any, expected: float):
    assert value == pytest.approx(expected, abs=0.001), (
        f"expected multiplier {expected}, got {value}"
    )


def assert_no_row_created(rows: Iterable[Dict[str, Any]]):
    listed = list(rows)
    assert listed == [], f"expected no rows to be created, found {listed}"


def assert_row_ids(rows: List[Dict[str, Any]], expected_ids: Iterable[str]):
    """Assert a listing contains exactly the expected ids, order-independent."""
    actual = sorted(row["id"] for row in rows)
    assert actual == sorted(expected_ids), f"expected {expected_ids}, got {actual}"


def assert_sorted_by_created_at(rows: List[Dict[str, Any]]):
    """PRD §2.3: collections come back ordered by created_at ascending."""
    stamps = [row["created_at"] for row in rows]
    assert stamps == sorted(stamps), f"rows are not created_at ascending: {stamps}"


def assert_claim_decision(
    claim: Dict[str, Any],
    decision: str,
    status: str,
    threshold_pct: Optional[int] = None,
    ratio_pct: Optional[float] = None,
):
    """Assert the adjudication outcome quartet on a WarrantyClaim (PRD §3.5)."""
    assert claim["decision"] == decision, claim
    assert claim["status"] == status, claim
    if threshold_pct is not None:
        assert claim["decision_threshold_pct"] == threshold_pct, claim
    if ratio_pct is not None:
        assert_pct(claim["repair_ratio_pct"], ratio_pct)


def assert_estimate_breakdown(
    estimate: Dict[str, Any],
    labor_subtotal_cents: int,
    parts_subtotal_cents: int,
    shop_supply_fee_cents: int,
    subtotal_cents: int,
    loyalty_discount_cents: int,
    expedite_fee_cents: int,
    tax_cents: int,
    total_cents: int,
):
    """Assert the eight pricing steps of PRD §3.7 line by line."""
    assert estimate["labor_subtotal_cents"] == labor_subtotal_cents, estimate
    assert estimate["parts_subtotal_cents"] == parts_subtotal_cents, estimate
    assert estimate["shop_supply_fee_cents"] == shop_supply_fee_cents, estimate
    assert estimate["subtotal_cents"] == subtotal_cents, estimate
    assert estimate["loyalty_discount_cents"] == loyalty_discount_cents, estimate
    assert estimate["expedite_fee_cents"] == expedite_fee_cents, estimate
    assert estimate["tax_cents"] == tax_cents, estimate
    assert estimate["total_cents"] == total_cents, estimate


def assert_part_lot_counts(
    lot: Dict[str, Any],
    on_hand_units: int,
    reserved_units: int,
    available_units: int,
    status: Optional[str] = None,
):
    """Assert the stockroom triple and band of PRD §2.10."""
    assert lot["on_hand_units"] == on_hand_units, lot
    assert lot["reserved_units"] == reserved_units, lot
    assert lot["available_units"] == available_units, lot
    assert lot["available_units"] == lot["on_hand_units"] - lot["reserved_units"], lot
    if status is not None:
        assert lot["status"] == status, lot


def assert_center_posture(
    center: Dict[str, Any],
    open_liability_cents: int,
    utilization_pct: Optional[float] = None,
    posture: Optional[str] = None,
):
    """Assert the liability rollup triple of PRD §2.9."""
    assert center["open_liability_cents"] == open_liability_cents, center
    if utilization_pct is not None:
        assert_pct(center["liability_utilization_pct"], utilization_pct)
    if posture is not None:
        assert center["liability_posture"] == posture, center
