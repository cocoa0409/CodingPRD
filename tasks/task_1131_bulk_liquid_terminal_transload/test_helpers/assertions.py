"""Entity assertions and domain invariant checkers (PRD §2.2, §2.5, §2.6, §3).

Assertions here only demand what the PRD pins for every implementation:
system-managed identity/timestamps, status membership, and PRD-named fields
when populated. Optional/nullable computed fields are type-checked only when
present and non-null.
"""
import numbers

from prd_bench_local_runner.testing import (
    assert_cost_precision,
    is_iso8601_timestamp,
    is_valid_uuid,
)


def _assert_common_fields(data: dict, entity_label: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity_label}.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_label}.created_at must be an ISO 8601 timestamp"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity_label}.updated_at must be an ISO 8601 timestamp"
    )
    assert isinstance(data.get("version"), int), f"{entity_label}.version must be an integer"


def _assert_numeric_if_present(data: dict, field: str, label: str):
    if field in data and data[field] is not None:
        assert isinstance(data[field], numbers.Real), f"{label}.{field} must be numeric"


def assert_customer(data: dict):
    _assert_common_fields(data, "Customer")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["contact_email"], str) and data["contact_email"]


def assert_tank(data: dict):
    _assert_common_fields(data, "Tank")
    assert isinstance(data["tank_code"], str) and data["tank_code"]
    assert data["product_grade"] in ["GASOLINE", "DIESEL", "JET", "ETHANOL", "CRUDE"]
    _assert_numeric_if_present(data, "capacity_bbl", "Tank")
    _assert_numeric_if_present(data, "safe_fill_pct", "Tank")
    _assert_numeric_if_present(data, "heel_bbl", "Tank")
    _assert_numeric_if_present(data, "working_capacity_bbl", "Tank")
    _assert_numeric_if_present(data, "current_inventory_bbl", "Tank")
    _assert_numeric_if_present(data, "provisional_inventory_bbl", "Tank")
    assert data["status"] in ["AVAILABLE", "MAINTENANCE", "RESTRICTED"]


def assert_terminal_resource(data: dict):
    _assert_common_fields(data, "TerminalResource")
    assert isinstance(data["resource_code"], str) and data["resource_code"]
    assert data["resource_type"] in ["DOCK", "RAIL_RACK", "TRUCK_BAY"]
    assert data["status"] in ["ACTIVE", "OUT_OF_SERVICE"]


def assert_lease_agreement(data: dict):
    _assert_common_fields(data, "LeaseAgreement")
    assert is_valid_uuid(data.get("customer_id", "")), "LeaseAgreement.customer_id must be a UUID"
    assert data["product_grade"] in ["GASOLINE", "DIESEL", "JET", "ETHANOL", "CRUDE"]
    for f in ("committed_capacity_bbl", "min_monthly_throughput_bbl", "throughput_fee_per_bbl",
              "shortfall_fee_per_bbl", "loss_allowance_pct", "excess_loss_rate_per_bbl",
              "reserved_capacity_bbl"):
        _assert_numeric_if_present(data, f, "LeaseAgreement")
    assert data["status"] in ["DRAFT", "ACTIVE", "SUSPENDED", "EXPIRED", "TERMINATED"]
    if data.get("suspension_reason") is not None:
        assert data["suspension_reason"] in ["MANUAL", "LOSS_CONTROL"]


def assert_lease_amendment(data: dict):
    _assert_common_fields(data, "LeaseAmendment")
    assert is_valid_uuid(data.get("lease_id", "")), "LeaseAmendment.lease_id must be a UUID"
    assert isinstance(data.get("base_lease_version"), int), "base_lease_version must be an integer"
    assert data["status"] in ["PROPOSED", "APPROVED", "REJECTED"]


def assert_tank_allocation(data: dict):
    _assert_common_fields(data, "TankAllocation")
    assert is_valid_uuid(data.get("lease_id", "")), "TankAllocation.lease_id must be a UUID"
    assert is_valid_uuid(data.get("tank_id", "")), "TankAllocation.tank_id must be a UUID"
    _assert_numeric_if_present(data, "allocated_bbl", "TankAllocation")
    assert data["status"] in ["RESERVED", "ACTIVE", "RELEASED"]


def assert_permit(data: dict):
    _assert_common_fields(data, "Permit")
    assert data["permit_type"] in ["VAPOR_CONTROL", "HOT_WORK"]
    assert is_valid_uuid(data.get("tank_id", "")), "Permit.tank_id must be a UUID"
    assert data["status"] in ["REQUESTED", "APPROVED", "REVOKED", "EXPIRED"]


def assert_movement(data: dict):
    _assert_common_fields(data, "Movement")
    assert is_valid_uuid(data.get("lease_id", "")), "Movement.lease_id must be a UUID"
    assert is_valid_uuid(data.get("tank_id", "")), "Movement.tank_id must be a UUID"
    assert data["direction"] in ["RECEIPT", "DISCHARGE"]
    assert data["mode"] in ["VESSEL", "RAIL", "TRUCK"]
    assert data["status"] in [
        "NOMINATED", "SCHEDULED", "ARRIVED", "IN_PROGRESS", "COMPLETED", "SUSPENDED", "CANCELLED",
    ]
    assert data["billing_status"] in ["UNBILLED", "ACCRUED", "INVOICED"]
    _assert_numeric_if_present(data, "declared_volume_bbl", "Movement")
    _assert_numeric_if_present(data, "demurrage_estimated_amount", "Movement")
    _assert_numeric_if_present(data, "demurrage_actual_amount", "Movement")
    for f in ("demurrage_estimated_amount", "demurrage_actual_amount"):
        if data.get(f) is not None:
            assert_cost_precision(data[f])


def assert_gauge_ticket(data: dict):
    # Append-only record (PRD §2.5): id + created_at only; no updated_at/version.
    assert is_valid_uuid(data.get("id", "")), "GaugeTicket.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "GaugeTicket.created_at must be an ISO 8601 timestamp"
    )
    assert "updated_at" not in data, "GaugeTicket must not carry updated_at"
    assert "version" not in data, "GaugeTicket must not carry version"
    assert data["ticket_type"] in ["OPENING", "CLOSING"]
    _assert_numeric_if_present(data, "observed_volume_bbl", "GaugeTicket")
    _assert_numeric_if_present(data, "observed_temp_f", "GaugeTicket")
    assert isinstance(data.get("recorded_by_user_id"), str) and data["recorded_by_user_id"]


def assert_quality_sample(data: dict):
    _assert_common_fields(data, "QualitySample")
    assert data["sample_type"] in ["FIRST_FOOT", "INLINE", "ALL_LEVELS"]
    assert data["lab_result"] in ["PENDING", "PASSED", "FAILED"]
    assert data["retain_status"] in ["RETAINED", "RELEASED"]
    _assert_numeric_if_present(data, "specific_gravity", "QualitySample")


def assert_custody_transfer(data: dict):
    _assert_common_fields(data, "CustodyTransfer")
    assert is_valid_uuid(data.get("movement_id", "")), "CustodyTransfer.movement_id must be a UUID"
    assert data["status"] in ["PROVISIONAL", "CERTIFIED", "DISPUTED", "VOID"]
    for f in ("provisional_volume_bbl", "certified_volume_bbl", "shrinkage_bbl",
              "allowed_loss_bbl", "excess_loss_bbl"):
        _assert_numeric_if_present(data, f, "CustodyTransfer")
    if data.get("excess_loss_charge") is not None:
        assert_cost_precision(data["excess_loss_charge"])


def assert_monthly_statement(data: dict):
    _assert_common_fields(data, "MonthlyStatement")
    assert is_valid_uuid(data.get("lease_id", "")), "MonthlyStatement.lease_id must be a UUID"
    assert data["status"] in ["OPEN", "CLOSED", "INVOICED"]
    for f in ("total_throughput_bbl", "shortfall_bbl", "total_excess_loss_bbl"):
        _assert_numeric_if_present(data, f, "MonthlyStatement")
    for f in ("throughput_fee_amount", "shortfall_fee_amount", "excess_loss_amount",
              "total_demurrage_amount", "total_dwell_amount", "statement_total_amount"):
        if data.get(f) is not None:
            assert isinstance(data[f], numbers.Real), f"MonthlyStatement.{f} must be numeric"
            assert_cost_precision(data[f])


def assert_tank_inventory_bounds(data: dict):
    """PRD §2.6 invariant anchor: certified inventory figure is consistent with
    the tank's working-capacity posture fields being numeric and comparable."""
    current = data.get("current_inventory_bbl")
    working = data.get("working_capacity_bbl")
    heel = data.get("heel_bbl")
    assert current is not None and working is not None and heel is not None
    if data.get("status") == "RESTRICTED":
        assert current > working or current < heel, (
            "RESTRICTED requires inventory outside [heel_bbl, working_capacity_bbl]"
        )
