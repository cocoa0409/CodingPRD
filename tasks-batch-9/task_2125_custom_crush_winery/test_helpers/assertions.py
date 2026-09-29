"""Entity assertions and domain invariant checkers."""
from decimal import ROUND_HALF_UP, Decimal

import pytest

from prd_bench_local_runner.testing import (
    assert_cost_precision,
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import STORAGE
from .types import (
    AllocationStatus,
    Appellation,
    BlendTrialStatus,
    BondStatus,
    BottlingLineStatus,
    BottlingRunStatus,
    ClientStatus,
    ContractStatus,
    DryGoodsItemType,
    FacilityZone,
    IntakeStatus,
    LotOrigin,
    OperationType,
    ProductionStatus,
    ReleaseOrderStatus,
    ReleaseType,
    TTBReportStatus,
    TTBVariant,
    Varietal,
    VesselCondition,
    VesselType,
    WorkOrderStatus,
)

_MEMBERS = lambda enum_cls: [m.value for m in enum_cls]  # noqa: E731


def assert_gallons_precision(value: float) -> None:
    """Volumes are carried in gallons to two decimal places (PRD 2.7)."""
    assert value == pytest.approx(round(value, 2)), (
        f"Gallons figure {value} carries more than two decimal places"
    )


def assert_common_fields(data: dict, label: str = "resource") -> None:
    """id / created_at / updated_at / version, carried by all thirteen types."""
    assert is_valid_uuid(data.get("id", "")), (
        f"{label}.id must be a bare UUID carrying no type prefix"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be ISO 8601 UTC"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label}.updated_at must be ISO 8601 UTC"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version must be an integer of at least 1"
    )


def assert_client(data: dict) -> None:
    assert_common_fields(data, "Client")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["ttb_permit_number"], str)
    assert isinstance(data["contact_email"], str)
    assert data["status"] in _MEMBERS(ClientStatus)
    assert data["bond_gallons_in_bond"] >= 0
    assert_gallons_precision(data["bond_gallons_in_bond"])
    assert data["taxpaid_gallons_ytd"] >= 0
    assert_gallons_precision(data["taxpaid_gallons_ytd"])
    if data["last_filed_period_end"] is not None:
        assert is_iso8601_timestamp(data["last_filed_period_end"])


def assert_contract(data: dict) -> None:
    assert_common_fields(data, "Contract")
    assert is_valid_uuid(data["client_id"])
    assert isinstance(data["harvest_year"], int)
    assert data["status"] in _MEMBERS(ContractStatus)
    assert data["committed_tons"] > 0
    assert data["tank_gallons_entitled"] > 0
    assert data["barrel_slots_entitled"] >= 0
    assert data["crush_rate_cents_per_ton"] > 0
    assert data["storage_rate_cents_per_gallon_month"] > 0
    assert data["labor_rate_cents_per_hour"] > 0
    assert is_iso8601_timestamp(data["effective_from"])
    assert is_iso8601_timestamp(data["effective_to"])
    assert data["tons_received"] >= 0
    assert data["gallons_allocated"] >= 0
    assert_gallons_precision(data["gallons_allocated"])
    assert isinstance(data["barrel_slots_used"], int) and data["barrel_slots_used"] >= 0
    assert isinstance(data["billed_total_cents"], int), (
        "billed_total_cents must be a whole number of cents"
    )
    if data["storage_billed_through"] is not None:
        assert is_iso8601_timestamp(data["storage_billed_through"])


def assert_vessel(data: dict) -> None:
    assert_common_fields(data, "Vessel")
    assert isinstance(data["vessel_code"], str) and data["vessel_code"]
    assert data["vessel_type"] in _MEMBERS(VesselType)
    assert data["capacity_gallons"] > 0
    assert data["facility_zone"] in _MEMBERS(FacilityZone)
    assert data["condition"] in _MEMBERS(VesselCondition)
    if data["last_released_at"] is not None:
        assert is_iso8601_timestamp(data["last_released_at"])


def assert_vessel_allocation(data: dict) -> None:
    assert_common_fields(data, "VesselAllocation")
    assert is_valid_uuid(data["contract_id"])
    assert is_valid_uuid(data["vessel_id"])
    assert data["status"] in _MEMBERS(AllocationStatus)
    assert is_iso8601_timestamp(data["start_at"])
    assert is_iso8601_timestamp(data["end_at"])
    assert data["allocated_gallons"] > 0
    assert isinstance(data["occupied_days"], int) and data["occupied_days"] >= 0
    if data["lot_id"] is not None:
        assert is_valid_uuid(data["lot_id"])
    if data["committed_at"] is not None:
        assert is_iso8601_timestamp(data["committed_at"])
    if data["released_at"] is not None:
        assert is_iso8601_timestamp(data["released_at"])


def assert_harvest_intake(data: dict) -> None:
    assert_common_fields(data, "HarvestIntake")
    assert is_valid_uuid(data["contract_id"])
    assert data["status"] in _MEMBERS(IntakeStatus)
    assert data["varietal"] in _MEMBERS(Varietal)
    assert data["appellation"] in _MEMBERS(Appellation)
    assert data["gross_weight_lbs"] > 0
    assert 0 <= data["tare_weight_lbs"] < data["gross_weight_lbs"]
    assert data["net_weight_lbs"] == pytest.approx(
        data["gross_weight_lbs"] - data["tare_weight_lbs"], abs=0.01
    ), "net_weight_lbs must be gross_weight_lbs less tare_weight_lbs"
    assert data["estimated_gallons"] >= 0
    assert isinstance(data["crush_fee_cents"], int)
    assert is_iso8601_timestamp(data["received_at"])
    if data["brix"] is not None:
        assert 10.00 <= data["brix"] <= 35.00
    if data["ph"] is not None:
        assert 2.50 <= data["ph"] <= 4.50


def assert_lot(data: dict) -> None:
    assert_common_fields(data, "Lot")
    assert is_valid_uuid(data["contract_id"])
    assert data["origin"] in _MEMBERS(LotOrigin)
    assert data["production_status"] in _MEMBERS(ProductionStatus)
    assert data["bond_status"] in _MEMBERS(BondStatus)
    assert data["varietal"] in _MEMBERS(Varietal)
    assert data["appellation"] in _MEMBERS(Appellation)
    assert isinstance(data["varietal_label"], str)
    assert isinstance(data["appellation_label"], str)
    assert data["volume_gallons"] >= 0
    assert_gallons_precision(data["volume_gallons"])
    assert data["loss_gallons"] >= 0
    assert_gallons_precision(data["loss_gallons"])
    assert isinstance(data["cases_bottled"], int) and data["cases_bottled"] >= 0
    assert isinstance(data["aging_days"], int) and data["aging_days"] >= 0
    assert isinstance(data["source_intake_ids"], list)
    assert isinstance(data["component_manifest"], list)
    if data["aging_start_at"] is not None:
        assert is_iso8601_timestamp(data["aging_start_at"])
    else:
        assert data["aging_days"] == 0, "aging_days is 0 whenever aging_start_at is null"


def assert_blend_trial(data: dict) -> None:
    assert_common_fields(data, "BlendTrial")
    assert is_valid_uuid(data["contract_id"])
    assert data["status"] in _MEMBERS(BlendTrialStatus)
    assert isinstance(data["round_number"], int) and data["round_number"] >= 1
    assert 0 <= data["declared_loss_pct"] <= 5
    assert isinstance(data["components"], list)
    assert data["total_component_gallons"] >= 0
    assert data["projected_loss_gallons"] >= 0
    assert data["projected_blend_gallons"] >= 0
    assert_gallons_precision(data["total_component_gallons"])
    assert_gallons_precision(data["projected_loss_gallons"])
    assert_gallons_precision(data["projected_blend_gallons"])


def assert_work_order(data: dict) -> None:
    assert_common_fields(data, "WorkOrder")
    assert is_valid_uuid(data["lot_id"])
    assert data["operation_type"] in _MEMBERS(OperationType)
    assert data["status"] in _MEMBERS(WorkOrderStatus)
    assert data["labor_hours"] > 0
    assert isinstance(data["crew_size"], int) and data["crew_size"] >= 1
    assert isinstance(data["material_cost_cents"], int)
    assert data["material_cost_cents"] >= 0
    assert isinstance(data["rush"], bool)
    for field in (
        "base_labor_cents",
        "rush_surcharge_cents",
        "subtotal_cents",
        "billable_amount_cents",
    ):
        assert isinstance(data[field], int), f"{field} must be whole cents"
        assert data[field] >= 0


def assert_bottling_line(data: dict) -> None:
    assert_common_fields(data, "BottlingLine")
    assert isinstance(data["line_code"], str) and data["line_code"]
    assert data["cases_per_hour"] > 0
    assert data["changeover_minutes"] >= 0
    assert data["daily_capacity_hours"] > 0
    assert data["status"] in _MEMBERS(BottlingLineStatus)


def assert_bottling_run(data: dict) -> None:
    assert_common_fields(data, "BottlingRun")
    assert is_valid_uuid(data["lot_id"])
    assert is_valid_uuid(data["line_id"])
    assert data["status"] in _MEMBERS(BottlingRunStatus)
    assert data["bottle_size_ml"] in (375, 750, 1500)
    assert isinstance(data["cases_planned"], int) and data["cases_planned"] >= 1
    assert is_iso8601_timestamp(data["scheduled_start"])
    assert is_iso8601_timestamp(data["scheduled_end"])
    assert data["run_hours"] == pytest.approx(round(data["run_hours"] / 0.25) * 0.25), (
        "run_hours must be an exact multiple of one quarter hour"
    )
    assert data["gallons_consumed"] >= 0
    assert_gallons_precision(data["gallons_consumed"])
    assert isinstance(data["supply_reservations"], list)


def assert_dry_goods_item(data: dict) -> None:
    assert_common_fields(data, "DryGoodsItem")
    assert is_valid_uuid(data["client_id"])
    assert data["item_type"] in _MEMBERS(DryGoodsItemType)
    assert isinstance(data["units_per_case"], int) and data["units_per_case"] >= 1
    for field in ("on_hand_units", "reserved_units", "available_units"):
        assert isinstance(data[field], int), f"{field} must be a whole unit count"
    assert data["available_units"] == data["on_hand_units"] - data["reserved_units"], (
        "available_units must equal on_hand_units less reserved_units"
    )


def assert_ttb_report(data: dict) -> None:
    assert_common_fields(data, "TTBReport")
    assert is_valid_uuid(data["client_id"])
    assert data["status"] in _MEMBERS(TTBReportStatus)
    assert data["variant"] in _MEMBERS(TTBVariant)
    assert is_iso8601_timestamp(data["period_start"])
    assert is_iso8601_timestamp(data["period_end"])
    assert isinstance(data["amendment_count"], int) and data["amendment_count"] >= 0
    for field in (
        "opening_gallons",
        "produced_gallons",
        "removed_taxpaid_gallons",
        "removed_in_bond_gallons",
        "loss_gallons",
        "closing_gallons",
        "variance_gallons",
    ):
        assert_gallons_precision(data[field])
    if data["filed_at"] is not None:
        assert is_iso8601_timestamp(data["filed_at"])


def assert_release_order(data: dict) -> None:
    assert_common_fields(data, "ReleaseOrder")
    assert is_valid_uuid(data["lot_id"])
    assert data["release_type"] in _MEMBERS(ReleaseType)
    assert data["status"] in _MEMBERS(ReleaseOrderStatus)
    assert data["gallons"] > 0
    assert_gallons_precision(data["gallons"])
    assert isinstance(data["excise_tax_cents"], int)
    assert data["excise_tax_cents"] >= 0
    if data["executed_at"] is not None:
        assert is_iso8601_timestamp(data["executed_at"])


# ─── Domain invariants ───────────────────────────────────────────────


def assert_ttb_reconciles(report: dict) -> None:
    """variance_gallons closes the books exactly as PRD 3.9 defines it."""
    expected = round_half_up(
        report["closing_gallons"]
        - (
            report["opening_gallons"]
            + report["produced_gallons"]
            - report["removed_taxpaid_gallons"]
            - report["removed_in_bond_gallons"]
            - report["loss_gallons"]
        ),
        2,
    )
    assert report["variance_gallons"] == pytest.approx(expected, abs=0.01), (
        f"variance_gallons {report['variance_gallons']} does not close the "
        f"reconciliation, which yields {expected}"
    )


def round_half_up(value: float, digits: int = 0) -> float:
    """Round half up, the rounding discipline PRD 2.7 pins for money and volume."""
    quantum = Decimal(1).scaleb(-digits)
    rounded = Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP)
    return int(rounded) if digits == 0 else float(rounded)


def assert_work_order_billing_chain(order: dict) -> None:
    """subtotal and billable follow the pinned five-step order of PRD 3.6."""
    assert order["subtotal_cents"] == (
        order["base_labor_cents"]
        + order["rush_surcharge_cents"]
        + order["material_cost_cents"]
    ), "subtotal_cents must be base labour plus rush surcharge plus materials"
    discount = round_half_up(
        order["subtotal_cents"] * order["volume_discount_pct"] / 100
    )
    assert order["billable_amount_cents"] == order["subtotal_cents"] - discount, (
        "billable_amount_cents must be subtotal less the rounded discount"
    )


def contract_gallons_invariant(lots) -> float:
    """Total across a contract's lots of volume_gallons plus loss_gallons."""
    return round(
        sum(lot["volume_gallons"] + lot["loss_gallons"] for lot in lots), 2
    )


def client_units_invariant(items) -> int:
    """Total across a client's dry-goods items of available plus reserved units."""
    return sum(item["available_units"] + item["reserved_units"] for item in items)


def whole_days_between(start_epoch_seconds: float, end_epoch_seconds: float) -> int:
    """Whole 86400-second days, remainder discarded, never negative (PRD 2.7)."""
    delta = end_epoch_seconds - start_epoch_seconds
    if delta <= 0:
        return 0
    return int(delta // STORAGE["SECONDS_PER_DAY"])
