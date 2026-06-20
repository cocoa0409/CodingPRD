"""Entity assertions and domain invariant checkers for the Donor-Advised Fund API."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_full(data: dict):
    """Resources with the full id/created_at/updated_at/version set."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def _assert_common_append_only(data: dict):
    """Append-only audit records carry ONLY id + created_at (no updated_at, no version)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "append-only record must not carry a version field"
    assert "updated_at" not in data, "append-only record must not carry an updated_at field"


def assert_sponsor(data: dict):
    _assert_common_full(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["ein"], str)
    assert isinstance(data["minimum_grant_cents"], int)
    assert isinstance(data["inactivity_quarters"], int)
    assert isinstance(data["admin_fee_bps_default"], int)
    assert isinstance(data["current_quarter_index"], int)


def assert_investment_pool(data: dict):
    _assert_common_full(data)
    assert data["risk_tier"] in ("CONSERVATIVE", "BALANCED", "GROWTH")
    assert data["status"] in ("OPEN", "CLOSED")
    assert isinstance(data["nav_per_unit_cents"], int)
    assert isinstance(data["fee_bps"], int)


def assert_nav_period(data: dict):
    _assert_common_full(data)
    assert data["status"] in ("ACTIVE", "SUPERSEDED")
    assert isinstance(data["from_quarter"], int)
    assert isinstance(data["to_quarter"], int)


def assert_charity(data: dict):
    _assert_common_full(data)
    assert data["status"] in ("PENDING_VETTING", "VETTED", "WATCHLISTED", "REVOKED")
    assert isinstance(data["legal_name"], str)
    assert isinstance(data["ein"], str)
    assert isinstance(data["is_private_foundation"], bool)


def assert_donor_account(data: dict):
    _assert_common_full(data)
    assert data["status"] in ("ACTIVE", "INACTIVE", "WIND_DOWN", "CLOSED")
    for f in ("cash_balance_cents", "invested_value_cents", "committed_grants_cents",
              "admin_fee_accrued_cents", "grantable_balance_cents"):
        assert isinstance(data[f], int), f"{f} must be an integer"


def assert_contribution(data: dict):
    _assert_common_full(data)
    assert data["asset_type"] in ("CASH", "SECURITIES", "CRYPTO")
    assert data["status"] in ("PENDING", "SETTLED", "REJECTED")


def assert_substantiation_receipt(data: dict):
    _assert_common_append_only(data)
    assert isinstance(data["deductible_value_cents"], int)
    assert isinstance(data["contribution_id"], str)
    assert isinstance(data["donor_account_id"], str)


def assert_pool_allocation(data: dict):
    _assert_common_full(data)
    assert data["status"] in ("ACTIVE", "LIQUIDATED")
    assert isinstance(data["units_micro"], int)


def assert_grant_recommendation(data: dict):
    _assert_common_full(data)
    assert data["status"] in ("SUBMITTED", "APPROVED", "SCHEDULED", "PAID", "REJECTED", "CANCELLED")
    assert data["recurrence"] in ("ONE_TIME", "RECURRING")
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["is_anonymous"], bool)


def assert_succession_plan(data: dict):
    _assert_common_full(data)
    assert data["plan_type"] in ("SUCCESSOR_ADVISOR", "LEGACY_GRANTS")
    assert data["status"] in ("DRAFT", "CONFIRMED", "EXECUTED")


def assert_rebalance_order(data: dict):
    _assert_common_full(data)
    assert data["status"] in ("DRAFT", "EXECUTED", "CANCELLED")
    assert isinstance(data["amount_cents"], int)


def assert_ledger_entry(data: dict):
    _assert_common_append_only(data)
    assert data["entry_type"] in (
        "CONTRIBUTION_SETTLED", "POOL_BUY", "POOL_REDEEM",
        "GRANT_PAID", "ADMIN_FEE", "LEGACY_DISBURSEMENT",
    )
    assert isinstance(data["signed_amount_cents"], int)


def assert_grantable_settled(account: dict):
    """The settled grantable balance reconciles to the PRD-defined derivation:
    cash + invested - committed - accrued fee."""
    expected = (account["cash_balance_cents"]
                + account["invested_value_cents"]
                - account["committed_grants_cents"]
                - account["admin_fee_accrued_cents"])
    assert account["grantable_balance_cents"] == expected, (
        f"grantable_balance_cents {account['grantable_balance_cents']} != "
        f"cash+invested-committed-fee {expected}"
    )
