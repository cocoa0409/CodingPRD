"""Ticketing: dual-variant pricing (provisional quote vs final charge),
per-line rounding order, the inclusive early-bird cutoff, and refund
arithmetic with its money-conservation invariant."""
from test_helpers import (
    TEST_USERS,
    api_client,
    ApiErrorId,
    create_ticket_order_payload,
    pay_ticket_order_payload,
    ticket_line,
    validate_error,
    validate_success,
)
from test_helpers.constants import (
    CLOCK_AFTER_CUTOFF,
    CLOCK_AT_CUTOFF,
    CLOCK_EARLY_BIRD,
)
from test_helpers.fixtures import (
    create_ticket_order,
    get_event,
    pay_ticket_order,
    set_clock,
    setup_paid_order,
    setup_published_event,
)
from test_helpers.test_users import make_spectator_headers

ORG = TEST_USERS["organizer_headers"]


def _published_event_with_order_before_cutoff(lines=None, buyer="spec-1"):
    """Published event; order created while the logical clock reads
    2026-05-10T12:00:00Z (before the early-bird cutoff). Returns (event, order)."""
    event = setup_published_event()
    set_clock(CLOCK_EARLY_BIRD)
    order = create_ticket_order(
        event["id"], buyer=buyer,
        **({"lines": lines} if lines is not None else {}),
    )
    return event, order


class TestDualVariantPricing:
    def test_ticket_provisional_quote_vs_final_charge(self, api):
        """PRD §3.7: "At payment the charge is recomputed by the same per-line
        discipline, but with `paid_at` — the logical now — as the pricing
        timestamp, and early-bird eligibility is re-evaluated against it rather
        than carried over: an order created before the cutoff but paid after it
        is charged the undiscounted price."

        Design: Difficulty/dual_variant_calc/ticket_provisional_quote_vs_final_charge
        """
        event, order = _published_event_with_order_before_cutoff()
        assert order["quoted_total_cents"] == 8508, (
            "provisional quote at created_at uses the early-bird discount"
        )

        set_clock(CLOCK_AFTER_CUTOFF)  # 2026-06-20, after the 2026-06-15 cutoff
        paid = validate_success(
            api_client.pay_ticket_order(order["id"], pay_ticket_order_payload(),
                                        make_spectator_headers("spec-1")),
            200,
        )
        assert paid["status"] == "PAID"
        assert paid["final_total_cents"] == 10547, (
            "final charge re-evaluates eligibility: 7797 + 2400 + 350 undiscounted"
        )
        assert paid["quoted_total_cents"] == 8508
        assert paid["quoted_total_cents"] != paid["final_total_cents"]

    def test_ticket_quote_is_never_overwritten_by_payment(self, api):
        """PRD §3.7: "At creation the server computes `quoted_total_cents`, a
        provisional quote that is never charged"
        PRD §3.7: "The result is stored as `final_total_cents`, `paid_at` is
        stamped, and the order moves `RESERVED → PAID`."

        Design: Difficulty/dual_variant_calc/ticket_provisional_quote_vs_final_charge
        """
        event, order = _published_event_with_order_before_cutoff()
        set_clock(CLOCK_AFTER_CUTOFF)
        pay_ticket_order(order["id"], buyer="spec-1")

        reread = validate_success(
            api_client.get_ticket_order(order["id"], ORG), 200
        )
        assert reread["status"] == "PAID"
        assert reread["quoted_total_cents"] == 8508, (
            "the provisional quote survives payment unchanged"
        )
        assert reread["final_total_cents"] == 10547
        assert reread["paid_at"] is not None


class TestPerLineRoundingOrder:
    def test_ticket_total_rounded_per_line_then_summed(self, api):
        """PRD §2.7: "Two rounding disciplines matter and must not be
        interchanged: ticket pricing rounds each line half-up before lines are
        summed, and the flat per-order service fee is added after the sum"
        PRD §3.7: "each line's result is rounded half-up to whole cents before
        any summation; and the order total is the sum of those rounded lines plus
        the event's `service_fee_cents`, added after the sum and never itself
        discounted."

        Design: Difficulty/combinatorial_formula/ticket_total_rounded_per_line_then_summed
        """
        event, order = _published_event_with_order_before_cutoff()
        # round_half_up(2599*3 * 0.8) = 6238 and 1200*2 * 0.8 = 1920;
        # 6238 + 1920 + 350 = 8508. Rounding per unit first would give
        # 2079*3 + 1920 + 350 = 8507 — one cent less.
        assert order["quoted_total_cents"] == 8508
        assert order["quoted_total_cents"] != 8507, (
            "per-unit-first rounding would yield 8507; per-line rounding yields 8508"
        )

    def test_ticket_single_line_rounding_boundary(self, api):
        """PRD §3.7: "each line's result is rounded half-up to whole cents before
        any summation; and the order total is the sum of those rounded lines plus
        the event's `service_fee_cents`, added after the sum and never itself
        discounted."

        Design: Difficulty/combinatorial_formula/ticket_total_rounded_per_line_then_summed
        """
        event, order = _published_event_with_order_before_cutoff(
            lines=[ticket_line("ADULT_DAY", 3)]
        )
        # round_half_up(7797 * 0.8) = round_half_up(6237.6) = 6238, + 350 fee.
        assert order["quoted_total_cents"] == 6588, (
            "a single line still rounds half-up per line before the fee is added"
        )


class TestEarlyBirdBoundary:
    def test_early_bird_price_at_exact_cutoff(self, api):
        """PRD §2.7: "The early-bird boundary is inclusive: a pricing timestamp
        exactly equal to the cutoff qualifies for the discount."
        PRD §3.7: "when the order's `created_at` falls on or before the event's
        `early_bird_cutoff_at` — an inclusive boundary — the extended amount is
        reduced by the `early_bird_pct` fraction"

        Design: Corner/calculations/early_bird_price_at_exact_cutoff
        """
        event, order = _published_event_with_order_before_cutoff()
        assert order["quoted_total_cents"] == 8508

        set_clock(CLOCK_AT_CUTOFF)  # exactly 2026-06-15T00:00:00Z
        paid = validate_success(
            api_client.pay_ticket_order(order["id"], pay_ticket_order_payload(),
                                        make_spectator_headers("spec-1")),
            200,
        )
        assert paid["final_total_cents"] == 8508, (
            "paid_at == cutoff still qualifies for the discount (inclusive)"
        )
        assert paid["final_total_cents"] == paid["quoted_total_cents"]


class TestRefundArithmetic:
    def test_refund_split_money_conservation(self, api):
        """PRD §3.7: "Under `PATRON_CHOICE` — permitted in any posture other than
        `COMPLETED` or `CANCELLED` (`ERR_INVALID_EVENT_POSTURE`) — the retained
        fee `retained_fee_cents` is `final_total_cents` multiplied by the event's
        `refund_retain_pct`, rounded half-up, and `refund_amount_cents` is the
        remainder."
        PRD §3.7: "Either way the invariant `refund_amount_cents` plus
        `retained_fee_cents` equals `final_total_cents` holds"

        Design: Difficulty/compensating_invariant/refund_split_money_conservation
        """
        event = setup_published_event()
        set_clock(CLOCK_EARLY_BIRD)
        order = setup_paid_order(event["id"], buyer="spec-1")
        assert order["final_total_cents"] == 8508

        refunded = validate_success(
            api_client.refund_ticket_order(order["id"], {"reason": "PATRON_CHOICE"},
                                           make_spectator_headers("spec-1")),
            200,
        )
        assert refunded["status"] == "REFUNDED"
        assert refunded["refund_reason"] == "PATRON_CHOICE"
        assert refunded["retained_fee_cents"] == 1276, (
            "round_half_up(8508 * 0.15) retained"
        )
        assert refunded["refund_amount_cents"] == 7232
        assert refunded["refund_amount_cents"] + refunded["retained_fee_cents"] == 8508, (
            "money is conserved: refund + retained == final_total_cents"
        )

    def test_refund_split_money_conservation_other_amounts(self, api):
        """PRD §3.7: "the retained fee `retained_fee_cents` is `final_total_cents`
        multiplied by the event's `refund_retain_pct`, rounded half-up, and
        `refund_amount_cents` is the remainder."
        PRD §3.7: "Either way the invariant `refund_amount_cents` plus
        `retained_fee_cents` equals `final_total_cents` holds"

        Design: Difficulty/compensating_invariant/refund_split_money_conservation
        """
        event = setup_published_event()
        order = setup_paid_order(
            event["id"], buyer="spec-1", lines=[ticket_line("ADULT_DAY", 1)]
        )
        # Default clock 2026-05-01 is before the cutoff:
        # final = round_half_up(2599 * 0.8) + 350 = 2079 + 350 = 2429.
        assert order["final_total_cents"] == 2429

        refunded = validate_success(
            api_client.refund_ticket_order(order["id"], {"reason": "PATRON_CHOICE"},
                                           make_spectator_headers("spec-1")),
            200,
        )
        assert refunded["retained_fee_cents"] == 364, "round_half_up(2429 * 0.15)"
        assert refunded["refund_amount_cents"] == 2065
        assert refunded["refund_amount_cents"] + refunded["retained_fee_cents"] == 2429

    def test_refund_of_refunded_order_rejected(self, api):
        """PRD §3.7: "Refunds move an order `PAID → REFUNDED`"
        PRD §3.7: "the order must be `RESERVED` (`ERR_INVALID_ORDER_STATUS`)" and
        the gate scan requires "the order is `PAID` (`ERR_INVALID_ORDER_STATUS`)"
        — the catalogue's order-state error for a from-state violation.

        Design: Corner/state_machines/refund_of_refunded_order_rejected
        """
        event = setup_published_event()
        order = setup_paid_order(event["id"], buyer="spec-1",
                                 lines=[ticket_line("ADULT_DAY", 1)])
        first = validate_success(
            api_client.refund_ticket_order(order["id"], {"reason": "PATRON_CHOICE"},
                                           make_spectator_headers("spec-1")),
            200,
        )
        assert first["status"] == "REFUNDED"

        second = api_client.refund_ticket_order(order["id"], {"reason": "PATRON_CHOICE"},
                                                make_spectator_headers("spec-1"))
        validate_error(second, ApiErrorId.ERR_INVALID_ORDER_STATUS, 409)
        reread = validate_success(api_client.get_ticket_order(order["id"], ORG), 200)
        assert reread["status"] == "REFUNDED"
        assert reread["refund_amount_cents"] == first["refund_amount_cents"]
        assert reread["retained_fee_cents"] == first["retained_fee_cents"], (
            "a second refund changes no amounts"
        )
