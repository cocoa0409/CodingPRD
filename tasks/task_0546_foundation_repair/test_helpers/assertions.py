"""Entity assertions and domain invariant checkers for the Foundation Repair API.

Each assert_{entity}() validates the system-managed shape every resource must expose
(PRD §2.4: id, created_at, updated_at, version) plus the entity's own fields.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """Every resource carries id, created_at, updated_at, and version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_lead(data: dict):
    _assert_common(data)
    assert isinstance(data["customer_name"], str)
    assert data["region_code"] in ("NORTH", "SOUTH", "EAST", "WEST")
    assert isinstance(data["financing_balance_cents"], int)
    assert isinstance(data["active_visit_count"], int)


def assert_inspection(data: dict):
    _assert_common(data)
    assert data["status"] in ("SCHEDULED", "COMPLETED", "CANCELLED")


def assert_scope(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "ENGINEERED", "SUPERSEDED")
    assert isinstance(data["pier_count"], int)
    assert isinstance(data["anchor_count"], int)


def assert_quote(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "SENT", "REVISED", "ACCEPTED", "REJECTED", "EXPIRED")


def assert_job(data: dict):
    _assert_common(data)
    assert data["fulfillment_status"] in (
        "UNSCHEDULED", "SCHEDULED", "IN_PROGRESS", "COMPLETED", "CANCELLED"
    )
    assert data["permit_status"] in ("NOT_STARTED", "PENDING", "APPROVED", "REJECTED")


def assert_crew(data: dict):
    _assert_common(data)
    assert isinstance(data["booked_minutes"], int)
    assert data["region_code"] in ("NORTH", "SOUTH", "EAST", "WEST")


def assert_permit(data: dict):
    _assert_common(data)
    assert data["status"] in ("PENDING", "APPROVED", "REJECTED")


def assert_warranty(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "VOID")
    assert isinstance(data["transfer_count"], int)
    assert isinstance(data["remediation_count"], int)


def assert_maintenance_visit(data: dict):
    _assert_common(data)
    assert data["status"] in ("SCHEDULED", "COMPLETED", "MISSED")


def assert_claim(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "FILED", "UNDER_REVIEW", "NEEDS_INFO", "APPROVED", "DENIED", "RESOLVED"
    )
