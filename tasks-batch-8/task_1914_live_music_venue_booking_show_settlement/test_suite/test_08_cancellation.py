"""Cancellation policy branches, cascade side effects, deposit returns."""
from test_helpers import (
    ACCT,
    PROM,
    VM,
    ApiErrorId,
    assert_cancellation_event,
    cancel_show,
    create_agent,
    create_artist,
    create_confirmed_show,
    create_offer,
    create_on_sale_show,
    create_show_with_deal,
    create_support,
    get_show,
    make_booking_agent_headers,
    pay_deposit,
    place_on_sale,
    postpone_show,
    sell_tickets,
    set_clock,
    submit_settlement,
    create_draft_settlement,
    accept_offer,
    create_tier,
    validate_error,
    validate_paginated,
    validate_success,
)


def _build_confirmed_with_deposit(artist, agent, show_overrides,
                                  offer_overrides, deposit_amount):
    """Build a show in CONFIRMED with an accepted deal and a paid deposit."""
    show, _hold = create_confirmed_show(artist["id"], agent, **show_overrides)
    offer = create_offer(
        show["id"], as_role="BOOKING_AGENT", agent=agent, **offer_overrides,
    )
    accept_offer(show["id"], offer["id"], as_role="VENUE_MANAGER")
    # PRD §3.8 requires a strictly positive amount_cents, so a zero deposit
    # (e.g. an artist with deposit_pct=0.0) means no wire is issued at all.
    wire = None
    if deposit_amount > 0:
        wire = pay_deposit(show["id"], artist["id"], deposit_amount)
    return show, offer, wire


def test_cancellation_policy_artist_vs_force_majeure(api):
    """PRD §3.9: "The artist penalty applies only when the reason is
    `ARTIST`, and it slides with notice: cancelling at least sixty days out
    carries no penalty; at least thirty but fewer than sixty days costs
    twenty-five percent of the deal's guarantee; at least fourteen but
    fewer than thirty costs fifty percent; at least seven but fewer than
    fourteen costs seventy-five percent; and fewer than seven days costs
    the full guarantee."
    PRD §3.9: "Under `ARTIST`, the deposit stays with the artist and
    `deposit_refundable_cents` is zero; the artist forfeits the lesser of
    the deposit actually paid and the penalty, and any penalty above the
    deposit remains owed by the artist but is not auto-collected."
    PRD §3.9: "Under `FORCE_MAJEURE`, no penalties run in either direction,
    the full `deposit_paid_cents` becomes refundable to the venue —
    `deposit_refundable_cents` equals the paid amount — and the show's
    `weather_or_emergency_flag` is set."

    Design: Difficulty/dual_variant_calc/cancellation_policy_artist_vs_force_majeure
    """
    set_clock()
    artist = create_artist(guarantee_floor_cents=50000, deposit_pct=0.25)
    agent = create_agent()
    offer_kw = dict(
        deal_kind="FLAT_GUARANTEE", guarantee_cents=100000,
        artist_split_pct=0, versus_threshold_cents=0,
        expense_budget_cents=10000, support_budget_cents=0,
        bar_split_pct=0.10, merch_split_pct=0.20,
    )
    s1, _, _ = _build_confirmed_with_deposit(
        artist, agent,
        dict(room="MAIN_ROOM", show_date="2026-09-15",
             doors_at_utc="2026-09-15T19:00:00Z",
             curfew_at_utc="2026-09-15T23:00:00Z",
             total_capacity=500, on_sale_at_utc="2026-08-15T10:00:00Z"),
        offer_kw, 25000,
    )
    s2, _, _ = _build_confirmed_with_deposit(
        artist, agent,
        dict(room="LOUNGE", show_date="2026-09-15",
             doors_at_utc="2026-09-15T19:00:00Z",
             curfew_at_utc="2026-09-15T23:00:00Z",
             total_capacity=200, on_sale_at_utc="2026-08-15T10:00:00Z"),
        offer_kw, 25000,
    )
    # 2026-08-26 is 20 days before 2026-09-15 → 14 <= 20 < 30 → penalty 0.50.
    set_clock("2026-08-26T12:00:00Z")

    ev1 = cancel_show(s1["id"], reason="ARTIST", as_role="BOOKING_AGENT",
                      agent=agent)
    assert_cancellation_event(ev1)
    assert ev1["artist_penalty_pct"] == 0.50
    assert ev1["artist_penalty_cents"] == 50000  # 0.50 × 100000
    assert ev1["deposit_refundable_cents"] == 0

    ev2 = cancel_show(s2["id"], reason="FORCE_MAJEURE", as_role="VENUE_MANAGER")
    assert_cancellation_event(ev2)
    assert ev2["artist_penalty_pct"] == 0.0
    assert ev2["artist_penalty_cents"] == 0
    assert ev2["deposit_refundable_cents"] == 25000


def test_cancellation_artist_penalty_sliding_scale_boundaries(api):
    """PRD §3.9: "cancelling at least sixty days out carries no penalty; at
    least thirty but fewer than sixty days costs twenty-five percent of the
    deal's guarantee; at least fourteen but fewer than thirty costs fifty
    percent; at least seven but fewer than fourteen costs seventy-five
    percent; and fewer than seven days costs the full guarantee."

    Design: Difficulty/dual_variant_calc/cancellation_policy_artist_vs_force_majeure
    """
    set_clock()
    artist = create_artist(guarantee_floor_cents=10000, deposit_pct=0.0)
    agent = create_agent()
    offer_kw = dict(
        deal_kind="FLAT_GUARANTEE", guarantee_cents=100000,
        artist_split_pct=0, versus_threshold_cents=0,
        expense_budget_cents=10000, support_budget_cents=0,
        bar_split_pct=0, merch_split_pct=0,
    )
    # Build 5 shows, all targeting show_date = 2026-12-31.
    # Cancellation on:
    #   2026-11-01 → 60 days out → 0.00
    #   2026-12-01 → 30 days out → 0.25
    #   2026-12-17 → 14 days out → 0.50
    #   2026-12-24 → 7 days out → 0.75
    #   2026-12-30 → 1 day out → 1.00
    cases = [
        ("2026-11-01T12:00:00Z", 0.00, 0),
        ("2026-12-01T12:00:00Z", 0.25, 25000),
        ("2026-12-17T12:00:00Z", 0.50, 50000),
        ("2026-12-24T12:00:00Z", 0.75, 75000),
        ("2026-12-30T12:00:00Z", 1.00, 100000),
    ]
    rooms = ["MAIN_ROOM", "LOUNGE"]
    for idx, (cancel_at, expected_pct, expected_cents) in enumerate(cases):
        # Alternate rooms and shift show_date by idx days to avoid cross-show
        # hold contention on the same (room, date).
        show_date = f"2026-12-{31 - idx:02d}" if idx < 4 else "2026-12-31"
        # Use per-case show_date to keep (room, date) pairs distinct.
        day = 10 + idx  # 2026-12-10, -11, -12, -13, -14
        show_date = f"2026-12-{day:02d}"
        s, _, _ = _build_confirmed_with_deposit(
            artist, agent,
            dict(room=rooms[idx % 2], show_date=show_date,
                 doors_at_utc=f"{show_date}T19:00:00Z",
                 curfew_at_utc=f"{show_date}T23:00:00Z",
                 total_capacity=200, on_sale_at_utc="2026-08-15T10:00:00Z"),
            offer_kw, 0,
        )
        # Recompute cancellation clock so days_before_show matches the case.
        # For case idx, choose cancel clock = show_date - N days.
        # days_before_show is floor calendar days from declaration date to
        # show_date. We pick declaration dates that hit the tier exactly:
        #  ≥60: cancel 2026-10-11 (60 days before 2026-12-10)
        #  ≥30: cancel 2026-11-11 (30 days before 2026-12-11)
        #  ≥14: cancel 2026-11-28 (14 days before 2026-12-12)
        #  ≥7:  cancel 2026-12-06 (7 days before 2026-12-13)
        #  <7:  cancel 2026-12-13 (1 day before 2026-12-14)
        cancel_clock = [
            "2026-10-11T12:00:00Z",
            "2026-11-11T12:00:00Z",
            "2026-11-28T12:00:00Z",
            "2026-12-06T12:00:00Z",
            "2026-12-13T12:00:00Z",
        ][idx]
        set_clock(cancel_clock)
        ev = cancel_show(s["id"], reason="ARTIST", as_role="VENUE_MANAGER")
        assert ev["artist_penalty_pct"] == expected_pct, (
            f"case {idx}: expected pct {expected_pct}, got {ev['artist_penalty_pct']}"
        )
        assert ev["artist_penalty_cents"] == expected_cents


def test_cancel_refunds_tickets_and_cancels_supports(api):
    """PRD §3.9: "Every ticket sale not already refunded is refunded —
    `refund_status` moves from `NONE` to `REFUNDED` — and the show's
    `tickets_sold` and revenue counters are recomputed. Every `CONFIRMED`
    support act moves to `CANCELLED`, and for each of them a
    `SUPPORT_BUYOUT` wire for the kill fee is initiated when the reason is
    `ARTIST`, `VENUE`, or `LOW_TICKET_SALES`; a `FORCE_MAJEURE` cancellation
    initiates none."

    Design: Difficulty/transitive_cascade/cancel_refunds_tickets_and_cancels_supports
    """
    set_clock()
    artist, agent, show, deal, tier = create_on_sale_show(
        offer_overrides=dict(
            deal_kind="FLAT_GUARANTEE", guarantee_cents=50000,
            artist_split_pct=0, versus_threshold_cents=0,
            expense_budget_cents=10000, support_budget_cents=20000,
            bar_split_pct=0, merch_split_pct=0,
        ),
        show_overrides=dict(room="LOUNGE", show_date="2026-10-15",
                            doors_at_utc="2026-10-15T19:00:00Z",
                            curfew_at_utc="2026-10-15T23:00:00Z",
                            total_capacity=200),
        tier_overrides=dict(face_price_cents=2000, capacity=200, tier_order=1),
    )
    sale = sell_tickets(show["id"], tier["id"], 10)
    support = create_support(
        show["id"], artist_name="Opener X",
        agreed_fee_cents=8000, buyout_fee_cents=6000,
    )

    ev = cancel_show(show["id"], reason="VENUE", as_role="VENUE_MANAGER")
    assert ev["reason"] == "VENUE"

    # Link 1: show CANCELLED, counters recomputed
    show_after = get_show(show["id"])
    assert show_after["status"] == "CANCELLED"
    assert show_after["tickets_sold"] == 0
    assert show_after["gross_ticket_revenue_cents"] == 0

    # Ticket sale flipped
    sale_after = validate_success(
        api.get_show_ticket_sale(show["id"], sale["id"], PROM), 200,
    )
    assert sale_after["refund_status"] == "REFUNDED"

    # Link 2: support act CANCELLED
    support_after = validate_success(
        api.get_support_act(show["id"], support["id"], PROM), 200,
    )
    assert support_after["status"] == "CANCELLED"

    # Link 3: a SUPPORT_BUYOUT wire for the kill fee = 0.5 × 8000 = 4000.
    wires, _ = validate_paginated(
        api.list_show_wire_transfers(
            show["id"], PROM, params={"purpose": "SUPPORT_BUYOUT"},
        )
    )
    buyout_wires = [w for w in wires if w["support_act_id"] == support["id"]]
    assert buyout_wires, "expected a SUPPORT_BUYOUT wire for the cancelled act"
    assert buyout_wires[0]["amount_cents"] == 4000
    assert buyout_wires[0]["status"] == "INITIATED"


def test_cancel_cascade_refunds_and_voids_deal(api):
    """PRD §3.9: "The show's deal is voided, its `status` moving from
    `ACTIVE` to `VOID`."

    Design: Difficulty/transitive_cascade/cancel_refunds_tickets_and_cancels_supports
    """
    set_clock()
    artist, agent, show, deal, tier = create_on_sale_show(
        offer_overrides=dict(
            deal_kind="FLAT_GUARANTEE", guarantee_cents=50000,
            artist_split_pct=0, versus_threshold_cents=0,
            expense_budget_cents=10000, support_budget_cents=0,
            bar_split_pct=0, merch_split_pct=0,
        ),
        show_overrides=dict(room="MAIN_ROOM", show_date="2026-10-16",
                            doors_at_utc="2026-10-16T19:00:00Z",
                            curfew_at_utc="2026-10-16T23:00:00Z"),
    )
    cancel_show(show["id"], reason="VENUE", as_role="VENUE_MANAGER")
    deal_after = validate_success(api.get_deal(deal["id"], VM), 200)
    assert deal_after["status"] == "VOID"


def test_wire_deposit_return_conserves_artist_cash_position(api):
    """PRD §3.8: "One special unwind exists for cancelled shows: a
    `COMPLETED` wire whose purpose is `ARTIST_DEPOSIT` may be marked
    `RETURNED` when the show is `CANCELLED`, subtracting the amount back
    out of the show's `deposit_paid_cents`."

    Design: Difficulty/compensating_invariant/wire_deposit_return_conserves_artist_cash_position
    """
    set_clock()
    artist = create_artist(deposit_pct=0.25, guarantee_floor_cents=10000)
    agent = create_agent()
    show, _hold = create_confirmed_show(
        artist["id"], agent,
        room="MAIN_ROOM", show_date="2026-12-15",
        doors_at_utc="2026-12-15T19:00:00Z",
        curfew_at_utc="2026-12-15T23:00:00Z",
        total_capacity=500, on_sale_at_utc="2026-08-10T10:00:00Z",
    )
    offer = create_offer(
        show["id"], as_role="BOOKING_AGENT", agent=agent,
        deal_kind="FLAT_GUARANTEE", guarantee_cents=100000,
        artist_split_pct=0, versus_threshold_cents=0,
        expense_budget_cents=10000, support_budget_cents=0,
        bar_split_pct=0, merch_split_pct=0,
    )
    accept_offer(show["id"], offer["id"], as_role="VENUE_MANAGER")
    wire = pay_deposit(show["id"], artist["id"], 25000)

    # After deposit completion
    assert get_show(show["id"])["deposit_paid_cents"] == 25000

    # Cancel under FORCE_MAJEURE and mark the deposit wire RETURNED.
    cancel_show(show["id"], reason="FORCE_MAJEURE", as_role="VENUE_MANAGER")
    returned = validate_success(
        api.mark_wire_transfer_returned(show["id"], wire["id"], ACCT), 200,
    )
    assert returned["status"] == "RETURNED"

    show_after = get_show(show["id"])
    assert show_after["deposit_paid_cents"] == 0


def test_wire_return_only_defined_for_artist_deposit_on_cancelled_show(api):
    """PRD §3.8: "One special unwind exists for cancelled shows: a
    `COMPLETED` wire whose purpose is `ARTIST_DEPOSIT` may be marked
    `RETURNED` when the show is `CANCELLED`, subtracting the amount back out
    of the show's `deposit_paid_cents`."

    Design: Difficulty/compensating_invariant/wire_deposit_return_conserves_artist_cash_position
    """
    set_clock()
    artist = create_artist(deposit_pct=0.25, guarantee_floor_cents=10000)
    agent = create_agent()
    show, _hold = create_confirmed_show(artist["id"], agent)
    offer = create_offer(
        show["id"], as_role="BOOKING_AGENT", agent=agent,
        deal_kind="FLAT_GUARANTEE", guarantee_cents=100000,
    )
    accept_offer(show["id"], offer["id"], as_role="VENUE_MANAGER")
    wire = pay_deposit(show["id"], artist["id"], 25000)
    # Without cancellation, mark-returned is invalid state.
    resp = api.mark_wire_transfer_returned(show["id"], wire["id"], ACCT)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)


def test_cancel_postponed_show_no_double_refund(api):
    """PRD §3.9: "A postponed show can still be cancelled afterward by a
    `VenueManager`; that cancellation records its event like any other but
    issues no further ticket refunds, because the tickets were already
    refunded when the show was postponed."

    Design: Corner/state_machines/cancel_postponed_show_no_double_refund
    """
    set_clock()
    artist, agent, show, deal, tier = create_on_sale_show(
        offer_overrides=dict(
            deal_kind="FLAT_GUARANTEE", guarantee_cents=50000,
            artist_split_pct=0, versus_threshold_cents=0,
            expense_budget_cents=5000, support_budget_cents=0,
            bar_split_pct=0.10, merch_split_pct=0.20,
        ),
        show_overrides=dict(room="MAIN_ROOM", show_date="2026-12-28",
                            doors_at_utc="2026-12-28T19:00:00Z",
                            curfew_at_utc="2026-12-28T23:00:00Z",
                            total_capacity=100),
        tier_overrides=dict(face_price_cents=2000, capacity=100, tier_order=1),
    )
    sell_tickets(show["id"], tier["id"], 5)
    new_show = postpone_show(show["id"])
    assert new_show["status"] == "HOLD_PENDING"
    # After postpone, tickets are refunded.
    assert get_show(show["id"])["tickets_sold"] == 0

    # Cancel the postponed show.
    cancel_show(show["id"], reason="VENUE", as_role="VENUE_MANAGER")
    after = get_show(show["id"])
    assert after["status"] == "CANCELLED"
    # Still zero — no double refund.
    assert after["tickets_sold"] == 0


def test_low_sales_threshold_boundary(api):
    """PRD §3.9: "`LOW_TICKET_SALES` is valid only while the show is
    `ON_SALE` and the show's `tickets_sold` is strictly below thirty
    percent of `total_capacity` rounded up to the next whole number;
    otherwise the cancellation is rejected with
    `ERR_LOW_SALES_THRESHOLD_NOT_MET` (HTTP 422)."

    Design: Corner/validations/low_sales_threshold_boundary
    """
    set_clock()
    # capacity=100 → ceil(0.30 * 100) = 30. Selling exactly 30 must fail.
    artist, agent, show, deal, tier = create_on_sale_show(
        offer_overrides=dict(
            deal_kind="FLAT_GUARANTEE", guarantee_cents=50000,
            artist_split_pct=0, versus_threshold_cents=0,
            expense_budget_cents=5000, support_budget_cents=0,
            bar_split_pct=0.10, merch_split_pct=0.20,
        ),
        show_overrides=dict(room="MAIN_ROOM", show_date="2027-02-10",
                            doors_at_utc="2027-02-10T19:00:00Z",
                            curfew_at_utc="2027-02-10T23:00:00Z",
                            total_capacity=100),
        tier_overrides=dict(face_price_cents=2000, capacity=100, tier_order=1),
    )
    sell_tickets(show["id"], tier["id"], 30)
    resp = api.cancel_show(show["id"], {"reason": "LOW_TICKET_SALES"}, PROM)
    validate_error(resp, ApiErrorId.ERR_LOW_SALES_THRESHOLD_NOT_MET, 422)
