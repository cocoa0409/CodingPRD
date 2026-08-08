"""Entity assertions and domain invariant checkers.

These validate the shape of each returned resource against the fields the PRD
declares, using the framework's generic UUID/timestamp validators internally.
"""
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
)


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_facility(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["unit_name"], str) and len(data["unit_name"]) > 0
    assert isinstance(data["unit_capacity"], int)
    assert isinstance(data["required_credential_types"], list) and len(data["required_credential_types"]) > 0
    assert isinstance(data["pending_pay_cents"], int)
    assert isinstance(data["outstanding_balance_cents"], int)
    assert isinstance(data["lifetime_billed_cents"], int)


def assert_clinician(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str)
    assert isinstance(data["email"], str)
    assert data["specialty"] in ("RN", "LPN", "CNA", "RT", "PT")
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["reliability_score"], int)
    assert isinstance(data["provisional_reliability_score"], int)
    assert isinstance(data["no_show_count"], int)
    assert isinstance(data["completed_shift_count"], int)


def assert_credential(data: dict):
    _assert_common(data)
    assert data["credential_type"] in ("RN_LICENSE", "BLS", "ACLS", "TB_SCREENING", "FIT_TEST")
    assert data["status"] in (
        "PENDING_VERIFICATION", "VERIFIED", "REJECTED", "EXPIRED", "REVOKED",
    )


def assert_shift(data: dict):
    _assert_common(data)
    assert data["status"] in ("OPEN", "ASSIGNED", "COMPLETED", "CANCELLED")
    assert isinstance(data["claim_count"], int)
    assert isinstance(data["estimated_pay_cents"], int)
    assert isinstance(data["base_pay_rate_cents_per_hour"], int)
    assert isinstance(data["effective_rate_cents_per_hour"], int)


def assert_staffing_order(data: dict):
    _assert_common(data)
    assert data["status"] in ("OPEN", "PARTIALLY_FILLED", "FILLED", "CLOSED", "CANCELLED")
    for c in ("shift_count", "open_count", "filled_count", "completed_count", "cancelled_count"):
        assert isinstance(data[c], int)
    # slot-partition invariant
    assert data["shift_count"] == data["open_count"] + data["filled_count"] + data["cancelled_count"], (
        f"slot partition broken: shift_count {data['shift_count']} != "
        f"open {data['open_count']} + filled {data['filled_count']} + cancelled {data['cancelled_count']}"
    )


def assert_shift_claim(data: dict):
    _assert_common(data)
    assert data["status"] in ("PENDING", "AWARDED", "DECLINED", "WITHDRAWN")


def assert_assignment(data: dict):
    _assert_common(data)
    assert data["work_status"] in (
        "PENDING_CONFIRMATION", "CONFIRMED", "WORKED",
        "CANCELLED_BY_CLINICIAN", "CANCELLED_BY_FACILITY", "NO_SHOW",
    )
    assert data["pay_status"] in (
        "UNBILLED", "TIMESHEET_PENDING", "PAYABLE", "INVOICED", "PAID", "WAIVED",
    )
    assert isinstance(data["estimated_pay_cents"], int)


def assert_timesheet(data: dict):
    _assert_common(data)
    assert data["status"] in ("SUBMITTED", "DISPUTED", "VERIFIED", "INVOICED", "PAID")
    assert isinstance(data["raw_minutes"], int)
    assert isinstance(data["dispute_count"], int)


def assert_reliability_event(data: dict):
    _assert_common(data)
    assert data["event_type"] in (
        "SHIFT_COMPLETED", "LATE_CANCELLATION", "VERY_LATE_CANCELLATION",
        "NO_SHOW", "FACILITY_CANCELLATION_CREDIT",
    )
    assert data["adjudication_status"] in ("PENDING", "CONFIRMED", "OVERTURNED")


def assert_invoice(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "ISSUED", "SETTLED", "VOID")
    assert data["markup_tier"] in ("TIER_1", "TIER_2", "TIER_3")
    assert isinstance(data["lines"], list)
    assert isinstance(data["bill_total_cents"], int)
    assert isinstance(data["pay_total_cents"], int)


def assert_facility_money_invariant(facility: dict, expected_outstanding: int):
    """outstanding_balance_cents equals the sum of bill_total_cents over ISSUED
    invoices; the caller supplies that aggregate."""
    assert facility["outstanding_balance_cents"] == expected_outstanding, (
        f"outstanding_balance_cents {facility['outstanding_balance_cents']} != "
        f"expected {expected_outstanding}"
    )
