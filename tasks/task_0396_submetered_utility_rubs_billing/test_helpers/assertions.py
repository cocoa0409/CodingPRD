"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_property(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["state_code"], str)
    assert data["integrity_status"] in ("OK", "NEEDS_REVIEW")


def assert_utility(data: dict):
    _assert_common(data)
    assert data["utility_type"] in ("WATER", "ELECTRIC", "GAS")
    assert data["allocation_method"] in ("CONSUMPTION", "RUBS")
    assert data["status"] in ("ACTIVE", "ARCHIVED")


def assert_unit(data: dict):
    _assert_common(data)
    assert data["status"] in ("VACANT", "OCCUPIED", "ARCHIVED")


def assert_meter(data: dict):
    _assert_common(data)
    assert data["status"] in ("UNASSIGNED", "ASSIGNED", "RETIRED")


def assert_lease(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "PENDING", "ACTIVE", "NOTICE_GIVEN", "MOVED_OUT", "CLOSED",
    )


def assert_vendor_bill(data: dict):
    _assert_common(data)
    assert data["status"] in ("RECEIVED", "APPROVED", "ALLOCATED", "VOIDED")


def assert_meter_read(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "PENDING", "SUBMITTED", "VALIDATED", "FLAGGED",
        "RE_READ_REQUESTED", "SUPERSEDED",
    )


def assert_billing_cycle(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "OPEN", "READS_LOCKED", "ALLOCATED", "STATEMENTS_ISSUED", "CLOSED",
    )


def assert_tenant_statement(data: dict):
    _assert_common(data)
    assert data["delivery_status"] in ("DRAFT", "ISSUED", "DELIVERED")
    assert data["payment_status"] in (
        "UNPAID", "PARTIALLY_PAID", "PAID", "DELINQUENT", "IN_COLLECTIONS",
    )
    assert_statement_totals_invariant(data)


def assert_statement_totals_invariant(data: dict):
    """PRD §3.8: total_due = utility + admin + late - credit; balance = total - paid."""
    expected_total = (
        data["utility_charge_cents"]
        + data["admin_fee_cents"]
        + data["late_fee_cents"]
        - data["credit_cents"]
    )
    assert data["total_due_cents"] == expected_total, (
        f"total_due_cents invariant: expected {expected_total}, got {data['total_due_cents']}"
    )
    expected_balance = data["total_due_cents"] - data["amount_paid_cents"]
    assert data["balance_due_cents"] == expected_balance, (
        f"balance_due_cents invariant: expected {expected_balance}, got {data['balance_due_cents']}"
    )


def assert_dispute(data: dict):
    _assert_common(data)
    assert data["status"] in ("OPEN", "UNDER_REVIEW", "RESOLVED", "REJECTED")


def assert_payment(data: dict):
    _assert_common(data)
    assert data["status"] in ("POSTED", "REVERSED")
