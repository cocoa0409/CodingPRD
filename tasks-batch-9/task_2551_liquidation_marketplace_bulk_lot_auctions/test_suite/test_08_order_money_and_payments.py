"""Sale-order money: the two settlement variants, the two status dimensions, payments."""

from test_helpers import (
    api_client,
    assert_instant,
    assert_pickup_appointment,
    assert_sale_order,
    book_appointment,
    complete_appointment,
    get_success_data,
    pay_order,
    payment_payload,
    read_appointment,
    read_buyer,
    read_order,
    setup_fixed_price_order,
    setup_paid_auction_order,
    total_count,
    validate_error,
    validate_success,
)

TWO_HUNDRED_UNIT_LINES = [
    {
        "sku": "APP-PAY-0200",
        "unit_count": 200,
        "unit_retail_cents": 10_000,
        "declared_condition": "USED_GOOD",
    },
]

PICKUP_WINDOW_START = "2026-08-18T14:00:00Z"
PICKUP_WINDOW_END = "2026-08-18T15:00:00Z"


def test_completion_swaps_the_estimated_freight_term_for_the_carrier_invoice():
    """The provisional settlement prices freight from the pallet count; completion
    re-derives the same waterfall on the invoiced figure and leaves the estimate on
    the row.

    PRD 3.6: "**The two settlement variants.** An order's `settlement_basis` names
    which variant of the money waterfall is currently in force. It begins as
    `PROVISIONAL` at order creation, whichever of the three sale mechanisms produced
    the order, and it uses `estimated_freight_cents` as the freight term. It becomes
    `FINAL` when the order's pickup appointment is completed, at which point the
    freight term becomes the carrier-invoiced `actual_freight_cents` supplied at
    completion."
    PRD 3.7: "The order's `settlement_basis` flips `PROVISIONAL → FINAL`, which
    re-derives `pre_fee_total_cents`, `total_due_cents` and `balance_due_cents` on the
    actual freight while leaving any already-assessed `late_fee_cents` alone."
    PRD 3.6: "Fourth, `balance_due_cents` is `total_due_cents` minus
    `amount_paid_cents`, **clamped at zero** — it never goes negative."

    Design: Difficulty/dual_variant_calc/order_settlement_provisional_vs_final_freight_delta
    """
    built = setup_paid_auction_order()
    env = built["env"]
    provisional = read_order(env, built["order"]["id"])
    assert_sale_order(provisional)
    assert provisional["settlement_basis"] == "PROVISIONAL"
    assert provisional["estimated_freight_cents"] == 17_000
    assert provisional["pre_fee_total_cents"] == 2_987_000
    assert provisional["total_due_cents"] == 2_987_000
    assert provisional["balance_due_cents"] == 0
    assert provisional["actual_freight_cents"] is None

    appointment = book_appointment(
        env,
        provisional,
        window_start_at=PICKUP_WINDOW_START,
        window_end_at=PICKUP_WINDOW_END,
    )
    completed = complete_appointment(
        env, appointment, actual_freight_cents=19_000, picked_up_unit_count=320
    )
    assert_pickup_appointment(completed)
    assert completed["appointment_status"] == "COMPLETED"

    final = read_order(env, provisional["id"])
    assert final["settlement_basis"] == "FINAL"
    assert final["actual_freight_cents"] == 19_000
    assert final["estimated_freight_cents"] == 17_000
    assert final["pre_fee_total_cents"] == 2_989_000
    assert final["total_due_cents"] == 2_989_000
    assert final["balance_due_cents"] == 2_000
    assert final["logistics_status"] == "PICKED_UP"


def test_the_whole_provisional_to_final_difference_is_freight_and_nothing_else():
    """Hammer and premium are identical under both variants, so the 2,000-cent move in
    the total is exactly the 19,000-minus-17,000 freight delta.

    PRD 3.6: "The hammer and premium terms are identical across the two variants, so
    the entire difference between a provisional and a final settlement is the
    difference between estimated and actual freight."
    PRD 3.6: "Consider an order with a hammer price of 2,700,000 cents on a 400-unit
    lot: the premium is 270,000 cents, estimated freight is 17,000 cents, and if the
    carrier ultimately invoices 19,000 cents the final settlement is exactly 2,000
    cents higher than the provisional one."
    PRD 3.6: "The selected `buyer_premium_bps` is snapshotted onto the order at
    creation and is never re-selected afterwards, so a later claim credit or freight
    correction never reprices the premium."

    Design: Difficulty/dual_variant_calc/order_settlement_provisional_vs_final_freight_delta
    """
    built = setup_paid_auction_order()
    env = built["env"]
    provisional = read_order(env, built["order"]["id"])
    provisional_total = provisional["total_due_cents"]
    assert provisional["buyer_premium_bps"] == 1_000
    assert provisional["buyer_premium_cents"] == 270_000
    assert provisional["pallet_count"] == 2

    appointment = book_appointment(
        env,
        provisional,
        window_start_at=PICKUP_WINDOW_START,
        window_end_at=PICKUP_WINDOW_END,
    )
    complete_appointment(
        env, appointment, actual_freight_cents=19_000, picked_up_unit_count=320
    )

    final = read_order(env, provisional["id"])
    assert final["hammer_price_cents"] == provisional["hammer_price_cents"] == 2_700_000
    assert final["buyer_premium_bps"] == 1_000
    assert final["buyer_premium_cents"] == 270_000
    assert final["total_due_cents"] - provisional_total == 2_000
    assert (
        final["actual_freight_cents"] - final["estimated_freight_cents"]
        == final["total_due_cents"] - provisional_total
    )


def test_paying_in_full_leaves_the_freight_dimension_where_it_started():
    """Money and freight are two dimensions over one row: full payment does not book
    anything, and the booking that follows moves only the logistics side.

    PRD 3.6: "`payment_status` tracks money and moves through `UNPAID`,
    `PARTIALLY_PAID`, `PAID` and `REFUND_ISSUED`. `logistics_status` tracks freight and
    moves through `AWAITING_APPOINTMENT`, `APPOINTMENT_SCHEDULED`, `PICKED_UP` and
    `ABANDONED`. Neither dimension's transitions constrain the other's in general; a
    new order begins at `UNPAID` and `AWAITING_APPOINTMENT` simultaneously and the two
    evolve separately."
    PRD 3.6: "a payment exactly equal to the outstanding balance advances `UNPAID →
    PAID` or `PARTIALLY_PAID → PAID`, drives `balance_due_cents` to zero and stamps
    `paid_at` with the logical clock instant at which the balance first reached zero."
    PRD 3.7: "The resulting `PickupAppointment` records its parent order through
    `sale_order_id`, begins with `appointment_status` `SCHEDULED`, `completed_at` null
    and `picked_up_unit_count` null, and carries the `dock_door_number` the platform
    assigns."
    PRD 3.7: "An accepted booking advances the order `AWAITING_APPOINTMENT →
    APPOINTMENT_SCHEDULED` and advances the order's `version` by one."

    Design: Difficulty/non_linear_state_machine/sale_order_payment_and_logistics_dimensions_advance_independently
    """
    built = setup_fixed_price_order()
    env = built["env"]
    order = read_order(env, built["order"]["id"])
    assert order["payment_status"] == "UNPAID"
    assert order["logistics_status"] == "AWAITING_APPOINTMENT"
    assert order["total_due_cents"] == 1_148_500

    pay_order(env, order)
    paid = read_order(env, order["id"])
    assert paid["payment_status"] == "PAID"
    assert paid["logistics_status"] == "AWAITING_APPOINTMENT"
    assert paid["amount_paid_cents"] == 1_148_500
    assert paid["balance_due_cents"] == 0
    assert_instant(paid["paid_at"], "2026-08-05T01:00:00Z")

    appointment = validate_success(
        api_client.book_pickup_appointment(
            order["id"],
            {
                "warehouse_id": env["warehouse"]["id"],
                "carrier_id": env["carrier"]["id"],
                "window_start_at": "2026-08-10T14:00:00Z",
                "window_end_at": "2026-08-10T15:00:00Z",
                "bol_number": "BOL-P1",
            },
            env["buyer_headers"],
        ),
        201,
    )
    assert_pickup_appointment(appointment)
    assert appointment["appointment_status"] == "SCHEDULED"
    assert appointment["sale_order_id"] == order["id"]
    assert appointment["dock_door_number"] == 1
    assert appointment["completed_at"] is None
    assert appointment["picked_up_unit_count"] is None

    scheduled = read_order(env, order["id"])
    assert scheduled["payment_status"] == "PAID"
    assert scheduled["logistics_status"] == "APPOINTMENT_SCHEDULED"


def test_cancelling_the_booking_cycles_the_freight_dimension_back_and_keeps_the_money():
    """The logistics dimension re-enters AWAITING_APPOINTMENT while payment stays
    settled, and the order is bookable again.

    PRD 3.7: "Cancellation advances the appointment `SCHEDULED → CANCELLED`, frees its
    dock-door interval so that exactly the same window becomes assignable again, and
    returns the order `APPOINTMENT_SCHEDULED → AWAITING_APPOINTMENT`, leaving the order
    with no appointment in `SCHEDULED` and advancing the order's `version` by one."
    PRD 3.6: "Exactly two cross-dimension guards exist, and both are one-directional:
    an appointment may only be scheduled while `payment_status` is `PAID`, and a
    payment may not be accepted while `logistics_status` is `ABANDONED`."
    PRD 3.6: "It begins as `PROVISIONAL` at order creation, whichever of the three sale
    mechanisms produced the order, and it uses `estimated_freight_cents` as the freight
    term."

    Design: Difficulty/non_linear_state_machine/sale_order_payment_and_logistics_dimensions_advance_independently
    """
    built = setup_fixed_price_order()
    env = built["env"]
    order = read_order(env, built["order"]["id"])
    pay_order(env, order)
    appointment = book_appointment(
        env,
        order,
        window_start_at="2026-08-10T14:00:00Z",
        window_end_at="2026-08-10T15:00:00Z",
        bol_number="BOL-P1",
    )
    assert read_order(env, order["id"])["logistics_status"] == "APPOINTMENT_SCHEDULED"

    get_success_data(
        api_client.cancel_pickup_appointment(
            appointment["id"],
            {"cancellation_reason": "buyer truck broke down"},
            env["buyer_headers"],
        )
    )

    cancelled = read_appointment(env, appointment["id"])
    assert cancelled["appointment_status"] == "CANCELLED"
    assert cancelled["picked_up_unit_count"] is None

    reread = read_order(env, order["id"])
    assert reread["logistics_status"] == "AWAITING_APPOINTMENT"
    assert reread["payment_status"] == "PAID"
    assert reread["amount_paid_cents"] == 1_148_500
    assert reread["balance_due_cents"] == 0
    assert_instant(reread["paid_at"], "2026-08-05T01:00:00Z")
    assert reread["settlement_basis"] == "PROVISIONAL"
    assert reread["actual_freight_cents"] is None

    assert total_count(
        api_client.list_pickup_appointments(
            env["buyer_headers"],
            {"sale_order_id": order["id"], "appointment_status": "SCHEDULED"},
        )
    ) == 0


def test_the_payment_amount_window_closes_from_both_sides_and_then_shuts_entirely():
    """Overpaying the full balance and overpaying the remainder are the same amount
    error, while a payment against a settled order is a state error.

    PRD 3.6: "The amount must be at least 1 cent and at most the order's current
    `balance_due_cents`; an amount outside that inclusive range — including any attempt
    to overpay — is refused with `ERR_PAYMENT_EXCEEDS_BALANCE`."
    PRD 3.6: "Payments are accepted only while `payment_status` is `UNPAID` or
    `PARTIALLY_PAID`; an order already `PAID` or `REFUND_ISSUED` refuses further
    payment with `ERR_ORDER_PAYMENT_STATE_INVALID`."
    PRD 3.6: "An accepted payment increases `amount_paid_cents` by the paid amount and
    recomputes `balance_due_cents`. A payment smaller than the outstanding balance
    advances `UNPAID → PARTIALLY_PAID`; a payment exactly equal to the outstanding
    balance advances `UNPAID → PAID` or `PARTIALLY_PAID → PAID`, drives
    `balance_due_cents` to zero and stamps `paid_at` with the logical clock instant at
    which the balance first reached zero."
    PRD 3.2: "The second part covers unsettled orders: over all of this buyer's sale
    orders whose `payment_status` is `UNPAID` or `PARTIALLY_PAID` and whose
    `logistics_status` is not `ABANDONED`, sum `balance_due_cents`."

    Design: Corner/errors/payment_amount_and_payment_state_errors_are_all_reachable
    """
    built = setup_fixed_price_order(lines=TWO_HUNDRED_UNIT_LINES)
    env = built["env"]
    order = read_order(env, built["order"]["id"])
    assert order["total_due_cents"] == 1_148_500
    assert order["payment_status"] == "UNPAID"

    over_the_whole = api_client.pay_sale_order(
        order["id"], payment_payload(1_148_501), env["buyer_headers"]
    )
    validate_error(over_the_whole, "ERR_PAYMENT_EXCEEDS_BALANCE", 422)
    assert read_order(env, order["id"])["amount_paid_cents"] == 0

    pay_order(env, order, 500_000)
    part_way = read_order(env, order["id"])
    assert part_way["payment_status"] == "PARTIALLY_PAID"
    assert part_way["amount_paid_cents"] == 500_000
    assert part_way["balance_due_cents"] == 648_500
    assert part_way["paid_at"] is None

    over_the_remainder = api_client.pay_sale_order(
        order["id"], payment_payload(648_501), env["buyer_headers"]
    )
    validate_error(over_the_remainder, "ERR_PAYMENT_EXCEEDS_BALANCE", 422)
    assert read_order(env, order["id"])["amount_paid_cents"] == 500_000

    pay_order(env, order, 648_500)
    settled = read_order(env, order["id"])
    assert settled["payment_status"] == "PAID"
    assert settled["amount_paid_cents"] == 1_148_500
    assert settled["balance_due_cents"] == 0
    assert_instant(settled["paid_at"], "2026-08-05T01:00:00Z")

    one_cent_too_many = api_client.pay_sale_order(
        order["id"], payment_payload(1), env["buyer_headers"]
    )
    error = validate_error(one_cent_too_many, "ERR_ORDER_PAYMENT_STATE_INVALID", 409)
    assert error["error_id"] != "ERR_PAYMENT_EXCEEDS_BALANCE"

    assert settled["late_fee_cents"] == 0
    assert settled["settlement_basis"] == "PROVISIONAL"
    assert read_buyer(env)["outstanding_exposure_cents"] == 0
