"""Entity assertions and shared invariant checkers.

Uses the framework's generic validators internally. Field names are PRD-exact.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """Common system-managed fields carried by every resource (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID with no type prefix"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        "version must be a positive integer"


def assert_customer(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str)
    assert isinstance(data["service_address"], str)
    assert isinstance(data["roofline_feet"], int)
    assert isinstance(data["outstanding_balance_cents"], int)
    assert data["status"] in ("ACTIVE", "INACTIVE")


def assert_contract(data: dict):
    _assert_common(data)
    assert data["contract_type"] in ("SEASONAL_RENTAL", "PERMANENT_PURCHASE")
    assert data["status"] in ("DRAFT", "ACTIVE", "RENEWED", "CANCELLED", "COMPLETED")


def assert_estimate(data: dict):
    _assert_common(data)
    assert data["product_line"] in ("SEASONAL", "PERMANENT")
    assert data["status"] in ("DRAFT", "QUOTED", "ACCEPTED", "REJECTED", "INVOICED")


def assert_route_day(data: dict):
    _assert_common(data)
    assert isinstance(data["booked_stops"], int)
    assert data["status"] in ("PLANNED", "DISPATCHED", "CLOSED")


def assert_route_assignment(data: dict):
    _assert_common(data)
    assert data["status"] in ("BOOKED", "DISPATCHED", "RELEASED", "COMPLETED")


def assert_job(data: dict):
    _assert_common(data)
    assert data["job_type"] in ("INSTALL", "TAKEDOWN", "SERVICE")
    assert data["status"] in (
        "SCHEDULED", "RESCHEDULED", "IN_PROGRESS", "COMPLETED", "CANCELLED")


def assert_service_call(data: dict):
    _assert_common(data)
    assert data["status"] in ("OPEN", "CLASSIFIED", "SCHEDULED", "RESOLVED")


def assert_storage_record(data: dict):
    _assert_common(data)
    assert data["status"] in ("STORED", "RETRIEVED", "DISPOSED")


def assert_financing_plan(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "PAID_OFF", "DEFAULTED")


def assert_payment(data: dict):
    _assert_common(data)
    assert data["status"] in ("POSTED", "REVERSED")


def assert_invoice(data: dict):
    _assert_common(data)
    assert data["source_type"] in ("INSTALL", "STORAGE", "SERVICE", "MANUAL")
    assert data["status"] in ("ISSUED", "PAID", "VOID")
