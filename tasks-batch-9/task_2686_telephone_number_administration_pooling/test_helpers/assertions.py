"""Entity assertions and domain invariant checkers."""
import pytest
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AllocationRequestStatus,
    AllocationStatus,
    AuditFindingStatus,
    CarrierType,
    CommenterType,
    CommentPosition,
    EligibilityStatus,
    FacilitiesReadinessStatus,
    FilingStatus,
    FindingType,
    LicenseStatus,
    NpaStatus,
    NpaType,
    PenaltyAction,
    PoolingStatus,
    PortRequestStatus,
    ReclamationOrderStatus,
    ReclamationReason,
    ReliefPlanStatus,
    RequestType,
    RoutingRecordStatus,
    RoutingStatus,
)

PCT_TOLERANCE = 0.005


def _members(enum_cls):
    return [member.value for member in enum_cls]


def assert_identity(data: dict) -> None:
    """Every row carries a UUID id and an ISO 8601 created_at."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601, got {data.get('created_at')!r}"


def assert_mutable_identity(data: dict) -> None:
    """Rows that can be mutated also carry updated_at and a version starting at 1."""
    assert_identity(data)
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1"


def assert_append_only_identity(data: dict) -> None:
    """Append-only rows carry id and created_at and nothing else from the quartet."""
    assert_identity(data)
    assert "updated_at" not in data, "append-only rows carry no updated_at"
    assert "version" not in data, "append-only rows carry no version"


def assert_pct(actual, expected, label: str = "percentage") -> None:
    """Percentages are published at two decimal places, rounded half up."""
    assert actual == pytest.approx(
        expected, abs=PCT_TOLERANCE
    ), f"{label}: expected {expected}, got {actual}"


def assert_two_decimal_places(value, label: str = "percentage") -> None:
    assert value is not None, f"{label} must be published"
    assert round(float(value), 2) == pytest.approx(
        float(value), abs=1e-9
    ), f"{label} must carry at most two decimal places, got {value}"


def assert_carrier(data: dict) -> None:
    assert_mutable_identity(data)
    assert len(data["ocn"]) == 4, "ocn is exactly four characters"
    assert 1 <= len(data["legal_name"]) <= 120
    assert data["carrier_type"] in _members(CarrierType)
    assert len(data["home_state_code"]) == 2
    assert data["license_status"] in _members(LicenseStatus)
    assert data["facilities_readiness_status"] in _members(FacilitiesReadinessStatus)
    assert data["eligibility_status"] in _members(EligibilityStatus)
    assert data["blocks_held_count"] >= 0
    assert data["reclamation_strike_count"] >= 0
    assert data["safety_valve_grant_count"] >= 0


def assert_fresh_carrier(data: dict) -> None:
    """A carrier that has only just been registered sits at both axes' start."""
    assert_carrier(data)
    assert data["license_status"] == "NONE"
    assert data["license_expires_on"] is None
    assert data["facilities_readiness_status"] == "NOT_SUBMITTED"
    assert data["switch_clli"] is None
    assert data["interconnection_ready"] is False
    assert data["eligibility_status"] == "INELIGIBLE"
    assert data["blocks_held_count"] == 0
    assert data["reclamation_strike_count"] == 0
    assert data["safety_valve_grant_count"] == 0
    assert data["probation_until"] is None
    assert data["version"] == 1


def assert_npa(data: dict) -> None:
    assert_mutable_identity(data)
    assert len(data["npa_code"]) == 3 and data["npa_code"].isdigit()
    assert data["npa_code"][0] in "23456789"
    assert data["npa_type"] in _members(NpaType)
    assert data["status"] in _members(NpaStatus)
    assert data["available_block_count"] >= 0
    assert data["total_block_count"] >= data["available_block_count"]


def assert_rate_center(data: dict) -> None:
    assert_mutable_identity(data)
    assert 1 <= len(data["name"]) <= 64
    assert len(data["lata_code"]) == 3 and data["lata_code"].isdigit()
    assert data["pooling_status"] in _members(PoolingStatus)
    assert isinstance(data["jeopardy_flag"], bool)
    assert isinstance(data["accepts_initial_requests"], bool)
    assert data["available_block_count"] >= 0
    assert data["assigned_block_count"] >= 0
    assert data["pending_request_count"] >= 0


def assert_accepts_initial_requests_is_derived(data: dict) -> None:
    """accepts_initial_requests is false exactly when the code is in jeopardy or
    the rate center is mid-transition to pooling."""
    expected = not (data["jeopardy_flag"] or data["pooling_status"] == "TRANSITIONAL")
    assert data["accepts_initial_requests"] is expected, (
        "accepts_initial_requests must be derived from jeopardy_flag and "
        f"pooling_status, got {data['accepts_initial_requests']} with "
        f"jeopardy_flag {data['jeopardy_flag']} and pooling_status {data['pooling_status']}"
    )


def assert_number_block(data: dict) -> None:
    assert_mutable_identity(data)
    assert len(data["nxx_code"]) == 3 and data["nxx_code"].isdigit()
    assert 0 <= data["thousands_digit"] <= 9
    assert data["allocation_status"] in _members(AllocationStatus)
    assert data["routing_status"] in _members(RoutingStatus)
    assert 0 <= data["contaminated_count"] <= 1000
    assert isinstance(data["is_pooling_eligible"], bool)
    assert data["npac_db_version"] >= 0


def assert_block_label(data: dict, npa_code: str) -> None:
    expected = f"{npa_code}-{data['nxx_code']}-{data['thousands_digit']}"
    assert data["block_label"] == expected, (
        f"block_label must read {expected}, got {data['block_label']}"
    )


def assert_is_pooling_eligible_is_derived(data: dict) -> None:
    """A block is pooling eligible when its contaminated_count is at most 100."""
    assert data["is_pooling_eligible"] is (data["contaminated_count"] <= 100)


def assert_unheld_block(data: dict) -> None:
    """A block sitting in the pool carries no holder and none of the holding stamps."""
    assert data["holder_carrier_id"] is None
    assert data["assigned_at"] is None
    assert data["activation_due_at"] is None
    assert data["activated_at"] is None


def assert_allocation_request(data: dict) -> None:
    assert_mutable_identity(data)
    assert data["request_type"] in _members(RequestType)
    assert 1 <= data["requested_block_count"] <= 10
    assert data["status"] in _members(AllocationRequestStatus)
    assert data["info_request_count"] >= 0
    assert data["granted_block_count"] >= 0
    assert isinstance(data["assigned_block_ids"], list)
    assert data["granted_block_count"] == len(data["assigned_block_ids"]) or data[
        "status"
    ] != "APPROVED"


def assert_fresh_allocation_request(data: dict) -> None:
    """A newly filed request opens undecided."""
    assert_allocation_request(data)
    assert data["status"] == "PENDING_REVIEW"
    assert data["info_request_count"] == 0
    assert data["granted_block_count"] == 0
    assert data["assigned_block_ids"] == []
    assert data["reviewer_user_id"] is None
    assert data["approver_user_id"] is None
    assert data["decided_at"] is None
    assert data["denial_reason"] is None
    assert data["superseded_by_request_id"] is None


def assert_utilization_filing(data: dict) -> None:
    assert_mutable_identity(data)
    assert data["status"] in _members(FilingStatus)
    assert data["reporting_period"][:4].isdigit()
    assert data["reporting_period"].endswith(("H1", "H2"))
    assert len(data["forecast_quarters"]) == 4
    assert all(quarter >= 0 for quarter in data["forecast_quarters"])
    assert data["blocks_held_at_period_end"] >= 1
    assert data["amendment_count"] >= 0


def assert_audit_finding(data: dict) -> None:
    assert_mutable_identity(data)
    assert data["finding_type"] in _members(FindingType)
    assert data["status"] in _members(AuditFindingStatus)
    assert data["penalty_action"] in _members(PenaltyAction)


def assert_reclamation_order(data: dict) -> None:
    assert_mutable_identity(data)
    assert data["reason"] in _members(ReclamationReason)
    assert data["status"] in _members(ReclamationOrderStatus)
    assert is_iso8601_timestamp(data["issued_at"])
    assert is_iso8601_timestamp(data["response_due_at"])
    assert isinstance(data["strike_applied"], bool)


def assert_relief_plan(data: dict) -> None:
    assert_mutable_identity(data)
    assert data["status"] in _members(ReliefPlanStatus)
    assert 7 <= data["comment_window_days"] <= 90
    assert data["comment_count"] >= 0


def assert_public_comment(data: dict) -> None:
    assert_append_only_identity(data)
    assert data["commenter_type"] in _members(CommenterType)
    assert data["position"] in _members(CommentPosition)
    assert 1 <= len(data["body"]) <= 1000
    assert data["weight"] > 0


def assert_port_request(data: dict) -> None:
    assert_mutable_identity(data)
    assert len(data["telephone_number"]) == 10 and data["telephone_number"].isdigit()
    assert len(data["requested_lrn"]) == 10 and data["requested_lrn"].isdigit()
    assert data["status"] in _members(PortRequestStatus)
    assert data["from_carrier_id"] != data["to_carrier_id"]


def assert_routing_record(data: dict) -> None:
    assert_append_only_identity(data)
    assert len(data["lrn"]) == 10 and data["lrn"].isdigit()
    assert 1 <= len(data["switch_clli"]) <= 11
    assert data["record_status"] in _members(RoutingRecordStatus)
    assert is_iso8601_timestamp(data["effective_at"])


def assert_single_open_routing_record(records: list) -> dict:
    """Exactly one row in a block's ledger is PUBLISHED with a null end_at."""
    open_rows = [row for row in records if row["record_status"] == "PUBLISHED"]
    assert len(open_rows) == 1, (
        f"exactly one routing record may be PUBLISHED, found {len(open_rows)} "
        f"of {len(records)} rows"
    )
    assert open_rows[0]["end_at"] is None, "the open record's end_at must be null"
    for row in records:
        if row["record_status"] != "PUBLISHED":
            assert row["end_at"] is not None, (
                "a closed routing record must carry an end_at"
            )
    return open_rows[0]


def assert_sweep_report(data: dict, orders_issued: int, blocks_released: int,
                        routing_activated: int, swept_at: str) -> None:
    assert data["orders_issued"] == orders_issued, (
        f"orders_issued: expected {orders_issued}, got {data['orders_issued']}"
    )
    assert data["blocks_released"] == blocks_released, (
        f"blocks_released: expected {blocks_released}, got {data['blocks_released']}"
    )
    assert data["routing_activated"] == routing_activated, (
        f"routing_activated: expected {routing_activated}, got {data['routing_activated']}"
    )
    assert data["swept_at"] == swept_at, (
        f"swept_at: expected {swept_at}, got {data['swept_at']}"
    )


def assert_inventory_conserved(npa: dict, rate_centers: list) -> None:
    """Every block counted at the code level is counted by exactly one rate center."""
    assert npa["available_block_count"] == sum(
        rc["available_block_count"] for rc in rate_centers
    ), "the code's available block count must equal the sum over its rate centers"
