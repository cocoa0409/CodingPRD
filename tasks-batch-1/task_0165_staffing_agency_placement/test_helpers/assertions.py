"""Entity assertions and domain invariant checkers for the Staffing API.

Built on the framework's generic validators (is_valid_uuid, is_iso8601_timestamp).
"""
from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp,
)


def _assert_common_mutable(data: dict):
    """id + created_at + updated_at + version present and well-formed."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be int >= 1, got {data.get('version')!r}"


def _assert_common_immutable(data: dict):
    """Immutable record: id + created_at only; NO updated_at, NO version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "immutable record must not carry a version field"
    assert "updated_at" not in data, "immutable record must not carry an updated_at field"


def assert_client(data: dict):
    _assert_common_mutable(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["credit_limit_cents"], int)
    assert isinstance(data["conversion_fee_pct"], (int, float))
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["outstanding_balance_cents"], int)
    assert isinstance(data["open_exposure_cents"], int)


def assert_skill(data: dict):
    _assert_common_immutable(data)
    assert isinstance(data["code"], str) and data["code"] == data["code"].upper()
    assert data["category"] in ("TECH", "CLINICAL", "INDUSTRIAL", "CLERICAL")


def assert_candidate(data: dict):
    _assert_common_mutable(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["skill_codes"], list)
    assert isinstance(data["base_pay_rate_cents"], int)
    assert data["status"] in ("AVAILABLE", "ON_ASSIGNMENT", "INACTIVE")


def assert_job_order(data: dict):
    _assert_common_mutable(data)
    assert isinstance(data["client_id"], str)
    assert isinstance(data["title"], str)
    assert data["employment_type"] in ("TEMP", "TEMP_TO_PERM", "DIRECT")
    assert isinstance(data["required_skill_code"], str)
    assert isinstance(data["openings"], int) and data["openings"] >= 1
    assert isinstance(data["bill_rate_cents"], int)
    assert isinstance(data["target_pay_rate_cents"], int)
    assert isinstance(data["filled_count"], int) and data["filled_count"] >= 0
    assert data["status"] in ("DRAFT", "OPEN", "ON_HOLD", "FILLED", "CLOSED", "CANCELLED")


def assert_submission(data: dict):
    _assert_common_mutable(data)
    assert isinstance(data["job_order_id"], str)
    assert isinstance(data["candidate_id"], str)
    assert isinstance(data["submitted_pay_rate_cents"], int)
    assert data["status"] in (
        "SUBMITTED", "CLIENT_REVIEW", "INTERVIEWING", "OFFER_EXTENDED",
        "PLACED", "REJECTED", "WITHDRAWN",
    )


def assert_interview(data: dict):
    _assert_common_mutable(data)
    assert isinstance(data["submission_id"], str)
    assert is_iso8601_timestamp(data["scheduled_start"])
    assert is_iso8601_timestamp(data["scheduled_end"])
    assert data["outcome"] in ("PENDING", "PASSED", "FAILED")


def assert_placement(data: dict):
    _assert_common_mutable(data)
    assert isinstance(data["submission_id"], str)
    assert isinstance(data["job_order_id"], str)
    assert isinstance(data["candidate_id"], str)
    assert data["placement_type"] in ("TEMP", "TEMP_TO_PERM", "DIRECT")
    assert isinstance(data["bill_rate_cents"], int)
    assert isinstance(data["pay_rate_cents"], int)
    assert isinstance(data["projected_weekly_bill_cents"], int)
    assert isinstance(data["projected_weekly_margin_cents"], int)
    assert isinstance(data["actual_margin_cents"], int)
    assert data["assignment_status"] in ("PENDING_START", "ACTIVE", "ENDED")
    assert data["conversion_status"] in ("NONE", "CONVERTED")


def assert_timesheet(data: dict):
    _assert_common_mutable(data)
    assert isinstance(data["placement_id"], str)
    assert is_iso8601_timestamp(data["week_start"])
    assert is_iso8601_timestamp(data["week_end"])
    assert isinstance(data["hours"], (int, float)) and data["hours"] > 0
    assert isinstance(data["pay_cents"], int)
    assert isinstance(data["bill_cents"], int)
    assert isinstance(data["margin_cents"], int)
    assert data["status"] in ("DRAFT", "SUBMITTED", "APPROVED", "REJECTED", "INVOICED")


def assert_invoice(data: dict):
    _assert_common_mutable(data)
    assert isinstance(data["client_id"], str)
    assert isinstance(data["subtotal_cents"], int)
    assert isinstance(data["volume_discount_cents"], int)
    assert isinstance(data["processing_fee_cents"], int)
    assert isinstance(data["total_cents"], int)
    assert data["status"] in ("DRAFT", "ISSUED", "PAID", "VOID")


def assert_invoice_line_item(data: dict):
    _assert_common_immutable(data)
    assert isinstance(data["invoice_id"], str)
    assert isinstance(data["timesheet_id"], str)
    assert isinstance(data["line_total_cents"], int)


def assert_conversion_fee(data: dict):
    _assert_common_mutable(data)
    assert isinstance(data["placement_id"], str)
    assert isinstance(data["client_id"], str)
    assert isinstance(data["annual_salary_cents"], int)
    assert isinstance(data["fee_cents"], int)
    assert data["status"] in ("BILLED", "WAIVED")


def assert_invoice_total_consistent(data: dict):
    """PRD 3.8: total_cents == subtotal_cents - volume_discount_cents + processing_fee_cents."""
    expected = (
        data["subtotal_cents"] - data["volume_discount_cents"] + data["processing_fee_cents"]
    )
    assert data["total_cents"] == expected, (
        f"total_cents {data['total_cents']} != subtotal {data['subtotal_cents']} "
        f"- discount {data['volume_discount_cents']} + fee {data['processing_fee_cents']} = {expected}"
    )
