"""Payload factories — one per entity, input fields only (PRD §3 / §4)."""
import itertools

_email_counter = itertools.count(1)


def unique_email(prefix: str = "patron") -> str:
    """Generate a per-process-unique email so multi-patron setups avoid collisions."""
    return f"{prefix}.{next(_email_counter)}@bookstore.test"


def create_patron_payload(**overrides) -> dict:
    payload = {
        "display_name": "Test Patron",
        "email": unique_email(),
    }
    payload.update(overrides)
    return payload


def create_intake_lot_payload(**overrides) -> dict:
    payload = {
        "acquisition_channel": "PURCHASE",
    }
    payload.update(overrides)
    return payload


def create_book_item_payload(**overrides) -> dict:
    payload = {
        "title": "Test Book",
        "author": "Test Author",
        "comp_median_cents": 10000,
    }
    payload.update(overrides)
    return payload


def create_appraisal_payload(expected_book_item_version, **overrides) -> dict:
    payload = {
        "basis": "FAIR_MARKET",
        "expected_book_item_version": expected_book_item_version,
    }
    payload.update(overrides)
    return payload


def create_listing_payload(**overrides) -> dict:
    payload = {
        "list_price_cents": 10000,
    }
    payload.update(overrides)
    return payload


def create_consignment_agreement_payload(patron_id, book_item_id, **overrides) -> dict:
    payload = {
        "patron_id": patron_id,
        "book_item_id": book_item_id,
        "commission_pct": 0.30,
    }
    payload.update(overrides)
    return payload


def create_buyback_offer_payload(patron_id, offer_value_cents, **overrides) -> dict:
    payload = {
        "patron_id": patron_id,
        "offer_value_cents": offer_value_cents,
    }
    payload.update(overrides)
    return payload


def create_fair_event_payload(**overrides) -> dict:
    payload = {
        "name": "Test Fair",
        "table_capacity": 10,
    }
    payload.update(overrides)
    return payload


def create_booth_slot_payload(booth_table, window_start, window_end, **overrides) -> dict:
    payload = {
        "booth_table": booth_table,
        "window_start": window_start,
        "window_end": window_end,
    }
    payload.update(overrides)
    return payload


def create_sale_order_payload(channel, line_items, **overrides) -> dict:
    payload = {
        "channel": channel,
        "line_items": line_items,
    }
    payload.update(overrides)
    return payload


def line_item(book_item_id, sale_price_cents, discount_pct=0) -> dict:
    return {
        "book_item_id": book_item_id,
        "sale_price_cents": sale_price_cents,
        "discount_pct": discount_pct,
    }


def create_shipment_payload(packing_station_label, weight_grams, zone,
                            pack_start, pack_end, **overrides) -> dict:
    payload = {
        "packing_station_label": packing_station_label,
        "weight_grams": weight_grams,
        "zone": zone,
        "pack_start": pack_start,
        "pack_end": pack_end,
    }
    payload.update(overrides)
    return payload
