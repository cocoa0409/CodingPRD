"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be a positive int"


def assert_tenant(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert data["reported_on_time_rate_pct"] is None or isinstance(data["reported_on_time_rate_pct"], int)
    assert isinstance(data["effective_reported_items"], int) and data["effective_reported_items"] >= 0


def assert_landlord(data: dict):
    _assert_common(data)
    assert isinstance(data["company_name"], str) and len(data["company_name"]) > 0
    assert isinstance(data["email"], str)


def assert_plan(data: dict):
    _assert_common(data)
    assert data["tier"] in ("BASIC", "PLUS", "PREMIUM")
    assert isinstance(data["monthly_fee_cents"], int) and data["monthly_fee_cents"] >= 0
    assert isinstance(data["back_reporting_included_months"], int) and data["back_reporting_included_months"] >= 0


def assert_enrollment(data: dict):
    _assert_common(data)
    assert data["status"] in ("PENDING_PAYMENT", "ACTIVE", "CANCELLED")
    assert isinstance(data["monthly_fee_cents"], int)
    assert isinstance(data["refund_cents"], int) and data["refund_cents"] >= 0
    assert isinstance(data["earned_cents"], int) and data["earned_cents"] >= 0


def assert_lease(data: dict):
    _assert_common(data)
    assert data["verification_status"] in (
        "PENDING_VERIFICATION", "VERIFIED", "REJECTED", "TERMINATED",
    )
    assert isinstance(data["rent_amount_cents"], int) and data["rent_amount_cents"] > 0
    assert 1 <= data["monthly_due_day"] <= 28


def assert_rent_payment(data: dict):
    _assert_common(data)
    assert data["status"] in ("RECORDED", "REPORTED")
    assert isinstance(data["on_time"], bool)
    assert isinstance(data["amount_paid_cents"], int) and data["amount_paid_cents"] >= 0


def assert_reported_item(data: dict):
    _assert_common(data)
    assert data["status"] in ("REPORTED", "DISPUTED", "CORRECTED", "RETRACTED")
    assert data["source"] in ("MONTHLY", "BACK_REPORT")
    assert isinstance(data["on_time"], bool)
    bs = data["bureau_statuses"]
    assert set(bs.keys()) == {"EQUIFAX", "EXPERIAN", "TRANSUNION"}, "bureau_statuses must key all three bureaus"
    for v in bs.values():
        assert v in ("FURNISHED", "DELETED")


def assert_dispute(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "OPEN", "INVESTIGATING", "RESOLVED_CORRECTED", "RESOLVED_UPHELD", "WITHDRAWN",
    )
    assert data["reason_code"] in ("NOT_MINE", "INCORRECT_AMOUNT", "INCORRECT_STATUS", "PAID_ON_TIME")


def assert_back_report_request(data: dict):
    _assert_common(data)
    assert data["status"] in ("PENDING", "APPROVED", "COMPLETED", "REJECTED")
    assert isinstance(data["billable_months"], int) and data["billable_months"] >= 0
    assert isinstance(data["fee_cents"], int) and data["fee_cents"] >= 0


def assert_invoice(data: dict):
    _assert_common(data)
    assert data["kind"] in ("SUBSCRIPTION", "BACK_REPORT")
    assert data["status"] in ("DUE", "PAID", "VOID")
    assert isinstance(data["amount_cents"], int)


def assert_score_snapshot(data: dict):
    """ScoreSnapshot is append-only: id + created_at, but NO version/updated_at."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "append-only snapshot must not carry a version field"
    assert "updated_at" not in data, "append-only snapshot must not carry an updated_at field"
    assert 300 <= data["score"] <= 850


def assert_money_conserved(earned_cents: int, refund_cents: int, paid_cents: int):
    """PRD §3.8: when the period was paid, earned + refund == paid, conserving the money."""
    assert earned_cents + refund_cents == paid_cents, (
        f"conserved-money invariant broken: {earned_cents} + {refund_cents} != {paid_cents}"
    )
