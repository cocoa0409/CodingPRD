"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_host_site(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["state_code"], str)
    assert isinstance(data["ada_required"], bool)
    assert isinstance(data["lifetime_gross_revenue_cents"], int)
    assert isinstance(data["station_count"], int)


def assert_station(data: dict):
    _assert_common(data)
    assert data["operational_status"] in ["PENDING", "COMMISSIONED", "SUSPENDED", "DECOMMISSIONED"]
    assert isinstance(data["total_ports"], int) and data["total_ports"] >= 0
    assert isinstance(data["available_ports"], int) and data["available_ports"] >= 0


def assert_port(data: dict):
    _assert_common(data)
    assert data["operational_status"] in ["IN_SERVICE", "OUT_OF_SERVICE"]
    assert data["occupancy_status"] in ["AVAILABLE", "RESERVED", "OCCUPIED"]
    assert data["connector_type"] in ["CCS1", "CCS2", "NACS", "CHADEMO"]


def assert_charging_session(data: dict):
    _assert_common(data)
    assert data["status"] in ["ACTIVE", "STOPPED", "FINALIZED", "VOIDED", "ABORTED"]
    assert isinstance(data["energy_cost_cents"], int)
    assert isinstance(data["idle_fee_cents"], int)
    assert isinstance(data["session_fee_cents"], int)
    assert isinstance(data["final_cost_cents"], int)


def assert_rebate_claim(data: dict):
    _assert_common(data)
    assert data["status"] in ["DRAFT", "SUBMITTED", "AUDITED", "APPROVED", "REJECTED"]
    assert data["compliance_status"] in ["PENDING", "COMPLIANT", "NON_COMPLIANT"]
    assert isinstance(data["estimated_amount_cents"], int)
    assert isinstance(data["audited_amount_cents"], int)


def assert_revenue_statement(data: dict):
    _assert_common(data)
    assert data["status"] in ["DRAFT", "FINALIZED"]
    assert data["basis"] in ["GROSS", "NET"]
    assert isinstance(data["gross_revenue_cents"], int)
    assert isinstance(data["host_share_cents"], int)
    assert isinstance(data["program_share_cents"], int)
