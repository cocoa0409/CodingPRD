"""Entity assertions and domain invariant checkers.

Each assert_{entity} validates the response shape against the PRD contract using
the framework's generic format checkers. Invariant checkers enforce the ledger
conservation rules described in PRD §2.8.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

_ITEM_STATES = {"INTAKE_REQUESTED", "RECEIVED", "AUTHENTICATED", "REJECTED", "LISTED", "SOLD", "DISPOSED"}
_LISTING_STATES = {"DRAFT", "ACTIVE", "SOLD"}
_OFFER_STATES = {"PENDING", "COUNTERED", "ACCEPTED", "DECLINED", "EXPIRED"}
_PAYMENT_STATES = {"PENDING", "CAPTURED", "REFUNDED"}
_FULFILLMENT_STATES = {"AWAITING_SHIPMENT", "SHIPPED", "DELIVERED", "RETURNED"}
_PAYOUT_STATES = {"SCHEDULED", "HELD", "RELEASED", "REVERSED"}
_DISPUTE_STATES = {"FILED", "RESOLVED_BUYER", "RESOLVED_SELLER"}


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_seller(data: dict):
    _assert_common(data)
    assert data["status"] == "ACTIVE"
    assert data["tier"] in {"STANDARD", "PREMIER", "ELITE"}
    for f in ("lifetime_net_sales_cents", "pending_payout_cents", "released_payout_cents",
              "reversed_payout_cents", "payout_balance_cents"):
        assert isinstance(data[f], int), f"{f} must be an integer number of cents"


def assert_buyer(data: dict):
    _assert_common(data)
    assert data["status"] == "ACTIVE"
    assert isinstance(data["lifetime_purchases_cents"], int)


def assert_category_policy(data: dict):
    _assert_common(data)
    assert data["category"] in {"HANDBAGS", "WATCHES", "JEWELRY", "APPAREL", "SHOES"}
    assert isinstance(data["buyer_fee_flat_cents"], int)
    assert isinstance(data["return_window_days"], int)
    assert data["listable_min_condition_grade"] in {"A", "B", "C", "D"}


def assert_item(data: dict):
    _assert_common(data)
    assert data["status"] in _ITEM_STATES
    assert data["intake_channel"] in {"DROP_OFF", "PICKUP"}
    assert isinstance(data["declared_value_cents"], int)
    assert isinstance(data.get("listable"), bool)


def assert_listing(data: dict):
    _assert_common(data)
    assert data["status"] in _LISTING_STATES
    assert isinstance(data["list_price_cents"], int)


def assert_offer(data: dict):
    _assert_common(data)
    assert data["status"] in _OFFER_STATES
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["round_number"], int)


def assert_sale(data: dict):
    _assert_common(data)
    assert data["sale_channel"] in {"DIRECT", "OFFER"}
    assert data["payment_status"] in _PAYMENT_STATES
    assert data["fulfillment_status"] in _FULFILLMENT_STATES
    for f in ("sale_price_cents", "commission_cents", "seller_net_payout_cents",
              "buyer_fee_cents", "tax_cents", "order_total_cents"):
        assert isinstance(data[f], int), f"{f} must be an integer number of cents"


def assert_payout(data: dict):
    _assert_common(data)
    assert data["status"] in _PAYOUT_STATES
    assert isinstance(data["amount_cents"], int)


def assert_dispute(data: dict):
    _assert_common(data)
    assert data["status"] in _DISPUTE_STATES
    assert data["type"] in {"AUTHENTICITY", "CONDITION", "CHANGE_OF_MIND"}


def assert_pickup(data: dict):
    _assert_common(data)
    assert data["status"] in {"SCHEDULED", "COMPLETED"}


def assert_seller_ledger_balance(seller: dict):
    """PRD §2.8: payout_balance_cents == pending_payout_cents + released_payout_cents."""
    assert seller["payout_balance_cents"] == seller["pending_payout_cents"] + seller["released_payout_cents"], (
        "payout_balance_cents must equal pending + released "
        f"(got balance={seller['payout_balance_cents']}, pending={seller['pending_payout_cents']}, "
        f"released={seller['released_payout_cents']})"
    )


def assert_payout_ledger_conserved(seller: dict, expected_total: int):
    """PRD §2.8: pending + released + reversed is conserved and equals the sum of all
    this seller's payout amounts (Q_payout)."""
    q = seller["pending_payout_cents"] + seller["released_payout_cents"] + seller["reversed_payout_cents"]
    assert q == expected_total, (
        f"Q_payout (pending+released+reversed) must be conserved at {expected_total}, got {q}"
    )
