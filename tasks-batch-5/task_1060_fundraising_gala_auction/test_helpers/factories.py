"""Payload factories — one per entity, input fields only."""
from .constants import TEST_DEFAULTS


def create_event_payload(**overrides) -> dict:
    payload = {
        "name": TEST_DEFAULTS["EVENT_NAME"],
        "event_start_utc": TEST_DEFAULTS["EVENT_START_UTC"],
        "event_end_utc": TEST_DEFAULTS["EVENT_END_UTC"],
    }
    payload.update(overrides)
    return payload


def create_table_payload(**overrides) -> dict:
    payload = {
        "table_name": TEST_DEFAULTS["TABLE_NAME"],
        "seat_count": TEST_DEFAULTS["TABLE_SEAT_COUNT"],
        "table_price_cents": TEST_DEFAULTS["TABLE_PRICE_CENTS"],
        "seat_price_cents": TEST_DEFAULTS["SEAT_PRICE_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_table_hold_payload(table_id, bidder_id, **overrides) -> dict:
    payload = {
        "table_id": table_id,
        "bidder_id": bidder_id,
        "hold_start_utc": "2026-07-05T18:00:00Z",
        "hold_end_utc": "2026-07-05T20:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_bidder_payload(event_id, **overrides) -> dict:
    payload = {
        "event_id": event_id,
        "display_name": "Ada Lovelace",
        "email": "ada@example.org",
        "paddle_number": 101,
    }
    payload.update(overrides)
    return payload


def create_sponsor_payload(event_id, **overrides) -> dict:
    payload = {
        "event_id": event_id,
        "org_name": "Acme Foundry",
        "tier": "GOLD",
        "commitment_cents": TEST_DEFAULTS["SPONSOR_COMMITMENT_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_program_ad_payload(sponsor_id, event_id, **overrides) -> dict:
    payload = {
        "sponsor_id": sponsor_id,
        "event_id": event_id,
        "ad_size": "FULL_PAGE",
        "artwork_ref": "art-v1",
    }
    payload.update(overrides)
    return payload


def create_ticket_order_payload(event_id, bidder_id, table_id, **overrides) -> dict:
    payload = {
        "event_id": event_id,
        "bidder_id": bidder_id,
        "table_id": table_id,
        "order_type": "SEAT",
        "seat_count": 3,
    }
    payload.update(overrides)
    return payload


def create_auction_item_payload(event_id, **overrides) -> dict:
    payload = {
        "event_id": event_id,
        "title": "Napa Weekend",
        "item_type": "SILENT",
        "starting_bid_cents": TEST_DEFAULTS["STARTING_BID_CENTS"],
        "min_increment_cents": TEST_DEFAULTS["MIN_INCREMENT_CENTS"],
        "estimated_fmv_cents": TEST_DEFAULTS["ESTIMATED_FMV_CENTS"],
        "open_at_utc": TEST_DEFAULTS["LOT_OPEN_AT_UTC"],
        "close_at_utc": TEST_DEFAULTS["LOT_CLOSE_AT_UTC"],
    }
    payload.update(overrides)
    return payload


def create_bid_payload(bidder_id, amount_cents, **overrides) -> dict:
    payload = {"bidder_id": bidder_id, "amount_cents": amount_cents}
    payload.update(overrides)
    return payload


def create_paddle_raise_payload(event_id, bidder_id, level_cents, **overrides) -> dict:
    payload = {
        "event_id": event_id,
        "bidder_id": bidder_id,
        "level_cents": level_cents,
    }
    payload.update(overrides)
    return payload


def create_pledge_payload(event_id, bidder_id, **overrides) -> dict:
    payload = {
        "event_id": event_id,
        "bidder_id": bidder_id,
        "total_amount_cents": 300_000,
        "installment_count": 3,
        "first_due_utc": "2026-10-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_invoice_payload(event_id, bidder_id, **overrides) -> dict:
    payload = {"event_id": event_id, "bidder_id": bidder_id}
    payload.update(overrides)
    return payload


def create_payment_payload(invoice_id, amount_cents, **overrides) -> dict:
    payload = {
        "invoice_id": invoice_id,
        "amount_cents": amount_cents,
        "method": "CARD",
    }
    payload.update(overrides)
    return payload


def create_reconciliation_run_payload(expected_event_version, **overrides) -> dict:
    payload = {
        "expected_event_version": expected_event_version,
        "revenue_basis": "BOOKED",
    }
    payload.update(overrides)
    return payload
