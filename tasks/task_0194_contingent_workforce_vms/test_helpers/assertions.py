"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp,
)


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), \
        f"version must be an integer, got {data.get('version')!r}"


def assert_program(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["client_name"], str)
    assert data["status"] in ("ACTIVE", "SUSPENDED", "CLOSED")
    assert is_iso8601_timestamp(data["current_clock"]), "current_clock must be ISO 8601"


def assert_supplier(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["tier"], int) and data["tier"] >= 1


def assert_worker(data: dict):
    _assert_common(data)
    assert isinstance(data["cumulative_engaged_days"], int)
    assert data["cumulative_engaged_days"] >= 0
    assert data["tenure_status"] in ("CLEAR", "WARNING", "BREACH")


def assert_requisition(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "DISTRIBUTED", "FILLED", "CLOSED", "CANCELLED")
    assert isinstance(data["openings"], int) and data["openings"] >= 1
    assert isinstance(data["filled_count"], int) and data["filled_count"] >= 0
    assert data["filled_count"] <= data["openings"], \
        f"filled_count {data['filled_count']} exceeds openings {data['openings']}"


def assert_distribution(data: dict):
    _assert_common(data)
    assert data["status"] in ("PENDING", "RELEASED", "REVOKED")
    assert isinstance(data["tier_at_distribution"], int)


def assert_submittal(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "SUBMITTED", "SHORTLISTED", "INTERVIEWING", "RATE_PROPOSED",
        "OFFERED", "HIRED", "REJECTED", "WITHDRAWN",
    )
    assert isinstance(data["pay_rate_cents"], int) and data["pay_rate_cents"] >= 1
    assert isinstance(data["bill_rate_cents"], int)
    assert isinstance(data["rounds"], int) and data["rounds"] >= 0


def assert_assignment(data: dict):
    _assert_common(data)
    assert data["engagement_status"] in ("ACTIVE", "ON_HOLD", "ENDED")
    assert data["compliance_status"] in ("CLEAR", "TENURE_WARNING", "TENURE_BREACH")
    assert isinstance(data["engaged_days"], int) and data["engaged_days"] >= 0


def assert_sow(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "ACTIVE", "COMPLETED", "CLOSED", "CANCELLED")
    assert isinstance(data["total_value_cents"], int) and data["total_value_cents"] >= 1
    assert isinstance(data["invoiced_value_cents"], int) and data["invoiced_value_cents"] >= 0


def assert_milestone(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "PENDING", "IN_PROGRESS", "SUBMITTED", "ACCEPTED", "REJECTED", "INVOICED",
    )
    assert isinstance(data["milestone_amount_cents"], int) and data["milestone_amount_cents"] >= 1
    assert isinstance(data["sequence"], int) and data["sequence"] >= 1


def assert_timesheet(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "SUBMITTED", "APPROVED", "REJECTED", "INVOICED")
    assert isinstance(data["pay_amount_cents"], int)
    assert isinstance(data["bill_amount_cents"], int)


def assert_expense(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "SUBMITTED", "APPROVED", "REJECTED", "INVOICED")
    assert data["category"] in ("TRAVEL", "LODGING", "MEALS", "EQUIPMENT", "OTHER")
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 1
