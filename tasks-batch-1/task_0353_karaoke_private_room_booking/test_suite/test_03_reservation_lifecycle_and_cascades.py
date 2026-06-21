"""Reservation lifecycle branches and the cascades they drive: cancel/refund vs
no-show/forfeit, close release, expiry, deposit-ledger conservation, room occupancy
conservation.

Covers difficulty queue rules non_linear_state_machine / transitive_cascade /
compensating_invariant and the corner state_machines section.
"""
from test_helpers import (
    setup_base, create_held_reservation, confirm_reservation,
    create_confirmed_reservation, create_checked_in_reservation,
    create_song, queue_song, close_reservation, set_clock,
    run_ops, get_room, get_customer, get_queue_entry, list_payments,
    sum_amount_for_kind, payments_of_kind,
    make_customer_headers,
)


def test_confirmed_cancel_outside_cutoff_refunds(api):
    """PRD §3.7: "if the current venue time is at or before `slot_start_utc` minus the
    venue's `cancellation_cutoff_hours` (that is, the guest is cancelling outside the
    cutoff window), the deposit is returned by appending a `Payment` of kind `REFUND`
    whose `amount_cents` equals `deposit_cents`".

    Confirmed 20:00 slot (deposit 3600), cancelled >24h before -> CANCELLED, one REFUND
    of 3600, no FORFEIT.

    Design: Difficulty/non_linear_state_machine/reservation_confirmed_branch_cancel_vs_noshow_diverge
    """
    base = setup_base(
        room_type_overrides={"name": "LARGE", "capacity": 12, "base_hourly_rate_cents": 6000,
                             "fb_minimum_cents": 0},
        clock_utc="2026-07-08T09:00:00.000Z",
    )
    venue, room, customer = base["venue"], base["room"], base["customer"]
    res = create_confirmed_reservation(
        venue, room, customer,
        "2026-07-10T20:00:00.000Z", "2026-07-10T22:00:00.000Z",
        confirm_clock_utc=None, party_size=6,
    )
    assert res["deposit_cents"] == 3600
    set_clock(venue["id"], "2026-07-08T10:00:00.000Z")
    cancelled = api.cancel_reservation(res["id"], make_customer_headers(customer["id"]))
    from test_helpers import validate_success
    data = validate_success(cancelled, 200)
    assert data["status"] == "CANCELLED"

    payments = list_payments(res["id"])
    refunds = payments_of_kind(payments, "REFUND")
    assert len(refunds) == 1 and refunds[0]["amount_cents"] == 3600
    assert len(payments_of_kind(payments, "FORFEIT")) == 0


def test_cancel_inside_cutoff_forfeits_deposit(api):
    """PRD §3.7: "otherwise the guest is cancelling inside the cutoff and forfeits the
    deposit, recorded by appending a `Payment` of kind `FORFEIT` whose `amount_cents`
    equals `deposit_cents`".

    Confirmed 20:00 slot (deposit 3600), cancelled 2h before (inside 24h cutoff) ->
    one FORFEIT of 3600, no REFUND.

    Design: Corner/state_machines/cancel_inside_cutoff_forfeits_deposit
    """
    base = setup_base(
        room_type_overrides={"name": "LARGE", "capacity": 12, "base_hourly_rate_cents": 6000},
        clock_utc="2026-08-26T10:00:00.000Z",
    )
    venue, room, customer = base["venue"], base["room"], base["customer"]
    res = create_confirmed_reservation(
        venue, room, customer,
        "2026-08-26T20:00:00.000Z", "2026-08-26T22:00:00.000Z",
        confirm_clock_utc=None, party_size=4,
    )
    assert res["deposit_cents"] == 3600
    set_clock(venue["id"], "2026-08-26T18:00:00.000Z")
    from test_helpers import validate_success
    data = validate_success(api.cancel_reservation(res["id"], make_customer_headers(customer["id"])), 200)
    assert data["status"] == "CANCELLED"

    payments = list_payments(res["id"])
    forfeits = payments_of_kind(payments, "FORFEIT")
    assert len(forfeits) == 1 and forfeits[0]["amount_cents"] == 3600
    assert len(payments_of_kind(payments, "REFUND")) == 0


def test_noshow_sweep_branch_forfeits_and_strikes(api):
    """PRD §3.7: "it transitions `CONFIRMED → NO_SHOW`, the deposit is forfeited by
    appending a `Payment` of kind `FORFEIT` whose `amount_cents` equals `deposit_cents`,
    the booking party's `no_show_strikes` is incremented by 1 ... its `PENDING` queue
    entries cascade to `CANCELLED`".

    Confirmed, clock past slot_start + grace, ops sweep -> NO_SHOW, FORFEIT 3600,
    no_show_strikes 1, PENDING queue entry CANCELLED. This is the divergent (no-show)
    branch from CONFIRMED relative to the refund-cancel branch.

    Design: Difficulty/non_linear_state_machine/reservation_confirmed_branch_cancel_vs_noshow_diverge
    """
    base = setup_base(
        room_type_overrides={"name": "LARGE", "capacity": 12, "base_hourly_rate_cents": 6000,
                             "fb_minimum_cents": 0},
        clock_utc="2026-07-12T19:00:00.000Z",
    )
    venue, room, customer = base["venue"], base["room"], base["customer"]
    song = create_song(venue["id"], title="Song X", artist="X")
    res = create_confirmed_reservation(
        venue, room, customer,
        "2026-07-12T20:00:00.000Z", "2026-07-12T22:00:00.000Z",
        confirm_clock_utc=None, party_size=6,
    )
    q = queue_song(res, customer, song["id"], priority=5)
    set_clock(venue["id"], "2026-07-12T20:16:00.000Z")
    run_ops(venue["id"])

    from test_helpers import get_reservation
    assert get_reservation(res["id"])["status"] == "NO_SHOW"
    assert get_customer(customer["id"])["no_show_strikes"] == 1
    assert get_queue_entry(q["id"])["status"] == "CANCELLED"
    forfeits = payments_of_kind(list_payments(res["id"]), "FORFEIT")
    assert len(forfeits) == 1 and forfeits[0]["amount_cents"] == 3600


def test_noshow_cascade_depth3(api):
    """PRD §3.7: "it transitions `CONFIRMED → NO_SHOW`, the deposit is forfeited by
    appending a `Payment` of kind `FORFEIT` whose `amount_cents` equals `deposit_cents`,
    the booking party's `no_show_strikes` is incremented by 1 (and that count, by
    definition, equals the number of that customer's reservations now in `NO_SHOW`), its
    `PENDING` queue entries cascade to `CANCELLED`".

    A single ops trigger drives reservation->NO_SHOW, Payment{FORFEIT,3600} +
    Customer.no_show_strikes++, and the queue entry -> CANCELLED.

    Design: Difficulty/transitive_cascade/noshow_cascade_payment_customer_queue_depth3
    """
    base = setup_base(
        room_type_overrides={"name": "LARGE", "capacity": 12, "base_hourly_rate_cents": 6000,
                             "fb_minimum_cents": 0},
        clock_utc="2026-07-12T19:00:00.000Z",
    )
    venue, room, customer = base["venue"], base["room"], base["customer"]
    song = create_song(venue["id"], title="Song X", artist="X")
    res = create_confirmed_reservation(
        venue, room, customer,
        "2026-07-12T20:00:00.000Z", "2026-07-12T22:00:00.000Z",
        confirm_clock_utc=None, party_size=6,
    )
    q = queue_song(res, customer, song["id"], priority=5)
    set_clock(venue["id"], "2026-07-12T20:16:00.000Z")
    run_ops(venue["id"])

    from test_helpers import get_reservation
    assert get_reservation(res["id"])["status"] == "NO_SHOW"
    assert get_customer(customer["id"])["no_show_strikes"] == 1
    assert get_queue_entry(q["id"])["status"] == "CANCELLED"
    forfeits = payments_of_kind(list_payments(res["id"]), "FORFEIT")
    assert len(forfeits) == 1 and forfeits[0]["amount_cents"] == 3600


def test_close_cascade_room_release_depth2(api):
    """PRD §3.4: "A successful close transitions the reservation `CHECKED_IN → CLOSED`,
    records `actual_end_utc`, recomputes the settled room subtotal, recomputes the
    food-and-beverage figures, computes the final total, appends a settlement payment,
    force-skips any songs still waiting in the queue, frees the room".
    PRD §3.4: "every still-`PENDING` `QueueEntry` on the reservation cascades to
    `SKIPPED` ... the room moves `OCCUPIED → AVAILABLE`".

    Close drives reservation->CLOSED, room OCCUPIED->AVAILABLE, PENDING queue->SKIPPED.

    Design: Difficulty/transitive_cascade/close_cascade_room_release_depth2
    """
    base = setup_base(
        room_type_overrides={"name": "LARGE", "capacity": 12, "base_hourly_rate_cents": 6000,
                             "fb_minimum_cents": 0},
        clock_utc="2026-07-13T19:00:00.000Z",
    )
    venue, room, customer = base["venue"], base["room"], base["customer"]
    song = create_song(venue["id"], title="Song Y", artist="Y")
    res = create_checked_in_reservation(
        venue, room, customer,
        "2026-07-13T20:00:00.000Z", "2026-07-13T22:00:00.000Z",
        checkin_clock_utc="2026-07-13T20:00:00.000Z",
    )
    q = queue_song(res, customer, song["id"], priority=5)
    closed = close_reservation(res, "2026-07-13T21:30:00.000Z")
    assert closed["status"] == "CLOSED"
    assert get_room(room["id"])["status"] == "AVAILABLE"
    assert get_queue_entry(q["id"])["status"] == "SKIPPED"


def test_queue_skip_head_promotes_next(api):
    """PRD §3.6: "A `FrontDesk` operator may also skip a `PENDING` entry, moving it
    `PENDING → SKIPPED`; ... both recompute `play_order` over the remaining `PENDING`
    entries".

    Two entries (S1 priority 10 head, S2 priority 20). Skipping the head leaves S2
    PENDING and promotes it to play_order 1 — the PENDING fork distinct from a play.

    Design: Difficulty/non_linear_state_machine/queue_entry_pending_branch_play_vs_skip_diverge
    """
    base = setup_base(
        room_type_overrides={"name": "LARGE", "capacity": 12, "base_hourly_rate_cents": 6000,
                             "fb_minimum_cents": 0},
        clock_utc="2026-07-11T19:00:00.000Z",
    )
    venue, room, customer = base["venue"], base["room"], base["customer"]
    s1 = create_song(venue["id"], title="Song One", artist="A")
    s2 = create_song(venue["id"], title="Song Two", artist="B")
    res = create_checked_in_reservation(
        venue, room, customer,
        "2026-07-11T20:00:00.000Z", "2026-07-11T22:00:00.000Z",
        checkin_clock_utc="2026-07-11T20:00:00.000Z",
    )
    q1 = queue_song(res, customer, s1["id"], priority=10)
    q2 = queue_song(res, customer, s2["id"], priority=20)

    from test_helpers import validate_success
    skipped = validate_success(api.skip_queue_entry(q1["id"], _fd()), 200)
    assert skipped["status"] == "SKIPPED"
    q2_after = get_queue_entry(q2["id"])
    assert q2_after["status"] == "PENDING"
    assert q2_after["play_order"] == 1


def test_held_reservation_expires_on_ops_run(api):
    """PRD §3.7: "any reservation still `HELD` whose `slot_start_utc` has already passed
    (the current venue time is strictly after `slot_start_utc`) — a hold that was never
    confirmed — is expired: it transitions `HELD → EXPIRED`, its `PENDING` queue entries
    cascade to `CANCELLED`, and its `version` is incremented by 1."

    HELD reservation with a PENDING queue entry, clock past slot_start, ops -> EXPIRED
    and the queue entry CANCELLED.

    Design: Corner/state_machines/held_reservation_expires_on_ops_run_after_slot_start
    """
    base = setup_base(
        room_type_overrides={"name": "LARGE", "capacity": 12, "base_hourly_rate_cents": 6000},
        clock_utc="2026-08-25T19:00:00.000Z",
    )
    venue, room, customer = base["venue"], base["room"], base["customer"]
    song = create_song(venue["id"], title="S", artist="A")
    res = create_held_reservation(venue, room, customer,
                                  "2026-08-25T20:00:00.000Z", "2026-08-25T22:00:00.000Z",
                                  party_size=4)
    q = queue_song(res, customer, song["id"], priority=5)
    set_clock(venue["id"], "2026-08-25T20:01:00.000Z")
    run_ops(venue["id"])

    from test_helpers import get_reservation
    assert get_reservation(res["id"])["status"] == "EXPIRED"
    assert get_queue_entry(q["id"])["status"] == "CANCELLED"


def test_cancel_held_reservation_no_payment(api):
    """PRD §3.7: "Cancelling a `HELD` reservation simply transitions it
    `HELD → CANCELLED`; because no deposit is ever collected at the held stage, no
    payment is appended, and any `PENDING` queue entries on the reservation cascade to
    `CANCELLED`".

    Cancelling a never-confirmed HELD reservation leaves an empty payment ledger.

    Design: Corner/state_machines/cancel_held_reservation_no_payment_appended
    """
    base = setup_base(
        room_type_overrides={"name": "LARGE", "capacity": 12, "base_hourly_rate_cents": 6000},
        clock_utc="2026-08-06T10:00:00.000Z",
    )
    venue, room, customer = base["venue"], base["room"], base["customer"]
    res = create_held_reservation(venue, room, customer,
                                  "2026-08-06T20:00:00.000Z", "2026-08-06T22:00:00.000Z",
                                  party_size=4)
    from test_helpers import validate_success
    data = validate_success(api.cancel_reservation(res["id"], make_customer_headers(customer["id"])), 200)
    assert data["status"] == "CANCELLED"
    assert list_payments(res["id"]) == []


def test_deposit_refund_ledger_nets_to_zero(api):
    """PRD §3.3: "appends a deposit payment event (a `Payment` of kind `DEPOSIT` whose
    `amount_cents` equals `deposit_cents`)".
    PRD §3.7: "the deposit is returned by appending a `Payment` of kind `REFUND` whose
    `amount_cents` equals `deposit_cents`".

    Confirm appends DEPOSIT 3600; cancel-outside-cutoff appends REFUND 3600; the
    conserved net (DEPOSIT - REFUND) is 0 and no FORFEIT exists.

    Design: Difficulty/compensating_invariant/deposit_refund_ledger_nets_to_zero
    """
    base = setup_base(
        room_type_overrides={"name": "LARGE", "capacity": 12, "base_hourly_rate_cents": 6000,
                             "fb_minimum_cents": 0},
        clock_utc="2026-07-20T09:00:00.000Z",
    )
    venue, room, customer = base["venue"], base["room"], base["customer"]
    res = create_confirmed_reservation(
        venue, room, customer,
        "2026-07-22T20:00:00.000Z", "2026-07-22T22:00:00.000Z",
        confirm_clock_utc=None, party_size=6,
    )
    assert res["deposit_cents"] == 3600
    from test_helpers import validate_success
    validate_success(api.cancel_reservation(res["id"], make_customer_headers(customer["id"])), 200)

    payments = list_payments(res["id"])
    assert sum_amount_for_kind(payments, "DEPOSIT") == 3600
    assert sum_amount_for_kind(payments, "DEPOSIT") - sum_amount_for_kind(payments, "REFUND") == 0


def test_room_occupancy_conserved_checkin_close(api):
    """PRD §3.4: "drives the room from `AVAILABLE → OCCUPIED`".
    PRD §3.4: "the room moves `OCCUPIED → AVAILABLE`".

    Check-in occupies the room; close frees it, so the room returns to AVAILABLE after
    the round trip (the occupancy count is conserved).

    Design: Difficulty/compensating_invariant/room_occupancy_conserved_checkin_close
    """
    base = setup_base(
        room_type_overrides={"name": "LARGE", "capacity": 12, "base_hourly_rate_cents": 6000,
                             "fb_minimum_cents": 0},
        clock_utc="2026-07-23T19:00:00.000Z",
    )
    venue, room, customer = base["venue"], base["room"], base["customer"]
    res = create_checked_in_reservation(
        venue, room, customer,
        "2026-07-23T20:00:00.000Z", "2026-07-23T22:00:00.000Z",
        checkin_clock_utc="2026-07-23T20:00:00.000Z",
    )
    assert get_room(room["id"])["status"] == "OCCUPIED"
    closed = close_reservation(res, "2026-07-23T21:30:00.000Z")
    assert closed["status"] == "CLOSED"
    assert get_room(room["id"])["status"] == "AVAILABLE"


def test_new_reservation_starts_in_held(api):
    """PRD §3.3: "A reservation is born in `HELD` status at `version` 1."

    Design: Corner/state_machines/new_reservation_starts_in_held
    """
    base = setup_base(
        room_type_overrides={"name": "LARGE", "capacity": 12, "base_hourly_rate_cents": 6000},
        clock_utc="2026-08-04T10:00:00.000Z",
    )
    venue, room, customer = base["venue"], base["room"], base["customer"]
    res = create_held_reservation(venue, room, customer,
                                  "2026-08-04T20:00:00.000Z", "2026-08-04T22:00:00.000Z",
                                  party_size=4)
    assert res["status"] == "HELD"
    assert res["version"] == 1


def _fd():
    from test_helpers import make_front_desk_headers
    return make_front_desk_headers()
