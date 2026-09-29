"""Entity-shape assertions and domain invariant checkers."""

from typing import Any, Dict, Iterable, List, Sequence, Tuple

import pytest

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import POUNDS_TOLERANCE, RATIO_TOLERANCE, household_income_limit_cents
from .types import AllocationStatus, DrawPosture


# ---------------------------------------------------------------------------
# Common field discipline (PRD §2.5)
# ---------------------------------------------------------------------------

def assert_identity_fields(row: Dict[str, Any], entity: str = "row") -> None:
    assert "id" in row, f"{entity} is missing id"
    assert is_valid_uuid(row["id"]), f"{entity} id {row['id']!r} is not a UUID"
    assert "created_at" in row, f"{entity} is missing created_at"
    assert is_iso8601_timestamp(row["created_at"]), (
        f"{entity} created_at {row['created_at']!r} is not an ISO 8601 instant"
    )


def assert_versioned_row(row: Dict[str, Any], entity: str = "row") -> None:
    """Every resource except a commodity carries updated_at and version."""
    assert_identity_fields(row, entity)
    assert "updated_at" in row, f"{entity} is missing updated_at"
    assert is_iso8601_timestamp(row["updated_at"]), (
        f"{entity} updated_at {row['updated_at']!r} is not an ISO 8601 instant"
    )
    assert isinstance(row.get("version"), int), f"{entity} version is not an integer"
    assert row["version"] >= 1, f"{entity} version {row.get('version')} is below 1"


def assert_fields_absent(row: Dict[str, Any], field_names: Iterable[str], entity: str = "row") -> None:
    for field in field_names:
        assert field not in row, f"{entity} unexpectedly exposes {field}"


# ---------------------------------------------------------------------------
# Per-entity shapes
# ---------------------------------------------------------------------------

def _require(row: Dict[str, Any], fields: Sequence[str], entity: str) -> None:
    missing = [f for f in fields if f not in row]
    assert not missing, f"{entity} is missing fields {missing}"


def assert_service_area(row: Dict[str, Any]) -> None:
    assert_versioned_row(row, "ServiceArea")
    _require(
        row,
        ["name", "county_code", "poverty_population", "urban_rural", "eligible_agency_count"],
        "ServiceArea",
    )


def assert_agency(row: Dict[str, Any]) -> None:
    assert_versioned_row(row, "Agency")
    _require(
        row,
        [
            "name",
            "service_area_id",
            "cold_storage_pallet_capacity",
            "prior_period_pounds_distributed",
            "prior_period_allocated_cases",
            "agreement_status",
            "training_status",
            "eligibility_posture",
            "agency_cases_on_hand",
            "delivered_cases_ytd",
            "renewal_count",
        ],
        "Agency",
    )


def assert_commodity(row: Dict[str, Any]) -> None:
    """A commodity is immutable configuration: only id and created_at, no version."""
    assert_identity_fields(row, "Commodity")
    _require(
        row,
        [
            "code",
            "name",
            "storage_class",
            "net_weight_lbs_per_case",
            "cases_per_pallet",
            "entitlement_value_cents_per_case",
            "shelf_life_days",
            "excess_case_ceiling",
        ],
        "Commodity",
    )
    assert_fields_absent(row, ["version", "updated_at"], "Commodity")


def assert_warehouse(row: Dict[str, Any]) -> None:
    assert_versioned_row(row, "Warehouse")
    _require(
        row,
        [
            "name",
            "dock_count",
            "dry_pallet_capacity",
            "cold_pallet_capacity",
            "frozen_pallet_capacity",
            "monitor_policy",
        ],
        "Warehouse",
    )


def assert_inventory_lot(row: Dict[str, Any]) -> None:
    assert_versioned_row(row, "InventoryLot")
    _require(
        row,
        [
            "commodity_id",
            "warehouse_id",
            "federal_lot_code",
            "cases_received",
            "cases_on_hand",
            "cases_committed",
            "cases_shipped_to_date",
            "pack_date",
            "best_by_date",
            "entitlement_value_cents",
            "status",
            "monitor_flag",
            "slow_moving_index",
        ],
        "InventoryLot",
    )


def assert_allocation_cycle(row: Dict[str, Any]) -> None:
    assert_versioned_row(row, "AllocationCycle")
    _require(
        row,
        [
            "cycle_code",
            "formula_variant",
            "allocatable_cases",
            "admin_funds_pool_cents",
            "offered_commodity_codes",
            "order_window_open_at",
            "order_window_close_at",
            "status",
            "draw_posture",
            "total_allocated_cases",
            "eligible_agency_count",
            "admin_funds_allocated_cents",
        ],
        "AllocationCycle",
    )
    assert row["draw_posture"] in (
        DrawPosture.NOT_STARTED,
        DrawPosture.PARTIAL,
        DrawPosture.FULLY_DRAWN,
    ), f"draw_posture {row['draw_posture']!r} is outside the declared set"


def assert_agency_allocation(row: Dict[str, Any]) -> None:
    assert_versioned_row(row, "AgencyAllocation")
    _require(
        row,
        [
            "cycle_id",
            "agency_id",
            "poverty_factor",
            "poverty_share",
            "prior_share",
            "raw_score",
            "floor_cases",
            "allocated_cases",
            "cases_committed",
            "cases_delivered",
            "cases_remaining",
            "distributed_pounds",
            "distribution_record_count",
            "record_compliance_pct",
            "admin_funds_base_cents",
            "admin_funds_withheld_cents",
            "admin_funds_cents",
            "status",
        ],
        "AgencyAllocation",
    )
    assert_entitlement_identity(row)


def assert_commodity_order(row: Dict[str, Any]) -> None:
    assert_versioned_row(row, "CommodityOrder")
    _require(
        row,
        [
            "cycle_id",
            "agency_id",
            "warehouse_id",
            "status",
            "line_count",
            "total_cases_requested",
            "total_cases_approved",
            "total_pounds",
            "total_pallets",
            "revision_count",
        ],
        "CommodityOrder",
    )


def assert_order_line(row: Dict[str, Any]) -> None:
    assert_versioned_row(row, "OrderLine")
    _require(
        row,
        [
            "order_id",
            "commodity_id",
            "cases_requested",
            "cases_approved",
            "line_pounds",
            "line_pallets",
            "storage_class",
            "lot_assignments",
        ],
        "OrderLine",
    )


def assert_delivery_appointment(row: Dict[str, Any]) -> None:
    assert_versioned_row(row, "DeliveryAppointment")
    _require(
        row,
        [
            "order_id",
            "warehouse_id",
            "agency_id",
            "dock_number",
            "window_start",
            "window_end",
            "dry_pallets",
            "cold_pallets",
            "frozen_pallets",
            "delivered_pounds",
            "status",
        ],
        "DeliveryAppointment",
    )


def assert_inventory_transfer(row: Dict[str, Any]) -> None:
    assert_versioned_row(row, "InventoryTransfer")
    _require(
        row,
        ["from_lot_id", "to_agency_id", "cases", "status", "transferred_value_cents"],
        "InventoryTransfer",
    )


def assert_recall(row: Dict[str, Any]) -> None:
    assert_versioned_row(row, "Recall")
    _require(
        row,
        [
            "source_lot_id",
            "commodity_code",
            "recall_class",
            "hold_scope",
            "reason",
            "initiated_by_user_id",
            "status",
            "held_lot_count",
            "action_count",
            "acknowledged_count",
            "dispositioned_count",
            "accounted_cases",
        ],
        "Recall",
    )


def assert_recall_action(row: Dict[str, Any]) -> None:
    assert_versioned_row(row, "RecallAction")
    _require(
        row, ["recall_id", "agency_id", "status", "exposed_cases"], "RecallAction"
    )


def assert_household_distribution(row: Dict[str, Any]) -> None:
    assert_versioned_row(row, "HouseholdDistribution")
    _require(
        row,
        [
            "agency_id",
            "cycle_id",
            "commodity_id",
            "household_size",
            "declared_monthly_income_cents",
            "participates_in_snap",
            "self_declaration_signed",
            "cases_distributed",
            "distribution_date",
            "pounds_distributed",
            "income_limit_cents",
            "eligibility_determination",
            "status",
        ],
        "HouseholdDistribution",
    )


def assert_admin_funds_report(row: Dict[str, Any]) -> None:
    _require(
        row,
        [
            "cycle_code",
            "admin_funds_pool_cents",
            "admin_funds_allocated_cents",
            "withheld_cents_total",
            "redistributed_cents_total",
            "allocation_line_count",
            "non_compliant_line_count",
        ],
        "admin funds report",
    )


# ---------------------------------------------------------------------------
# Numeric comparisons
# ---------------------------------------------------------------------------

def assert_pounds(actual: Any, expected: float, label: str = "pounds") -> None:
    assert actual == pytest.approx(expected, abs=POUNDS_TOLERANCE), (
        f"{label} expected {expected} but got {actual}"
    )


def assert_ratio(actual: Any, expected: float, label: str = "ratio") -> None:
    assert actual == pytest.approx(expected, abs=RATIO_TOLERANCE), (
        f"{label} expected {expected} but got {actual}"
    )


def instant(iso_utc: str) -> str:
    """Render an instant the way PRD §2.5 requires: three fractional digits."""
    if iso_utc.endswith("Z") and "." not in iso_utc:
        return f"{iso_utc[:-1]}.000Z"
    return iso_utc


def assert_instant(actual: Any, expected: str, label: str = "timestamp") -> None:
    """Compare a rendered timestamp with an expected instant."""
    assert actual == instant(expected), (
        f"{label} expected {instant(expected)} but got {actual}"
    )


# ---------------------------------------------------------------------------
# Domain invariants
# ---------------------------------------------------------------------------

def assert_entitlement_identity(allocation: Dict[str, Any]) -> None:
    """cases_remaining == allocated_cases - cases_committed - cases_delivered."""
    expected = (
        allocation["allocated_cases"]
        - allocation["cases_committed"]
        - allocation["cases_delivered"]
    )
    assert allocation["cases_remaining"] == expected, (
        "cases_remaining "
        f"{allocation['cases_remaining']} does not equal allocated_cases "
        f"{allocation['allocated_cases']} minus cases_committed "
        f"{allocation['cases_committed']} minus cases_delivered "
        f"{allocation['cases_delivered']}"
    )


def assert_lot_ledger(
    lot: Dict[str, Any],
    cases_on_hand: int,
    cases_committed: int,
    cases_shipped_to_date: int,
) -> None:
    assert lot["cases_on_hand"] == cases_on_hand, (
        f"cases_on_hand expected {cases_on_hand} but got {lot['cases_on_hand']}"
    )
    assert lot["cases_committed"] == cases_committed, (
        f"cases_committed expected {cases_committed} but got {lot['cases_committed']}"
    )
    assert lot["cases_shipped_to_date"] == cases_shipped_to_date, (
        "cases_shipped_to_date expected "
        f"{cases_shipped_to_date} but got {lot['cases_shipped_to_date']}"
    )


def program_case_total(lots: Iterable[Dict[str, Any]], agencies: Iterable[Dict[str, Any]]) -> int:
    """PRD §2.9: on-hand cases of AVAILABLE/WATCH/HOLD lots plus agency on-hand cases."""
    lot_term = sum(
        lot["cases_on_hand"]
        for lot in lots
        if lot["status"] in ("AVAILABLE", "WATCH", "HOLD")
    )
    agency_term = sum(agency["agency_cases_on_hand"] for agency in agencies)
    return lot_term + agency_term


def assert_agency_axes(
    agency: Dict[str, Any],
    agreement_status: str,
    training_status: str,
    eligibility_posture: str,
) -> None:
    assert agency["agreement_status"] == agreement_status, (
        f"agreement_status expected {agreement_status} but got {agency['agreement_status']}"
    )
    assert agency["training_status"] == training_status, (
        f"training_status expected {training_status} but got {agency['training_status']}"
    )
    assert agency["eligibility_posture"] == eligibility_posture, (
        "eligibility_posture expected "
        f"{eligibility_posture} but got {agency['eligibility_posture']}"
    )


def assert_income_limit(distribution: Dict[str, Any]) -> None:
    expected = household_income_limit_cents(distribution["household_size"])
    assert distribution["income_limit_cents"] == expected, (
        f"income_limit_cents expected {expected} for household_size "
        f"{distribution['household_size']} but got {distribution['income_limit_cents']}"
    )


def assert_lot_assignments(
    line: Dict[str, Any], expected: Sequence[Tuple[str, int]]
) -> None:
    """Compare lot_assignments in fill order as (lot_id, cases) pairs."""
    actual: List[Tuple[str, int]] = [
        (entry["lot_id"], entry["cases"]) for entry in line["lot_assignments"]
    ]
    assert actual == list(expected), (
        f"lot_assignments expected {list(expected)} but got {actual}"
    )


def assert_allocation_sum_matches_pool(
    allocations: Sequence[Dict[str, Any]], allocatable_cases: int
) -> None:
    total = sum(row["allocated_cases"] for row in allocations)
    assert total == allocatable_cases, (
        f"allocated_cases sum {total} does not equal allocatable_cases {allocatable_cases}"
    )


def assert_admin_funds_sum_matches_pool(
    allocations: Sequence[Dict[str, Any]], admin_funds_pool_cents: int
) -> None:
    total = sum(row["admin_funds_cents"] for row in allocations)
    assert total == admin_funds_pool_cents, (
        f"admin_funds_cents sum {total} does not equal pool {admin_funds_pool_cents}"
    )


def assert_all_reconciled(allocations: Sequence[Dict[str, Any]]) -> None:
    for row in allocations:
        assert row["status"] == AllocationStatus.RECONCILED, (
            f"entitlement {row['id']} is {row['status']} rather than RECONCILED"
        )


def find_by(rows: Sequence[Dict[str, Any]], **criteria: Any) -> Dict[str, Any]:
    """Return the single row matching every criterion, failing loudly otherwise."""
    matches = [
        row for row in rows if all(row.get(k) == v for k, v in criteria.items())
    ]
    assert len(matches) == 1, (
        f"expected exactly one row matching {criteria} but found {len(matches)}"
    )
    return matches[0]
