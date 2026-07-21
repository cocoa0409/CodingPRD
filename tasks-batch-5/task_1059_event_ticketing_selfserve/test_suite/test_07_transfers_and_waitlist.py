"""Passing a ticket on, and the queue for inventory that is already gone."""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    ApiErrorId,
    assert_transfer_request, assert_waitlist_entry,
    create_waitlist_entry_payload,
    setup_draft_event, setup_onsale_event, setup_transfer_offer,
    setup_sold_out_tier, setup_offered_waitlist_entry, setup_waitlist_entry,
    setup_paid_order, create_ticket_type, create_buyer, publish_event,
    join_waitlist, run_waitlist_sweep, void_attendee, set_clock,
    read_attendee, read_transfer_request, read_waitlist_entry, read_ticket_type,
    make_buyer_headers,
)


# ---------------------------------------------------------------------------
# The transfer offer cycle
# ---------------------------------------------------------------------------

def test_declined_transfer_offer_can_be_resent_and_counts_the_resend():
    """PRD §3.6: "A declined offer is not dead. Sending it again returns it from
    `DECLINED` to `SENT`, sets a fresh `offer_expires_at` seventy-two hours ahead of
    the current time, and increments `resend_count` by 1 — that counter records
    precisely how many times an offer has re-entered `SENT` after a decline."
    PRD §3.6: "Declining takes the offer from `SENT` to `DECLINED`, likewise
    identifies the responding buyer with `to_buyer_id` and likewise requires that
    buyer's `email` to equal `to_email`, and clears `offer_expires_at` back to null."

    Design: Difficulty/non_linear_state_machine/transfer_request_sent_declined_resent_cycle_on_transfer_entity
    """
    ctx = setup_transfer_offer(recipient_email="gil@example.com",
                               event_overrides={"title": "Loop Night",
                                                "starts_at": "2026-08-05T18:00:00Z",
                                                "ends_at": "2026-08-05T22:00:00Z"})
    recipient_headers = make_buyer_headers(ctx["recipient"]["id"])

    declined = validate_success(api_client.decline_transfer_request(
        ctx["transfer_id"], {"to_buyer_id": ctx["recipient"]["id"]},
        recipient_headers), 200)
    assert declined["status"] == "DECLINED"
    assert declined["offer_expires_at"] is None, \
        f"Declining clears the deadline, got {declined['offer_expires_at']}"

    resent = validate_success(api_client.send_transfer_request(
        ctx["transfer_id"], ctx["paid"]["buyer_headers"]), 200)

    assert_transfer_request(resent)
    assert resent["status"] == "SENT"
    assert resent["resend_count"] == 1, \
        f"Re-entering SENT after a decline counts once, got {resent['resend_count']}"
    assert resent["offer_expires_at"].startswith("2026-07-08T10:00:00"), (
        "A fresh deadline sits seventy-two hours ahead of the current time, got "
        f"{resent['offer_expires_at']}")


def test_accepting_a_resent_offer_moves_the_admission_to_the_new_holder():
    """PRD §3.6: "The linked admission then moves to `TRANSFERRED`: its `buyer_id`
    becomes the accepting buyer, its `holder_email` becomes that buyer's email, and it
    remains scannable exactly as an `ISSUED` admission is."
    PRD §3.6: "Accepting takes the offer from `SENT` to `ACCEPTED` and requires the
    offer to be in `SENT`, the current time to be strictly before `offer_expires_at`,
    and the accepting buyer's `email` to equal the offer's `to_email`."

    Design: Difficulty/non_linear_state_machine/transfer_request_sent_declined_resent_cycle_on_transfer_entity
    """
    ctx = setup_transfer_offer(recipient_email="gil@example.com",
                               event_overrides={"title": "Loop Night",
                                                "starts_at": "2026-08-05T18:00:00Z",
                                                "ends_at": "2026-08-05T22:00:00Z"})
    recipient = ctx["recipient"]
    recipient_headers = make_buyer_headers(recipient["id"])
    admission_id = ctx["paid"]["attendees"][0]["id"]

    validate_success(api_client.decline_transfer_request(
        ctx["transfer_id"], {"to_buyer_id": recipient["id"]}, recipient_headers), 200)
    validate_success(api_client.send_transfer_request(
        ctx["transfer_id"], ctx["paid"]["buyer_headers"]), 200)

    accepted = validate_success(api_client.accept_transfer_request(
        ctx["transfer_id"], {"to_buyer_id": recipient["id"]}, recipient_headers), 200)

    assert accepted["status"] == "ACCEPTED"
    assert accepted["resend_count"] == 1
    assert accepted["to_buyer_id"] == recipient["id"]

    admission = read_attendee(admission_id)
    assert admission["status"] == "TRANSFERRED", \
        f"Expected the admission to move to TRANSFERRED, got {admission['status']}"
    assert admission["buyer_id"] == recipient["id"]
    assert admission["holder_email"] == "gil@example.com", \
        f"The holder email follows the accepting buyer, got {admission['holder_email']}"


def test_accepting_after_the_offer_deadline_expires_the_offer():
    """PRD §3.6: "An accept or a decline attempted at or after `offer_expires_at`
    finds the offer in `SENT` but past its deadline: the offer is moved to `EXPIRED`
    and the triggering call is itself rejected with `ERR_TRANSFER_TTL_EXPIRED`."

    Design: Corner/state_machines/corner_transfer_accept_after_ttl_returns_transfer_ttl_expired
    """
    ctx = setup_transfer_offer(recipient_email="fig@example.com",
                               event_overrides={"title": "TTL Night",
                                                "starts_at": "2026-09-26T18:00:00Z",
                                                "ends_at": "2026-09-26T22:00:00Z"})
    holder = ctx["paid"]["buyer"]
    admission_id = ctx["paid"]["attendees"][0]["id"]

    # The offer was sent at 10:00, so it lapses at 2026-07-08T10:00:00Z.
    set_clock("2026-07-08T11:00:00Z")

    resp = api_client.accept_transfer_request(
        ctx["transfer_id"], {"to_buyer_id": ctx["recipient"]["id"]},
        make_buyer_headers(ctx["recipient"]["id"]))
    validate_error(resp, ApiErrorId.ERR_TRANSFER_TTL_EXPIRED.value, 409)

    assert read_transfer_request(ctx["transfer_id"], holder)["status"] == "EXPIRED"
    admission = read_attendee(admission_id)
    assert admission["buyer_id"] == holder["id"], \
        "A lapsed offer leaves the admission with its original holder"
    assert admission["status"] == "ISSUED"


# ---------------------------------------------------------------------------
# Joining the queue only when inventory is exactly gone
# ---------------------------------------------------------------------------

def _event_with_full_and_open_tiers():
    """ONSALE event carrying a fully sold two-seat tier and an untouched five-seat tier."""
    ctx = setup_draft_event(
        event_overrides={"title": "Queue Night", "starts_at": "2026-08-22T18:00:00Z",
                         "ends_at": "2026-08-22T22:00:00Z"},
        tier_overrides={"name": "Full Tier", "tier_rank": 1, "quantity_total": 2})
    ctx["open_tier"] = create_ticket_type(ctx["organizer"], ctx["event"],
                                          name="Open Tier", tier_rank=2,
                                          quantity_total=5)
    ctx["event"] = publish_event(ctx["organizer"], ctx["event"])
    ctx["event_version"] = ctx["event"]["version"]
    setup_paid_order(ctx, buyer=create_buyer(email="nia@example.com",
                                             display_name="Nia"), quantity=2)
    return ctx


def test_waitlist_join_accepted_when_the_tier_is_exactly_exhausted():
    """PRD §3.7: "A waitlist exists to capture demand that arrives after inventory is
    gone, and the platform is strict about that premise: a buyer may only join the
    queue for a tier that is *exactly* exhausted."
    PRD §3.7: "The entry is created in `WAITING` status with `claimed_order_id`,
    `offered_at` and `offer_expires_at` all null."

    Design: Difficulty/boundary_precision_check/waitlist_join_requires_availability_of_exactly_zero
    """
    ctx = _event_with_full_and_open_tiers()
    waiter = create_buyer(email="omar@example.com", display_name="Omar")

    entry = validate_success(join_waitlist(ctx, waiter, 2), 201)

    assert_waitlist_entry(entry)
    assert entry["status"] == "WAITING", f"Expected WAITING, got {entry['status']}"
    assert entry["requested_quantity"] == 2
    assert entry["claimed_order_id"] is None
    assert entry["offered_at"] is None
    assert entry["offer_expires_at"] is None
    assert read_ticket_type(ctx["tt_id"])["sold_count"] == 2


def test_waitlist_join_rejected_while_any_capacity_remains():
    """PRD §3.7: "If the tier's available quantity is greater than zero at that
    moment, the request is rejected with `ERR_CAPACITY_AVAILABLE` — the buyer should
    simply buy."

    Design: Difficulty/boundary_precision_check/waitlist_join_requires_availability_of_exactly_zero
    """
    ctx = _event_with_full_and_open_tiers()
    waiter = create_buyer(email="omar2@example.com", display_name="Omar Two")

    resp = api_client.create_waitlist_entry(
        create_waitlist_entry_payload(ctx["open_tier"]["id"], waiter["id"], 2),
        make_buyer_headers(waiter["id"]))
    validate_error(resp, ApiErrorId.ERR_CAPACITY_AVAILABLE.value, 409)

    rows, meta = validate_paginated(api_client.list_waitlist_entries(
        make_buyer_headers(waiter["id"]),
        params={"ticket_type_id": ctx["open_tier"]["id"]}))
    assert meta["total_count"] == 0, \
        f"A refused join queues nobody, got total_count {meta['total_count']}"


# ---------------------------------------------------------------------------
# The sweep
# ---------------------------------------------------------------------------

def test_sweep_offers_the_oldest_waiting_entry_first():
    """PRD §3.7: "Candidates are the entries still in `WAITING`, ranked by
    `created_at` ascending and tie-broken by `requested_quantity` ascending, and each
    candidate is offered only if its `requested_quantity` is less than or equal to the
    sweep's remaining capacity — a candidate too large for what remains is skipped
    rather than partially served, and a smaller candidate behind it may still be
    reached."
    PRD §3.7: "Offering an entry moves it `WAITING → OFFERED`, sets `offered_at` to
    the current time and `offer_expires_at` to twenty-four hours later, and increases
    the tier's `held_count` by the entry's `requested_quantity`, which is what stops
    the offered inventory from being bought out from under the queue."

    Design: Corner/endpoints/corner_waitlist_sweep_offers_oldest_entry_first
    """
    ctx = setup_sold_out_tier(quantity_total=2, clock="2026-07-05T10:00:00Z",
                              event_overrides={"title": "Fifo Night",
                                               "starts_at": "2026-10-14T18:00:00Z",
                                               "ends_at": "2026-10-14T22:00:00Z"})
    first_in_queue = setup_waitlist_entry(
        ctx, buyer=create_buyer(email="abe@example.com", display_name="Abe"),
        requested_quantity=1)
    second_in_queue = setup_waitlist_entry(
        ctx, buyer=create_buyer(email="bo@example.com", display_name="Bo"),
        requested_quantity=1)

    # Voiding one admission frees exactly one seat.
    void_attendee(ctx, ctx["paid"]["attendees"][0]["id"])
    report = run_waitlist_sweep(ctx)

    assert report["offered_count"] == 1, \
        f"One freed seat serves one candidate, got {report['offered_count']}"
    assert report["remaining_available"] == 0, \
        f"Expected the freed seat to be fully allocated, got {report['remaining_available']}"

    offered = read_waitlist_entry(first_in_queue["entry_id"], first_in_queue["buyer"])
    assert offered["status"] == "OFFERED", \
        f"The earlier entry is served first, got {offered['status']}"
    assert offered["offer_expires_at"].startswith("2026-07-06T10:00:00"), (
        "The offer deadline sits twenty-four hours after the sweep, got "
        f"{offered['offer_expires_at']}")

    skipped = read_waitlist_entry(second_in_queue["entry_id"], second_in_queue["buyer"])
    assert skipped["status"] == "WAITING", \
        f"The later entry stays queued, got {skipped['status']}"
    assert read_ticket_type(ctx["tt_id"])["held_count"] == 1, \
        "The offered inventory is held against the tier"


def test_stale_offer_expires_on_the_next_sweep_and_can_be_requeued():
    """PRD §3.7: "First it retires stale offers: every entry on the tier in `OFFERED`
    status whose `offer_expires_at` is at or before the current time is moved to
    `EXPIRED`, and the tier's `held_count` is decremented by that entry's
    `requested_quantity`."
    PRD §3.7: "Requeuing returns an entry from `EXPIRED` to `WAITING`, requires the
    entry to be in `EXPIRED` and the event to be in `ONSALE` or `PAUSED`, and clears
    both `offered_at` and `offer_expires_at` back to null."

    Design: Corner/state_machines/corner_waitlist_offer_expires_then_requeues_to_waiting
    """
    ctx = setup_offered_waitlist_entry(quantity_total=2, clock="2026-07-05T10:00:00Z",
                                       requested_quantity=1)
    waiting = ctx["waiting"]
    offered = read_waitlist_entry(waiting["entry_id"], waiting["buyer"])
    assert offered["status"] == "OFFERED"
    assert offered["offer_expires_at"].startswith("2026-07-06T10:00:00")

    # Twenty-five hours after the offer, its deadline has passed.
    set_clock("2026-07-06T11:00:00Z")
    run_waitlist_sweep(ctx)

    lapsed = read_waitlist_entry(waiting["entry_id"], waiting["buyer"])
    assert lapsed["status"] == "EXPIRED", \
        f"The stale offer is retired by the sweep, got {lapsed['status']}"

    requeued = validate_success(api_client.requeue_waitlist_entry(
        waiting["entry_id"], make_buyer_headers(waiting["buyer"]["id"])), 200)
    assert requeued["status"] == "WAITING"
    assert requeued["offer_expires_at"] is None
    assert requeued["offered_at"] is None
