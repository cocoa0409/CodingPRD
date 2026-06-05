"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so a broken precondition
surfaces as a clear "Setup failed" error rather than a confusing assertion failure.

The ticketing domain has one dominant setup chain reused by nearly every claim:
  create event -> create tier(s) -> open presale [-> open general]
  -> register+verify fan -> join queue -> advance-queue (offer) -> create order -> pay
Helpers below expose the controllable knobs (face value, capacity, multiplier,
sales phase, quantity) and return the intermediate entities tests need to assert on.

The acting Fan role is entity_backed: every ownership-gated call threads
make_fan_headers(fan["id"]).
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_fan_payload,
    create_event_payload,
    create_price_tier_payload,
    create_queue_entry_payload,
    create_order_payload,
)
from .test_users import TEST_USERS, make_fan_headers

PROMOTER = TEST_USERS["promoter_headers"]
ANON = TEST_USERS["anonymous_headers"]
SCANNER = TEST_USERS["scanner_headers"]

CLOCK_T0 = "2026-06-01T00:00:00Z"


# ─── Primitive building blocks ────────────────────────────────────────────

def set_clock(iso: str):
    """Pin the server clock to a fixed instant for offer-expiry / velocity tests."""
    return get_success_data(api_client.set_clock({"to_iso8601": iso}, PROMOTER))


def register_fan(email, device="dev-unique", full_name="F", **overrides):
    """Register a Fan (lands UNVERIFIED). Returns the Fan dict."""
    payload = create_fan_payload(email=email, device_fingerprint=device,
                                 full_name=full_name, **overrides)
    return get_success_data(api_client.create_fan(payload, ANON))


def register_and_verify_fan(email, device="dev-unique", full_name="F"):
    """Register a Fan then run the verify step (-> VERIFIED for a clean fan)."""
    fan = register_fan(email, device=device, full_name=full_name)
    verified = get_success_data(
        api_client.verify_fan(fan["id"], make_fan_headers(fan["id"]))
    )
    return verified


def create_event(face_value_cents=10000, venue_capacity=100, presale_code="S",
                 resale_cap_pct=110, title="E", **overrides):
    """Create an Event in DRAFT. Returns the Event dict."""
    payload = create_event_payload(
        title=title, venue_capacity=venue_capacity, presale_code=presale_code,
        face_value_cents=face_value_cents, resale_cap_pct=resale_cap_pct, **overrides
    )
    return get_success_data(api_client.create_event(payload, PROMOTER))


def create_tier(event_id, allocation=50, base_multiplier_bps=10000, name="FLOOR"):
    """Create a PriceTier under a DRAFT event. Returns the tier dict."""
    payload = create_price_tier_payload(
        event_id, allocation=allocation, base_multiplier_bps=base_multiplier_bps, name=name
    )
    return get_success_data(api_client.create_price_tier(payload, PROMOTER))


def open_to_phase(event, target_phase):
    """Advance an event through DRAFT -> PRESALE [-> GENERAL].

    target_phase is 'PRESALE' or 'GENERAL'. Returns the latest Event dict.
    """
    ev_id = event["id"]
    res = get_success_data(
        api_client.open_presale(ev_id, {"expected_event_version": event["version"]}, PROMOTER)
    )
    if target_phase == "GENERAL":
        res = get_success_data(
            api_client.open_general(ev_id, {"expected_event_version": res["version"]}, PROMOTER)
        )
    return res


# ─── Tier 1/2: Event in a sales phase with one tier ───────────────────────

def setup_event_with_tier(phase="GENERAL", face_value_cents=10000, venue_capacity=100,
                          presale_code="S", resale_cap_pct=110, allocation=50,
                          base_multiplier_bps=10000):
    """Create event + one tier and walk the event to `phase`.

    Returns (event_after_phase, tier).
    """
    event = create_event(face_value_cents=face_value_cents, venue_capacity=venue_capacity,
                         presale_code=presale_code, resale_cap_pct=resale_cap_pct)
    tier = create_tier(event["id"], allocation=allocation,
                       base_multiplier_bps=base_multiplier_bps)
    event = open_to_phase(event, phase)
    return event, tier


# ─── Tier 3: Full lifecycle to OFFERED / PAID / ticket ────────────────────

def join_queue(event, tier, fan, requested_qty=1, presale_code_used="S"):
    """Verified fan joins the queue for a tier. Returns the QueueEntry dict."""
    payload = create_queue_entry_payload(
        event["id"], fan["id"], tier["id"],
        requested_qty=requested_qty, presale_code_used=presale_code_used
    )
    return get_success_data(
        api_client.create_queue_entry(payload, make_fan_headers(fan["id"]))
    )


def advance(event_id, tier_id=None, max_offers=50):
    """Promoter advances the queue (offers + sweeps). Returns the offered list."""
    payload = {}
    if tier_id is not None:
        payload["tier_id"] = tier_id
    if max_offers is not None:
        payload["max_offers"] = max_offers
    return get_success_data(api_client.advance_queue(event_id, payload, PROMOTER))


def create_offered_entry(event, tier, fan, requested_qty=1, presale_code_used="S"):
    """Join queue then advance so the entry becomes OFFERED.

    Returns the refreshed QueueEntry dict (status OFFERED).
    """
    qe = join_queue(event, tier, fan, requested_qty=requested_qty,
                    presale_code_used=presale_code_used)
    advance(event["id"], tier_id=tier["id"], max_offers=max(50, requested_qty + 5))
    return get_success_data(
        api_client.get_queue_entry(qe["id"], make_fan_headers(fan["id"]))
    )


def create_pending_order(event, tier, fan, requested_qty=1, presale_code_used="S"):
    """Reach a PENDING Order: join -> advance(OFFERED) -> create order.

    Returns (queue_entry, order).
    """
    qe = create_offered_entry(event, tier, fan, requested_qty=requested_qty,
                              presale_code_used=presale_code_used)
    order = get_success_data(api_client.create_order(
        create_order_payload(qe["id"], fan["id"], tier["id"], quantity=requested_qty),
        make_fan_headers(fan["id"]),
    ))
    return qe, order


def create_paid_order(event, tier, fan, requested_qty=1, presale_code_used="S"):
    """Reach a PAID Order. Returns (queue_entry, paid_order)."""
    qe, order = create_pending_order(event, tier, fan, requested_qty=requested_qty,
                                     presale_code_used=presale_code_used)
    paid = get_success_data(api_client.pay_order(
        order["id"], {"expected_order_version": order["version"]},
        make_fan_headers(fan["id"]),
    ))
    return qe, paid


def get_ticket_for_order(order_id, fan_id):
    """Fetch the (first) Ticket issued for a PAID order. Returns the Ticket dict."""
    data, _meta = _list_tickets(order_id, fan_id)
    assert data, f"Setup failed: no tickets issued for order {order_id}"
    return data[0]


def _list_tickets(order_id, fan_id):
    from prd_bench_local_runner.testing import validate_paginated
    res = api_client.list_tickets(make_fan_headers(fan_id), params={"order_id": order_id})
    return validate_paginated(res)


def setup_held_ticket(phase="GENERAL", face_value_cents=10000, venue_capacity=100,
                      resale_cap_pct=110, base_multiplier_bps=10000,
                      email="holder@x.com", device="dev-holder"):
    """End-to-end: event(phase) + tier + verified fan holding one VALID/HELD ticket.

    Returns (event, tier, fan, order, ticket).
    """
    event, tier = setup_event_with_tier(
        phase=phase, face_value_cents=face_value_cents, venue_capacity=venue_capacity,
        resale_cap_pct=resale_cap_pct, base_multiplier_bps=base_multiplier_bps,
    )
    fan = register_and_verify_fan(email, device=device)
    _qe, order = create_paid_order(event, tier, fan, requested_qty=1)
    ticket = get_ticket_for_order(order["id"], fan["id"])
    return event, tier, fan, order, ticket


def setup_open_listing(list_price_cents=11000, resale_cap_pct=110, face_value_cents=10000):
    """Seller holds a VALID/HELD ticket and lists it OPEN.

    Returns (event, tier, seller, ticket, listing).
    """
    from .factories import create_resale_listing_payload
    event, tier, seller, _order, ticket = setup_held_ticket(
        resale_cap_pct=resale_cap_pct, face_value_cents=face_value_cents,
        email="seller@x.com", device="dev-seller",
    )
    listing = get_success_data(api_client.create_resale_listing(
        create_resale_listing_payload(ticket["id"], seller["id"], list_price_cents),
        make_fan_headers(seller["id"]),
    ))
    return event, tier, seller, ticket, listing


def setup_pending_transfer(recipient_verified=True):
    """Sender (verified) holds a ticket and initiates a transfer to a recipient.

    recipient_verified controls whether the recipient runs the verify step.
    Returns (event, tier, sender, recipient, ticket, transfer).
    """
    from .factories import create_transfer_payload
    event, tier, sender, _order, ticket = setup_held_ticket(
        email="sender@x.com", device="dev-sender",
    )
    if recipient_verified:
        recipient = register_and_verify_fan("recip@x.com", device="dev-recip")
    else:
        recipient = register_fan("recip@x.com", device="dev-recip")
    transfer = get_success_data(api_client.create_transfer(
        create_transfer_payload(ticket["id"], sender["id"], recipient["id"]),
        make_fan_headers(sender["id"]),
    ))
    return event, tier, sender, recipient, ticket, transfer


# ─── Tier 4: demand-band targeting (pre-sell N seats to set sold_ratio) ────

def pre_sell_seats(event, tier, seats, base_email="seed", device="dev-seed",
                   presale_code_used="S"):
    """Pre-sell `seats` tickets in this tier via one seed fan, committing
    Event.tickets_sold_count to `seats` so a later order observes that sold_ratio.

    Returns the refreshed Event dict.
    """
    if seats <= 0:
        return get_success_data(api_client.get_event(event["id"], PROMOTER))
    seed = register_and_verify_fan(f"{base_email}@x.com", device=device)
    _qe, _paid = create_paid_order(event, tier, seed, requested_qty=seats,
                                   presale_code_used=presale_code_used)
    return get_success_data(api_client.get_event(event["id"], PROMOTER))
