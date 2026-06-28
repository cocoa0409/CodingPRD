"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID without prefix, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version begins at 1 and increments"


def assert_customer(data: dict):
    _assert_common(data)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["full_name"], str)
    assert isinstance(data["state_code"], str)
    assert isinstance(data["annual_income_cents"], int)
    assert data["annual_income_cents"] >= 0


def assert_project(data: dict):
    _assert_common(data)
    assert data["status"] in [
        "LEAD", "MEASURED", "QUOTED", "SOLD", "IN_PRODUCTION",
        "INSTALLED", "CLOSED", "CANCELLED",
    ], f"unexpected project status {data['status']!r}"


def assert_measure(data: dict):
    _assert_common(data)
    assert data["status"] in ["SCHEDULED", "COMPLETED", "CANCELLED"]


def assert_quote(data: dict):
    _assert_common(data)
    assert data["status"] in [
        "DRAFT", "QUOTED", "REVISING", "APPROVED",
        "SUPERSEDED", "EXPIRED", "DECLINED",
    ], f"unexpected quote status {data['status']!r}"
    assert data["scope"] in ["PAINT", "REFACE", "REDOOR"]
    assert isinstance(data["estimate_total_cents"], int)
    assert data["estimate_total_cents"] >= 0
    assert isinstance(data["is_active"], bool)


def assert_addon(data: dict):
    _assert_common(data)
    assert data["kind"] in ["HARDWARE", "COUNTERTOP"]
    assert data["status"] in ["PROPOSED", "APPROVED", "REMOVED"]
    assert isinstance(data["price_cents"], int)
    assert data["price_cents"] >= 0


def assert_change_order(data: dict):
    _assert_common(data)
    assert data["status"] in ["PENDING", "ACCEPTED", "REJECTED"]


def assert_material_order(data: dict):
    _assert_common(data)
    assert data["status"] in ["PLACED", "READY", "RECEIVED", "CANCELLED"]
    assert isinstance(data["base_lead_time_days"], int)
    assert data["base_lead_time_days"] >= 0
    assert data["lead_extension_days"] >= 0
    assert is_iso8601_timestamp(data.get("ready_at", "")), "ready_at must be ISO 8601"


def assert_crew(data: dict):
    _assert_common(data)
    assert isinstance(data["daily_job_capacity"], int) and data["daily_job_capacity"] >= 1
    assert isinstance(data["skill_finishes"], list) and len(data["skill_finishes"]) > 0
    assert isinstance(data["is_active"], bool)


def assert_install_job(data: dict):
    _assert_common(data)
    assert data["status"] in ["SCHEDULED", "IN_PROGRESS", "DONE", "CANCELLED"]


def assert_warranty_claim(data: dict):
    _assert_common(data)
    assert data["status"] in ["SUBMITTED", "APPROVED", "DENIED", "RESOLVED"]
    assert isinstance(data["covered"], bool)


def assert_financing_application(data: dict):
    _assert_common(data)
    assert data["status"] in ["SUBMITTED", "APPROVED", "DECLINED"]
    assert isinstance(data["monthly_payment_cents"], int)
    assert data["monthly_payment_cents"] >= 0
    assert data["dti_ratio"] >= 0
