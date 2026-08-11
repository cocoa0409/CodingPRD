"""Refunds: the money invariant, terminal-redemption guards, and fiscal bounds."""
from test_helpers import (
    ApiErrorId,
    assert_order_money_invariant,
    get_order,
    make_build_season,
    make_faire_day,
    make_paid_order,
    set_clock,
    setup_group_order_paid,
    tickets_of_order,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import ANY, GATE, OPERATOR
from test_helpers.test_users import make_guest_headers


def test_refund_terminal_redemption_states_rejected(api, gate_agent_headers):
    """PRD §3.5: "Two redemption-state gates follow: a `FULLY_REDEEMED` order has
    nothing left to refund and fails with `ERR_NOTHING_REFUNDABLE`, while a
    `RAINCHECKED` or `VOID` order fails with `ERR_ORDER_NOT_REFUNDABLE`."

    Design: Corner/validations/refund_terminal_redemption_states_rejected
    """
    set_clock()
    season = make_build_season(name="RefundGuard Revel", volunteer_min_hours=0)
    day1 = make_faire_day(season["id"], "2026-06-06T00:00:00Z")
    day2 = make_faire_day(season["id"], "2026-06-07T00:00:00Z")
    season = validate_success(api.open_season(season["id"], OPERATOR), 200)
    validate_success(api.open_sales(day1["id"], OPERATOR), 200)
    validate_success(api.open_sales(day2["id"], OPERATOR), 200)
    order_x = make_paid_order(season["id"], "g-x@example.com", "DAY", 1, 3000, day1["id"])
    order_y = make_paid_order(season["id"], "g-y@example.com", "DAY", 1, 3000, day2["id"])

    # Order X: its single ticket redeems at the gate -> FULLY_REDEEMED.
    set_clock("2026-06-06T07:00:00Z")
    validate_success(api.open_gates(day1["id"], OPERATOR), 200)
    ticket_x = tickets_of_order(order_x["id"])[0]
    validate_success(api.redeem_ticket(ticket_x["id"], gate_agent_headers), 200)

    # Order Y: its day is weather-cancelled -> RAINCHECKED.
    validate_success(api.cancel_weather(day2["id"], OPERATOR), 200)

    res = api.refund_order(order_x["id"], {"refund_cents": 100}, gate_agent_headers)
    validate_error(res, ApiErrorId.ERR_NOTHING_REFUNDABLE, expected_status=409)

    res = api.refund_order(order_y["id"], {"refund_cents": 100}, gate_agent_headers)
    validate_error(res, ApiErrorId.ERR_ORDER_NOT_REFUNDABLE, expected_status=409)


def test_refund_money_invariant_partial_then_full(api, gate_agent_headers):
    """PRD §2.10: "Within a ticket order, money is conserved: `refunded_cents` plus
    `retained_cents` always equals `total_cents`. Every refund adds its amount to
    `refunded_cents` and recomputes `retained_cents` as the total minus what has
    been refunded, and no refund may exceed the `retained_cents` that remain."
    PRD §3.5: "when the refund falls short of the remaining retained amount the
    order becomes `PARTIALLY_REFUNDED`, and when it equals that amount exactly the
    order becomes `REFUNDED`."

    Design: Difficulty/compensating_invariant/refund_money_invariant_retained_plus_refunded
    """
    season, day, order = setup_group_order_paid(quantity=10)
    assert order["total_cents"] == 27000  # 10 * 3000 * 0.90

    first = validate_success(
        api.refund_order(order["id"], {"refund_cents": 5000}, gate_agent_headers), 200
    )
    assert first["refunded_cents"] == 5000
    assert first["retained_cents"] == 22000
    assert first["payment_status"] == "PARTIALLY_REFUNDED"
    assert_order_money_invariant(first)

    second = validate_success(
        api.refund_order(order["id"], {"refund_cents": 22000}, gate_agent_headers), 200
    )
    assert second["refunded_cents"] == 27000
    assert second["retained_cents"] == 0
    assert second["payment_status"] == "REFUNDED"
    assert_order_money_invariant(second)


def test_refund_exceeding_retained_rejected(api, gate_agent_headers):
    """PRD §3.5: "Finally the amount is bounded by what the order retains: a
    `refund_cents` exceeding `retained_cents` is rejected with
    `ERR_REFUND_EXCEEDS_PAID` (HTTP 422). A successful refund adds to
    `refunded_cents` and recomputes `retained_cents`, preserving the money invariant
    of §2.10"

    Design: Difficulty/compensating_invariant/refund_money_invariant_retained_plus_refunded
    """
    season, day, order = setup_group_order_paid(quantity=10)
    validate_success(
        api.refund_order(order["id"], {"refund_cents": 5000}, gate_agent_headers), 200
    )

    # The order retains 22000 and remains PARTIALLY_REFUNDED; one cent over the
    # remainder overshoots the fiscal bound while the order is still refundable.
    res = api.refund_order(order["id"], {"refund_cents": 22001}, gate_agent_headers)
    validate_error(res, ApiErrorId.ERR_REFUND_EXCEEDS_PAID, expected_status=422)

    final = get_order(order["id"])
    assert final["refunded_cents"] == 5000
    assert final["retained_cents"] == 22000
    assert_order_money_invariant(final)
