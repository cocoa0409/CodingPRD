"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be a positive int, got {data.get('version')}"


def assert_association(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["state_code"], str)
    assert isinstance(data["trust_balance_cents"], int)


def assert_account(data: dict):
    _assert_common(data)
    assert data["status"] in [
        "CURRENT", "DELINQUENT", "PAYMENT_PLAN", "LIEN", "FORECLOSURE",
        "BANKRUPTCY", "CHARGED_OFF", "CLOSED",
    ], f"unexpected account status {data['status']}"
    assert isinstance(data["total_balance_cents"], int)
    assert isinstance(data["aging"], dict)


def assert_assessment(data: dict):
    _assert_common(data)
    assert data["status"] in ["OPEN", "PARTIAL", "PAID", "WAIVED"]
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["balance_cents"], int)


def assert_payment(data: dict):
    _assert_common(data)
    assert data["status"] in ["POSTED", "REVERSED"]
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["allocations"], list)
    assert isinstance(data["unapplied_cents"], int)


def assert_notice(data: dict):
    _assert_common(data)
    assert data["status"] in ["DRAFT", "SENT", "DISPUTED", "EXPIRED", "VOID"]
    assert data["notice_type"] in ["VALIDATION", "DEMAND", "INTENT_TO_LIEN", "INTENT_TO_FORECLOSE"]


def assert_payment_plan(data: dict):
    _assert_common(data)
    assert data["status"] in ["DRAFT", "ACTIVE", "BREACHED", "SUSPENDED", "COMPLETED", "CANCELLED"]
    assert isinstance(data["total_amount_cents"], int)
    assert isinstance(data["missed_count"], int)


def assert_lien(data: dict):
    _assert_common(data)
    assert data["status"] in ["RECORDED", "STAYED", "FORECLOSING", "RELEASED"]
    assert isinstance(data["recorded_amount_cents"], int)


def assert_foreclosure_referral(data: dict):
    _assert_common(data)
    assert data["status"] in ["REFERRED", "FILED", "STAYED", "SALE_COMPLETED", "WITHDRAWN"]


def assert_bankruptcy_case(data: dict):
    _assert_common(data)
    assert data["status"] in ["FILED", "DISCHARGED", "DISMISSED"]
    assert data["chapter"] in ["CH7", "CH13"]


def assert_remittance(data: dict):
    _assert_common(data)
    assert data["status"] in ["PENDING", "REMITTED", "VOID"]
    assert isinstance(data["gross_amount_cents"], int)
    assert isinstance(data["management_fee_cents"], int)
    assert isinstance(data["net_amount_cents"], int)


def assert_net_equals_gross_minus_fee(data: dict):
    """Conservation: net_amount_cents == gross_amount_cents - management_fee_cents."""
    assert data["net_amount_cents"] == data["gross_amount_cents"] - data["management_fee_cents"], \
        f"net {data['net_amount_cents']} != gross {data['gross_amount_cents']} - fee {data['management_fee_cents']}"
