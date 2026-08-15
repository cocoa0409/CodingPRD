"""Entity assertions and domain invariant checkers.

Common-field presence (id / created_at / updated_at / version) follows
PRD §2.5; status values follow the lifecycle enumerations of PRD §3.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict, entity_label: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity_label}.id must be a UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{entity_label}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"{entity_label}.updated_at must be ISO 8601"
    assert isinstance(
        data.get("version"), int
    ), f"{entity_label}.version must be an integer"


def assert_customer(data: dict):
    _assert_common_fields(data, "Customer")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["site_address"], str)
    assert isinstance(data["site_max_container_gal"], int)
    assert data["status"] in ["PROSPECT", "ACTIVE", "SUSPENDED", "TERMINATED"]
    assert isinstance(data["missed_pickup_count"], int)
    assert isinstance(data["rebate_balance_cents"], int)


def assert_contract(data: dict):
    _assert_common_fields(data, "Contract")
    assert data["pricing_mode"] in ["REBATE", "SERVICE_FEE"]
    assert isinstance(data["index_code"], str) and data["index_code"]
    assert data["status"] in [
        "DRAFT",
        "ACTIVE",
        "RENEWAL_OFFERED",
        "AT_RISK",
        "TERMINATED_VOLUNTARY",
        "TERMINATED_POACHED",
        "EXPIRED",
    ]
    assert isinstance(data["term_start"], str)
    assert isinstance(data["term_end"], str)


def assert_container(data: dict):
    _assert_common_fields(data, "Container")
    assert data["status"] in ["PLACED", "ACTIVE", "LOCKED", "REMOVED"]
    assert isinstance(data["customer_id"], str)


def assert_truck(data: dict):
    _assert_common_fields(data, "Truck")
    assert data["status"] in ["IN_SERVICE", "OUT_OF_SERVICE"]
    assert isinstance(data["plate"], str) and data["plate"]


def assert_route_manifest(data: dict):
    _assert_common_fields(data, "RouteManifest")
    assert data["status"] in [
        "DRAFT",
        "DISPATCHED",
        "IN_PROGRESS",
        "COMPLETED",
        "RECONCILED",
    ]
    assert isinstance(data["truck_id"], str)
    assert isinstance(data["driver_ref"], str)
    assert isinstance(data["service_date"], str)


def assert_pickup_visit(data: dict):
    _assert_common_fields(data, "PickupVisit")
    assert data["status"] in [
        "SCHEDULED",
        "EN_ROUTE",
        "COMPLETED",
        "FAILED",
        "SKIPPED",
        "VOID",
    ]
    assert isinstance(data["manifest_id"], str)
    assert isinstance(data["container_id"], str)


def assert_quality_sample(data: dict):
    _assert_common_fields(data, "QualitySample")
    assert data["status"] in ["COLLECTED", "SUBMITTED", "GRADED", "DISPUTED"]
    assert isinstance(data["pickup_visit_id"], str)
    if data["status"] == "GRADED":
        assert data["grade"] in ["A", "B", "C", "REJECT"]


def assert_market_index_quote(data: dict):
    _assert_common_fields(data, "MarketIndexQuote")
    assert data["status"] in ["DRAFT", "PUBLISHED", "SUPERSEDED"]
    assert isinstance(data["index_code"], str)


def assert_settlement(data: dict):
    _assert_common_fields(data, "Settlement")
    assert data["status"] in ["PROVISIONAL", "FINALIZED", "PAID", "VOID"]
    assert isinstance(data["provisional_total_cents"], int)
    assert isinstance(data["final_total_cents"], int)


def assert_settlement_line(data: dict):
    _assert_common_fields(data, "SettlementLine")
    assert data["variant"] in ["PROVISIONAL", "FINAL"]
    assert data["pricing_mode"] in ["REBATE", "SERVICE_FEE"]
    assert isinstance(data["line_amount_cents"], int)
    assert isinstance(data["settlement_id"], str)
    assert isinstance(data["pickup_visit_id"], str)


def assert_complaint(data: dict):
    _assert_common_fields(data, "Complaint")
    assert data["status"] in [
        "OPEN",
        "INVESTIGATING",
        "ESCALATED",
        "RESOLVED",
        "REOPENED",
        "CLOSED",
    ]
    assert data["category"] in ["SPILL", "ODOR", "NUISANCE", "THEFT_ATTEMPT"]
    assert data["severity"] in ["LOW", "MEDIUM", "HIGH"]


def assert_theft_incident(data: dict):
    _assert_common_fields(data, "TheftIncident")
    assert data["status"] in ["REPORTED", "CONFIRMED", "DISMISSED", "RESOLVED"]
    assert isinstance(data["container_id"], str)


def assert_processing_batch(data: dict):
    _assert_common_fields(data, "ProcessingBatch")
    assert data["status"] in ["INTAKE", "PROCESSED", "SOLD"]
    assert isinstance(data["manifest_id"], str)
