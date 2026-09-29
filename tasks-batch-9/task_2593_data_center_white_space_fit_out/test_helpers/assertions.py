"""Entity assertions and domain invariant checkers."""
import pytest
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{entity}.created_at must be an ISO 8601 UTC timestamp"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"{entity}.updated_at must be an ISO 8601 UTC timestamp"
    assert isinstance(data.get("version"), int), f"{entity}.version must be an integer"
    assert data["version"] >= 1, f"{entity}.version starts at 1"


def assert_hall(data: dict):
    _assert_common(data, "Hall")
    assert data["status"] in ("PLANNING", "FIT_OUT", "COMMISSIONING", "LIVE")
    assert data["tenant_mode"] in ("SINGLE_TENANT", "MULTI_TENANT")
    assert data["cooling_redundancy"] in ("N", "N_PLUS_1")
    assert data["thermal_posture"] in ("NOMINAL", "CONSTRAINED", "CRITICAL")
    assert data["release_posture"] in ("OPEN", "RESTRICTED", "LOCKED")
    assert_hall_power_ledger_balances(data)
    assert_custody_partition(data)


def assert_hall_power_ledger_balances(data: dict):
    """committed_kw + commissioning_reserve_kw + spare_kw == design_kw_capacity."""
    total = (
        data["committed_kw"] + data["commissioning_reserve_kw"] + data["spare_kw"]
    )
    assert total == pytest.approx(data["design_kw_capacity"], abs=0.01), (
        "committed_kw + commissioning_reserve_kw + spare_kw must equal "
        f"design_kw_capacity, got {total} vs {data['design_kw_capacity']}"
    )


def assert_custody_partition(data: dict):
    """custody_ops_count + custody_fitout_count == rack_total_count."""
    assert (
        data["custody_ops_count"] + data["custody_fitout_count"]
        == data["rack_total_count"]
    ), (
        "custody_ops_count plus custody_fitout_count must equal rack_total_count, got "
        f"{data['custody_ops_count']} + {data['custody_fitout_count']} != "
        f"{data['rack_total_count']}"
    )
    assert data["at_risk_rack_count"] <= data["custody_fitout_count"], (
        "at-risk racks sit on the fit-out side of the custody partition"
    )


def assert_tenant(data: dict):
    _assert_common(data, "Tenant")
    assert isinstance(data["code"], str) and 1 <= len(data["code"]) <= 16
    assert data["contracted_kw"] > 0
    assert data["allocated_kw"] >= 0


def assert_pdu(data: dict):
    _assert_common(data, "PowerDistributionUnit")
    assert data["status"] in ("PLANNED", "COMMISSIONED")
    assert data["feed_side"] in ("A", "B")
    assert 0.50 <= data["measured_derate_factor"] <= 1.00


def assert_busway(data: dict):
    _assert_common(data, "Busway")
    assert data["status"] in ("INSTALLED", "ENERGIZED", "ISOLATED")
    assert data["usable_variant"] in ("DESIGN", "COMMISSIONED")
    assert data["redundancy_topology"] in ("N", "N_PLUS_1", "TWO_N")
    assert data["voltage_v"] in (400, 415, 480)
    assert data["feed_count"] >= 0
    assert data["committed_kw"] <= data["usable_kw"] + 1e-9, (
        "a busway's committed load never exceeds its usable ceiling"
    )


def assert_containment_zone(data: dict):
    _assert_common(data, "ContainmentZone")
    assert data["leakage_status"] in ("UNTESTED", "PASS", "FAIL", "REMEDIATION")
    assert data["zone_type"] in ("HOT_AISLE", "COLD_AISLE")
    assert data["containment_kind"] in ("RIGID_ROOF", "CURTAIN", "CHIMNEY")
    assert data["test_count"] >= 0


def assert_cooling_unit(data: dict):
    _assert_common(data, "CoolingUnit")
    assert data["status"] in ("INSTALLED", "COMMISSIONED", "IN_SERVICE", "MAINTENANCE")
    assert data["redundancy_role"] in ("PRIMARY", "REDUNDANT")


def assert_cage(data: dict):
    _assert_common(data, "Cage")
    assert data["operational_status"] in (
        "FIT_OUT",
        "SECURED",
        "DEGRADED",
        "RELEASED",
    )
    assert 0.00 <= data["camera_coverage_pct"] <= 100.00, (
        "camera coverage is capped at 100.00"
    )
    assert data["active_reader_zone_count"] >= 0


def assert_security_device(data: dict):
    _assert_common(data, "SecurityDevice")
    assert data["status"] in ("PLANNED", "ACTIVE")
    assert data["device_type"] in ("CAMERA", "CARD_READER")


def assert_rack(data: dict):
    _assert_common(data, "Rack")
    assert data["status"] in (
        "PLANNED",
        "INSTALLED",
        "POWERED",
        "AT_RISK",
        "RELEASED",
    )
    assert data["u_height"] in (42, 45, 48)
    assert data["required_feed_count"] in (1, 2)
    assert data["energized_feed_count"] >= 0


def assert_rack_feed(data: dict):
    _assert_common(data, "RackFeed")
    assert data["status"] in ("RESERVED", "ENERGIZED", "DERATED", "RELEASED")
    assert data["feed_side"] in ("A", "B")


def assert_commissioning_package(data: dict):
    _assert_common(data, "CommissioningPackage")
    assert data["level"] in ("L1", "L2", "L3", "L4", "L5")
    assert data["script_status"] in ("NOT_STARTED", "SCRIPT_APPROVED", "EXECUTED")
    assert data["witness_status"] in ("PENDING", "WITNESSED", "REJECTED", "BLOCKED")
    assert data["package_state"] in (
        "DRAFT",
        "IN_EXECUTION",
        "CERTIFIED",
        "FAILED",
        "BLOCKED",
        "SUPERSEDED",
    )


def assert_load_bank_test(data: dict):
    _assert_common(data, "LoadBankTest")
    assert data["status"] in ("SCHEDULED", "RUNNING", "COMPLETED", "ABORTED")
    assert data["result"] in (None, "PASS", "FAIL")


def assert_mop(data: dict):
    _assert_common(data, "MethodOfProcedure")
    assert data["status"] in (
        "DRAFT",
        "UNDER_REVIEW",
        "REVISION_REQUESTED",
        "APPROVED",
        "SCHEDULED",
        "IN_EXECUTION",
        "CLOSED",
        "BACKED_OUT",
        "REJECTED",
    )
    assert data["risk_class"] in ("LOW", "MEDIUM", "HIGH")
    assert data["target_resource_type"] in (
        "BUSWAY",
        "COOLING_UNIT",
        "CONTAINMENT_ZONE",
        "RACK",
    )
    assert data["revision_count"] >= 0
    assert data["approval_count"] >= 0


def assert_mop_approval(data: dict):
    """An approval row is immutable evidence: only id and created_at, no
    updated_at and no version at all."""
    assert is_valid_uuid(data.get("id", "")), "MopApproval.id must be a UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), "MopApproval.created_at must be an ISO 8601 UTC timestamp"
    assert "updated_at" not in data, "an approval record carries no updated_at"
    assert "version" not in data, "an approval record carries no version"
    assert data["decision"] in ("APPROVE", "REQUEST_REVISION", "REJECT")
    assert data["sequence"] >= 1


def assert_release_packet(data: dict):
    _assert_common(data, "ReleasePacket")
    assert data["status"] in (
        "DRAFT",
        "SUBMITTED",
        "ACCEPTED",
        "REJECTED",
        "SUSPENDED",
        "SUPERSEDED",
    )
    assert data["rack_in_scope_count"] >= 0
    assert 0.00 <= data["asset_tag_completion_pct"] <= 100.00


def assert_two_decimal_places(value: float, field: str = "value"):
    assert value == round(value, 2), f"{field} must carry 2 decimal places, got {value}"


def assert_three_decimal_places(value: float, field: str = "value"):
    assert value == round(value, 3), f"{field} must carry 3 decimal places, got {value}"


def assert_five_decimal_places(value: float, field: str = "value"):
    assert value == round(value, 5), f"{field} must carry 5 decimal places, got {value}"


def assert_kw(actual: float, expected: float, field: str = "value"):
    assert actual == pytest.approx(expected, abs=0.005), (
        f"{field}: expected {expected}, got {actual}"
    )


def assert_kw3(actual: float, expected: float, field: str = "value"):
    assert actual == pytest.approx(expected, abs=0.0005), (
        f"{field}: expected {expected}, got {actual}"
    )


def assert_kw5(actual: float, expected: float, field: str = "value"):
    assert actual == pytest.approx(expected, abs=0.000005), (
        f"{field}: expected {expected}, got {actual}"
    )
