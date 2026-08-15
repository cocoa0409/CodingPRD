"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AmnestyWindowStatus,
    DispositionRoute,
    DumpingReportStatus,
    FeeAssessmentKind,
    FeeAssessmentStatus,
    HouseholdStatus,
    ItemCategory,
    MissedReasonCode,
    NotificationKind,
    PickupRequestStatus,
    RefusalReasonCode,
    RouteDayStatus,
    ServiceZone,
    SetoutClassification,
)


def assert_household(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data["street_address"], str) and data["street_address"]
    assert data["service_zone"] in {z.value for z in ServiceZone}
    assert data["status"] in {s.value for s in HouseholdStatus}
    assert isinstance(data["annual_allowance_items"], int)
    assert data["annual_allowance_items"] >= 0
    assert "suspension_reason" in data
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_household_allowance(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_valid_uuid(data.get("household_id", ""))
    assert isinstance(data["calendar_year"], int)
    for field in ("items_consumed", "items_released", "over_allowance_items"):
        assert isinstance(data[field], int), f"{field} must be an integer"
    assert is_iso8601_timestamp(data.get("created_at", ""))


def assert_amnesty_window(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data["label"], str) and data["label"]
    assert is_iso8601_timestamp(data.get("starts_at", ""))
    assert is_iso8601_timestamp(data.get("ends_at", ""))
    assert data["status"] in {s.value for s in AmnestyWindowStatus}
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_route_day(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert data["service_zone"] in {z.value for z in ServiceZone}
    assert isinstance(data["route_date"], str) and len(data["route_date"]) == 10
    assert isinstance(data["max_load_units"], int) and data["max_load_units"] >= 0
    assert isinstance(data["max_stops"], int) and data["max_stops"] >= 0
    assert isinstance(data["committed_load_units"], int)
    assert isinstance(data["committed_stops"], int)
    assert isinstance(data["projected_load_units"], int)
    assert isinstance(data["projected_fullness_pct"], int)
    assert data["status"] in {s.value for s in RouteDayStatus}
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_pickup_request(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_valid_uuid(data.get("household_id", ""))
    assert data.get("route_day_id") is None or is_valid_uuid(data["route_day_id"])
    assert data["status"] in {s.value for s in PickupRequestStatus}
    assert data.get("scheduled_date") is None or isinstance(data["scheduled_date"], str)
    assert isinstance(data["load_units"], int)
    assert isinstance(data["provisional_total_cents"], int)
    assert data.get("final_total_cents") is None or isinstance(
        data["final_total_cents"], int
    )
    assert isinstance(data["amnesty_applied"], bool)
    assert data.get("refusal_reason_code") is None or data["refusal_reason_code"] in {
        c.value for c in RefusalReasonCode
    }
    assert data.get("missed_reason_code") is None or data["missed_reason_code"] in {
        c.value for c in MissedReasonCode
    }
    assert data.get("setout_classification") is None or data[
        "setout_classification"
    ] in {c.value for c in SetoutClassification}
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_pickup_item(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_valid_uuid(data.get("pickup_request_id", ""))
    assert isinstance(data["sequence_no"], int) and data["sequence_no"] >= 1
    assert data["category"] in {c.value for c in ItemCategory}
    assert isinstance(data["is_oversize"], bool)
    assert isinstance(data["preparation_ack"], bool)
    assert isinstance(data["item_fee_cents"], int)
    assert isinstance(data["within_allowance"], bool)
    assert data.get("disposition_route") is None or data["disposition_route"] in {
        r.value for r in DispositionRoute
    }
    assert is_iso8601_timestamp(data.get("created_at", ""))


def assert_fee_assessment(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert data.get("pickup_request_id") is None or is_valid_uuid(
        data["pickup_request_id"]
    )
    assert is_valid_uuid(data.get("household_id", ""))
    assert data["kind"] in {k.value for k in FeeAssessmentKind}
    assert isinstance(data["amount_cents"], int)
    assert data["status"] in {s.value for s in FeeAssessmentStatus}
    assert data.get("settled_at") is None or is_iso8601_timestamp(data["settled_at"])
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_dumping_report(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_valid_uuid(data.get("household_id", ""))
    assert data.get("pickup_request_id") is None or is_valid_uuid(
        data["pickup_request_id"]
    )
    assert is_iso8601_timestamp(data.get("reported_at", ""))
    assert data["status"] in {s.value for s in DumpingReportStatus}
    assert "determination_notes" in data
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_notification(data: dict):
    """Notifications are append-only: id + created_at, NO updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_valid_uuid(data.get("pickup_request_id", ""))
    assert data["kind"] in {k.value for k in NotificationKind}
    assert "reason_code" in data
    assert isinstance(data.get("message", ""), str)
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert "updated_at" not in data, "Notification must not carry updated_at"
    assert "version" not in data, "Notification must not carry version"


def assert_allowance_invariants(ledger: dict):
    """Ledger counters are non-negative integers after any operation."""
    assert ledger["items_consumed"] >= 0
    assert ledger["items_released"] >= 0
    assert ledger["over_allowance_items"] >= 0


def assert_route_capacity_invariants(route: dict):
    """Committed counters never exceed configured maximums."""
    assert 0 <= route["committed_load_units"] <= route["max_load_units"]
    assert 0 <= route["committed_stops"] <= route["max_stops"]
