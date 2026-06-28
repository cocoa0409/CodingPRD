"""Entity assertions and domain invariant checkers.

Each assert_{entity}() validates the structural contract of an entity response:
UUID id, ISO-8601 timestamps, present version (for common-fields entities), and
enum-membership of status fields. Lean records (model / load assessment /
exercise log) carry only id + created_at and never assert updated_at / version.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


# ─── Common-field block (id + created_at + updated_at + version) ─────────────
def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


# ─── Lean record block (id + created_at only) ────────────────────────────────
def _assert_lean_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "lean record must not carry a version field"


def assert_customer(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["service_address"], str) and data["service_address"]
    assert isinstance(data["elevation_ft"], int) and data["elevation_ft"] >= 0


def assert_technician(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["license_no"], str) and data["license_no"]
    assert isinstance(data["gas_certified"], bool)
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["open_dispatch_count"], int) and data["open_dispatch_count"] >= 0


def assert_model(data: dict):
    _assert_lean_fields(data)
    assert isinstance(data["sku"], str) and data["sku"]
    assert isinstance(data["rated_kw"], (int, float)) and data["rated_kw"] > 0
    assert isinstance(data["fuel_types"], list) and len(data["fuel_types"]) > 0
    assert data["unit_price_cents"] >= 0
    assert data["warranty_months"] >= 0


def assert_project(data: dict):
    _assert_common_fields(data)
    assert data["status"] in (
        "DRAFT", "SIZED", "PERMITTED", "INSTALLED", "ACTIVATED", "CANCELLED"
    )
    assert data["permit_status"] in ("NONE", "APPROVED", "REJECTED")
    assert data["sizing_method"] in ("STAGGERED", "FULL_LOAD")
    assert data["fuel_type"] in ("NG", "PROPANE")


def assert_load_assessment(data: dict):
    _assert_lean_fields(data)
    assert data["method"] in ("STAGGERED", "FULL_LOAD")
    assert isinstance(data["computed_required_kw"], (int, float))
    assert isinstance(data["peak_demand_w"], int)


def assert_unit(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["serial_no"], str) and data["serial_no"]
    assert data["registration_status"] in ("UNREGISTERED", "REGISTERED")
    assert data["warranty_status"] in ("ACTIVE", "LAPSED", "VOID")
    assert data["monitoring_health"] in ("OK", "DEGRADED", "OFFLINE")
    assert data["operating_status"] in (
        "OPERATIONAL", "SERVICE_DUE", "NON_COMPLIANT", "DECOMMISSIONED"
    )
    assert 0 <= data["compliance_score"] <= 100
    assert data["runtime_hours"] >= 0


def assert_maintenance_plan(data: dict):
    _assert_common_fields(data)
    assert data["frequency"] in ("ANNUAL", "SEMI_ANNUAL")
    assert data["status"] in ("ACTIVE", "SUSPENDED", "CANCELLED")
    assert data["visits_per_year"] in (1, 2)
    assert data["annual_price_cents"] >= 0


def assert_maintenance_visit(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("SCHEDULED", "COMPLETED", "MISSED", "CANCELLED")


def assert_warranty_claim(data: dict):
    _assert_common_fields(data)
    assert data["status"] in (
        "OPEN", "UNDER_REVIEW", "APPROVED", "DENIED", "WITHDRAWN"
    )


def assert_repair_dispatch(data: dict):
    _assert_common_fields(data)
    assert data["origin"] in ("WARRANTY", "PAID", "RECALL")
    assert data["status"] in (
        "REQUESTED", "DISPATCHED", "IN_PROGRESS", "RESOLVED", "CLOSED", "CANCELLED"
    )
    assert isinstance(data["billable"], bool)


def assert_recall_campaign(data: dict):
    _assert_common_fields(data)
    assert data["severity"] in ("ADVISORY", "MANDATORY")
    assert data["status"] in ("DRAFT", "OPEN", "CLOSED")


def assert_recall_remediation(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("PENDING", "SCHEDULED", "COMPLETED", "OVERDUE")
