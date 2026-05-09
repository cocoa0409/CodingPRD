"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_seller(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"Seller.id must be valid UUID, got {data.get('id')!r}"
    assert isinstance(data.get("display_name"), str) and 1 <= len(data["display_name"]) <= 80
    assert data.get("status") in ("ACTIVE", "SUSPENDED"), f"Seller.status: {data.get('status')!r}"
    assert isinstance(data.get("total_lots_listed"), int) and data["total_lots_listed"] >= 0
    assert isinstance(data.get("gross_proceeds_cents"), int)
    assert isinstance(data.get("net_proceeds_cents"), int)
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data.get("version"), int) and data["version"] >= 1


def assert_bidder(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"Bidder.id must be valid UUID, got {data.get('id')!r}"
    assert isinstance(data.get("display_name"), str)
    assert isinstance(data.get("identity_verified"), bool)
    assert isinstance(data.get("wallet_balance_cents"), int) and data["wallet_balance_cents"] >= 0
    assert isinstance(data.get("held_deposit_cents"), int) and data["held_deposit_cents"] >= 0
    assert data.get("status") in ("ACTIVE", "RESTRICTED", "SUSPENDED")
    assert isinstance(data.get("risk_score"), (int, float))
    assert 0 <= data["risk_score"] <= 100
    assert isinstance(data.get("withdrawal_count"), int) and data["withdrawal_count"] >= 0
    assert isinstance(data.get("dispute_loss_count"), int) and data["dispute_loss_count"] >= 0
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data.get("version"), int) and data["version"] >= 1


def assert_lot(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert is_valid_uuid(data.get("seller_id", ""))
    assert isinstance(data.get("title"), str) and 1 <= len(data["title"]) <= 200
    assert data.get("category") in ("ART", "COLLECTIBLE", "ELECTRONICS", "JEWELRY", "REAL_ESTATE", "VEHICLE")
    assert data.get("condition") in ("NEW", "LIKE_NEW", "USED_GOOD", "USED_FAIR", "FOR_PARTS")
    assert isinstance(data.get("physical_item_serial"), str)
    assert isinstance(data.get("reserve_price_cents"), int) and data["reserve_price_cents"] >= 1
    assert isinstance(data.get("starting_bid_cents"), int) and data["starting_bid_cents"] >= 1
    assert data.get("status") in (
        "DRAFT", "SCHEDULED", "LIVE", "SOLD", "UNSOLD", "REOFFERED",
        "DEFAULTED", "DISPUTED", "REFUNDED", "RELISTED", "CANCELLED",
    )
    assert isinstance(data.get("current_price_cents"), int)
    assert isinstance(data.get("bid_count"), int) and data["bid_count"] >= 0
    assert isinstance(data.get("has_met_reserve"), bool)
    assert isinstance(data.get("extension_count"), int) and data["extension_count"] >= 0
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data.get("version"), int) and data["version"] >= 1


def assert_bid(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert is_valid_uuid(data.get("lot_id", ""))
    assert is_valid_uuid(data.get("bidder_id", ""))
    assert isinstance(data.get("amount_cents"), int) and data["amount_cents"] >= 1
    assert data.get("source") in ("MANUAL", "PROXY")
    assert data.get("status") in ("ACTIVE", "WINNING", "OUTBID", "WITHDRAWN_BY_RISK")
    assert is_iso8601_timestamp(data.get("placed_at", ""))
    assert isinstance(data.get("triggered_extension"), bool)
    assert is_iso8601_timestamp(data.get("created_at", ""))


def assert_auto_bid_proxy(data: dict, *, owner_view: bool = True):
    assert is_valid_uuid(data.get("id", ""))
    assert is_valid_uuid(data.get("lot_id", ""))
    assert is_valid_uuid(data.get("bidder_id", ""))
    if owner_view:
        assert isinstance(data.get("max_amount_cents"), int) and data["max_amount_cents"] >= 1
    assert data.get("status") in ("ACTIVE", "EXHAUSTED", "CANCELLED")
    assert isinstance(data.get("bids_emitted_count"), int) and data["bids_emitted_count"] >= 0
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data.get("version"), int) and data["version"] >= 1


def assert_invoice(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert is_valid_uuid(data.get("lot_id", ""))
    assert is_valid_uuid(data.get("buyer_id", ""))
    assert is_valid_uuid(data.get("seller_id", ""))
    assert isinstance(data.get("hammer_price_cents"), int)
    assert isinstance(data.get("buyer_premium_cents"), int)
    assert isinstance(data.get("seller_commission_cents"), int)
    assert isinstance(data.get("buyer_total_cents"), int)
    assert isinstance(data.get("seller_payout_cents"), int)
    assert isinstance(data.get("platform_take_cents"), int)
    assert data.get("status") in ("PENDING", "ISSUED", "PAID", "REVERSED")
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data.get("version"), int) and data["version"] >= 1


def assert_dispute(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert is_valid_uuid(data.get("lot_id", ""))
    assert is_valid_uuid(data.get("invoice_id", ""))
    assert data.get("filed_by") in ("BIDDER", "SELLER")
    assert isinstance(data.get("reason"), str) and 1 <= len(data["reason"]) <= 500
    assert isinstance(data.get("evidence"), list)
    assert isinstance(data.get("claimed_refund_amount_cents"), int)
    assert data.get("status") in ("FILED", "UNDER_REVIEW", "RESOLVED_REFUND", "RESOLVED_RELIST", "RESOLVED_DENIED")
    assert is_iso8601_timestamp(data.get("filed_at", ""))
    assert is_iso8601_timestamp(data.get("created_at", ""))


def assert_deposit(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert is_valid_uuid(data.get("bidder_id", ""))
    assert is_valid_uuid(data.get("lot_id", ""))
    assert isinstance(data.get("amount_cents"), int) and data["amount_cents"] >= 1
    assert data.get("status") in ("HELD", "RELEASED", "FORFEITED", "PARTIAL_REFUND")
    assert isinstance(data.get("refund_amount_cents"), int) and data["refund_amount_cents"] >= 0
    assert isinstance(data.get("forfeit_amount_cents"), int) and data["forfeit_amount_cents"] >= 0
    if data["status"] != "HELD":
        assert data.get("terminal_reason") in (
            "LOSING_BIDDER", "WINNER_PAID",
            "WINNER_DEFAULT_REOFFER_FILLED", "WINNER_DEFAULT_NO_REOFFER",
            "BIDDER_RISK_WITHDRAWN", "DISPUTE_REFUND",
        )
    assert is_iso8601_timestamp(data.get("created_at", ""))


def assert_invoice_money_invariants(invoice: dict):
    """buyer_total = hammer + buyer_premium; seller_payout = hammer - seller_commission;
    platform_take = buyer_premium + seller_commission."""
    assert invoice["buyer_total_cents"] == invoice["hammer_price_cents"] + invoice["buyer_premium_cents"], (
        f"buyer_total_cents must equal hammer + buyer_premium: "
        f"{invoice['buyer_total_cents']} vs {invoice['hammer_price_cents']} + {invoice['buyer_premium_cents']}"
    )
    assert invoice["seller_payout_cents"] == invoice["hammer_price_cents"] - invoice["seller_commission_cents"], (
        f"seller_payout_cents must equal hammer - seller_commission"
    )
    assert invoice["platform_take_cents"] == invoice["buyer_premium_cents"] + invoice["seller_commission_cents"]


def assert_error_envelope(response, expected_error_id: str, expected_status: int = None):
    """Assertion for tests where we want to check the envelope manually."""
    if expected_status is not None:
        assert response.status_code == expected_status, (
            f"Expected status {expected_status}, got {response.status_code}: {response.text}"
        )
    body = response.json()
    assert body.get("response_type") == "error", f"response_type must be 'error': {body}"
    assert body["data"].get("error_id") == expected_error_id, (
        f"Expected error_id={expected_error_id}, got {body['data'].get('error_id')!r}"
    )
