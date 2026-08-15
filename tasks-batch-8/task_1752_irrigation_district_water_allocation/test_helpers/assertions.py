"""Entity assertions and domain invariant checkers.

Field names are PRD-exact (PRD §2.4 common properties; §3 entity narratives).
Numeric comparisons use a tight tolerance only to absorb JSON float
serialization; a one-cent rounding error is still a failure.
"""
import pytest

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def assert_amount(actual, expected, label: str = "amount"):
    """Acre-foot / dollar quantities are pinned to 2-decimal half-up values."""
    assert actual is not None, f"{label}: expected {expected}, got None"
    assert actual == pytest.approx(expected, abs=1e-6), (
        f"{label}: expected {expected}, got {actual}"
    )


def _assert_common(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be ISO 8601 UTC"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be ISO 8601 UTC"
    )
    assert isinstance(data.get("version"), int), f"{entity}.version must be an integer"


def assert_water_account(data: dict):
    _assert_common(data, "WaterAccount")
    assert isinstance(data["holder_name"], str) and data["holder_name"]
    assert isinstance(data["parcel_number"], str) and data["parcel_number"]
    assert isinstance(data["irrigated_acres"], (int, float))
    assert data["irrigated_acres"] > 0
    assert data["priority_class"] in ("SENIOR", "JUNIOR")
    assert data["status"] in ("ACTIVE", "SUSPENDED", "CLOSED")


def assert_season(data: dict):
    _assert_common(data, "IrrigationSeason")
    assert isinstance(data["year"], int)
    assert data["announced_af_per_acre"] > 0
    assert 0 <= data["carryover_cap_pct"] <= 100
    assert data["billing_method"] in ("PER_ACRE", "PER_AF_DELIVERED")
    assert data["status"] in ("DRAFT", "ANNOUNCED", "OPEN", "CLOSED")


def assert_season_allocation(data: dict):
    _assert_common(data, "SeasonAllocation")
    assert is_valid_uuid(data.get("water_account_id", ""))
    assert is_valid_uuid(data.get("season_id", ""))
    for field in ("base_entitlement_af", "effective_entitlement_af", "carryover_in_af",
                  "transfers_in_af", "transfers_out_af", "delivered_af",
                  "committed_af", "available_af", "over_allocated_af"):
        assert isinstance(data[field], (int, float)), (
            f"SeasonAllocation.{field} must be numeric, got {data.get(field)!r}"
        )
    # Null until drought effectuation / season close respectively.
    assert data.get("curtailed_entitlement_af") is None or isinstance(
        data["curtailed_entitlement_af"], (int, float))
    assert data.get("carryover_out_af") is None or isinstance(
        data["carryover_out_af"], (int, float))
    assert data["status"] in ("ACTIVE", "CURTAILED", "CLOSED")


def assert_turnout_order(data: dict):
    _assert_common(data, "TurnoutOrder")
    assert is_valid_uuid(data.get("water_account_id", ""))
    assert is_valid_uuid(data.get("season_allocation_id", ""))
    assert is_valid_uuid(data.get("canal_reach_id", ""))
    assert data["requested_cfs"] > 0
    assert data["requested_start_at"] < data["requested_end_at"]
    assert isinstance(data["requested_quantity_af"], (int, float))
    assert data.get("actual_delivered_af") is None or isinstance(
        data["actual_delivered_af"], (int, float))
    assert isinstance(data["over_delivered"], bool)
    assert data["status"] in (
        "REQUESTED", "SCHEDULED", "FLOWING", "DELIVERED", "CANCELLED", "REJECTED",
    )


def assert_rider_work_order(data: dict):
    _assert_common(data, "RiderWorkOrder")
    assert is_valid_uuid(data.get("turnout_order_id", ""))
    assert isinstance(data["rider_user_id"], str) and data["rider_user_id"]
    assert data.get("measured_cfs") is None or data["measured_cfs"] > 0
    assert data.get("measured_hours") is None or data["measured_hours"] > 0
    assert data.get("measured_af") is None or isinstance(
        data["measured_af"], (int, float))
    assert data["status"] in (
        "ASSIGNED", "IN_PROGRESS", "MEASUREMENT_SUBMITTED", "VERIFIED", "CANCELLED",
    )


def assert_assessment_invoice(data: dict):
    _assert_common(data, "AssessmentInvoice")
    assert is_valid_uuid(data.get("water_account_id", ""))
    assert is_valid_uuid(data.get("season_id", ""))
    assert data["billing_method_snapshot"] in ("PER_ACRE", "PER_AF_DELIVERED")
    for field in ("acreage_line_amount", "toll_line_amount",
                  "penalty_line_amount", "total_amount"):
        assert isinstance(data[field], (int, float)), (
            f"AssessmentInvoice.{field} must be numeric, got {data.get(field)!r}"
        )
    assert data.get("issued_at") is None or is_iso8601_timestamp(data["issued_at"])
    assert data.get("paid_at") is None or is_iso8601_timestamp(data["paid_at"])
    assert data["status"] in ("DRAFT", "ISSUED", "DELINQUENT", "LIEN_FILED", "PAID")


def assert_canal_reach(data: dict):
    _assert_common(data, "CanalReach")
    assert isinstance(data["name"], str) and data["name"]
    assert data["max_capacity_cfs"] > 0
    assert data["status"] in ("IN_SERVICE", "SHUTDOWN")


def assert_maintenance_window(data: dict):
    _assert_common(data, "MaintenanceWindow")
    assert is_valid_uuid(data.get("canal_reach_id", ""))
    assert data["start_at"] < data["end_at"]
    assert data["status"] in ("PLANNED", "ACTIVE", "COMPLETED", "CANCELLED")


def assert_transfer_request(data: dict):
    _assert_common(data, "TransferRequest")
    assert is_valid_uuid(data.get("from_account_id", ""))
    assert is_valid_uuid(data.get("to_account_id", ""))
    assert data["from_account_id"] != data["to_account_id"]
    assert is_valid_uuid(data.get("season_id", ""))
    assert data["quantity_af"] > 0
    assert data["status"] in ("PENDING", "APPROVED", "POSTED", "REJECTED", "CANCELLED")


def assert_drought_declaration(data: dict):
    _assert_common(data, "DroughtDeclaration")
    assert is_valid_uuid(data.get("season_id", ""))
    assert data["stage"] in ("STAGE_1", "STAGE_2", "STAGE_3")
    assert isinstance(data["senior_curtailment_pct"], (int, float))
    assert isinstance(data["junior_curtailment_pct"], (int, float))
    assert data["status"] in ("PROPOSED", "EFFECTIVE", "LIFTED")


def assert_allocation_ledger_invariants(data: dict):
    """Domain invariants on the allocation ledger (PRD §3.2).

    available_af == entitlement pool - delivered - committed, and
    over_allocated_af is the delivered excess over the pool, floored at zero.
    """
    pool = (
        data["effective_entitlement_af"]
        + data["carryover_in_af"]
        + data["transfers_in_af"]
        - data["transfers_out_af"]
    )
    assert_amount(
        data["available_af"],
        round(pool - data["delivered_af"] - data["committed_af"], 2),
        "SeasonAllocation.available_af",
    )
    assert_amount(
        data["over_allocated_af"],
        round(max(0.0, data["delivered_af"] - pool), 2),
        "SeasonAllocation.over_allocated_af",
    )
