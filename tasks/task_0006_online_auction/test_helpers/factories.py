"""Payload factories — one per entity, input fields only."""
import uuid
from .types import LotCategory, LotCondition, DisputeFiledBy, DisputeOutcome


def _unique_serial(prefix: str = "SN") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12].upper()}"


def create_seller_payload(**overrides) -> dict:
    defaults = {"display_name": "Acme Auction House"}
    defaults.update(overrides)
    return defaults


def create_bidder_payload(**overrides) -> dict:
    defaults = {"display_name": "BidderOne"}
    defaults.update(overrides)
    return defaults


def credit_wallet_payload(amount_cents: int = 1_000_000) -> dict:
    return {"amount_cents": amount_cents}


def create_lot_payload(
    seller_id: str,
    *,
    title: str = "Test Lot",
    category: str = LotCategory.ART.value,
    condition: str = LotCondition.NEW.value,
    physical_item_serial: str = None,
    reserve_price_cents: int = 100_000,
    starting_bid_cents: int = 50_000,
    scheduled_start_at: str = "2030-01-01T00:00:00.000Z",
    scheduled_end_at: str = "2030-01-01T02:00:00.000Z",
    **overrides,
) -> dict:
    defaults = {
        "seller_id": seller_id,
        "title": title,
        "category": category,
        "condition": condition,
        "physical_item_serial": physical_item_serial or _unique_serial(),
        "reserve_price_cents": reserve_price_cents,
        "starting_bid_cents": starting_bid_cents,
        "scheduled_start_at": scheduled_start_at,
        "scheduled_end_at": scheduled_end_at,
    }
    defaults.update(overrides)
    return defaults


def place_bid_payload(amount_cents: int) -> dict:
    return {"amount_cents": amount_cents}


def create_proxy_payload(max_amount_cents: int) -> dict:
    return {"max_amount_cents": max_amount_cents}


def file_dispute_payload(
    *,
    filed_by: str = DisputeFiledBy.BIDDER.value,
    reason: str = "Item not as described",
    evidence: list = None,
    claimed_refund_amount_cents: int = 10_000,
    **overrides,
) -> dict:
    defaults = {
        "filed_by": filed_by,
        "reason": reason,
        "evidence": evidence if evidence is not None else [{"url": "https://example.com/photo.jpg", "kind": "photo"}],
        "claimed_refund_amount_cents": claimed_refund_amount_cents,
    }
    defaults.update(overrides)
    return defaults


def resolve_dispute_payload(outcome: str, *, resolution_refund_amount_cents: int = None, **overrides) -> dict:
    payload = {"outcome": outcome}
    if outcome == DisputeOutcome.REFUND.value:
        if resolution_refund_amount_cents is None:
            resolution_refund_amount_cents = 10_000
        payload["resolution_refund_amount_cents"] = resolution_refund_amount_cents
    elif resolution_refund_amount_cents is not None:
        # only include when caller explicitly passes one (used by negative tests)
        payload["resolution_refund_amount_cents"] = resolution_refund_amount_cents
    payload.update(overrides)
    return payload


def advance_clock_payload(seconds: int) -> dict:
    return {"seconds": seconds}


def event_payment_confirmed_payload(invoice_id: str, paid_at: str) -> dict:
    return {"invoice_id": invoice_id, "paid_at": paid_at}


def event_identity_verified_payload(bidder_id: str, verified_at: str = "2030-01-01T00:00:00.000Z") -> dict:
    return {"bidder_id": bidder_id, "verified_at": verified_at}


def event_logistics_delivered_payload(lot_id: str, delivered_at: str = "2030-01-15T00:00:00.000Z") -> dict:
    return {"lot_id": lot_id, "delivered_at": delivered_at}


def event_account_takeover_payload(bidder_id: str) -> dict:
    return {"bidder_id": bidder_id}


def unique_serial(prefix: str = "SN") -> str:
    return _unique_serial(prefix)
