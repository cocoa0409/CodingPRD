"""Composite setup helpers.

Most interesting claims need the platform in a state that takes five to fifteen
API calls to reach. These helpers encapsulate those preambles so tests can hold
only their assertions. Every helper builds its preconditions from scratch using
declared endpoints only, because each test starts against an empty database.

Identity threading: after an Organizer or Buyer record is created, every
ownership-gated call below uses make_organizer_headers(organizer["id"]) or
make_buyer_headers(buyer["id"]) with that record's real id.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_organizer_payload, create_venue_payload, create_buyer_payload,
    create_event_payload, create_ticket_type_payload, create_seat_block_payload,
    create_promo_code_payload, create_order_payload, order_item_payload,
    create_refund_request_payload, item_refund, create_scan_payload,
    create_waitlist_entry_payload, create_payout_payload,
    create_transfer_request_payload,
)
from .test_users import (
    TEST_USERS, ANONYMOUS_HEADERS, make_organizer_headers, make_buyer_headers,
    make_finance_officer_headers, make_gate_staff_headers,
    ADMIN_USER_ID, GATE_USER_ID, FINANCE_USER_ID, FINANCE_USER_ID_2,
)

ADMIN = TEST_USERS["platform_admin_headers"]
GATE = TEST_USERS["gate_staff_headers"]
FINANCE = TEST_USERS["finance_officer_headers"]
FINANCE_2 = TEST_USERS["finance_officer_headers_2"]


# ---------------------------------------------------------------------------
# Tier 0: primitives
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str) -> str:
    """Move the logical clock. Returns the resulting current_utc."""
    data = get_success_data(api_client.set_clock(to_iso8601, ADMIN))
    return data.get("current_utc")


def create_organizer(**overrides) -> dict:
    return get_success_data(
        api_client.create_organizer(create_organizer_payload(**overrides), ADMIN))


def create_venue(**overrides) -> dict:
    return get_success_data(
        api_client.create_venue(create_venue_payload(**overrides), ADMIN))


def create_buyer(**overrides) -> dict:
    """Buyer self-registration is open to the unauthenticated public."""
    return get_success_data(
        api_client.create_buyer(create_buyer_payload(**overrides), ANONYMOUS_HEADERS))


def create_event(organizer: dict, venue: dict, **overrides) -> dict:
    headers = make_organizer_headers(organizer["id"])
    payload = create_event_payload(organizer["id"], venue["id"], **overrides)
    return get_success_data(api_client.create_event(payload, headers))


def create_ticket_type(organizer: dict, event: dict, **overrides) -> dict:
    headers = make_organizer_headers(organizer["id"])
    payload = create_ticket_type_payload(event["id"], **overrides)
    return get_success_data(api_client.create_ticket_type(payload, headers))


def create_seat_block(organizer: dict, ticket_type: dict, **overrides) -> dict:
    headers = make_organizer_headers(organizer["id"])
    payload = create_seat_block_payload(ticket_type["id"], **overrides)
    return get_success_data(api_client.create_seat_block(payload, headers))


def create_promo_code(organizer: dict, event: dict, **overrides) -> dict:
    headers = make_organizer_headers(organizer["id"])
    payload = create_promo_code_payload(event["id"], **overrides)
    return get_success_data(api_client.create_promo_code(payload, headers))


def publish_event(organizer: dict, event: dict) -> dict:
    headers = make_organizer_headers(organizer["id"])
    return get_success_data(api_client.publish_event(event["id"], headers))


def read_event(event_id: str, headers=None) -> dict:
    """Reading an event is open to every role including Anonymous."""
    return get_success_data(
        api_client.get_event(event_id, headers or ANONYMOUS_HEADERS))


def event_version(event_id: str) -> int:
    return read_event(event_id)["version"]


def read_ticket_type(ticket_type_id: str) -> dict:
    return get_success_data(
        api_client.get_ticket_type(ticket_type_id, ANONYMOUS_HEADERS))


def read_seat_block(seat_block_id: str) -> dict:
    return get_success_data(
        api_client.get_seat_block(seat_block_id, ANONYMOUS_HEADERS))


def read_organizer(organizer_id: str) -> dict:
    return get_success_data(api_client.get_organizer(organizer_id, FINANCE))


def organizer_version(organizer_id: str) -> int:
    return read_organizer(organizer_id)["version"]


def read_order(order_id: str, buyer: dict = None) -> dict:
    headers = make_buyer_headers(buyer["id"]) if buyer else TEST_USERS["platform_admin_headers"]
    return get_success_data(api_client.get_order(order_id, headers))


def read_attendee(attendee_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.get_attendee(attendee_id, headers or ADMIN))


def read_refund_request(refund_request_id: str) -> dict:
    return get_success_data(api_client.get_refund_request(refund_request_id, FINANCE))


def read_transfer_request(transfer_request_id: str, buyer: dict) -> dict:
    return get_success_data(
        api_client.get_transfer_request(transfer_request_id, make_buyer_headers(buyer["id"])))


def read_waitlist_entry(waitlist_entry_id: str, buyer: dict) -> dict:
    return get_success_data(
        api_client.get_waitlist_entry(waitlist_entry_id, make_buyer_headers(buyer["id"])))


def read_payout(payout_id: str) -> dict:
    return get_success_data(api_client.get_payout(payout_id, FINANCE))


def order_items_of(order_id: str, buyer: dict) -> list:
    return get_success_data(
        api_client.list_order_items(make_buyer_headers(buyer["id"]),
                                    params={"order_id": order_id}))


def attendees_of(order_id: str, buyer: dict) -> list:
    return get_success_data(
        api_client.list_attendees(make_buyer_headers(buyer["id"]),
                                  params={"order_id": order_id}))


# ---------------------------------------------------------------------------
# Tier 1 / 2: marketplace and a published event
# ---------------------------------------------------------------------------

def setup_marketplace(venue_overrides=None, organizer_overrides=None) -> dict:
    """Seed one organizer and one venue. Returns a context dict."""
    organizer = create_organizer(**(organizer_overrides or {}))
    venue = create_venue(**(venue_overrides or {}))
    return {
        "organizer": organizer,
        "org_id": organizer["id"],
        "org_headers": make_organizer_headers(organizer["id"]),
        "venue": venue,
        "venue_id": venue["id"],
    }


def setup_draft_event(clock=None, event_overrides=None, tier_overrides=None,
                      with_tier=True, seat_block_overrides=None) -> dict:
    """Organizer + venue + DRAFT event, optionally with one tier and seat block."""
    if clock:
        set_clock(clock)
    ctx = setup_marketplace()
    ctx["event"] = create_event(ctx["organizer"], ctx["venue"],
                                **(event_overrides or {}))
    ctx["event_id"] = ctx["event"]["id"]
    ctx["ticket_type"] = None
    ctx["tt_id"] = None
    ctx["seat_block"] = None
    ctx["sb_id"] = None
    if with_tier:
        ctx["ticket_type"] = create_ticket_type(ctx["organizer"], ctx["event"],
                                                **(tier_overrides or {}))
        ctx["tt_id"] = ctx["ticket_type"]["id"]
        if seat_block_overrides is not None:
            ctx["seat_block"] = create_seat_block(ctx["organizer"], ctx["ticket_type"],
                                                  **seat_block_overrides)
            ctx["sb_id"] = ctx["seat_block"]["id"]
    return ctx


def setup_onsale_event(clock=None, event_overrides=None, tier_overrides=None,
                       seat_block_overrides=None) -> dict:
    """Organizer + venue + one tier + published (ONSALE) event.

    The returned context carries `event_version`, the version observed at publish,
    which is what a checkout page would have rendered.
    """
    ctx = setup_draft_event(clock=clock, event_overrides=event_overrides,
                            tier_overrides=tier_overrides,
                            seat_block_overrides=seat_block_overrides)
    ctx["event"] = publish_event(ctx["organizer"], ctx["event"])
    ctx["event_version"] = ctx["event"]["version"]
    return ctx


def setup_reserved_onsale_event(clock=None, event_overrides=None,
                                tier_overrides=None, seat_from=1, seat_to=10,
                                row_label="A") -> dict:
    """ONSALE event whose single tier is RESERVED and backed by one seat block."""
    tier = {"name": "Orchestra", "tier_rank": 2, "seating_mode": "RESERVED"}
    tier.update(tier_overrides or {})
    return setup_onsale_event(
        clock=clock, event_overrides=event_overrides, tier_overrides=tier,
        seat_block_overrides={"row_label": row_label, "seat_from": seat_from,
                              "seat_to": seat_to})


# ---------------------------------------------------------------------------
# Tier 3: checkout lifecycle shortcuts
# ---------------------------------------------------------------------------

def place_order(ctx: dict, buyer: dict, items, expected_event_version=None,
                promo_code=None):
    """Create an order, defaulting the concurrency guard to the live version."""
    version = (expected_event_version if expected_event_version is not None
               else event_version(ctx["event_id"]))
    extras = {}
    if promo_code is not None:
        extras["promo_code"] = promo_code
    payload = create_order_payload(ctx["event_id"], buyer["id"], items, version, **extras)
    return api_client.create_order(payload, make_buyer_headers(buyer["id"]))


def create_held_order(ctx: dict, buyer: dict, quantity=1, seat_numbers=None,
                      expected_event_version=None, promo_code=None) -> dict:
    """Create one order line's worth of held inventory. Returns the order."""
    item = order_item_payload(
        ctx["tt_id"], quantity,
        seat_block_id=ctx["sb_id"] if seat_numbers is not None else None,
        seat_numbers=seat_numbers)
    return get_success_data(place_order(ctx, buyer, [item],
                                        expected_event_version=expected_event_version,
                                        promo_code=promo_code))


def pay_order(order_id: str, buyer: dict) -> dict:
    return get_success_data(
        api_client.pay_order(order_id, make_buyer_headers(buyer["id"])))


def setup_paid_order(ctx: dict, buyer=None, quantity=1, seat_numbers=None,
                     promo_code=None) -> dict:
    """Create a buyer if needed, hold inventory, then capture payment.

    Returns {buyer, order, items, attendees}. After this the tier's sold_count
    reflects the minted admissions.
    """
    buyer = buyer or create_buyer()
    order = create_held_order(ctx, buyer, quantity=quantity,
                              seat_numbers=seat_numbers, promo_code=promo_code)
    order = pay_order(order["id"], buyer)
    return {
        "buyer": buyer,
        "buyer_headers": make_buyer_headers(buyer["id"]),
        "order": order,
        "order_id": order["id"],
        "items": order_items_of(order["id"], buyer),
        "attendees": attendees_of(order["id"], buyer),
    }


def scan_attendee(attendee_id: str, event_id: str, gate_code="GATE-A",
                  gate_user_id=GATE_USER_ID) -> dict:
    return get_success_data(api_client.create_scan(
        create_scan_payload(attendee_id, event_id, gate_code),
        make_gate_staff_headers(gate_user_id)))


# ---------------------------------------------------------------------------
# Tier 4: refunds
# ---------------------------------------------------------------------------

def open_refund_request(paid: dict, quantity=None, policy=None, reason="cannot attend",
                        item_index=0):
    """Open a refund request against one line of a paid order. Returns the response."""
    line = paid["items"][item_index]
    qty = quantity if quantity is not None else line["quantity"]
    extras = {"reason": reason}
    if policy is not None:
        extras["policy"] = policy
    payload = create_refund_request_payload(
        paid["order_id"], [item_refund(line["id"], qty)], **extras)
    return api_client.create_refund_request(payload, paid["buyer_headers"])


def setup_refund_request(paid: dict, quantity=None, policy=None,
                         reason="cannot attend") -> dict:
    return get_success_data(open_refund_request(paid, quantity=quantity, policy=policy,
                                                reason=reason))


def approve_refund(ctx: dict, refund_request_id: str) -> dict:
    return get_success_data(
        api_client.approve_refund_request(refund_request_id, ctx["org_headers"]))


def settle_refund(refund_request_id: str, finance_user_id=FINANCE_USER_ID) -> dict:
    return get_success_data(api_client.settle_refund_request(
        refund_request_id, make_finance_officer_headers(finance_user_id)))


def setup_approved_refund(ctx: dict, paid: dict, quantity=None, policy=None) -> dict:
    """Open then approve a refund; the money fields are computed at approval."""
    rr = setup_refund_request(paid, quantity=quantity, policy=policy)
    return approve_refund(ctx, rr["id"])


# ---------------------------------------------------------------------------
# Tier 5: settlement — completion, payouts and the reserve
# ---------------------------------------------------------------------------

def close_sales(ctx: dict) -> dict:
    return get_success_data(
        api_client.close_event_sales(ctx["event_id"], ctx["org_headers"]))


def complete_event(ctx: dict) -> dict:
    return get_success_data(
        api_client.complete_event(ctx["event_id"], ctx["org_headers"]))


def close_and_complete_event(ctx: dict, clock_after_end: str) -> dict:
    """Close sales, move the clock past ends_at, then complete the event."""
    close_sales(ctx)
    set_clock(clock_after_end)
    return complete_event(ctx)


def open_payout(ctx: dict, expected_organizer_version=None,
                finance_user_id=FINANCE_USER_ID):
    """Open a payout, defaulting the concurrency guard to the live version."""
    version = (expected_organizer_version if expected_organizer_version is not None
               else organizer_version(ctx["org_id"]))
    payload = create_payout_payload(ctx["org_id"], ctx["event_id"], version)
    return api_client.create_payout(payload, make_finance_officer_headers(finance_user_id))


def setup_payout(ctx: dict, expected_organizer_version=None,
                 finance_user_id=FINANCE_USER_ID) -> dict:
    return get_success_data(open_payout(ctx, expected_organizer_version, finance_user_id))


def setup_completed_event_with_payout(quantity=1, clock_start="2026-07-05T10:00:00Z",
                                      clock_after_end="2026-08-02T00:00:00Z",
                                      starts_at="2026-08-01T18:00:00Z",
                                      ends_at="2026-08-01T22:00:00Z",
                                      fee_mode="PASS_ON",
                                      refund_policy="FEE_RETAINED",
                                      price_cents=5000,
                                      scan_all=False) -> dict:
    """Full settlement preamble.

    Publishes an event, sells and pays for `quantity` general-admission tickets,
    optionally scans every admission, closes sales, advances the clock past the
    event's end, completes it, and opens a payout. Returns a context dict
    extended with `paid` and `payout`.
    """
    ctx = setup_onsale_event(
        clock=clock_start,
        event_overrides={"starts_at": starts_at, "ends_at": ends_at,
                         "fee_mode": fee_mode, "refund_policy": refund_policy},
        tier_overrides={"price_cents": price_cents})
    paid = setup_paid_order(ctx, quantity=quantity)
    if scan_all:
        scan_clock = starts_at.replace("T18:", "T17:")
        set_clock(scan_clock)
        for attendee in paid["attendees"]:
            scan_attendee(attendee["id"], ctx["event_id"])
    close_and_complete_event(ctx, clock_after_end)
    ctx["paid"] = paid
    ctx["payout"] = setup_payout(ctx)
    ctx["payout_id"] = ctx["payout"]["id"]
    return ctx


def setup_eligible_payout(**kwargs) -> dict:
    """Completed event whose payout has been marked ELIGIBLE."""
    ctx = setup_completed_event_with_payout(**kwargs)
    ctx["payout"] = get_success_data(
        api_client.mark_payout_eligible(ctx["payout_id"], FINANCE))
    return ctx


def setup_approved_payout(**kwargs) -> dict:
    """Completed event whose payout is APPROVED by finance operator fin-1."""
    ctx = setup_eligible_payout(**kwargs)
    ctx["payout"] = get_success_data(
        api_client.approve_payout(ctx["payout_id"], FINANCE))
    return ctx


def setup_released_payout(**kwargs) -> dict:
    """Approved by fin-1 then released by fin-2, satisfying segregation of duties."""
    ctx = setup_approved_payout(**kwargs)
    ctx["payout"] = get_success_data(
        api_client.release_payout(ctx["payout_id"], FINANCE_2))
    return ctx


# ---------------------------------------------------------------------------
# Tier 4: waitlist and transfers
# ---------------------------------------------------------------------------

def setup_sold_out_tier(quantity_total=2, clock="2026-07-05T10:00:00Z",
                        event_overrides=None) -> dict:
    """Publish a tier and sell every seat of it, so its available quantity is 0."""
    overrides = {"starts_at": "2026-09-25T18:00:00Z", "ends_at": "2026-09-25T22:00:00Z"}
    overrides.update(event_overrides or {})
    ctx = setup_onsale_event(clock=clock, event_overrides=overrides,
                             tier_overrides={"quantity_total": quantity_total})
    ctx["paid"] = setup_paid_order(ctx, quantity=quantity_total)
    return ctx


def join_waitlist(ctx: dict, buyer: dict, requested_quantity=1):
    return api_client.create_waitlist_entry(
        create_waitlist_entry_payload(ctx["tt_id"], buyer["id"], requested_quantity),
        make_buyer_headers(buyer["id"]))


def setup_waitlist_entry(ctx: dict, buyer=None, requested_quantity=1) -> dict:
    buyer = buyer or create_buyer()
    entry = get_success_data(join_waitlist(ctx, buyer, requested_quantity))
    return {"buyer": buyer, "entry": entry, "entry_id": entry["id"]}


def void_attendee(ctx: dict, attendee_id: str, reason="guest withdrew") -> dict:
    return get_success_data(api_client.void_attendee(
        attendee_id, ctx["org_headers"], {"reason": reason}))


def run_waitlist_sweep(ctx: dict) -> dict:
    return get_success_data(
        api_client.waitlist_sweep(ctx["tt_id"], ctx["org_headers"]))


def setup_offered_waitlist_entry(quantity_total=2, clock="2026-07-05T10:00:00Z",
                                 requested_quantity=1) -> dict:
    """Sell a tier out, queue a buyer, free one seat by voiding, then sweep.

    Returns the context extended with `waiting` (the queued buyer and entry) and
    `sweep` (the sweep report).
    """
    ctx = setup_sold_out_tier(quantity_total=quantity_total, clock=clock)
    ctx["waiting"] = setup_waitlist_entry(ctx, requested_quantity=requested_quantity)
    void_attendee(ctx, ctx["paid"]["attendees"][0]["id"])
    ctx["sweep"] = run_waitlist_sweep(ctx)
    return ctx


def setup_transfer_offer(clock="2026-07-05T10:00:00Z",
                         recipient_email="recipient@example.com",
                         event_overrides=None, send=True) -> dict:
    """Paid single admission plus a transfer offer aimed at a second buyer.

    Returns the context extended with `paid`, `recipient` and `transfer`.
    """
    overrides = {"starts_at": "2026-09-26T18:00:00Z", "ends_at": "2026-09-26T22:00:00Z"}
    overrides.update(event_overrides or {})
    ctx = setup_onsale_event(clock=clock, event_overrides=overrides)
    paid = setup_paid_order(ctx, quantity=1)
    recipient = create_buyer(email=recipient_email, display_name="Recipient")
    transfer = get_success_data(api_client.create_transfer_request(
        create_transfer_request_payload(paid["attendees"][0]["id"], recipient_email),
        paid["buyer_headers"]))
    if send:
        transfer = get_success_data(
            api_client.send_transfer_request(transfer["id"], paid["buyer_headers"]))
    ctx["paid"] = paid
    ctx["recipient"] = recipient
    ctx["transfer"] = transfer
    ctx["transfer_id"] = transfer["id"]
    return ctx
