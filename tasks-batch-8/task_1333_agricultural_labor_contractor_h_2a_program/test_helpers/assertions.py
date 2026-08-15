"""Entity assertions and domain invariant checkers (PRD 2.5, 3.x).

Field presence follows the PRD: append-only ledger entries (housing
inspections, work logs) carry only ``id`` and ``created_at`` and must NOT
expose ``updated_at``/``version`` (PRD 2.5); every other resource carries the
standard ``id``/``created_at``/``updated_at``/``version`` system fields.
"""
from typing import List

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a server-minted UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_append_only_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a server-minted UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "append-only ledger entries must not expose updated_at (PRD 2.5)"
    assert "version" not in data, "append-only ledger entries must not expose version (PRD 2.5)"


def assert_grower(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["fein"], str) and data["fein"]
    assert data["status"] in ["ACTIVE", "SUSPENDED", "DEBARRED"]
    assert data["debarment_ends_on"] is None or isinstance(data["debarment_ends_on"], str)


def assert_wage_determination(data: dict):
    _assert_common_fields(data)
    assert data["activity"] in ["HARVEST", "PACKING", "PLANTING", "GENERAL"]
    assert isinstance(data["effective_year"], int)
    assert isinstance(data["aewr_hourly_cents"], int) and data["aewr_hourly_cents"] > 0
    assert isinstance(data["prevailing_hourly_cents"], int) and data["prevailing_hourly_cents"] > 0
    assert data["status"] in ["PUBLISHED", "SUPERSEDED"]


def assert_job_order(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [
        "DRAFT", "SUBMITTED", "DEFICIENCY", "CERTIFIED", "RECRUITING",
        "PETITIONING", "ACTIVE", "CLOSING", "CLOSED", "WITHDRAWN",
    ]
    assert isinstance(data["total_calendar_days"], int)
    assert isinstance(data["total_workdays"], int)
    assert isinstance(data["required_hourly_floor_cents"], int)
    assert isinstance(data["domestic_hired_count"], int)
    assert isinstance(data["visa_worker_ceiling"], int)


def assert_domestic_application(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["APPLIED", "HIRED", "REJECTED", "WITHDRAWN"]
    assert isinstance(data["applied_on"], str)


def assert_worker(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["REGISTERED", "PETITIONED", "VISA_ISSUED", "WORKING", "DEPARTED", "ABANDONED"]
    assert data["petition_id"] is None or isinstance(data["petition_id"], str)


def assert_visa_petition(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["DRAFT", "FILED", "RFE", "APPROVED", "DENIED", "WITHDRAWN"]
    assert isinstance(data["requested_worker_count"], int) and data["requested_worker_count"] >= 1
    assert isinstance(data["rfe_count"], int) and 0 <= data["rfe_count"] <= 2


def assert_consular_appointment(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["SCHEDULED", "COMPLETED", "CANCELLED"]
    assert data["outcome"] in [None, "ISSUED", "REFUSED", "NO_SHOW"]


def assert_housing_unit(data: dict):
    _assert_common_fields(data)
    assert data["inspection_status"] in ["UNINSPECTED", "CERTIFIED", "FAILED", "EXPIRED"]
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert isinstance(data["occupied_count"], int) and data["occupied_count"] >= 0


def assert_housing_inspection(data: dict):
    _assert_append_only_fields(data)
    assert data["result"] in ["PASS", "FAIL"]


def assert_housing_assignment(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["OCCUPIED", "VACATED"]


def assert_worker_assignment(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["PLANNED", "ACTIVE", "COMPLETED", "TERMINATED", "TRANSFERRED_OUT"]
    assert data["end_reason"] in [None, "COMPLETED", "FOR_CAUSE", "ABANDONED", "TRANSFERRED_OUT"]
    assert isinstance(data["guarantee_eligible"], bool)


def assert_work_log(data: dict):
    _assert_append_only_fields(data)
    assert data["hours_worked"] > 0
    assert data["units_picked"] >= 0


def assert_wage_reconciliation(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["OPEN", "FINALIZED"]
    for field in (
        "piece_earnings_cents", "hourly_floor_earnings_cents", "makeup_pay_cents",
        "guarantee_basis_workdays", "guaranteed_quarters", "worked_quarters",
        "shortfall_quarters", "guarantee_pay_cents",
        "inbound_transport_owed_cents", "outbound_transport_owed_cents", "total_due_cents",
    ):
        assert isinstance(data[field], int), f"{field} must be integer cents, got {data.get(field)!r}"
    assert isinstance(data["guarantee_applied"], bool)
    assert data["shortfall_quarters"] >= 0, "shortfall is floored at zero (no negative clawback)"


def assert_transfer_request(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["PENDING", "GROWER_APPROVED", "APPROVED", "REJECTED", "CANCELLED"]
    assert data["reason"] in ["CONTRACT_IMPOSSIBILITY", "GROWER_REQUEST", "WORKER_REQUEST"]


def assert_audit_case(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["OPEN", "FINDINGS_ISSUED", "CLOSED_NO_ACTION", "RESOLVED_PENALTY", "RESOLVED_DEBARMENT"]
    assert data["trigger_source"] in ["MANUAL", "ABANDONMENT", "HOUSING", "WAGE_DISCREPANCY"]
    assert isinstance(data["findings"], list)
