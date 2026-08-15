"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

AGREEMENT_STATUSES = ["DRAFT", "PENDING_ACCEPTANCE", "ACTIVE", "SUSPENDED",
                      "REJECTED", "TERMINATED"]
VISIT_STATUSES = ["SCHEDULED", "CHECKED_IN", "COUNTS_SUBMITTED", "CONFIRMED",
                  "DISPUTED", "MISSED", "CANCELLED"]
AUDIT_STATUSES = ["SCHEDULED", "IN_PROGRESS", "SUBMITTED", "DISPUTED",
                  "CERTIFIED", "LOCKED"]
STATEMENT_STATUSES = ["PROVISIONAL", "FINALIZED", "DISPUTED", "APPROVED", "PAID"]
PROMOTION_STATUSES = ["DRAFT", "SCHEDULED", "ACTIVE", "SUSPENDED", "ENDED",
                      "CANCELLED"]
ALLOCATION_STATUSES = ["PLANNED", "ACTIVE", "CLOSED"]
DIRECTIVE_STATUSES = ["SCHEDULED", "EFFECTIVE", "SUPERSEDED"]
MARKDOWN_STATUSES = ["REQUESTED", "APPROVED", "REJECTED", "APPLIED", "EXPIRED"]
SEASONAL_STATUSES = ["PLANNED", "SET_IN_PROGRESS", "SET_COMPLETE",
                     "ACTIVE_SEASON", "TEARDOWN_DUE", "TORN_DOWN", "RECONCILED"]
RACK_CATEGORIES = ["SNACKS", "BEVERAGES", "IMPULSE", "HOUSEWARES", "SEASONAL",
                   "PERSONAL_CARE"]
STOCK_POSTURES = ["DEPLETED", "LOW", "NORMAL"]


def _assert_common(data: dict, with_version: bool = True):
    assert is_valid_uuid(data.get("id", "")), "id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    if with_version:
        assert is_iso8601_timestamp(data.get("updated_at", "")), \
            "updated_at must be ISO 8601"
        assert isinstance(data.get("version"), int) and data["version"] >= 1, \
            "version must be a positive integer"


def assert_program(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["promo_min_gap_days"], int)
    assert isinstance(data["min_payout_cents"], int)
    assert data["default_settlement_cadence"] in ["WEEKLY", "BIWEEKLY", "MONTHLY"]
    assert data["status"] in ["ACTIVE", "ARCHIVED"]


def assert_store(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["store_code"], str) and data["store_code"]
    assert isinstance(data["total_facings"], int) and data["total_facings"] >= 1
    assert data["status"] in ["ACTIVE", "CLOSED"]


def assert_agreement(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("program_id", ""))
    assert is_valid_uuid(data.get("store_id", ""))
    assert 0 < data["base_margin_pct"] < 1
    assert 0 <= data["shrink_retailer_share_pct"] <= 1
    assert isinstance(data["restock_value_cap_cents"], int)
    assert data["status"] in AGREEMENT_STATUSES
    assert data["shrink_valuation_mode"] in ["JOBBER_COST", "BLENDED_RETAIL"]
    assert data["markdown_liability"] in ["JOBBER", "RETAILER", "SHARED"]
    assert data["settlement_cadence"] in ["WEEKLY", "BIWEEKLY", "MONTHLY"]
    assert isinstance(data["cumulative_delivered_units"], int)
    assert isinstance(data["cumulative_shrink_units"], int)
    assert isinstance(data["cumulative_shrink_ratio"], (int, float))


def assert_product(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("program_id", ""))
    assert isinstance(data["sku"], str) and data["sku"]
    assert data["jobber_cost_cents"] >= 1
    assert data["min_retail_cents"] >= 1
    assert data["units_per_facing"] >= 1
    assert data["status"] in ["ACTIVE", "DISCONTINUED"]


def assert_space_allocation(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("store_agreement_id", ""))
    assert data["category"] in RACK_CATEGORIES
    assert isinstance(data["facings"], int) and data["facings"] >= 1
    assert data["status"] in ALLOCATION_STATUSES


def assert_price_directive(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("store_agreement_id", ""))
    assert is_valid_uuid(data.get("product_id", ""))
    assert isinstance(data["price_cents"], int) and data["price_cents"] >= 1
    assert data["status"] in DIRECTIVE_STATUSES


def assert_promotion(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("program_id", ""))
    assert is_valid_uuid(data.get("product_id", ""))
    assert 0 < data["depth_pct"] <= 0.50
    assert 0 <= data["jobber_funding_pct"] <= 1
    assert data["status"] in PROMOTION_STATUSES


def assert_inventory_balance(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("store_agreement_id", ""))
    assert is_valid_uuid(data.get("product_id", ""))
    for field in ("on_hand_units", "lifetime_delivered_units",
                  "lifetime_scanned_units", "lifetime_customer_return_units",
                  "lifetime_shrink_units", "lifetime_rma_units",
                  "reorder_point_units"):
        assert isinstance(data[field], int), f"{field} must be an integer"
    assert data["stock_posture"] in STOCK_POSTURES


def assert_balance_ledger_invariant(data: dict):
    """PRD section 3.6: "on hand equals delivered minus scanned plus customer
    returns minus shrink minus vendor returns"."""
    expected = (data["lifetime_delivered_units"]
                - data["lifetime_scanned_units"]
                + data["lifetime_customer_return_units"]
                - data["lifetime_shrink_units"]
                - data["lifetime_rma_units"])
    assert data["on_hand_units"] == expected, (
        f"ledger invariant broken: on_hand {data['on_hand_units']} != "
        f"{expected}")


def assert_route(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("program_id", ""))
    assert isinstance(data["assigned_driver_id"], str)
    assert data["status"] in ["ACTIVE", "INACTIVE"]


def assert_service_visit(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("route_id", ""))
    assert is_valid_uuid(data.get("store_agreement_id", ""))
    assert data["status"] in VISIT_STATUSES
    assert isinstance(data["total_counted_units"], int)
    assert isinstance(data["total_restock_units"], int)
    assert isinstance(data["applied_restock_value_cents"], int)
    assert isinstance(data["auto_restock_flag"], bool)
    assert isinstance(data["suggested_restock_units"], int)


def assert_scan_event(data: dict):
    """ScanEvent is append-only: id and created_at, no updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    assert "updated_at" not in data, "ScanEvent must not carry updated_at"
    assert "version" not in data, "ScanEvent must not carry version"
    assert data["event_type"] in ["SALE", "RETURN", "VOID"]
    assert data["status"] in ["MATCHED", "UNMATCHED"]
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["client_event_id"], str)
    assert isinstance(data["is_promo_priced"], bool)


def assert_audit_count(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("store_agreement_id", ""))
    assert data["scope"] in ["FULL", "CATEGORY"]
    assert data["status"] in AUDIT_STATUSES
    for field in ("variance_units", "free_allowance_units", "chargeable_units",
                  "variance_value_cents", "retailer_charge_cents"):
        assert isinstance(data[field], int), f"{field} must be an integer"


def assert_markdown_authorization(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("store_agreement_id", ""))
    assert is_valid_uuid(data.get("product_id", ""))
    assert data["auth_type"] in ["MARKDOWN", "RETURN_TO_VENDOR"]
    assert isinstance(data["units"], int) and data["units"] >= 1
    assert data["status"] in MARKDOWN_STATUSES
    assert isinstance(data["credit_cents"], int)


def assert_settlement_statement(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("store_agreement_id", ""))
    assert isinstance(data["period_index"], int) and data["period_index"] >= 0
    assert data["status"] in STATEMENT_STATUSES
    assert data["variant_used"] in ["PROVISIONAL", "FINAL"]
    for field in ("gross_scanned_sales_cents", "scanned_units",
                  "promo_scan_units", "promo_jobber_funding_cents",
                  "markdown_credit_cents", "net_sales_cents",
                  "retailer_margin_cents", "shrink_retailer_charge_cents",
                  "teardown_penalty_cents", "net_payable_to_jobber_cents"):
        assert isinstance(data[field], int), f"{field} must be an integer"
    assert isinstance(data["margin_pct"], (int, float))


def assert_seasonal_set(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("store_agreement_id", ""))
    assert data["category"] in RACK_CATEGORIES
    assert isinstance(data["allocated_facings"], int)
    assert data["status"] in SEASONAL_STATUSES
    assert isinstance(data["penalty_cents"], int)
