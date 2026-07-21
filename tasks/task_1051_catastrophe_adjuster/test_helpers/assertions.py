"""Entity assertions and domain invariant checkers (verify against the PRD contract)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID without prefix, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be a positive int"


def _assert_ledger_common(data: dict):
    """For append-only records (TimeEntry, Payment): id + created_at only."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "append-only records must not carry version"
    assert "updated_at" not in data, "append-only records must not carry updated_at"


def assert_adjuster(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert data["adjuster_type"] in ("INDEPENDENT", "CAT", "STAFF")
    assert isinstance(data["home_state"], str) and len(data["home_state"]) == 2
    assert data["status"] in ("ACTIVE", "INACTIVE")


def assert_license(data: dict):
    _assert_common(data)
    assert data["status"] in ("PENDING", "ACTIVE", "SUSPENDED", "EXPIRED")
    assert data["license_type"] in ("ALL_LINES", "PROPERTY")


def assert_cat_event(data: dict):
    _assert_common(data)
    assert data["status"] in ("OPEN", "CLOSED")
    assert isinstance(data["roster_capacity"], int)
    assert isinstance(data["roster_filled_count"], int)
    assert data["roster_filled_count"] >= 0
    assert data["roster_filled_count"] <= data["roster_capacity"]


def assert_deployment(data: dict):
    _assert_common(data)
    assert data["status"] in ("REQUESTED", "CONFIRMED", "ACTIVE", "COMPLETED", "WITHDRAWN")


def assert_claim(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "INTAKE", "ASSIGNED", "IN_PROGRESS", "UNDER_REVIEW", "SETTLED", "CLOSED", "REOPENED",
    )
    assert data["policy_type"] in ("RCV", "ACV")
    assert isinstance(data["rcv_cents"], int) and data["rcv_cents"] >= 0
    assert isinstance(data["reserve_consumed_cents"], int) and data["reserve_consumed_cents"] >= 0


def assert_assignment(data: dict):
    _assert_common(data)
    assert data["work_status"] in ("OFFERED", "ACCEPTED", "FIELDWORK", "WORK_COMPLETE", "DECLINED")
    assert data["billing_status"] in ("NOT_BILLED", "BILLED", "PAID")


def assert_inspection(data: dict):
    _assert_common(data)
    assert data["status"] in ("SCHEDULED", "IN_PROGRESS", "COMPLETED", "REOPENED")


def assert_estimate(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "APPROVED")
    assert isinstance(data["rcv_total_cents"], int)
    assert isinstance(data["acv_total_cents"], int)
    assert isinstance(data["net_payable_cents"], int)
    assert data["recoverable_depreciation_cents"] == data["rcv_total_cents"] - data["acv_total_cents"]


def assert_report(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "SUBMITTED", "APPROVED", "REVISION_REQUESTED")
    assert isinstance(data["revision_count"], int) and data["revision_count"] >= 0
    assert isinstance(data["photo_count"], int) and data["photo_count"] >= 0


def assert_fee_schedule(data: dict):
    _assert_common(data)


def assert_fee_bill(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "SUBMITTED", "APPROVED", "PAID", "REJECTED", "VOID")
    assert data["billing_method"] in ("FEE_SCHEDULE", "TIME_AND_EXPENSE")
    assert isinstance(data["subtotal_cents"], int)
    assert isinstance(data["total_cents"], int)


def assert_time_entry(data: dict):
    _assert_ledger_common(data)
    assert data["activity"] in ("INSPECTION", "ESTIMATING", "REPORT", "TRAVEL")


def assert_payment(data: dict):
    _assert_ledger_common(data)
    assert data["method"] in ("ACH", "CHECK")
    assert isinstance(data["amount_cents"], int)
