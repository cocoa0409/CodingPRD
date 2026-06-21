"""Entity assertions and domain invariant checkers.

Each assert_{entity} validates the response structure against the PRD contract.
Append-only records (FinanceTransaction, LayawayInstallment) carry only
id + created_at (PRD §2.4), so their checkers do not demand updated_at/version.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be int"


def _assert_append_only_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "append-only record must not carry updated_at"
    assert "version" not in data, "append-only record must not carry version"


def assert_shop(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["state_code"] in ("FL", "TX", "CA")
    assert isinstance(data["police_reporting_enabled"], bool)


def assert_cash_drawer(data: dict):
    _assert_common(data)
    assert isinstance(data["shop_id"], str)
    assert isinstance(data["balance_cents"], int)


def assert_storage_bin(data: dict):
    _assert_common(data)
    assert isinstance(data["shop_id"], str)
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1


def assert_state_schedule(data: dict):
    _assert_common(data)
    assert data["state_code"] in ("FL", "TX", "CA")
    for field in ("monthly_interest_bps", "monthly_storage_fee_cents", "setup_fee_cents",
                  "term_days", "grace_days", "max_principal_cents", "max_periods_total",
                  "loan_to_value_bps", "layaway_buffer_days"):
        assert isinstance(data[field], int), f"{field} must be int"


def assert_customer(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["gov_id_number"], str)
    assert isinstance(data["is_flagged"], bool)


def assert_pawn_item(data: dict):
    _assert_common(data)
    assert data["status"] in ("INTAKE", "APPRAISED", "PLEDGED", "REDEEMED",
                              "FORFEITED", "RELEASED_TO_POLICE")
    assert data["police_report_status"] in ("NOT_REQUIRED", "PENDING_REPORT", "REPORTED")


def assert_loan(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "IN_GRACE", "REDEEMED", "FORFEITED",
                              "VOIDED", "POLICE_HELD")
    assert isinstance(data["principal_cents"], int)
    assert isinstance(data["setup_fee_cents"], int)
    assert isinstance(data["periods_charged"], int)
    assert isinstance(data["renewal_count"], int)
    assert isinstance(data["police_hold_flag"], bool)


def assert_inventory_item(data: dict):
    _assert_common(data)
    assert data["status"] in ("AVAILABLE", "ON_LAYAWAY", "SOLD", "RECALLED")
    assert isinstance(data["cost_basis_cents"], int)
    assert isinstance(data["list_price_cents"], int)
    assert isinstance(data["floor_price_cents"], int)
    # The forfeiture pricing invariant: the listing never sits below cost (PRD §3.7).
    assert data["list_price_cents"] >= data["cost_basis_cents"], "list_price must be >= cost_basis"
    assert data["floor_price_cents"] == data["cost_basis_cents"], "floor_price must equal cost_basis"


def assert_layaway_plan(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "DEFAULTED", "COMPLETED")
    assert isinstance(data["total_price_cents"], int)
    assert isinstance(data["deposit_cents"], int)
    assert isinstance(data["paid_cents"], int)
    assert isinstance(data["installment_count"], int)


def assert_police_hold(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "RELEASED", "EXECUTED")
    assert data["subject_kind"] in ("PAWN_ITEM", "INVENTORY_ITEM")


def assert_finance_transaction(data: dict):
    _assert_append_only_common(data)
    assert data["kind"] in ("DISBURSEMENT", "EXTENSION_FEE", "RENEWAL_FEE",
                            "REDEMPTION_PAYOFF", "VOID_REVERSAL")
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["periods_in_charge"], int)


def assert_layaway_installment(data: dict):
    _assert_append_only_common(data)
    assert isinstance(data["sequence"], int) and data["sequence"] >= 1
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["paid"], bool)
