"""Entity assertions and domain invariant checkers.

Each assert_{entity}() validates the response shape against the PRD contract,
using the framework's generic format checkers internally.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_full(data: dict):
    """id + created_at + updated_at + version (full-resource entities)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an int"


def _assert_common_light(data: dict):
    """id + created_at only (line items, audit entries)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data or data.get("updated_at") is None, \
        "append-only entity must not carry updated_at"
    assert "version" not in data or data.get("version") is None, \
        "append-only entity must not carry version"


def assert_tax_jurisdiction(data: dict):
    _assert_common_full(data)
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert data["sourcing_rule"] in ("ORIGIN", "DESTINATION")
    assert isinstance(data["state_rate"], (int, float))
    assert isinstance(data["local_rate"], (int, float))
    assert isinstance(data["combined_rate"], (int, float))


def assert_product_category(data: dict):
    _assert_common_full(data)
    assert isinstance(data["jurisdiction_id"], str)
    assert isinstance(data["category_code"], str) and len(data["category_code"]) > 0
    assert data["taxability"] in ("FULL", "REDUCED", "EXEMPT")


def assert_seller(data: dict):
    _assert_common_full(data)
    assert isinstance(data["legal_name"], str) and len(data["legal_name"]) > 0
    assert isinstance(data["origin_state_code"], str) and len(data["origin_state_code"]) == 2
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_nexus_profile(data: dict):
    _assert_common_full(data)
    assert isinstance(data["seller_id"], str)
    assert isinstance(data["jurisdiction_id"], str)
    assert isinstance(data["cumulative_taxable_sales"], (int, float))
    assert isinstance(data["cumulative_txn_count"], int)
    assert data["nexus_status"] in ("NO_NEXUS", "THRESHOLD_MET", "REGISTERED")


def assert_exemption_certificate(data: dict):
    _assert_common_full(data)
    assert isinstance(data["seller_id"], str)
    assert isinstance(data["jurisdiction_id"], str)
    assert isinstance(data["customer_ref"], str)
    assert isinstance(data["exempt_category_code"], str)
    assert data["status"] in ("ACTIVE", "REVOKED", "EXPIRED")


def assert_marketplace_facilitator(data: dict):
    _assert_common_full(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["collecting_state_codes"], list)
    assert len(data["collecting_state_codes"]) >= 1


def assert_transaction(data: dict):
    _assert_common_full(data)
    assert isinstance(data["seller_id"], str)
    assert isinstance(data["jurisdiction_id"], str)
    assert isinstance(data["customer_ref"], str)
    assert isinstance(data["customer_exempt_requested"], bool)
    assert data["settlement_status"] in ("PENDING", "SETTLED", "VOIDED")
    assert data["audit_status"] in ("UNREVIEWED", "FLAGGED", "CLEARED")


def assert_transaction_line_item(data: dict):
    _assert_common_light(data)
    assert isinstance(data["transaction_id"], str)
    assert isinstance(data["category_code"], str)
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["unit_price"], (int, float)) and data["unit_price"] > 0


def assert_use_tax_accrual(data: dict):
    _assert_common_full(data)
    assert isinstance(data["seller_id"], str)
    assert isinstance(data["jurisdiction_id"], str)
    assert isinstance(data["purchase_amount"], (int, float))
    assert isinstance(data["accrued_use_tax"], (int, float))
    assert data["status"] in ("ACCRUED", "INCLUDED_IN_RETURN")


def assert_tax_return(data: dict):
    _assert_common_full(data)
    assert isinstance(data["seller_id"], str)
    assert isinstance(data["jurisdiction_id"], str)
    assert data["status"] in ("DRAFT", "ACCEPTED", "REJECTED", "FILED", "REMITTED")
    assert isinstance(data["tax_due"], (int, float))


def assert_remittance_payment(data: dict):
    _assert_common_full(data)
    assert isinstance(data["tax_return_id"], str)
    assert isinstance(data["amount"], (int, float))
    assert data["status"] == "APPLIED"


def assert_money_2dp(value: float):
    """A money amount must carry at most two decimal places."""
    assert isinstance(value, (int, float)), f"expected numeric money value, got {value!r}"
    rounded = round(float(value) + 1e-9, 2)
    assert abs(float(value) - rounded) < 1e-6, f"{value} is not held to 2 decimal places"
