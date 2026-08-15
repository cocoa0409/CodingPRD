"""Customer cancellation timing policy and the operator refund pipeline:
policy-computed amounts, approve cap, payment-axis transitions, wallet credits,
and money conservation (PRD §3.4, §3.7, §3.8)."""
from test_helpers import (
    ApiErrorId,
    approve_refund,
    assert_payment_conservation,
    cancel_flight,
    create_confirmed_booking,
    customer_cancel,
    enter_weather_review,
    get_customer,
    get_reservation,
    list_refunds,
    pay_refund,
    record_no_go,
    set_clock,
    setup_early_customer_cancel,
    setup_scheduled_flight,
    sole_refund,
    validate_error,
)

# Declared weights above 600 lbs need extra gross headroom on the balloon so
# the booking-time weight-and-balance check (PRD §3.4) passes; SHARED fares do
# not depend on the balloon, so asserted amounts are unchanged.
ROOMY_BALLOON = {"max_gross_weight_lbs": 1500}


class TestCustomerCancelTiming:
    def test_customer_cancel_late_forfeits_fare(self, api, ops_headers):
        """PRD §3.7: "Cancelling a `CONFIRMED` reservation forks on timing: when
        the cancellation lands before the point 24 hours ahead of the flight's
        `dawn_window_start` — that is, strictly earlier than `dawn_window_start`
        minus 24 hours — the reason is `CUSTOMER_CANCEL_EARLY` and a `Refund` is
        auto-created in `REQUESTED`; otherwise the reason is
        `CUSTOMER_CANCEL_LATE`, no refund is created at all, and the fare is
        forfeited with `payment_status` left at `PAID`."

        Design: Corner/calculations/customer_cancel_late_forfeits_fare
        """
        ctx = setup_scheduled_flight()
        customer, reservation = create_confirmed_booking(
            ctx["flight"], party_size=1, declared_weight_lbs=180
        )
        assert reservation["paid_cents"] == 29900
        # 2026-08-09T12:00:00Z is 17.5h before the 2026-08-10T05:30:00Z window —
        # inside the 24-hour late window.
        set_clock("2026-08-09T12:00:00Z")
        cancelled = customer_cancel(reservation, customer)
        assert cancelled["cancel_reason"] == "CUSTOMER_CANCEL_LATE"
        assert cancelled["payment_status"] == "PAID", "the fare is forfeited"
        assert cancelled["retained_revenue_cents"] == 29900
        assert list_refunds(reservation["id"]) == [], (
            "no refund record is created for a late customer cancel"
        )


class TestRefundAmountPolicy:
    def test_refund_charter_total_then_round(self, api):
        """PRD §3.7: "On a `CHARTER` flight, the requested amount is the
        reservation's `paid_cents` multiplied by the policy percentage, divided
        by 100, rounded half-up to the nearest cent." — with an 80-percent early
        cancel, 184900 * 80 / 100 = 147920."

        Design: Corner/calculations/refund_charter_total_then_round
        """
        ctx = setup_early_customer_cancel(
            party_size=4,
            declared_weight_lbs=560,
            photo_package_tier="STANDARD",
            flight_kw={"kind": "CHARTER"},
        )
        reservation = ctx["reservation"]
        # REGULAR charter, capacity 6: flat 180000 + STANDARD 4900 = 184900.
        assert reservation["paid_cents"] == 184900
        assert reservation["cancel_reason"] == "CUSTOMER_CANCEL_EARLY"
        assert ctx["refund"]["requested_amount_cents"] == 147920

    def test_refund_per_passenger_first_rounding_pinned(self, api):
        """PRD §3.7: "Otherwise — the 80-percent early-cancel case — the
        computation rounds per passenger first: divide `paid_cents` by
        `party_size` and round half-up to get the per-passenger paid amount,
        multiply that per-passenger figure by 80 and divide by 100 with a
        half-up round to get the per-passenger refund, then multiply the
        per-passenger refund by `party_size` for the requested amount.
        Multiplying first and rounding the total is a different answer and is
        not the specification."

        Design: Difficulty/combinatorial_formula/refund_per_passenger_rounding_order
        """
        # paid 102100 over party 3: per-passenger-first gives
        # round(102100/3)=34033 -> round(34033*0.8)=27226 -> x3 = 81678;
        # total-then-round would give round(102100*0.8) = 81680.
        ctx = setup_scheduled_flight(balloon_kw=dict(ROOMY_BALLOON))
        customer, reservation = create_confirmed_booking(
            ctx["flight"], party_size=3, declared_weight_lbs=660,
            photo_package_tier="STANDARD",
        )
        assert reservation["quoted_fare_cents"] == 102100  # 3*32400 + 4900
        assert reservation["paid_cents"] == 102100
        set_clock("2026-08-08T00:00:00Z")
        cancelled = customer_cancel(reservation, customer)
        assert cancelled["cancel_reason"] == "CUSTOMER_CANCEL_EARLY"
        refund = sole_refund(reservation["id"])
        assert refund["requested_amount_cents"] == 81678, (
            f"per-passenger-first rounding pins 81678; total-first would be "
            f"81680 — got {refund['requested_amount_cents']}"
        )
        assert refund["requested_amount_cents"] != 81680

    def test_refund_per_passenger_first_rounding_second_witness(self, api):
        """PRD §3.7: "Otherwise — the 80-percent early-cancel case — the
        computation rounds per passenger first: divide `paid_cents` by
        `party_size` and round half-up to get the per-passenger paid amount,
        multiply that per-passenger figure by 80 and divide by 100 with a
        half-up round to get the per-passenger refund, then multiply the
        per-passenger refund by `party_size` for the requested amount.
        Multiplying first and rounding the total is a different answer and is
        not the specification." — paid 94600 over party 3: per-passenger-first
        gives round(94600/3)=31533 -> round(31533*0.8)=25226 -> x3 = 75678,
        while total-first would give round(94600*0.8) = 75680.

        Design: Difficulty/combinatorial_formula/refund_per_passenger_rounding_order
        """
        ctx = setup_early_customer_cancel(
            party_size=3, declared_weight_lbs=600, photo_package_tier="STANDARD"
        )
        reservation = ctx["reservation"]
        assert reservation["paid_cents"] == 94600  # 3*29900 + 4900 (avg 200: no surcharge)
        assert reservation["cancel_reason"] == "CUSTOMER_CANCEL_EARLY"
        assert ctx["refund"]["requested_amount_cents"] == 75678
        assert ctx["refund"]["requested_amount_cents"] != 75680


class TestRefundPipeline:
    def test_approve_refund_above_requested_cap(self, api, ops_headers):
        """PRD §3.7: "An `OperationsManager` approves a `REQUESTED` refund by
        supplying `approved_amount_cents`, which must not exceed
        `requested_amount_cents` — an over-cap approval is rejected with
        `ERR_REFUND_POLICY_VIOLATION` (HTTP 422) — moving the refund to
        `APPROVED`."

        Design: Corner/validations/approve_refund_above_requested_cap
        """
        ctx = setup_early_customer_cancel(party_size=1, declared_weight_lbs=180)
        refund = ctx["refund"]
        assert refund["requested_amount_cents"] == 23920  # 80% of 29900, party 1
        resp = api.refund_event(
            refund["id"], {"event_type": "APPROVE", "approved_amount_cents": 23921},
            ops_headers,
        )
        validate_error(resp, ApiErrorId.ERR_REFUND_POLICY_VIOLATION)
        refunds = list_refunds(ctx["reservation"]["id"])
        assert refunds[0]["status"] == "REQUESTED", (
            "a rejected approve leaves the refund REQUESTED"
        )

    def test_refund_invalid_from_state_double_approve(self, api, ops_headers):
        """PRD §2.9: "From-state validity: the resource is in a state from which
        the requested transition exists (`ERR_INVALID_STATE`, HTTP 409)."
        PRD §3.7: "An `OperationsManager` approves a `REQUESTED` refund by
        supplying `approved_amount_cents`, which must not exceed
        `requested_amount_cents` — an over-cap approval is rejected with
        `ERR_REFUND_POLICY_VIOLATION` (HTTP 422) — moving the refund to
        `APPROVED`." — APPROVE is not a transition out of APPROVED.

        Design: Corner/state_machines/refund_invalid_from_state_double_approve
        """
        ctx = setup_early_customer_cancel(party_size=1, declared_weight_lbs=180)
        refund = ctx["refund"]
        approved = approve_refund(refund["id"], 23920)
        assert approved["status"] == "APPROVED"
        resp = api.refund_event(
            refund["id"], {"event_type": "APPROVE", "approved_amount_cents": 23920},
            ops_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestParallelPaymentDimension:
    def test_cancel_leaves_payment_axis_paid_until_refund_pay(self, api, ops_headers):
        """PRD §3.7: a customer early cancel moves booking to `CANCELLED` while
        the payment axis is still `PAID`; then "the reservation's
        `refunded_cents` grows by `approved_amount_cents`; its `payment_status`
        moves to `PARTIALLY_REFUNDED` when the cumulative refunded total is
        still below `paid_cents`".

        Design: Difficulty/non_linear_state_machine/reservation_parallel_payment_dimension
        """
        ctx = setup_early_customer_cancel(party_size=1, declared_weight_lbs=180)
        reservation = ctx["reservation"]
        refund = ctx["refund"]
        # Intermediate combination: booking axis terminal, payment axis unmoved.
        assert reservation["booking_status"] == "CANCELLED"
        assert reservation["payment_status"] == "PAID"
        assert refund["status"] == "REQUESTED"
        assert refund["requested_amount_cents"] == 23920

        approve_refund(refund["id"], 23920)
        paid = pay_refund(refund["id"], "ORIGINAL_PAYMENT")
        assert paid["status"] == "PAID"
        assert paid["paid_at"] is not None
        after = get_reservation(reservation["id"])
        assert after["booking_status"] == "CANCELLED"
        assert after["payment_status"] == "PARTIALLY_REFUNDED", (
            "23920 of 29900 refunded -> still below paid_cents"
        )
        assert after["refunded_cents"] == 23920

    def test_full_refund_pay_moves_payment_axis_to_refunded(self, api, ops_headers):
        """PRD §3.7: "its `payment_status` moves to `PARTIALLY_REFUNDED` when
        the cumulative refunded total is still below `paid_cents`, and to
        `REFUNDED` when a payment brings the cumulative `refunded_cents` exactly
        level with `paid_cents`". A weather cancel carries a 100-percent policy
        ("The policy percentage is 100 for `WEATHER_CANCEL`"), and on a SHARED
        flight "a 100-percent policy triggers the full-fare carve-out: the
        requested amount is simply `paid_cents`, exactly."

        Design: Difficulty/non_linear_state_machine/reservation_parallel_payment_dimension
        """
        ctx = setup_scheduled_flight()
        customer, reservation = create_confirmed_booking(
            ctx["flight"], party_size=1, declared_weight_lbs=180
        )
        enter_weather_review(ctx)
        record_no_go(ctx)
        cancel_flight(ctx)
        refund = sole_refund(reservation["id"])
        assert refund["reason"] == "WEATHER_CANCEL"
        assert refund["requested_amount_cents"] == 29900, "100% full-fare carve-out"

        approve_refund(refund["id"], 29900)
        pay_refund(refund["id"], "ORIGINAL_PAYMENT")
        after = get_reservation(reservation["id"])
        assert after["booking_status"] == "CANCELLED"
        assert after["payment_status"] == "REFUNDED", (
            "cumulative refunded_cents exactly level with paid_cents"
        )
        assert after["refunded_cents"] == 29900
        assert after["retained_revenue_cents"] == 0
        assert_payment_conservation(after)


class TestPaymentConservation:
    def test_payment_conserved_wallet_credit_refund(self, api, ops_headers):
        """PRD §3.7: "the reservation's `retained_revenue_cents` is always
        `paid_cents` minus `refunded_cents`. When `paid_via` is `WALLET_CREDIT`,
        the approved amount is also credited to the customer's
        `wallet_credit_cents`."

        Design: Difficulty/compensating_invariant/payment_conserved_across_partial_refund
        """
        ctx = setup_scheduled_flight(balloon_kw=dict(ROOMY_BALLOON))
        customer, reservation = create_confirmed_booking(
            ctx["flight"], party_size=3, declared_weight_lbs=660,
            photo_package_tier="STANDARD",
        )
        assert reservation["paid_cents"] == 102100
        set_clock("2026-08-08T00:00:00Z")
        customer_cancel(reservation, customer)
        refund = sole_refund(reservation["id"])
        assert refund["requested_amount_cents"] == 81678

        approve_refund(refund["id"], 81678)
        pay_refund(refund["id"], "WALLET_CREDIT")

        after = get_reservation(reservation["id"])
        assert after["refunded_cents"] == 81678
        assert after["retained_revenue_cents"] == 20422, "102100 - 81678"
        assert_payment_conservation(after)
        assert after["payment_status"] == "PARTIALLY_REFUNDED"
        assert get_customer(customer["id"])["wallet_credit_cents"] == 81678, (
            "WALLET_CREDIT payout lands in the customer's wallet"
        )

    def test_payment_conserved_original_payment_keeps_wallet(self, api, ops_headers):
        """PRD §3.7: "the reservation's `retained_revenue_cents` is always
        `paid_cents` minus `refunded_cents`. When `paid_via` is `WALLET_CREDIT`,
        the approved amount is also credited to the customer's
        `wallet_credit_cents`." — paying via `ORIGINAL_PAYMENT` performs no
        wallet credit, while the per-reservation money conservation still holds.

        Design: Difficulty/compensating_invariant/payment_conserved_across_partial_refund
        """
        ctx = setup_scheduled_flight(balloon_kw=dict(ROOMY_BALLOON))
        customer, reservation = create_confirmed_booking(
            ctx["flight"], party_size=3, declared_weight_lbs=660,
            photo_package_tier="STANDARD",
        )
        set_clock("2026-08-08T00:00:00Z")
        customer_cancel(reservation, customer)
        refund = sole_refund(reservation["id"])

        approve_refund(refund["id"], 81678)
        pay_refund(refund["id"], "ORIGINAL_PAYMENT")

        after = get_reservation(reservation["id"])
        assert after["refunded_cents"] == 81678
        assert after["retained_revenue_cents"] == 20422
        assert_payment_conservation(after)
        assert get_customer(customer["id"])["wallet_credit_cents"] == 0, (
            "ORIGINAL_PAYMENT refunds do not touch the wallet"
        )
