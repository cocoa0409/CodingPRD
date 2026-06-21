"""Entity assertions and domain invariant checkers for the Art Auction
Consignment API. Generic UUID / timestamp validators come from the framework.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_seller(data: dict):
    _assert_common(data)
    assert isinstance(data["legal_name"], str) and len(data["legal_name"]) > 0
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["country_code"], str) and len(data["country_code"]) > 0


def assert_bidder(data: dict):
    _assert_common(data)
    assert isinstance(data["legal_name"], str) and len(data["legal_name"]) > 0
    assert isinstance(data["credit_limit_cents"], int)
    assert isinstance(data["outstanding_balance_cents"], int)
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_auction_sale(data: dict):
    _assert_common(data)
    assert data["status"] in ("CATALOGING", "PUBLISHED", "LIVE", "CLOSED")
    assert isinstance(data["lot_count"], int) and data["lot_count"] >= 0
    assert isinstance(data["currency"], str) and len(data["currency"]) > 0


def assert_premium_schedule(data: dict):
    """A PremiumSchedule is immutable: it carries id + created_at only (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "PremiumSchedule is immutable and must not carry a version field"
    assert "updated_at" not in data, "PremiumSchedule must not carry an updated_at field"
    assert isinstance(data["tiers"], list) and len(data["tiers"]) >= 1


def assert_consignment(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "ACTIVE", "TERMINATED")
    assert isinstance(data["seller_commission_bps"], int)
    assert isinstance(data["lot_count"], int) and data["lot_count"] >= 0


def assert_lot(data: dict):
    _assert_common(data)
    assert data["sale_status"] in ("CATALOGED", "OPEN", "SOLD", "BOUGHT_IN", "WITHDRAWN")
    assert data["settlement_status"] in ("NONE", "INVOICED", "STATEMENTED", "SETTLED")
    assert isinstance(data["lot_number"], int)
    assert isinstance(data["hammer_price_cents"], int) and data["hammer_price_cents"] >= 0
    assert isinstance(data["artist_alive"], bool)


def assert_paddle_registration(data: dict):
    _assert_common(data)
    assert data["registration_type"] in ("FLOOR", "ABSENTEE", "PHONE")
    assert data["status"] in ("ACTIVE", "REVOKED")
    assert isinstance(data["paddle_number"], int) and data["paddle_number"] >= 1


def assert_bid(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACCEPTED", "RETRACTED", "WINNING")
    assert data["bid_channel"] in ("FLOOR", "ABSENTEE", "PHONE")
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0


def assert_invoice(data: dict):
    _assert_common(data)
    assert data["status"] in ("ISSUED", "PAID", "VOID")
    assert isinstance(data["hammer_price_cents"], int)
    assert isinstance(data["buyers_premium_cents"], int)
    assert isinstance(data["total_due_cents"], int)
    assert isinstance(data["amount_paid_cents"], int)


def assert_resale_royalty(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACCRUED", "REMITTED", "REVERSED")
    assert data["bearer"] == "SELLER"
    assert isinstance(data["royalty_cents"], int) and data["royalty_cents"] >= 0


def assert_seller_statement(data: dict):
    _assert_common(data)
    assert data["status"] in ("PENDING", "PAID", "REVERSED")
    assert isinstance(data["seller_commission_cents"], int)
    assert isinstance(data["resale_royalty_withheld_cents"], int)
    assert isinstance(data["net_payable_cents"], int)


def assert_payout(data: dict):
    _assert_common(data)
    assert data["status"] == "DISBURSED"
    assert isinstance(data["amount_cents"], int)


def assert_seller_statement_decomposition(data: dict):
    """Hammer is conserved across the seller-side split (PRD §3.8):
    net_payable == hammer - commission - royalty_withheld, and never negative."""
    h = data["hammer_price_cents"]
    comm = data["seller_commission_cents"]
    roy = data["resale_royalty_withheld_cents"]
    net = data["net_payable_cents"]
    assert net == h - comm - roy, (
        f"net_payable_cents {net} must equal hammer {h} - commission {comm} - royalty {roy}"
    )
    assert net >= 0, f"net_payable_cents must never be negative, got {net}"
