"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

from .types import (
    CarrierStanding, PermitStatus, Classification, PermitType, ReservationStatus,
    StructurePosture, BridgeAnalysisStatus, BridgeMethod, PilotCarStatus, EscortStatus,
    EscortRole, BondStatus, ViolationStatus, ViolationType, Severity,
)


def _enum_values(enum_cls):
    return [e.value for e in enum_cls]


def assert_carrier(data: dict):
    assert is_valid_uuid(data.get("id", "")), "carrier id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["legal_name"], str) and len(data["legal_name"]) > 0
    assert isinstance(data["usdot_number"], str) and len(data["usdot_number"]) > 0
    assert isinstance(data["total_escrow_deposited_cents"], int)
    assert isinstance(data["escrow_balance_cents"], int)
    assert isinstance(data["active_bond_amount_cents"], int)
    assert isinstance(data["unpaid_fee_balance_cents"], int)
    assert data["compliance_standing"] in _enum_values(CarrierStanding)
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_permit(data: dict):
    assert is_valid_uuid(data.get("id", "")), "permit id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["permit_type"] in _enum_values(PermitType)
    assert data["status"] in _enum_values(PermitStatus)
    assert isinstance(data["length_in"], int)
    assert isinstance(data["width_in"], int)
    assert isinstance(data["height_in"], int)
    assert isinstance(data["gross_weight_lbs"], int)
    assert isinstance(data["num_axles"], int)
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_route_segment(data: dict):
    assert is_valid_uuid(data.get("id", "")), "route segment id must be a valid UUID"
    assert data["reservation_status"] in _enum_values(ReservationStatus)
    assert isinstance(data["sequence_index"], int) and data["sequence_index"] >= 1


def assert_structure(data: dict):
    assert is_valid_uuid(data.get("id", "")), "structure id must be a valid UUID"
    assert data["posture"] in _enum_values(StructurePosture)


def assert_structure_conserves_tonnage(data: dict):
    """committed_tonnage + available_tonnage == rated_capacity_tonnage (PRD §3.1)."""
    total = data["committed_tonnage"] + data["available_tonnage"]
    assert abs(total - data["rated_capacity_tonnage"]) < 1e-9, (
        f"tonnage not conserved: committed {data['committed_tonnage']} + "
        f"available {data['available_tonnage']} != rated {data['rated_capacity_tonnage']}"
    )


def assert_bridge_analysis(data: dict):
    assert is_valid_uuid(data.get("id", "")), "bridge analysis id must be a valid UUID"
    assert data["status"] in _enum_values(BridgeAnalysisStatus)
    if data.get("method") is not None:
        assert data["method"] in _enum_values(BridgeMethod)


def assert_pilot_car(data: dict):
    assert is_valid_uuid(data.get("id", "")), "pilot car id must be a valid UUID"
    assert data["status"] in _enum_values(PilotCarStatus)


def assert_escort_assignment(data: dict):
    assert is_valid_uuid(data.get("id", "")), "escort assignment id must be a valid UUID"
    assert data["role"] in _enum_values(EscortRole)
    assert data["status"] in _enum_values(EscortStatus)


def assert_bond(data: dict):
    assert is_valid_uuid(data.get("id", "")), "bond id must be a valid UUID"
    assert data["status"] in _enum_values(BondStatus)
    assert isinstance(data["amount_cents"], int)


def assert_violation(data: dict):
    assert is_valid_uuid(data.get("id", "")), "violation id must be a valid UUID"
    assert data["violation_type"] in _enum_values(ViolationType)
    assert data["severity"] in _enum_values(Severity)
    assert data["status"] in _enum_values(ViolationStatus)
    assert isinstance(data["penalty_cents"], int)


def assert_travel_restriction(data: dict):
    assert is_valid_uuid(data.get("id", "")), "travel restriction id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def assert_carrier_escrow_conserved(data: dict):
    """escrow_balance_cents + active_bond_amount_cents == total_escrow_deposited_cents
    (PRD §2.9), true whenever no bond has been forfeited."""
    total = data["escrow_balance_cents"] + data["active_bond_amount_cents"]
    assert total == data["total_escrow_deposited_cents"], (
        f"escrow not conserved: balance {data['escrow_balance_cents']} + "
        f"active_bond {data['active_bond_amount_cents']} != "
        f"total_deposited {data['total_escrow_deposited_cents']}"
    )
