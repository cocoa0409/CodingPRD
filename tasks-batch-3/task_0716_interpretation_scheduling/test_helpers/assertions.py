"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_client(data: dict):
    _common(data)
    assert isinstance(data["org_name"], str) and len(data["org_name"]) > 0
    assert data["org_type"] in ["HOSPITAL", "COURT", "CLINIC", "LAW_FIRM"]
    assert data["status"] in ["ACTIVE", "SUSPENDED"]
    assert isinstance(data["credit_limit_cents"], int)
    assert isinstance(data["outstanding_balance_cents"], int)


def assert_interpreter(data: dict):
    _common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["status"] in ["AVAILABLE", "BUSY", "OFFLINE", "DEACTIVATED"]
    assert isinstance(data["max_concurrent_load"], int)
    assert isinstance(data["active_load"], int) and data["active_load"] >= 0
    assert isinstance(data["rating_count"], int)
    assert data["rating_avg"] is None or isinstance(data["rating_avg"], (int, float))
    assert isinstance(data["no_show_strikes"], int) and data["no_show_strikes"] >= 0


def assert_request(data: dict):
    _common(data)
    assert data["modality"] in ["PHONE", "VIDEO", "ONSITE"]
    assert data["required_tier"] in ["MEDICAL", "LEGAL", "COURT"]
    assert data["scheduling_mode"] in ["ON_DEMAND", "SCHEDULED"]
    assert data["status"] in ["OPEN", "ASSIGNED", "FULFILLED", "CANCELLED", "UNFULFILLABLE"]
    assert isinstance(data["cancellation_fee_cents"], int) and data["cancellation_fee_cents"] >= 0


def assert_assignment(data: dict):
    _common(data)
    assert data["lifecycle_status"] in [
        "OFFERED", "ACCEPTED", "DECLINED", "EXPIRED", "IN_SESSION", "COMPLETED", "CANCELLED",
    ]
    assert data["billing_status"] in ["UNBILLED", "BILLABLE", "INVOICED", "WAIVED"]
    assert data["assignment_type"] in ["ON_DEMAND", "SCHEDULED"]


def assert_session(data: dict):
    _common(data)
    assert data["status"] in [
        "CONNECTING", "ACTIVE", "ENDED", "DISPUTED", "RECONCILED",
        "CLIENT_NO_SHOW", "INTERPRETER_NO_SHOW",
    ]
    assert isinstance(data["billed_units"], int) and data["billed_units"] >= 0
    assert isinstance(data["billed_amount_cents"], int) and data["billed_amount_cents"] >= 0


def assert_rating(data: dict):
    _common(data)
    assert isinstance(data["score"], int) and 1 <= data["score"] <= 5


def assert_complaint(data: dict):
    _common(data)
    assert data["category"] in ["QUALITY", "CONDUCT", "BILLING", "NO_SHOW"]
    assert data["status"] in ["FILED", "UNDER_REVIEW", "NEEDS_INFO", "UPHELD", "DISMISSED"]
    assert isinstance(data["remedy_credit_cents"], int) and data["remedy_credit_cents"] >= 0


def assert_invoice(data: dict):
    _common(data)
    assert data["status"] in ["DRAFT", "ISSUED", "SETTLED", "VOID"]
    assert isinstance(data["line_count"], int)
    assert isinstance(data["subtotal_cents"], int)
    assert isinstance(data["fees_cents"], int)
    assert isinstance(data["total_cents"], int)
