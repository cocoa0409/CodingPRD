"""Domain assertion helpers for precision, envelopes and common fields.

Precision follows the PRD: money is integer cents (exact equality), masses
carry 3 decimals, ratios 4 decimals, ppm / flash points / aisle widths 1.
"""

from typing import Any, Dict, Optional

import pytest

MASS_TOLERANCE = 0.001
RATIO_TOLERANCE = 0.0001
ONE_DECIMAL_TOLERANCE = 0.05


def assert_cents(actual: Any, expected: int, label: str = "cents") -> None:
    """Money is an integer number of cents, so the comparison is exact."""
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"{label} must be an integer number of cents, got {actual!r}"
    )
    assert actual == expected, f"{label}: expected {expected} cents, got {actual}"


def assert_mass(actual: Any, expected: float, label: str = "mass_kg") -> None:
    assert actual == pytest.approx(expected, abs=MASS_TOLERANCE), (
        f"{label}: expected {expected} kg, got {actual}"
    )


def assert_ratio(actual: Any, expected: float, label: str = "ratio") -> None:
    assert actual == pytest.approx(expected, abs=RATIO_TOLERANCE), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_one_decimal(actual: Any, expected: float, label: str = "value") -> None:
    assert actual == pytest.approx(expected, abs=ONE_DECIMAL_TOLERANCE), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_common_fields(row: Dict[str, Any]) -> None:
    """Mutable rows carry id, created_at, updated_at and version."""
    for field in ("id", "created_at", "updated_at", "version"):
        assert field in row, f"expected common field {field} on {sorted(row)}"
    assert isinstance(row["version"], int) and row["version"] >= 1


def assert_immutable_row(row: Dict[str, Any]) -> None:
    """Immutable rows carry only id and created_at: no updated_at, no version."""
    assert "id" in row and "created_at" in row
    assert "updated_at" not in row, "immutable rows must not expose updated_at"
    assert "version" not in row, "immutable rows must not expose version"


def assert_assurance(
    facility: Dict[str, Any],
    *,
    base_cents: Optional[int] = None,
    tier: Optional[str] = None,
    estimate_cents: Optional[int] = None,
    reserve_cents: Optional[int] = None,
    liability_cents: Optional[int] = None,
    required_cents: Optional[int] = None,
    posted_cents: Optional[int] = None,
    shortfall_cents: Optional[int] = None,
) -> None:
    """Check any subset of the facility's assurance figures."""
    if base_cents is not None:
        assert_cents(facility["closure_base_cost_cents"], base_cents, "closure_base_cost_cents")
    if tier is not None:
        assert facility["assurance_tier"] == tier
    if estimate_cents is not None:
        assert_cents(
            facility["closure_cost_estimate_cents"], estimate_cents, "closure_cost_estimate_cents"
        )
    if reserve_cents is not None:
        assert_cents(
            facility["corrective_action_reserve_cents"],
            reserve_cents,
            "corrective_action_reserve_cents",
        )
    if liability_cents is not None:
        assert_cents(
            facility["active_treatment_liability_cents"],
            liability_cents,
            "active_treatment_liability_cents",
        )
    if required_cents is not None:
        assert_cents(
            facility["required_assurance_cents"], required_cents, "required_assurance_cents"
        )
    if posted_cents is not None:
        assert_cents(facility["posted_assurance_cents"], posted_cents, "posted_assurance_cents")
    if shortfall_cents is not None:
        assert_cents(
            facility["assurance_shortfall_cents"], shortfall_cents, "assurance_shortfall_cents"
        )


def assert_unit_state(
    unit: Dict[str, Any],
    *,
    posture: Optional[str] = None,
    status: Optional[str] = None,
    container_count: Optional[int] = None,
    stored_kg: Optional[float] = None,
    reserved_kg: Optional[float] = None,
    utilization_pct: Optional[float] = None,
    effective_aisle_width_cm: Optional[float] = None,
    inspection_overdue: Optional[bool] = None,
) -> None:
    if posture is not None:
        assert unit["posture"] == posture, f"posture: expected {posture}, got {unit['posture']}"
    if status is not None:
        assert unit["status"] == status
    if container_count is not None:
        assert unit["container_count"] == container_count
    if stored_kg is not None:
        assert_mass(unit["stored_kg"], stored_kg, "stored_kg")
    if reserved_kg is not None:
        assert_mass(unit["reserved_kg"], reserved_kg, "reserved_kg")
    if utilization_pct is not None:
        assert_ratio(unit["utilization_pct"], utilization_pct, "utilization_pct")
    if effective_aisle_width_cm is not None:
        assert_one_decimal(
            unit["effective_aisle_width_cm"], effective_aisle_width_cm, "effective_aisle_width_cm"
        )
    if inspection_overdue is not None:
        assert unit["inspection_overdue"] is inspection_overdue


def assert_mass_ledger_balances(facility: Dict[str, Any]) -> None:
    """received_mass_kg equals the sum of its five destinations."""
    destinations = (
        facility["held_mass_kg"]
        + facility["unallocated_receipt_kg"]
        + facility["returned_mass_kg"]
        + facility["treated_residue_kg"]
        + facility["destroyed_mass_kg"]
    )
    assert_mass(destinations, facility["received_mass_kg"], "mass ledger destinations")


def assert_generator_ledger(
    generator: Dict[str, Any],
    *,
    open_cents: Optional[int] = None,
    settled_cents: Optional[int] = None,
    voided_cents: Optional[int] = None,
    adjustment_cents: Optional[int] = None,
) -> None:
    if open_cents is not None:
        assert_cents(generator["open_charge_cents"], open_cents, "open_charge_cents")
    if settled_cents is not None:
        assert_cents(generator["settled_charge_cents"], settled_cents, "settled_charge_cents")
    if voided_cents is not None:
        assert_cents(generator["voided_charge_cents"], voided_cents, "voided_charge_cents")
    if adjustment_cents is not None:
        assert_cents(
            generator["charge_adjustment_cents"], adjustment_cents, "charge_adjustment_cents"
        )
