"""Entity assertions and domain invariant checkers.

Uses the framework's generic validators internally. Every resource carries the
common id/created_at/updated_at/version fields (PRD §2.4).
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_patron(data: dict):
    _assert_common(data)
    assert isinstance(data["display_name"], str) and len(data["display_name"]) > 0
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert data["status"] == "ACTIVE"
    assert isinstance(data["store_credit_cents"], int)
    assert isinstance(data["consignor_payable_cents"], int)
    assert data["store_credit_cents"] >= 0, "store credit ledger must never be negative"
    assert data["consignor_payable_cents"] >= 0, "consignor payable ledger must never be negative"


def assert_intake_lot(data: dict):
    _assert_common(data)
    assert data["acquisition_channel"] in ["BUYBACK", "CONSIGNMENT", "PURCHASE", "FAIR"]
    assert data["status"] in ["DRAFT", "SETTLED", "REJECTED"]
    assert isinstance(data["item_count"], int)


def assert_book_item(data: dict):
    _assert_common(data)
    assert isinstance(data["title"], str)
    assert isinstance(data["author"], str)
    assert data["status"] in ["INTAKE", "GRADED", "APPRAISED", "LISTED", "SOLD", "WITHDRAWN"]
    assert isinstance(data["provenance"], list)


def assert_appraisal(data: dict):
    _assert_common(data)
    assert data["basis"] in ["FAIR_MARKET", "RETAIL_REPLACEMENT"]
    assert data["status"] in ["ISSUED", "SUPERSEDED", "VOIDED"]
    assert isinstance(data["fair_market_value_cents"], int)
    assert isinstance(data["retail_replacement_value_cents"], int)
    assert isinstance(data["final_value_cents"], int)


def assert_consignment_agreement(data: dict):
    _assert_common(data)
    assert data["status"] in ["PROPOSED", "AMENDED", "ACTIVE", "SETTLED"]
    assert data["fee_model"] in ["GROSS_COMMISSION", "NET_COMMISSION"]
    assert isinstance(data["amendment_no"], int)


def assert_catalog_listing(data: dict):
    _assert_common(data)
    assert data["online_status"] in ["DRAFT", "LIVE", "SOLD", "DELISTED"]
    assert data["shop_status"] in ["DRAFT", "ON_SHELF", "SOLD", "PULLED"]
    assert isinstance(data["list_price_cents"], int)


def assert_buyback_offer(data: dict):
    _assert_common(data)
    assert data["status"] in ["PENDING", "AUTO_APPROVED", "ACCEPTED", "VOIDED"]
    assert isinstance(data["offer_value_cents"], int)
    assert isinstance(data["auto_approved"], bool)


def assert_fair_event(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str)
    assert isinstance(data["table_capacity"], int)
    assert isinstance(data["reserved_display_count"], int)


def assert_booth_slot(data: dict):
    _assert_common(data)
    assert data["status"] == "RESERVED"
    assert isinstance(data["booth_table"], str)


def assert_sale_order(data: dict):
    _assert_common(data)
    assert data["channel"] in ["ONLINE", "SHOP"]
    assert data["status"] in ["DRAFT", "CONFIRMED", "REFUNDED"]
    assert isinstance(data["subtotal_cents"], int)
    assert isinstance(data["total_cents"], int)
    assert data["total_cents"] >= 0, "total_cents is floored at 0"


def assert_shipment(data: dict):
    _assert_common(data)
    assert data["status"] == "PACKED"
    assert isinstance(data["shipping_cost_cents"], int)
    assert data["zone"] in [1, 2, 3, 4]
