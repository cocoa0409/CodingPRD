"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    ApprovalStatus,
    AssemblyRecordStatus,
    ClaimEligibility,
    ClaimStatus,
    CommercialStatus,
    DecisionAction,
    FindingCondition,
    LoanerAssignmentStatus,
    LoanerUnitStatus,
    OrderStatus,
    PhysicalStatus,
    RunInResult,
    RunInTestStatus,
    ShipmentDirection,
    ShipmentStatus,
)


def _assert_common_fields(data: dict, entity: str):
    """PRD §2.4: every primary resource carries id, created_at, updated_at,
    version."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be ISO 8601")
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be ISO 8601")
    assert isinstance(data.get("version"), int), f"{entity}.version must be an integer"


def assert_customer(data: dict):
    _assert_common_fields(data, "Customer")
    assert isinstance(data["legal_name"], str) and len(data["legal_name"]) > 0
    assert isinstance(data["credit_limit_cents"], int)
    assert isinstance(data["outstanding_approved_cents"], int)
    assert isinstance(data["credit_hold"], bool)


def assert_gear_unit(data: dict):
    _assert_common_fields(data, "GearUnit")
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["serial_number"], str) and len(data["serial_number"]) > 0
    assert isinstance(data["model"], str)
    assert isinstance(data["rated_torque_nm"], int)
    assert isinstance(data["cumulative_service_hours"], int)
    assert data["physical_status"] in [s.value for s in PhysicalStatus]
    assert data["commercial_status"] in [s.value for s in CommercialStatus]


def assert_reman_order(data: dict):
    _assert_common_fields(data, "RemanOrder")
    assert isinstance(data["gear_unit_id"], str)
    assert isinstance(data["intake_hours"], int)
    assert isinstance(data["quoted_estimate_cents"], int)
    assert isinstance(data["approved_scope_cents"], int)
    assert isinstance(data["rush"], bool)
    assert data["status"] in [s.value for s in OrderStatus]
    # Completion snapshots are null until the order completes (PRD §3.2).
    if data["status"] == OrderStatus.COMPLETED.value:
        assert isinstance(data.get("completed_at_hours"), int)
        assert isinstance(data.get("completed_at_utc"), str)
    else:
        assert data.get("completed_at_hours") is None
        assert data.get("completed_at_utc") is None


def assert_teardown_finding(data: dict):
    """PRD §2.4: the findings log is append-only — a finding carries only id
    and created_at; both updated_at and version are absent on it."""
    assert is_valid_uuid(data.get("id", "")), "TeardownFinding.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "TeardownFinding.created_at must be ISO 8601")
    assert "updated_at" not in data, "append-only finding must not carry updated_at"
    assert "version" not in data, "append-only finding must not carry version"
    assert isinstance(data["reman_order_id"], str)
    assert isinstance(data["component_code"], str) and len(data["component_code"]) > 0
    assert data["condition"] in [c.value for c in FindingCondition]
    assert isinstance(data["severity"], int) and 1 <= data["severity"] <= 5
    assert isinstance(data["notes"], str)


def assert_component_decision(data: dict):
    _assert_common_fields(data, "ComponentDecision")
    assert isinstance(data["reman_order_id"], str)
    assert isinstance(data["component_code"], str)
    assert data["action"] in [a.value for a in DecisionAction]
    assert isinstance(data["labor_hours"], (int, float))
    assert isinstance(data["material_cents"], int)
    assert isinstance(data["line_total_cents"], int)
    assert data["approval_status"] in [s.value for s in ApprovalStatus]


def assert_assembly_record(data: dict):
    _assert_common_fields(data, "AssemblyRecord")
    assert isinstance(data["reman_order_id"], str)
    assert isinstance(data["backlash_mm"], (int, float))
    assert isinstance(data["radial_clearance_mm"], (int, float))
    assert isinstance(data["axial_clearance_mm"], (int, float))
    assert isinstance(data["recorded_by"], str)
    assert isinstance(data["within_tolerance"], bool)
    assert data["status"] in [s.value for s in AssemblyRecordStatus]


def assert_run_in_test(data: dict):
    _assert_common_fields(data, "RunInTest")
    assert isinstance(data["reman_order_id"], str)
    assert isinstance(data["duration_minutes"], int)
    assert isinstance(data["max_temp_c"], (int, float))
    assert isinstance(data["vibration_mm_s"], (int, float))
    assert isinstance(data["oil_particle_count"], int)
    assert isinstance(data["oil_baseline_established"], bool)
    assert data["result"] in [r.value for r in RunInResult]
    assert data["status"] in [s.value for s in RunInTestStatus]


def assert_loaner_unit(data: dict):
    _assert_common_fields(data, "LoanerUnit")
    assert isinstance(data["serial_number"], str) and len(data["serial_number"]) > 0
    assert isinstance(data["model"], str)
    assert data["status"] in [s.value for s in LoanerUnitStatus]


def assert_loaner_assignment(data: dict):
    _assert_common_fields(data, "LoanerAssignment")
    assert isinstance(data["loaner_unit_id"], str)
    assert isinstance(data["reman_order_id"], str)
    assert isinstance(data["start_date"], str)
    assert isinstance(data["end_date"], str)
    assert data["status"] in [s.value for s in LoanerAssignmentStatus]


def assert_freight_shipment(data: dict):
    _assert_common_fields(data, "FreightShipment")
    assert isinstance(data["reman_order_id"], str)
    assert data["direction"] in [d.value for d in ShipmentDirection]
    assert isinstance(data["weight_kg"], int)
    assert isinstance(data["rigging_bay_date"], str)
    assert isinstance(data["rigging_bay_hours"], int)
    assert isinstance(data["freight_charge_cents"], int)
    assert data["status"] in [s.value for s in ShipmentStatus]


def assert_warranty_claim(data: dict):
    _assert_common_fields(data, "WarrantyClaim")
    assert isinstance(data["reman_order_id"], str)
    assert isinstance(data["reported_hours"], int)
    assert isinstance(data["claim_reason"], str)
    assert data["status"] in [s.value for s in ClaimStatus]
    # Eligibility resolves only once the linked order is COMPLETED (PRD §3.7).
    eligibility = data.get("eligibility")
    assert eligibility is None or eligibility in [e.value for e in ClaimEligibility]


def assert_credit_invariants(customer: dict):
    """PRD §2.10: exposure is a non-negative integer-cents aggregate and the
    hold flag is exactly 'outstanding strictly greater than the limit'."""
    outstanding = customer["outstanding_approved_cents"]
    limit = customer["credit_limit_cents"]
    assert isinstance(outstanding, int) and outstanding >= 0
    assert customer["credit_hold"] == (outstanding > limit), (
        f"credit_hold must be (outstanding {outstanding} > limit {limit})")
