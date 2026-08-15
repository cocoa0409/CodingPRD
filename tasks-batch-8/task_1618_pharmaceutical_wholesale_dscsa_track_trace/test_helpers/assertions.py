"""Entity assertions and domain invariant checkers.

Every primary resource carries id/created_at/updated_at/version (PRD §2.4);
the EpcisEvent ledger entry carries only id + created_at.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_trading_partner(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["partner_name"], str) and len(data["partner_name"]) > 0
    assert data["partner_kind"] in ("CUSTOMER", "SUPPLIER")
    assert isinstance(data["credit_limit_cents"], int) and data["credit_limit_cents"] >= 0
    assert isinstance(data["open_receivable_cents"], int)
    assert isinstance(data["allocation_watermark_units"], int)


def assert_partner_state_license(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("partner_id", "")), "partner_id must be a UUID"
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert isinstance(data["license_number"], str) and len(data["license_number"]) > 0
    assert data["license_scope"] in ("RX_ONLY", "RX_AND_CONTROLLED", "RX_AND_COLD_CHAIN", "FULL")
    assert data["license_status"] in ("ACTIVE", "SUSPENDED", "REVOKED")


def assert_product(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["ndc"], str) and len(data["ndc"]) > 0
    assert isinstance(data["product_name"], str) and len(data["product_name"]) > 0
    assert isinstance(data["is_controlled"], bool)
    assert isinstance(data["is_cold_chain"], bool)
    assert isinstance(data["wholesale_acquisition_cost_cents"], int)
    assert data["wholesale_acquisition_cost_cents"] >= 0
    assert isinstance(data["is_340b_contracted"], bool)
    assert data["shortage_status"] in ("NORMAL", "SHORTAGE")


def assert_allocation_policy(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("product_id", "")), "product_id must be a UUID"
    assert isinstance(data["pool_units"], int) and data["pool_units"] >= 0
    assert isinstance(data["remaining_units"], int) and data["remaining_units"] >= 0
    assert data["remaining_units"] <= data["pool_units"]
    assert data["policy_mode"] in ("PRO_RATA", "EQUAL_SHARE")
    assert data["policy_status"] in ("OPEN", "EXHAUSTED", "CLOSED")


def assert_serialized_case(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["sscc"], str) and len(data["sscc"]) > 0
    assert is_valid_uuid(data.get("product_id", "")), "product_id must be a UUID"
    assert isinstance(data["lot_number"], str) and len(data["lot_number"]) > 0
    assert data["case_status"] in (
        "COMMISSIONED", "SHIPPED", "RECEIVED", "QUARANTINED", "DECOMMISSIONED"
    )


def assert_serialized_unit(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["sni"], str) and len(data["sni"]) > 0
    assert is_valid_uuid(data.get("case_id", "")), "case_id must be a UUID"
    assert data["unit_status"] in (
        "COMMISSIONED", "SHIPPED", "RECEIVED", "QUARANTINED", "DECOMMISSIONED"
    )


def assert_purchase_order(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("customer_id", "")), "customer_id must be a UUID"
    assert isinstance(data["ship_to_state"], str) and len(data["ship_to_state"]) == 2
    assert data["fulfillment_status"] in (
        "DRAFT", "CONFIRMED", "ALLOCATED", "SHIPPED", "DELIVERED", "CANCELLED"
    )
    assert data["financial_status"] in (
        "UNBILLED", "INVOICED", "PARTIALLY_PAID", "PAID", "CREDITED"
    )
    assert isinstance(data["invoice_total_cents"], int)
    assert isinstance(data["invoice_balance_cents"], int)
    assert data["invoice_balance_cents"] >= 0
    assert isinstance(data["is_340b_order"], bool)


def assert_order_line(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("order_id", "")), "order_id must be a UUID"
    assert is_valid_uuid(data.get("product_id", "")), "product_id must be a UUID"
    assert isinstance(data["quantity_requested"], int) and data["quantity_requested"] > 0
    assert isinstance(data["quantity_allocated"], int)
    assert 0 <= data["quantity_allocated"] <= data["quantity_requested"]
    assert data["line_status"] in ("PENDING", "ALLOCATED", "PARTIALLY_ALLOCATED", "UNFULFILLABLE")


def assert_epcis_event(data: dict):
    # Ledger entry: id + created_at only among the common fields (PRD §2.4).
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "EpcisEvent must not carry updated_at"
    assert "version" not in data, "EpcisEvent must not carry version"
    assert data["event_type"] in (
        "COMMISSION", "AGGREGATE", "SHIP", "RECEIVE",
        "QUARANTINE", "RELEASE", "DECOMMISSION",
    )
    assert is_valid_uuid(data.get("subject_case_id", "")), "subject_case_id must be a UUID"
    assert isinstance(data["txn_history_hash"], str)


def assert_suspect_investigation(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("case_id", "")), "case_id must be a UUID"
    assert isinstance(data["opened_reason"], str) and len(data["opened_reason"]) > 0
    assert data["investigation_status"] in (
        "OPEN", "QUARANTINED", "CLEARED", "CONFIRMED_ILLEGITIMATE"
    )
    assert isinstance(data["reopen_count"], int) and data["reopen_count"] >= 0


def assert_chargeback_claim(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("order_id", "")), "order_id must be a UUID"
    assert isinstance(data["claimed_amount_cents"], int) and data["claimed_amount_cents"] > 0
    assert isinstance(data["computed_amount_cents"], int)
    assert data["claim_status"] in ("SUBMITTED", "VALIDATED", "SETTLED", "DENIED")


def assert_return_authorization(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("order_id", "")), "order_id must be a UUID"
    assert is_valid_uuid(data.get("product_id", "")), "product_id must be a UUID"
    assert isinstance(data["quantity_returned"], int) and data["quantity_returned"] > 0
    assert data["return_status"] in ("REQUESTED", "RECEIVED", "CREDITED", "REJECTED")
    assert isinstance(data["credit_amount_cents"], int) and data["credit_amount_cents"] >= 0
