"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp,
)

COMMON_STATES = {
    "branch": ["OPEN", "AUDIT_FROZEN"],
    "teller": ["ACTIVE", "SUSPENDED"],
    "account": ["OPEN", "CLOSED"],
    "drawer": ["OPEN", "COUNTING", "BALANCED", "OUT_OF_BALANCE", "CLOSED"],
}


def _assert_common(data, with_version=True):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    if with_version:
        assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
        assert isinstance(data["version"], int) and data["version"] >= 1
    else:
        assert "updated_at" not in data, "append-only records must not carry updated_at"
        assert "version" not in data, "append-only records must not carry version"


def assert_branch(data):
    _assert_common(data)
    assert data["status"] in COMMON_STATES["branch"]
    for f in ("drawer_limit_cents", "vault_cash_cents", "over_short_investigation_threshold_cents"):
        assert isinstance(data[f], int), f"{f} must be integer cents"


def assert_teller(data):
    _assert_common(data)
    assert data["status"] in COMMON_STATES["teller"]
    assert isinstance(data["branch_id"], str)


def assert_account(data):
    _assert_common(data)
    assert data["status"] in COMMON_STATES["account"]
    assert isinstance(data["balance_cents"], int)


def assert_drawer(data):
    _assert_common(data)
    assert data["status"] in COMMON_STATES["drawer"]
    assert isinstance(data["cash_balance_cents"], int)
    assert isinstance(data["expected_cash_cents"], int)
    assert isinstance(data["business_date"], str)


def assert_transaction(data):
    _assert_common(data)
    assert data["type"] in ["CASH_DEPOSIT", "CASH_WITHDRAWAL", "CHECK_DEPOSIT",
                            "CASHIERS_CHECK_PURCHASE", "MONEY_ORDER_PURCHASE"]
    assert data["status"] in ["POSTED", "VOIDED"]
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert isinstance(data["fee_cents"], int)
    assert isinstance(data["is_ctr_exempt"], bool)


def assert_cash_order(data):
    _assert_common(data)
    assert data["status"] in ["PENDING", "APPROVED", "REJECTED", "DELIVERED", "CANCELLED"]
    assert isinstance(data["ordered_amount_cents"], int)
    assert isinstance(data["projected_need_cents"], int)
    assert isinstance(data["suggested_order_cents"], int)


def assert_teller_request(data):
    _assert_common(data)
    assert data["type"] in ["ISSUE_INSTRUMENT", "FEE_WAIVER", "OVER_LIMIT_TRANSACTION"]
    assert data["status"] in ["PENDING", "EXECUTED", "REJECTED", "EXPIRED"]
    assert isinstance(data["params"], dict)


def assert_hold(data):
    _assert_common(data)
    assert data["status"] in ["ACTIVE", "RELEASED", "WAIVED"]
    assert data["hold_type"] in ["STANDARD", "LARGE_CHECK"]
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0
    assert isinstance(data["release_day_offset"], int)


def assert_ctr_filing(data):
    _assert_common(data, with_version=False)
    assert data["status"] in ["FILED", "AMENDED"]
    assert data["trigger_direction"] in ["CASH_IN", "CASH_OUT", "BOTH"]
    assert isinstance(data["transaction_ids"], list)


def assert_over_short_case(data):
    _assert_common(data)
    assert data["status"] in ["OPEN", "UNDER_INVESTIGATION", "RESOLVED", "WAIVED"]
    assert isinstance(data["variance_cents"], int)


def assert_approval(data):
    _assert_common(data, with_version=False)
    assert data["action_type"] in ["TELLER_REQUEST", "OVER_SHORT_WAIVER", "HOLD_WAIVER"]
    assert data["status"] in ["APPROVED", "REJECTED"]


def assert_audit(data):
    _assert_common(data)
    assert data["type"] in ["SCHEDULED", "SURPRISE"]
    assert data["status"] in ["PLANNED", "IN_PROGRESS", "COMPLETED", "CANCELLED"]
