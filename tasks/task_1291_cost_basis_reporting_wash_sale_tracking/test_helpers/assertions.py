"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_brokerage_firm(data: dict):
    _assert_common(data)
    assert isinstance(data["legal_name"], str) and len(data["legal_name"]) > 0
    assert isinstance(data["tax_year_open"], int)
    assert isinstance(data["wash_sale_window_days"], int)
    assert isinstance(data["correction_deadline_days"], int)


def assert_customer(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("firm_id", "")), "firm_id must be a UUID"
    assert isinstance(data["taxpayer_tin"], str) and len(data["taxpayer_tin"]) > 0
    assert isinstance(data["display_name"], str)
    assert data["status"] in ("ACTIVE", "SUSPENDED", "CLOSED")
    assert isinstance(data["wash_sale_scope_key"], str)


def assert_account(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("firm_id", ""))
    assert is_valid_uuid(data.get("customer_id", ""))
    assert isinstance(data["account_number"], str) and len(data["account_number"]) > 0
    assert data["account_type"] in ("TAXABLE", "IRA", "ROTH_IRA")
    assert data["default_disposal_method"] in ("FIFO", "LIFO", "HIFO", "SPECIFIC_ID")
    assert data["status"] in ("OPEN", "RESTRICTED", "CLOSED")


def assert_security(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("firm_id", ""))
    assert isinstance(data["cusip"], str) and len(data["cusip"]) == 9
    assert isinstance(data["ticker"], str)
    assert data["security_type"] in ("EQUITY", "CORPORATE_BOND", "OPTION", "MUTUAL_FUND")
    assert isinstance(data["covered_security_effective_date"], str)


def assert_tax_lot(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("firm_id", ""))
    assert is_valid_uuid(data.get("account_id", ""))
    assert is_valid_uuid(data.get("security_id", ""))
    assert isinstance(data["acquisition_date"], str)
    assert data["quantity"] > 0
    assert data["quantity_remaining"] >= 0
    assert isinstance(data["original_cost_basis_cents"], int)
    assert isinstance(data["adjusted_cost_basis_cents"], int)
    assert data["acquisition_kind"] in (
        "PURCHASE", "GIFT", "INHERITANCE", "TRANSFER_IN", "CORPORATE_ACTION_DERIVED"
    )
    assert isinstance(data["wash_sale_taint_basis_cents"], int)
    assert data["covered_status"] in ("COVERED", "NONCOVERED")
    assert data["lot_status"] in ("OPEN", "PARTIALLY_DISPOSED", "FULLY_DISPOSED", "SUPERSEDED")


def assert_disposition(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("firm_id", ""))
    assert is_valid_uuid(data.get("account_id", ""))
    assert is_valid_uuid(data.get("security_id", ""))
    assert isinstance(data["trade_date"], str)
    assert isinstance(data["settlement_date"], str)
    assert data["quantity"] > 0
    assert isinstance(data["proceeds_cents"], int)
    assert data["method"] in ("FIFO", "LIFO", "HIFO", "SPECIFIC_ID")
    assert data["status"] in ("PENDING", "SETTLED", "CORRECTED", "VOIDED")


def assert_corporate_action(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("firm_id", ""))
    assert is_valid_uuid(data.get("security_id", ""))
    assert data["action_type"] in ("SPLIT", "REVERSE_SPLIT", "MERGER", "SPINOFF")
    assert isinstance(data["effective_date"], str)
    assert data["status"] in ("ANNOUNCED", "EFFECTIVE", "CANCELLED")


def assert_transfer_statement(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("firm_id", ""))
    assert is_valid_uuid(data.get("account_id", ""))
    assert data["direction"] in ("INBOUND", "OUTBOUND")
    assert isinstance(data["counterparty_firm_name"], str)
    assert is_valid_uuid(data.get("security_id", ""))
    assert data["quantity"] > 0
    assert isinstance(data["transfer_date"], str)
    assert data["status"] in ("PENDING", "DELIVERED", "ACCEPTED", "REJECTED", "SUPERSEDED")


def assert_wash_sale_event(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("firm_id", ""))
    assert is_valid_uuid(data.get("disposition_id", ""))
    assert is_valid_uuid(data.get("triggering_lot_id", ""))
    assert is_valid_uuid(data.get("sold_lot_id", ""))
    assert isinstance(data["disallowed_loss_cents"], int)
    assert data["disallowed_loss_cents"] > 0
    assert isinstance(data["wash_sale_window_start"], str)
    assert isinstance(data["wash_sale_window_end"], str)
    assert data["matching_rule"] in ("SHARE_FOR_SHARE", "PARTIAL_PRORATA")


def assert_tax_form_1099b(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("firm_id", ""))
    assert is_valid_uuid(data.get("customer_id", ""))
    assert isinstance(data["tax_year"], int)
    assert data["status"] in ("DRAFT", "GENERATED", "FILED", "CORRECTION_PENDING", "REFILED", "FROZEN")
    for field in (
        "short_term_proceeds_cents", "short_term_basis_cents", "short_term_gain_cents",
        "long_term_proceeds_cents", "long_term_basis_cents", "long_term_gain_cents",
        "disallowed_wash_sale_loss_cents",
    ):
        assert isinstance(data[field], int), f"{field} must be integer cents"
    assert isinstance(data["correction_count"], int)
    assert data["short_term_gain_cents"] == data["short_term_proceeds_cents"] - data["short_term_basis_cents"], (
        "short_term_gain_cents must equal short_term_proceeds_cents - short_term_basis_cents"
    )
    assert data["long_term_gain_cents"] == data["long_term_proceeds_cents"] - data["long_term_basis_cents"], (
        "long_term_gain_cents must equal long_term_proceeds_cents - long_term_basis_cents"
    )


def assert_basis_change_request(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("firm_id", ""))
    assert is_valid_uuid(data.get("customer_id", ""))
    assert is_valid_uuid(data.get("tax_lot_id", ""))
    assert data["request_kind"] in (
        "COVERAGE_RECLASS", "BASIS_AMOUNT_CORRECTION",
        "ACQUISITION_DATE_CORRECTION", "GIFT_BASIS_SUPPLY",
    )
    assert data["status"] in ("PENDING", "UNDER_REVIEW", "APPROVED", "APPLIED", "REJECTED", "RESUBMITTED")
