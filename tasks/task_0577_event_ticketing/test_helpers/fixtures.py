"""
Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures produce clear
"Setup failed" errors rather than confusing assertion failures. Every helper builds its
preconditions from scratch — each test runs against an empty database.

Identity threading: after a Buyer entity is created, every ownership-gated call for that
buyer uses make_buyer_headers(buyer["id"]) — never the shared TEST_USERS constant.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_buyer_payload, create_event_payload, create_price_level_payload,
    create_seat_payload, create_queue_token_payload, create_hold_payload,
    create_order_payload,
)
from .test_users import TEST_USERS, make_buyer_headers, make_promoter_headers

BOX = TEST_USERS["box_office_headers"]
PROMOTER = make_promoter_headers()


# ─── Low-level building blocks ────────────────────────────────────────────
def set_clock(iso: str):
    """Advance the logical clock to `iso` (BoxOffice capability)."""
    return get_success_data(api_client.set_clock(iso, BOX))


def register_buyer(name: str = "Test Buyer", email: str = None) -> dict:
    payload = create_buyer_payload(name=name)
    if email is not None:
        payload["email"] = email
    return get_success_data(api_client.create_buyer(payload, BOX))


def create_event(**overrides) -> dict:
    return get_success_data(api_client.create_event(create_event_payload(**overrides), PROMOTER))


def create_price_level(event_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_price_level(event_id, create_price_level_payload(**overrides), PROMOTER)
    )


def create_seat(event_id: str, price_level_id: str, section="A", row="1", seat_number="1") -> dict:
    return get_success_data(
        api_client.create_seat(
            event_id, create_seat_payload(price_level_id, section, row, seat_number), BOX
        )
    )


def set_status(event_id: str, target_status: str, new_event_datetime: str = None) -> dict:
    payload = {"target_status": target_status}
    if new_event_datetime is not None:
        payload["new_event_datetime"] = new_event_datetime
    return get_success_data(api_client.set_event_status(event_id, payload, PROMOTER))


def get_event(event_id: str) -> dict:
    return get_success_data(api_client.get_event(event_id, BOX))


def event_version(event_id: str) -> int:
    return get_event(event_id)["version"]


def admit_buyer(event_id: str, buyer_id: str) -> dict:
    """Join the queue then admit the token. Returns the ADMITTED QueueToken."""
    token = get_success_data(
        api_client.create_queue_token(
            event_id, create_queue_token_payload(buyer_id), make_buyer_headers(buyer_id)
        )
    )
    return get_success_data(api_client.admit_queue_token(token["id"], BOX))


def hold_seats(event_id: str, seat_ids, buyer_id: str, presale_code: str = None) -> dict:
    """Create a hold, auto-capturing the event's current version for the OCC guard."""
    payload = create_hold_payload(seat_ids, buyer_id, event_version(event_id))
    if presale_code is not None:
        payload["presale_code"] = presale_code
    return get_success_data(
        api_client.create_hold(event_id, payload, make_buyer_headers(buyer_id))
    )


def create_order(hold_id: str, buyer_id: str, delivery_method: str = "MOBILE") -> dict:
    return get_success_data(
        api_client.create_order(
            create_order_payload(hold_id, delivery_method), make_buyer_headers(buyer_id)
        )
    )


def pay_order(order_id: str, buyer_id: str) -> dict:
    return get_success_data(api_client.pay_order(order_id, make_buyer_headers(buyer_id)))


def tickets_for_order(order_id: str, buyer_id: str) -> list:
    resp = api_client.list_tickets(make_buyer_headers(buyer_id), params={"order_id": order_id})
    data = get_success_data(resp)
    # get_success_data returns the data payload (a list for list endpoints)
    return data if isinstance(data, list) else data.get("data", data)


# ─── Composite: event standing up ─────────────────────────────────────────
def setup_onsale_event(num_seats: int = 1, base_face_value_cents: int = 9990,
                       dynamic_pricing_enabled: bool = False, is_platinum: bool = False,
                       service_fee_pct: float = 0.15, service_fee_flat_cents: int = 500,
                       hold_ttl_minutes: int = 15, purchase_window_minutes: int = 30,
                       event_datetime: str = "2026-08-01T19:00:00Z") -> dict:
    """
    Create an event, one price level, `num_seats` seats, then drive DRAFT -> ANNOUNCED -> ONSALE.
    Returns {event, price_level, seats}. `event` reflects the ONSALE response (version captured).
    """
    event = create_event(
        hold_ttl_minutes=hold_ttl_minutes,
        purchase_window_minutes=purchase_window_minutes,
        event_datetime=event_datetime,
    )
    pl = create_price_level(
        event["id"],
        base_face_value_cents=base_face_value_cents,
        is_platinum=is_platinum,
        service_fee_pct=service_fee_pct,
        service_fee_flat_cents=service_fee_flat_cents,
        dynamic_pricing_enabled=dynamic_pricing_enabled,
    )
    seats = [
        create_seat(event["id"], pl["id"], section="A", row="1", seat_number=str(i + 1))
        for i in range(num_seats)
    ]
    set_status(event["id"], "ANNOUNCED")
    onsale = set_status(event["id"], "ONSALE")
    return {"event": onsale, "price_level": pl, "seats": seats}


def setup_presale_event(num_seats: int = 1, presale_code: str = "SECRET",
                        presale_max_uses: int = 5, base_face_value_cents: int = 9990) -> dict:
    """Create an event with a presale code, drive DRAFT -> ANNOUNCED -> PRESALE."""
    event = create_event(presale_code=presale_code, presale_max_uses=presale_max_uses)
    pl = create_price_level(event["id"], base_face_value_cents=base_face_value_cents)
    seats = [
        create_seat(event["id"], pl["id"], section="A", row="1", seat_number=str(i + 1))
        for i in range(num_seats)
    ]
    set_status(event["id"], "ANNOUNCED")
    presale = set_status(event["id"], "PRESALE")
    return {"event": presale, "price_level": pl, "seats": seats}


# ─── Composite: paid order (buyer through pay) ────────────────────────────
def setup_paid_order(num_seats: int = 1, delivery_method: str = "MOBILE",
                     base_face_value_cents: int = 9990, dynamic_pricing_enabled: bool = False,
                     is_platinum: bool = False, service_fee_pct: float = 0.15,
                     service_fee_flat_cents: int = 500) -> dict:
    """
    Full path to a PAID order: register buyer -> event ONSALE -> admit -> hold -> order -> pay.
    Returns {buyer, event, price_level, seats, hold, order, tickets}.
    """
    buyer = register_buyer()
    env = setup_onsale_event(
        num_seats=num_seats, base_face_value_cents=base_face_value_cents,
        dynamic_pricing_enabled=dynamic_pricing_enabled, is_platinum=is_platinum,
        service_fee_pct=service_fee_pct, service_fee_flat_cents=service_fee_flat_cents,
    )
    admit_buyer(env["event"]["id"], buyer["id"])
    seat_ids = [s["id"] for s in env["seats"]]
    hold = hold_seats(env["event"]["id"], seat_ids, buyer["id"])
    order = create_order(hold["id"], buyer["id"], delivery_method)
    paid = pay_order(order["id"], buyer["id"])
    tickets = tickets_for_order(order["id"], buyer["id"])
    return {
        "buyer": buyer,
        "event": env["event"],
        "price_level": env["price_level"],
        "seats": env["seats"],
        "hold": hold,
        "order": paid,
        "tickets": tickets,
    }


def setup_admitted_buyer_on_onsale_event(num_seats: int = 1, **pricing) -> dict:
    """Register a buyer, stand up an ONSALE event, and admit the buyer.
    Returns {buyer, event, price_level, seats}. No hold placed yet."""
    buyer = register_buyer()
    env = setup_onsale_event(num_seats=num_seats, **pricing)
    admit_buyer(env["event"]["id"], buyer["id"])
    return {"buyer": buyer, **env}
