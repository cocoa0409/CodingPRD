"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
)

SELLER_STATUSES = ["ACTIVE", "FLAGGED", "BANNED"]
COMMODITY_STATUSES = ["ACTIVE", "SUPERSEDED"]
TICKET_STATUSES = ["DRAFT", "WEIGHED", "HOLD", "RELEASED", "REPORTED", "PAID"]
PAYOUT_STATUSES = ["PENDING", "SETTLED", "VOID"]
CONTAINER_STATUSES = ["STAGED", "DISPATCHED", "CLOSED"]
SHIPMENT_STATUSES = ["SHIPPED", "SETTLED"]
HEDGE_STATUSES = ["OPEN", "CLOSED"]
REPORT_STATUSES = ["OPEN", "CLEARED"]
CATEGORIES = ["FERROUS", "NON_FERROUS"]


def _assert_common_mutable(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID with no prefix"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        "version must be an int >= 1"


def assert_seller(data: dict):
    _assert_common_mutable(data)
    assert isinstance(data["legal_name"], str) and len(data["legal_name"]) > 0
    assert data["id_type"] in ["DRIVERS_LICENSE", "STATE_ID", "PASSPORT"]
    assert isinstance(data["id_number"], str)
    assert data["status"] in SELLER_STATUSES
    assert isinstance(data["ytd_cash_paid_cents"], int) and data["ytd_cash_paid_cents"] >= 0
    assert isinstance(data["requires_1099"], bool)
    assert isinstance(data["open_theft_reports"], int) and data["open_theft_reports"] >= 0


def assert_commodity_price(data: dict):
    _assert_common_mutable(data)
    assert isinstance(data["grade_code"], str) and len(data["grade_code"]) > 0
    assert data["category"] in CATEGORIES
    assert isinstance(data["spot_price_cents_per_lb"], int) and data["spot_price_cents_per_lb"] >= 0
    assert isinstance(data["mill_price_cents_per_lb"], int) and data["mill_price_cents_per_lb"] >= 0
    assert data["status"] in COMMODITY_STATUSES


def assert_ticket(data: dict):
    _assert_common_mutable(data)
    assert is_valid_uuid(data.get("seller_id", "")), "seller_id must be a valid UUID"
    assert data["status"] in TICKET_STATUSES
    assert isinstance(data["gross_weight_lb"], (int, float)) and data["gross_weight_lb"] > 0
    assert isinstance(data["gross_valuation_cents"], int) and data["gross_valuation_cents"] >= 0


def assert_line_item(data: dict):
    """TicketLineItem is append-only: id + created_at only, no version/updated_at."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data.get("ticket_id", "")), "ticket_id must be a valid UUID"
    assert isinstance(data["grade_code"], str) and len(data["grade_code"]) > 0
    assert is_valid_uuid(data.get("commodity_price_id", "")), "commodity_price_id must be a valid UUID"
    assert isinstance(data["weight_lb"], (int, float)) and data["weight_lb"] > 0
    assert isinstance(data["line_valuation_cents"], int) and data["line_valuation_cents"] >= 0


def assert_payout(data: dict):
    _assert_common_mutable(data)
    assert is_valid_uuid(data.get("ticket_id", "")), "ticket_id must be a valid UUID"
    assert is_valid_uuid(data.get("seller_id", "")), "seller_id must be a valid UUID"
    assert data["method"] in ["CASH", "CHECK"]
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0
    assert isinstance(data["form_1099_issued"], bool)
    assert data["status"] in PAYOUT_STATUSES


def assert_container(data: dict):
    _assert_common_mutable(data)
    assert data["category"] in CATEGORIES
    assert isinstance(data["capacity_lb"], (int, float)) and data["capacity_lb"] > 0
    assert isinstance(data["loaded_weight_lb"], (int, float)) and data["loaded_weight_lb"] >= 0
    assert data["status"] in CONTAINER_STATUSES


def assert_mill_shipment(data: dict):
    _assert_common_mutable(data)
    assert is_valid_uuid(data.get("container_id", "")), "container_id must be a valid UUID"
    assert data["category"] in CATEGORIES
    assert isinstance(data["shipped_weight_lb"], (int, float)) and data["shipped_weight_lb"] >= 0
    assert isinstance(data["expected_settlement_cents"], int)
    assert data["status"] in SHIPMENT_STATUSES


def assert_hedge(data: dict):
    _assert_common_mutable(data)
    assert data["category"] in CATEGORIES
    assert isinstance(data["hedged_weight_lb"], (int, float)) and data["hedged_weight_lb"] > 0
    assert isinstance(data["locked_price_cents_per_lb"], int) and data["locked_price_cents_per_lb"] >= 0
    assert isinstance(data["realized_weight_lb"], (int, float)) and data["realized_weight_lb"] >= 0
    assert isinstance(data["realized_pnl_cents"], int)
    assert data["status"] in HEDGE_STATUSES


def assert_theft_report(data: dict):
    _assert_common_mutable(data)
    assert is_valid_uuid(data.get("seller_id", "")), "seller_id must be a valid UUID"
    assert isinstance(data["reason"], str)
    assert data["status"] in REPORT_STATUSES


# ---------------------------------------------------------------------------
# Domain invariant checkers
# ---------------------------------------------------------------------------
def assert_hedge_invariants(data: dict):
    """realized_weight_lb may never exceed hedged_weight_lb (PRD §3.7/§3.8)."""
    assert data["realized_weight_lb"] <= data["hedged_weight_lb"], \
        "realized_weight_lb must never exceed hedged_weight_lb"


def assert_container_invariants(data: dict):
    """loaded_weight_lb may never exceed capacity_lb (PRD §3.4/§3.6)."""
    assert data["loaded_weight_lb"] <= data["capacity_lb"], \
        "loaded_weight_lb must never exceed capacity_lb"
