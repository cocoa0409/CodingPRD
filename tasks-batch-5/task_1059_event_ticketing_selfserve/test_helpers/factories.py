"""Payload factories — one per creatable resource, input fields only."""
import itertools

_counter = itertools.count(1)


def unique_suffix() -> str:
    """Monotonic suffix so repeated factory calls inside one test stay distinct."""
    return str(next(_counter))


def create_organizer_payload(**overrides) -> dict:
    n = unique_suffix()
    payload = {
        "display_name": f"Test Promoter {n}",
        "contact_email": f"ops{n}@promoter.example",
    }
    payload.update(overrides)
    return payload


def create_venue_payload(**overrides) -> dict:
    n = unique_suffix()
    payload = {
        "name": f"Test Hall {n}",
        "city": "Portland",
        "seated_capacity": 200,
    }
    payload.update(overrides)
    return payload


def create_buyer_payload(**overrides) -> dict:
    n = unique_suffix()
    payload = {
        "email": f"buyer{n}@example.com",
        "display_name": f"Test Buyer {n}",
    }
    payload.update(overrides)
    return payload


def create_event_payload(organizer_id: str, venue_id: str, **overrides) -> dict:
    payload = {
        "organizer_id": organizer_id,
        "venue_id": venue_id,
        "title": "Test Night",
        "starts_at": "2026-09-10T18:00:00Z",
        "ends_at": "2026-09-10T22:00:00Z",
        "fee_mode": "PASS_ON",
        "refund_policy": "FEE_RETAINED",
    }
    payload.update(overrides)
    return payload


def create_ticket_type_payload(event_id: str, **overrides) -> dict:
    payload = {
        "event_id": event_id,
        "name": "General",
        "tier_rank": 1,
        "price_cents": 5000,
        "quantity_total": 10,
        "seating_mode": "GA",
    }
    payload.update(overrides)
    return payload


def create_seat_block_payload(ticket_type_id: str, **overrides) -> dict:
    payload = {
        "ticket_type_id": ticket_type_id,
        "row_label": "A",
        "seat_from": 1,
        "seat_to": 10,
    }
    payload.update(overrides)
    return payload


def create_promo_code_payload(event_id: str, **overrides) -> dict:
    payload = {
        "event_id": event_id,
        "code": "SAVE10",
        "kind": "PERCENT",
        "percent_bp": 1000,
        "amount_cents": 0,
        "max_uses": 5,
        "valid_from": "2026-07-01T00:00:00Z",
        "valid_until": "2026-09-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def order_item_payload(ticket_type_id: str, quantity: int = 1,
                       seat_block_id=None, seat_numbers=None) -> dict:
    """One entry of the order's items array."""
    item = {"ticket_type_id": ticket_type_id, "quantity": quantity}
    if seat_block_id is not None:
        item["seat_block_id"] = seat_block_id
    if seat_numbers is not None:
        item["seat_numbers"] = seat_numbers
    return item


def create_order_payload(event_id: str, buyer_id: str, items, expected_event_version: int,
                         **overrides) -> dict:
    payload = {
        "event_id": event_id,
        "buyer_id": buyer_id,
        "items": items,
        "expected_event_version": expected_event_version,
    }
    payload.update(overrides)
    return payload


def create_refund_request_payload(order_id: str, item_refunds, **overrides) -> dict:
    payload = {
        "order_id": order_id,
        "item_refunds": item_refunds,
        "reason": "cannot attend",
    }
    payload.update(overrides)
    return payload


def item_refund(order_item_id: str, quantity: int) -> dict:
    return {"order_item_id": order_item_id, "quantity": quantity}


def create_transfer_request_payload(attendee_id: str, to_email: str, **overrides) -> dict:
    payload = {"attendee_id": attendee_id, "to_email": to_email}
    payload.update(overrides)
    return payload


def create_waitlist_entry_payload(ticket_type_id: str, buyer_id: str,
                                  requested_quantity: int = 1, **overrides) -> dict:
    payload = {
        "ticket_type_id": ticket_type_id,
        "buyer_id": buyer_id,
        "requested_quantity": requested_quantity,
    }
    payload.update(overrides)
    return payload


def create_scan_payload(attendee_id: str, event_id: str, gate_code: str = "GATE-A",
                        **overrides) -> dict:
    payload = {
        "attendee_id": attendee_id,
        "event_id": event_id,
        "gate_code": gate_code,
    }
    payload.update(overrides)
    return payload


def create_payout_payload(organizer_id: str, event_id: str,
                          expected_organizer_version: int, **overrides) -> dict:
    payload = {
        "organizer_id": organizer_id,
        "event_id": event_id,
        "expected_organizer_version": expected_organizer_version,
    }
    payload.update(overrides)
    return payload
