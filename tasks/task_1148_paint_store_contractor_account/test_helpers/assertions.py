"""Entity assertions and domain invariant checkers (PRD §2.5, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

ACCOUNT_STATUSES = ["ACTIVE", "SUSPENDED"]
TIERS = ["STANDARD", "SILVER", "GOLD", "PLATINUM"]
JOB_STATUSES = ["OPEN", "ON_HOLD", "COMPLETE"]
CATEGORIES = ["FLAT", "NON_FLAT", "INDUSTRIAL_MAINTENANCE"]
PRODUCT_STATUSES = ["ACTIVE", "DISCONTINUED"]
FORMULA_STATUSES = ["ACTIVE", "RETIRED"]
FORMULA_SOURCES = ["LIBRARY", "COLOR_MATCH"]
MATCH_STATUSES = ["SUBMITTED", "PROPOSED", "REVISION_REQUESTED", "APPROVED", "ABANDONED"]
BULLETIN_STATUSES = ["DRAFT", "PUBLISHED", "EFFECTIVE"]
SPEC_STATUSES = ["DRAFT", "SUBMITTED", "APPROVED", "REJECTED", "NEEDS_REVISION", "SUPERSEDED"]
PAYMENT_STATUSES = ["UNPAID", "PAID", "PARTIALLY_REFUNDED", "REFUNDED"]
FULFILLMENT_STATUSES = ["PENDING", "OUT_FOR_DELIVERY", "DELIVERED", "CANCELLED"]
DELIVERY_STATUSES = ["SCHEDULED", "EN_ROUTE", "DELIVERED", "FAILED"]
REBATE_STATUSES = ["ACCRUED", "FINALIZED", "DISPUTED", "PAID"]
LOYALTY_TYPES = ["EARN", "REDEEM", "CLAWBACK"]
MISTINT_STATUSES = ["LISTED", "SOLD", "WRITTEN_OFF"]


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        "version must be a positive integer"


def _assert_append_only(data: dict):
    # PRD §2.5: append-only ledger rows carry only id and created_at.
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "append-only ledger row must not expose version"
    assert "updated_at" not in data, "append-only ledger row must not expose updated_at"


def assert_contractor_account(data: dict):
    _assert_common(data)
    assert isinstance(data["company_name"], str) and data["company_name"]
    assert data["status"] in ACCOUNT_STATUSES
    assert data["tier"] in TIERS
    assert isinstance(data["credit_limit_cents"], int) and data["credit_limit_cents"] >= 0
    for f in ("outstanding_balance_cents", "loyalty_points_balance",
              "ytd_net_volume_cents", "lifetime_rebate_paid_cents"):
        assert isinstance(data[f], int), f"{f} must be integer cents/points"


def assert_job_account(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["contractor_account_id"])
    assert is_valid_uuid(data["jurisdiction_id"])
    assert isinstance(data["job_name"], str) and data["job_name"]
    assert isinstance(data["site_address"], str) and data["site_address"]
    assert data["budget_cap_cents"] is None or (
        isinstance(data["budget_cap_cents"], int) and data["budget_cap_cents"] >= 0)
    assert data["status"] in JOB_STATUSES
    assert isinstance(data["spent_cents"], int)


def assert_jurisdiction(data: dict):
    _assert_common(data)
    assert isinstance(data["code"], str) and data["code"]
    assert isinstance(data["name"], str) and data["name"]


def assert_voc_rule(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["jurisdiction_id"])
    assert data["category"] in CATEGORIES
    assert isinstance(data["max_voc_gpl"], int) and data["max_voc_gpl"] > 0
    assert is_iso8601_timestamp(data["effective_from"])
    assert data["effective_to"] is None or is_iso8601_timestamp(data["effective_to"])


def assert_product(data: dict):
    _assert_common(data)
    assert isinstance(data["sku"], str) and data["sku"]
    assert isinstance(data["name"], str) and data["name"]
    assert data["category"] in CATEGORIES
    assert isinstance(data["voc_gpl"], int) and data["voc_gpl"] > 0
    assert isinstance(data["list_price_cents"], int) and data["list_price_cents"] >= 0
    assert isinstance(data["tintable"], bool)
    assert data["status"] in PRODUCT_STATUSES
    assert data["replacement_product_id"] is None or is_valid_uuid(data["replacement_product_id"])


def assert_tint_formula(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["product_id"])
    assert isinstance(data["color_code"], str) and data["color_code"]
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["shots"], list)
    assert isinstance(data["revision"], int) and data["revision"] >= 1
    assert data["source"] in FORMULA_SOURCES
    assert data["status"] in FORMULA_STATUSES
    assert data["supersedes_formula_id"] is None or is_valid_uuid(data["supersedes_formula_id"])


def assert_color_match_request(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["contractor_account_id"])
    assert is_valid_uuid(data["product_id"])
    assert isinstance(data["sample_reference"], str)
    assert data["status"] in MATCH_STATUSES
    assert isinstance(data["iteration_count"], int) and data["iteration_count"] >= 0
    assert data["formula_id"] is None or is_valid_uuid(data["formula_id"])


def assert_product_bulletin(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["product_id"])
    assert is_valid_uuid(data["replacement_product_id"])
    assert isinstance(data["title"], str) and data["title"]
    assert is_iso8601_timestamp(data["effective_date"])
    assert data["status"] in BULLETIN_STATUSES
    assert data["published_at"] is None or is_iso8601_timestamp(data["published_at"])
    assert data["effected_at"] is None or is_iso8601_timestamp(data["effected_at"])


def assert_spec_sheet(data: dict):
    _assert_common(data)
    assert isinstance(data["project_code"], str) and data["project_code"]
    assert isinstance(data["architect_name"], str)
    assert isinstance(data["title"], str) and data["title"]
    assert data["status"] in SPEC_STATUSES
    assert data["rejection_reason"] is None or isinstance(data["rejection_reason"], str)
    assert data["approved_at"] is None or is_iso8601_timestamp(data["approved_at"])
    assert data["supersedes_spec_sheet_id"] is None or is_valid_uuid(data["supersedes_spec_sheet_id"])
    for f in ("pull_through_ordered_pct", "pull_through_delivered_pct"):
        assert isinstance(data[f], (int, float)), f"{f} must be a number"


def assert_spec_line(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["spec_sheet_id"])
    assert is_valid_uuid(data["product_id"])
    assert isinstance(data["specified_qty"], int) and data["specified_qty"] > 0
    assert isinstance(data["obsoleted"], bool)
    assert isinstance(data["ordered_qty"], int) and data["ordered_qty"] >= 0
    assert isinstance(data["delivered_qty"], int) and data["delivered_qty"] >= 0


def assert_order(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["contractor_account_id"])
    assert is_valid_uuid(data["job_account_id"])
    assert data["payment_status"] in PAYMENT_STATUSES
    assert data["fulfillment_status"] in FULFILLMENT_STATUSES
    assert data["tier_snapshot"] in TIERS
    for f in ("subtotal_cents", "discount_cents", "tax_cents", "total_cents", "refunded_cents"):
        assert isinstance(data[f], int), f"{f} must be integer cents"
    assert data["total_cents"] == data["subtotal_cents"] + data["tax_cents"], \
        "total must equal subtotal plus tax (PRD §3.6)"
    assert data["paid_at"] is None or is_iso8601_timestamp(data["paid_at"])


def assert_order_line(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["order_id"])
    assert is_valid_uuid(data["product_id"])
    assert data["formula_id"] is None or is_valid_uuid(data["formula_id"])
    assert data["spec_line_id"] is None or is_valid_uuid(data["spec_line_id"])
    assert isinstance(data["quantity"], int) and data["quantity"] > 0
    assert isinstance(data["returned_quantity"], int) and data["returned_quantity"] >= 0
    assert isinstance(data["unit_list_price_cents"], int)
    assert isinstance(data["unit_price_cents"], int)
    assert isinstance(data["line_total_cents"], int)
    assert isinstance(data["is_custom_tint"], bool)
    assert data["is_custom_tint"] == (data["formula_id"] is not None), \
        "is_custom_tint must mirror formula_id presence (PRD §3.6)"


def assert_return_record(data: dict):
    _assert_append_only(data)
    assert is_valid_uuid(data["order_line_id"])
    assert isinstance(data["quantity"], int) and data["quantity"] > 0
    for f in ("refund_merchandise_cents", "tax_refund_cents", "total_credit_cents"):
        assert isinstance(data[f], int), f"{f} must be integer cents"
    assert data["total_credit_cents"] == data["refund_merchandise_cents"] + data["tax_refund_cents"], \
        "total credit must equal merchandise plus tax refund (PRD §3.7)"


def assert_delivery(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["order_id"])
    assert is_valid_uuid(data["job_account_id"])
    assert is_iso8601_timestamp(data["window_start"])
    assert is_iso8601_timestamp(data["window_end"])
    assert data["status"] in DELIVERY_STATUSES
    assert data["failure_reason"] is None or isinstance(data["failure_reason"], str)
    assert data["dispatched_at"] is None or is_iso8601_timestamp(data["dispatched_at"])
    assert data["delivered_at"] is None or is_iso8601_timestamp(data["delivered_at"])


def assert_rebate_statement(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["contractor_account_id"])
    assert is_iso8601_timestamp(data["period_start"])
    assert is_iso8601_timestamp(data["period_end"])
    assert data["status"] in REBATE_STATUSES
    assert isinstance(data["provisional_amount_cents"], int)
    assert data["final_amount_cents"] is None or isinstance(data["final_amount_cents"], int)
    assert isinstance(data["adjustment_cents"], int)
    assert data["payable_cents"] is None or isinstance(data["payable_cents"], int)
    assert data["period_net_cents"] is None or isinstance(data["period_net_cents"], int)
    assert data["paid_at"] is None or is_iso8601_timestamp(data["paid_at"])


def assert_loyalty_transaction(data: dict):
    _assert_append_only(data)
    assert is_valid_uuid(data["contractor_account_id"])
    assert data["order_id"] is None or is_valid_uuid(data["order_id"])
    assert data["type"] in LOYALTY_TYPES
    assert isinstance(data["points_delta"], int)
    assert isinstance(data["note"], str)


def assert_mistint_listing(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["product_id"])
    assert data["formula_id"] is None or is_valid_uuid(data["formula_id"])
    assert isinstance(data["quantity"], int) and data["quantity"] > 0
    assert isinstance(data["cost_basis_cents"], int) and data["cost_basis_cents"] >= 0
    assert isinstance(data["list_price_cents"], int)
    assert isinstance(data["current_price_cents"], int)
    assert data["status"] in MISTINT_STATUSES
    assert data["sold_price_cents"] is None or isinstance(data["sold_price_cents"], int)
    assert data["sold_to_contractor_account_id"] is None or \
        is_valid_uuid(data["sold_to_contractor_account_id"])


def assert_account_ledger_invariants(account: dict):
    """Domain invariants that must hold on every account read (PRD §3.1)."""
    assert account["outstanding_balance_cents"] >= 0, \
        "outstanding balance is a sum of unpaid order totals and cannot be negative"
