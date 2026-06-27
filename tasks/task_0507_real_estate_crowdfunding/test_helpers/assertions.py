"""Entity assertions and domain invariant checkers for the Real Estate Crowdfunding API."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """id + created_at + updated_at + version present and well-formed (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_append_only(data: dict):
    """Append-only record: id + created_at only, no updated_at / version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "append-only record must not carry version"
    assert "updated_at" not in data, "append-only record must not carry updated_at"


def assert_fund(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["vehicle_type"] in ("REIT", "PARTNERSHIP")
    assert data["status"] in ("OPEN", "CLOSED_TO_NEW", "WINDING_DOWN")
    assert data["gross_asset_value_cents"] >= 0
    assert data["total_liabilities_cents"] >= 0
    assert data["shares_outstanding"] >= 0
    assert data["nav_per_share_cents"] >= 0
    assert isinstance(data["total_capital_cents"], int)
    assert isinstance(data["current_valuation_seq"], int)


def assert_share_class(data: dict):
    _assert_common(data)
    assert isinstance(data["fund_id"], str)
    assert isinstance(data["class_code"], str) and len(data["class_code"]) > 0
    assert data["min_investment_cents"] >= 0
    assert 0 <= data["mgmt_fee_bps"] <= 1000
    assert isinstance(data["accredited_only"], bool)
    assert isinstance(data["drip_eligible"], bool)
    assert data["status"] in ("OFFERING", "SUSPENDED", "CLOSED")


def assert_project(data: dict):
    _assert_common(data)
    assert isinstance(data["fund_id"], str)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["acquisition_cost_cents"] >= 0
    assert data["appraised_value_cents"] >= 0
    assert data["status"] in ("ACQUIRED", "STABILIZED", "DISPOSED")


def assert_investor(data: dict):
    _assert_common(data)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["accredited_status"] in ("NON_ACCREDITED", "ACCREDITED")
    assert data["annual_income_cents"] >= 0
    assert data["net_worth_cents"] >= 0
    assert data["suitability_status"] in ("PENDING", "APPROVED", "REJECTED")
    assert data["ytd_invested_cents"] >= 0


def assert_subscription(data: dict):
    _assert_common(data)
    assert isinstance(data["investor_id"], str)
    assert isinstance(data["share_class_id"], str)
    assert data["funded_amount_cents"] >= 0
    assert isinstance(data["drip_elected"], bool)
    assert data["status"] in ("PENDING_ACH", "SETTLED", "REVERSED", "CANCELLED")


def assert_holding(data: dict):
    _assert_common(data)
    assert isinstance(data["investor_id"], str)
    assert isinstance(data["share_class_id"], str)
    assert data["shares_owned"] >= 0
    assert data["cost_basis_cents"] >= 0
    assert isinstance(data["drip_elected"], bool)


def assert_distribution(data: dict):
    _assert_common(data)
    assert isinstance(data["fund_id"], str)
    assert isinstance(data["period_label"], str) and len(data["period_label"]) > 0
    assert data["dividend_per_share_cents"] > 0
    assert data["status"] in ("DECLARED", "PAID", "CANCELLED")
    assert data["total_paid_cents"] >= 0


def assert_redemption_request(data: dict):
    _assert_common(data)
    assert isinstance(data["holding_id"], str)
    assert data["shares_requested"] > 0
    assert data["status"] in ("QUEUED", "DEFERRED", "FULFILLED", "REJECTED", "CANCELLED")
    assert isinstance(data["queue_seq"], int)


def assert_valuation(data: dict):
    _assert_append_only(data)
    assert isinstance(data["fund_id"], str)
    assert isinstance(data["seq"], int) and data["seq"] >= 1
    assert isinstance(data["period_label"], str) and len(data["period_label"]) > 0


def assert_distribution_allocation(data: dict):
    _assert_append_only(data)
    assert isinstance(data["distribution_id"], str)
    assert isinstance(data["holding_id"], str)
    assert data["mode"] in ("CASH", "DRIP")


def assert_tax_document(data: dict):
    _assert_append_only(data)
    assert isinstance(data["investor_id"], str)
    assert isinstance(data["fund_id"], str)
    assert data["doc_type"] in ("FORM_1099_DIV", "FORM_K1")
    assert data["ordinary_dividends_cents"] >= 0
    assert data["reinvested_dividends_cents"] >= 0
