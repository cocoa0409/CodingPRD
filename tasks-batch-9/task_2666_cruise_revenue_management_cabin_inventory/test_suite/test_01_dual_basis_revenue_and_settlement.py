"""
Quantities the PRD deliberately publishes twice, on two different bases.

Two of them exist. RALBD is divided by two capacity denominators in the same
response (PRD 3.9), and the cancellation penalty is evaluated at two different
instants with only the second one moving cash (PRD 3.6).
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    ERR_BOOKING_NOT_AWAITING_SETTLEMENT,
    REVENUE_MANAGER,
    assert_instant_equals,
    fixtures as fx,
)

GROUP_FARE = {
    "window_open_days_to_sail": 730,
    "window_close_days_to_sail": 0,
    "base_lower_berth_fare_cents": 150000,
    "third_berth_fare_cents": 50000,
    "fourth_berth_fare_cents": 40000,
}


def _group_held_world(api):
    """A 10-berth / 4-night voyage with 5 IA cabins, 2 of them fenced by a block.

    PRD 3.9: "available_lower_berth_days_net first computes group_held_lower_berths
    as the sum, across every allotment of the sailing, of that allotment's
    group_held_cabins multiplied by its cabin category's lower_berths".
    """
    world = fx.simple_world(
        api,
        voyage_code="GRP-2701",
        nights=4,
        total_lower_berths=10,
        physical_cabins=5,
        oversell_allowance=0,
        fare_overrides=GROUP_FARE,
    )
    world.block = fx.make_group_block(
        api,
        world.sailing["id"],
        world.category["id"],
        cabins_held=2,
        review_date="2026-09-15T00:00:00Z",
        release_policy="ATTRITION_50",
    )
    world.pair = fx.guest_with_booking(api, world)
    return world


def test_revenue_summary_divides_one_revenue_total_by_both_capacity_bases(api):
    """One revenue total, two denominators, two RALBD figures.

    PRD 3.9: "available_lower_berth_days_gross is total_lower_berths multiplied
    by nights: every lower berth on the ship counts as sellable whether or not
    it is fenced inside a group hold." And: "Each variant is then a single
    division of total revenue by its own denominator, rounded half up exactly
    once, written to ralbd_gross_cents and ralbd_net_cents respectively."

    Design: Difficulty/dual_variant_calc/ralbd_gross_versus_net_capacity_basis_on_group_held_sailing
    """
    world = _group_held_world(api)

    summary = validate_success(
        api.revenue_summary(world.sailing["id"], REVENUE_MANAGER)
    )

    assert summary["gross_ticket_revenue_cents"] == 300000
    assert summary["projected_onboard_revenue_cents"] == 72000
    assert summary["compensation_liability_cents"] == 0
    # 10 lower berths x 4 nights on the gross basis; the 2 fenced cabins carry
    # 2 lower berths each, so the net basis loses 4 berths over 4 nights.
    assert summary["available_lower_berth_days_gross"] == 40
    assert summary["available_lower_berth_days_net"] == 24
    assert summary["ralbd_gross_cents"] == 9300
    assert summary["ralbd_net_cents"] == 15500
    assert summary["ralbd_net_cents"] - summary["ralbd_gross_cents"] == 6200
    # PRD 3.9: the alert "always reads the net variant, never the gross one",
    # and 15500 is strictly below the 20,000-cent floor.
    assert summary["revenue_alert"] is True

    inventory = fx.read_inventory(api, world.inventory["id"])
    assert inventory["group_held_cabins"] == 2
    assert inventory["available_cabins"] == 2


def test_without_a_group_fence_the_two_capacity_bases_coincide(api):
    """With nothing fenced, the net denominator equals the gross one.

    PRD 3.9: "The net basis strips out capacity the revenue manager cannot
    transact against, so whenever any group cabins are held the net figure is at
    least the gross figure." With no block on the sailing there is nothing to
    strip, so both denominators and both RALBD figures agree.

    Design: Difficulty/dual_variant_calc/ralbd_gross_versus_net_capacity_basis_on_group_held_sailing
    """
    world = fx.simple_world(
        api,
        voyage_code="GRP-2702",
        nights=4,
        total_lower_berths=10,
        physical_cabins=5,
        oversell_allowance=0,
        fare_overrides=GROUP_FARE,
    )
    fx.guest_with_booking(api, world)

    summary = validate_success(
        api.revenue_summary(world.sailing["id"], REVENUE_MANAGER)
    )

    assert summary["available_lower_berth_days_gross"] == 40
    assert summary["available_lower_berth_days_net"] == 40
    assert summary["ralbd_gross_cents"] == 9300
    assert summary["ralbd_net_cents"] == 9300
    assert summary["revenue_alert"] is True

    inventory = fx.read_inventory(api, world.inventory["id"])
    assert inventory["group_held_cabins"] == 0


def _gold_guest_paid_in_full(api):
    """A GOLD guest's fully paid 3-guest booking on AUR-2701, net 361531.

    PRD 3.4 step 9 stacks the 3 percent loyalty offer on top of the 15 percent
    campaign, per component, giving the 361531 the penalty schedule works from.
    """
    world = fx.simple_world(api, voyage_code="AUR-2701")
    promo = fx.make_promotion(
        api,
        world.sailing["id"],
        world.sailing["version"],
        code="EARLY15",
        audience="GENERAL",
        discount_pct=0.15,
        starts_on="2026-08-01T00:00:00Z",
        ends_on="2026-09-10T00:00:00Z",
        max_redemptions=5,
    )
    fx.activate_promotion(api, promo["id"])
    guest = fx.make_guest(api, prior_sailings_count=4)
    booking = fx.make_booking(
        api,
        world.sailing["id"],
        world.category["id"],
        guest["id"],
        third_berth_guests=1,
        promotion_id=promo["id"],
    )
    assert booking["net_ticket_cents"] == 361531
    fx.pay(api, booking["id"], "DEPOSIT", 75000)
    fx.pay(api, booking["id"], "FINAL_PAYMENT", 286531)
    fx.confirm(api, booking["id"])
    world.promo = promo
    world.guest = guest
    world.booking = fx.read_booking(api, booking["id"])
    return world


def test_settlement_penalty_is_re_evaluated_at_the_settlement_instant(api):
    """The final penalty reads the band at settlement, not the band at cancel.

    PRD 3.6: "Because the logical clock may have advanced between cancellation
    and settlement, the final evaluation can land in a harsher band than the
    provisional one did; the final figure is the only one that moves money, and
    the provisional figure is never retroactively corrected." The cancel instant
    sits 100 days out (the 0.25 band) and the settlement instant 77 days out
    (the 0.50 band).

    Design: Difficulty/dual_variant_calc/cancellation_penalty_provisional_quote_versus_final_settlement
    """
    world = _gold_guest_paid_in_full(api)
    booking_id = world.booking["id"]

    fx.set_clock(api, "2026-10-02T00:00:00Z")
    fx.cancelled_booking(api, booking_id)
    fx.set_clock(api, "2026-10-25T00:00:00Z")

    settled = validate_success(api.settle_cancellation(booking_id, REVENUE_MANAGER))

    assert settled["net_ticket_cents"] == 361531
    assert settled["provisional_penalty_cents"] == 90383
    assert settled["cancellation_penalty_cents"] == 180766
    assert settled["refund_cents"] == 180765
    assert settled["payment_status"] == "REFUNDED"
    assert_instant_equals(settled["settled_at"], "2026-10-25T00:00:00Z", "settled_at")

    ledger = fx.payment_events(api, booking_id)
    assert [event["kind"] for event in ledger] == [
        "DEPOSIT",
        "FINAL_PAYMENT",
        "REFUND",
    ]
    assert [event["amount_cents"] for event in ledger] == [75000, 286531, 180765]


def test_provisional_quote_moves_no_cash_and_appends_no_payment_event(api):
    """At the cancel instant only the disclosure quote is written.

    PRD 3.6: "At the cancel instant the provisional evaluation runs and its
    result is written to provisional_penalty_cents. That figure is a disclosure
    quote only: no money moves, no payment event is appended, and
    cancellation_penalty_cents and refund_cents both stay null."

    Design: Difficulty/dual_variant_calc/cancellation_penalty_provisional_quote_versus_final_settlement
    """
    world = _gold_guest_paid_in_full(api)
    booking_id = world.booking["id"]

    fx.set_clock(api, "2026-10-02T00:00:00Z")
    cancelled = fx.cancelled_booking(api, booking_id)

    assert cancelled["provisional_penalty_cents"] == 90383
    assert cancelled["cancellation_penalty_cents"] is None
    assert cancelled["refund_cents"] is None
    assert cancelled["payment_status"] == "PENALTY_ASSESSED"
    assert cancelled["booking_status"] == "CANCELLED"
    assert cancelled["amount_paid_cents"] == 361531

    ledger = fx.payment_events(api, booking_id)
    assert [event["kind"] for event in ledger] == ["DEPOSIT", "FINAL_PAYMENT"]


def test_a_settled_booking_cannot_be_settled_a_second_time(api):
    """Settlement is only available while the money dimension is PENALTY_ASSESSED.

    PRD 3.6: "It requires payment_status to be PENALTY_ASSESSED (otherwise
    ERR_BOOKING_NOT_AWAITING_SETTLEMENT) and booking_status to be CANCELLED."
    The first settlement moves the money dimension to REFUNDED, so the second
    call no longer meets that precondition.

    Design: Difficulty/dual_variant_calc/cancellation_penalty_provisional_quote_versus_final_settlement
    """
    world = _gold_guest_paid_in_full(api)
    booking_id = world.booking["id"]

    fx.set_clock(api, "2026-10-02T00:00:00Z")
    fx.cancelled_booking(api, booking_id)
    fx.set_clock(api, "2026-10-25T00:00:00Z")
    fx.settled_booking(api, booking_id)

    response = api.settle_cancellation(booking_id, REVENUE_MANAGER)
    validate_error(response, ERR_BOOKING_NOT_AWAITING_SETTLEMENT)

    still_settled = fx.read_booking(api, booking_id)
    assert still_settled["cancellation_penalty_cents"] == 180766
    assert still_settled["refund_cents"] == 180765
    assert len(fx.payment_events(api, booking_id)) == 3
