"""Payload factories — one per creatable entity, input fields only."""

DEFAULTS = {
    "AUCTION_STARTS_AT": "2026-03-02T10:00:00Z",
    "AUCTION_ENDS_AT": "2026-03-20T10:00:00Z",
    "IMAGE_URL": "http://img/default.jpg",
}


def create_estate_payload(**overrides) -> dict:
    """POST /estates. commission_bps/buyer_premium_bps/soft_close_seconds
    are optional (server defaults apply)."""
    payload = {
        "seller_name": "Test Seller",
        "seller_email": "seller@example.com",
        "auction_starts_at": DEFAULTS["AUCTION_STARTS_AT"],
        "auction_ends_at": DEFAULTS["AUCTION_ENDS_AT"],
    }
    payload.update(overrides)
    return payload


def create_lot_payload(estate_id, **overrides) -> dict:
    """POST /lots. reserve_cents is optional."""
    payload = {
        "estate_id": estate_id,
        "title": "Test Lot",
        "description": "A description of the lot's condition.",
        "category": "misc",
        "condition_grade": "B",
        "starting_bid_cents": 10000,
    }
    payload.update(overrides)
    return payload


def create_photo_payload(lot_id, **overrides) -> dict:
    """POST /photos. caption/condition_note/is_primary are optional."""
    payload = {
        "lot_id": lot_id,
        "image_url": DEFAULTS["IMAGE_URL"],
    }
    payload.update(overrides)
    return payload


def create_buyer_payload(**overrides) -> dict:
    """POST /buyers."""
    payload = {
        "display_name": "Test Buyer",
        "email": "buyer@example.com",
    }
    payload.update(overrides)
    return payload


def create_bid_payload(lot_id, buyer_id, amount_cents, expected_lot_version,
                       **overrides) -> dict:
    """POST /bids. All four fields are required."""
    payload = {
        "lot_id": lot_id,
        "buyer_id": buyer_id,
        "amount_cents": amount_cents,
        "expected_lot_version": expected_lot_version,
    }
    payload.update(overrides)
    return payload


def create_pickup_window_payload(estate_id, starts_at, ends_at, capacity,
                                 **overrides) -> dict:
    """POST /pickup-windows. label is optional."""
    payload = {
        "estate_id": estate_id,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "capacity": capacity,
    }
    payload.update(overrides)
    return payload


def create_dispute_payload(order_id, lot_id, reason="item not as described",
                           **overrides) -> dict:
    """POST /disputes."""
    payload = {
        "order_id": order_id,
        "lot_id": lot_id,
        "reason": reason,
    }
    payload.update(overrides)
    return payload
