"""Payload factories — one per entity, input fields only (Auction House PRD §3)."""


def create_saleroom_payload(**overrides) -> dict:
    defaults = {"name": "Main", "location": "NYC", "capacity": 100}
    defaults.update(overrides)
    return defaults


def create_consignor_payload(**overrides) -> dict:
    # payout_method is optional (defaults to CHECK server-side, PRD §3.1).
    defaults = {"display_name": "Estate A", "email": "a@x.com"}
    defaults.update(overrides)
    return defaults


def create_bidder_payload(**overrides) -> dict:
    # deposit_cents is optional (defaults to 0 server-side, PRD §3.1).
    defaults = {
        "display_name": "Buyer",
        "email": "b@x.com",
        "paddle_number": "P1",
        "deposit_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def create_auction_payload(saleroom_id, **overrides) -> dict:
    defaults = {
        "title": "Spring",
        "sale_type": "LIVE",
        "saleroom_id": saleroom_id,
        "scheduled_start": "2026-06-10T10:00:00Z",
        "scheduled_end": "2026-06-10T18:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_consignment_payload(consignor_id, **overrides) -> dict:
    defaults = {
        "consignor_id": consignor_id,
        "commission_rate": 0.15,
        "estimate_low_cents": 100_000,
        "estimate_high_cents": 200_000,
        "intake_window_start": "2026-05-02T09:00:00Z",
        "intake_window_end": "2026-05-02T10:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_lot_payload(consignment_id, auction_id, **overrides) -> dict:
    defaults = {
        "consignment_id": consignment_id,
        "auction_id": auction_id,
        "title": "Vase",
        "category": "ART",
        "reserve_cents": 0,
        "starting_bid_cents": 100_000,
        "estimate_low_cents": 100_000,
        "estimate_high_cents": 200_000,
        "lot_number": 1,
    }
    defaults.update(overrides)
    return defaults


def create_bid_payload(bidder_id, amount_cents, expected_lot_version, **overrides) -> dict:
    defaults = {
        "bidder_id": bidder_id,
        "bid_type": "LIVE",
        "amount_cents": amount_cents,
        "expected_lot_version": expected_lot_version,
    }
    defaults.update(overrides)
    return defaults


def create_dispute_payload(invoice_line_id, **overrides) -> dict:
    defaults = {"invoice_line_id": invoice_line_id, "reason": "Authenticity challenged"}
    defaults.update(overrides)
    return defaults
