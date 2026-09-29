"""
Immediate consistency, proved in both directions on one booking.

PRD 2.8 promises there is "no deferred reconciliation", so every figure below is read
exactly once, straight after the write that produced it - never re-read to let a
value settle.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import (
    RESERVATION_AGENT,
    assert_capacity_identity,
    assert_instant_equals,
    assert_two_decimal_pct,
    factories as f,
    fixtures as fx,
)

FLAT_FARE_50K = {
    "window_open_days_to_sail": 730,
    "window_close_days_to_sail": 0,
    "base_lower_berth_fare_cents": 50000,
    "third_berth_fare_cents": 20000,
    "fourth_berth_fare_cents": 15000,
}


def test_a_sale_and_its_cancellation_are_both_visible_on_the_very_next_read(api):
    """The create response is already complete, and the parents are already correct.

    PRD 2.8: "This API keeps derived state consistent immediately, inside the request
    that caused the change - there is no deferred reconciliation. When an operation
    changes a booking's money, occupancy, or status, the sailing's aggregates are
    recomputed in the same request; when a group block's held cabins change, the affected
    allotment's counters are recomputed in the same request". PRD 3.6 makes the
    cancellation just as prompt: "The sailing's occupancy chain and revenue chain -
    including `compensation_liability_cents` - are then recomputed", while "no money
    moves, no payment event is appended, and `cancellation_penalty_cents` and
    `refund_cents` both stay null".

    Design: Corner/consistency_model/every_derived_field_is_visible_in_the_same_response
    """
    world = fx.simple_world(
        api,
        voyage_code="CST-2701",
        nights=4,
        total_lower_berths=40,
        category_overrides={"lower_berths": 2},
        physical_cabins=10,
        oversell_allowance=0,
        fare_overrides=FLAT_FARE_50K,
    )
    guest = fx.make_guest(api, full_name="Ada Ames", email="ada@example.com")

    booking = validate_success(
        api.create_booking(
            f.booking_payload(
                world.sailing["id"],
                world.category["id"],
                guest["id"],
                occupancy_adults=2,
            ),
            RESERVATION_AGENT,
        ),
        201,
    )
    # Everything the buildup produces is on the create response itself.
    assert booking["booked_days_to_sail"] == 162
    assert booking["lower_berth_subtotal_cents"] == 100000
    # 100,000 sits below the 250,000 floor, so no berth discount tier applies.
    assert float(booking["berth_discount_pct"]) == 0.0
    assert_two_decimal_pct(booking["berth_discount_pct"], "berth_discount_pct")
    assert booking["net_ticket_cents"] == 100000
    assert booking["deposit_due_cents"] == 50000
    assert booking["balance_due_cents"] == 100000
    assert booking["projected_onboard_gross_cents"] == 72000
    assert booking["projected_onboard_net_cents"] == 72000
    assert booking["payment_terms"] == "STANDARD"
    assert_instant_equals(
        booking["deposit_due_date"], "2026-08-08T00:00:00Z", "deposit_due_date"
    )
    assert_instant_equals(
        booking["final_payment_due_date"],
        "2026-10-27T17:00:00Z",
        "final_payment_due_date",
    )

    sold = validate_success(api.get_sailing(world.sailing["id"], RESERVATION_AGENT))
    # No revenue-summary call sits between the sale and this read.
    assert sold["lower_berths_sold"] == 2
    assert float(sold["occupancy_pct"]) == 5.0
    assert_two_decimal_pct(sold["occupancy_pct"], "occupancy_pct")
    assert sold["gross_ticket_revenue_cents"] == 100000
    assert sold["projected_onboard_revenue_cents"] == 72000
    # (100,000 + 72,000) over 40 berths x 4 nights is exactly 1,075.
    assert sold["ralbd_gross_cents"] == 1075
    assert sold["ralbd_net_cents"] == 1075
    assert sold["revenue_alert"] is True

    consumed = validate_success(
        api.get_sailing_inventory(world.inventory["id"], RESERVATION_AGENT)
    )
    assert consumed["booked_cabins"] == 1
    assert consumed["available_cabins"] == 9
    assert consumed["effective_oversell_cabins"] == 0
    assert_capacity_identity(consumed)

    event = validate_success(
        api.post_payment(
            booking["id"], f.payment_payload("DEPOSIT", 50000), RESERVATION_AGENT
        ),
        201,
    )
    assert event["resulting_payment_status"] == "DEPOSIT_PAID"
    paid = fx.read_booking(api, booking["id"])
    assert paid["amount_paid_cents"] == 50000
    assert paid["balance_due_cents"] == 50000

    cancelled = validate_success(
        api.cancel_booking(
            booking["id"], {"reason": "GUEST_CHANGED_PLANS"}, RESERVATION_AGENT
        )
    )
    assert cancelled["booking_status"] == "CANCELLED"
    assert cancelled["payment_status"] == "PENALTY_ASSESSED"
    assert cancelled["cancel_reason"] == "GUEST_CHANGED_PLANS"
    assert cancelled["cancelled_at"] is not None
    # 162 days out is inside the penalty-free band, and settlement has not run.
    assert cancelled["provisional_penalty_cents"] == 0
    assert cancelled["cancellation_penalty_cents"] is None
    assert cancelled["refund_cents"] is None

    emptied = validate_success(api.get_sailing(world.sailing["id"], RESERVATION_AGENT))
    # The retraction is as prompt as the publication was.
    assert emptied["lower_berths_sold"] == 0
    assert float(emptied["occupancy_pct"]) == 0.0
    assert emptied["gross_ticket_revenue_cents"] == 0
    assert emptied["projected_onboard_revenue_cents"] == 0
    assert emptied["ralbd_gross_cents"] == 0
    assert emptied["ralbd_net_cents"] == 0
    assert emptied["revenue_alert"] is True
    assert emptied["confirmed_bookings_count"] == 0
    assert emptied["paid_in_full_bookings_count"] == 0

    returned = validate_success(
        api.get_sailing_inventory(world.inventory["id"], RESERVATION_AGENT)
    )
    # The cabin is back without any sweep.
    assert returned["booked_cabins"] == 0
    assert returned["available_cabins"] == 10
    assert_capacity_identity(returned)

    # PRD 3.4 defines the counter by status, not by history: "bookings_count, which
    # counts the guest's bookings whose booking_status is anything other than
    # CANCELLED". The cancellation is the guest's only booking, so it drops back to 0.
    assert fx.read_guest(api, guest["id"])["bookings_count"] == 0
