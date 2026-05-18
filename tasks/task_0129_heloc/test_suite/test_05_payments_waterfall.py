"""Payments: waterfall allocation, minimum-payment computation, and
state-based rejections.

Covers PRD §3.4 (payment posting, interest-first waterfall, principal
clamping) and the minimum_payment_due_cents per-status variants.
"""
from __future__ import annotations

import math

import pytest

from test_helpers import (
    ApiErrorId,
    assert_credit_conservation,
    assert_payment,
    assert_version_incremented_by_one,
    close_heloc,
    create_payment_payload,
    get_heloc,
    make_borrower_headers,
    post_payment,
    run_billing_cycle_sweep,
    setup_active_heloc,
    setup_active_heloc_with_balance,
    setup_heloc_closed_no_balance,
    setup_heloc_default_via_bankruptcy,
    setup_heloc_in_repay,
    setup_heloc_with_accrued_interest,
    validate_error,
    validate_success,
)


# ===========================================================================
# §3.4 Waterfall: interest first, then principal
# ===========================================================================
class TestWaterfallAllocation:

    def test_interest_settled_first_then_principal(self, api):
        """PRD §3.4: "When a payment is accepted, the system applies a
        waterfall allocation that settles accrued interest before
        principal. The interest_component_cents is the smaller of the
        payment's amount_cents and the HELOC's accrued_interest_cents
        immediately before the payment; the principal_component_cents
        is the payment's amount_cents minus the interest_component_cents."

        Construct a HELOC with known accrued_interest_cents > 0 by
        running a billing cycle on a drawn balance, then post a
        payment that exceeds accrued interest — observe interest
        bucket fully cleared and principal reduced by the remainder.
        """
        borrower, _, _, heloc = setup_heloc_with_accrued_interest(
            draw_amount_cents=1_000_000,
            cycles_to_accrue=1,
            margin_bps=300,
            periodic_cap_bps=200,
            lifetime_cap_bps=2000,
            lifetime_floor_bps=100,
            prime_rate_bps_at_origination=500,
        )
        # After one cycle at current_rate_bps=800 on principal
        # 1_000_000: cycle_interest = round_half_up(
        # 1_000_000 * 800/10000 * 30/365) =
        # round_half_up(6575.342) = 6575.
        accrued_before = heloc["accrued_interest_cents"]
        assert accrued_before == 6575, (
            f"PRD §3.7 accrual must round-half-up; got {accrued_before}"
        )

        principal_before = heloc["principal_balance_cents"]
        resp = api.create_payment(
            heloc["id"],
            create_payment_payload(amount_cents=10_000),
            make_borrower_headers(borrower["id"]),
        )
        payment = validate_success(resp, 201)
        assert_payment(payment)
        assert payment["interest_component_cents"] == 6_575
        assert payment["principal_component_cents"] == 3_425
        assert payment["amount_cents"] == 10_000

        h2 = get_heloc(
            heloc["id"], make_borrower_headers(borrower["id"]),
        )
        assert h2["accrued_interest_cents"] == 0
        assert (
            h2["principal_balance_cents"]
            == principal_before - 3_425
        )
        assert_version_incremented_by_one(h2, heloc)
        # available_credit must move back up by 3425.
        assert_credit_conservation(h2)

    def test_payment_smaller_than_accrued_only_interest_reduced(
        self, api,
    ):
        """PRD §3.4: "The interest_component_cents is the smaller of
        the payment's amount_cents and the HELOC's
        accrued_interest_cents immediately before the payment".

        With payment < accrued, interest_component = amount and
        principal_component = 0.
        """
        borrower, _, _, heloc = setup_heloc_with_accrued_interest(
            draw_amount_cents=1_000_000, cycles_to_accrue=1,
        )
        accrued_before = heloc["accrued_interest_cents"]
        assert accrued_before > 0
        # Pay just one cent. minimum_payment_due (DRAW) is
        # accrued_interest_cents = 6575. We need to bypass that floor
        # — but PRD §3.4 forces payment >= minimum_payment_due.
        # Instead, we send EXACTLY accrued so principal_component=0
        # and interest_component=accrued.
        resp = api.create_payment(
            heloc["id"],
            create_payment_payload(amount_cents=accrued_before),
            make_borrower_headers(borrower["id"]),
        )
        payment = validate_success(resp, 201)
        assert payment["interest_component_cents"] == accrued_before
        assert payment["principal_component_cents"] == 0
        h2 = get_heloc(
            heloc["id"], make_borrower_headers(borrower["id"]),
        )
        assert h2["accrued_interest_cents"] == 0
        assert (
            h2["principal_balance_cents"]
            == heloc["principal_balance_cents"]
        )

    def test_payment_components_sum_to_amount(self, api):
        """PRD §3.4: "the principal_component_cents is the payment's
        amount_cents minus the interest_component_cents".
        """
        borrower, _, _, heloc = setup_heloc_with_accrued_interest(
            draw_amount_cents=500_000, cycles_to_accrue=1,
        )
        resp = api.create_payment(
            heloc["id"],
            create_payment_payload(amount_cents=12_345),
            make_borrower_headers(borrower["id"]),
        )
        payment = validate_success(resp, 201)
        assert (
            payment["interest_component_cents"]
            + payment["principal_component_cents"]
            == payment["amount_cents"]
        )


# ===========================================================================
# §3.4 minimum_payment_due in DRAW (interest-only)
# ===========================================================================
class TestMinimumPaymentDrawVariant:

    def test_minimum_payment_in_draw_equals_accrued_interest(self, api):
        """PRD §3.4: "When the HELOC is in DRAW, the minimum is exactly
        the accrued_interest_cents carried since the last
        billing-cycle reset — the draw period requires nothing more
        than interest service."
        """
        borrower, _, _, heloc = setup_heloc_with_accrued_interest(
            draw_amount_cents=1_000_000, cycles_to_accrue=1,
        )
        h = get_heloc(
            heloc["id"], make_borrower_headers(borrower["id"]),
        )
        assert h["status"] == "DRAW"
        assert (
            h["minimum_payment_due_cents"]
            == h["accrued_interest_cents"]
        )

    def test_payment_below_minimum_in_draw_rejected(self, api):
        """PRD §3.4: "The supplied amount_cents must be at least the
        HELOC's minimum_payment_due_cents computed at request time, or
        the request is rejected with ERR_PAYMENT_BELOW_MINIMUM."
        """
        borrower, _, _, heloc = setup_heloc_with_accrued_interest(
            draw_amount_cents=1_000_000, cycles_to_accrue=1,
        )
        # minimum == accrued_interest_cents (6575). Pay 1 below.
        resp = api.create_payment(
            heloc["id"],
            create_payment_payload(
                amount_cents=heloc["accrued_interest_cents"] - 1,
            ),
            make_borrower_headers(borrower["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PAYMENT_BELOW_MINIMUM.value)


# ===========================================================================
# §3.4 minimum_payment_due in DEFAULT (full payoff)
# ===========================================================================
class TestMinimumPaymentDefaultVariant:

    def test_minimum_payment_in_default_is_full_payoff(self, api):
        """PRD §3.4: "When the HELOC is in DEFAULT, the minimum is the
        full payoff demand: principal_balance_cents plus
        accrued_interest_cents."
        """
        # Build a HELOC with a draw + accrued interest, then default.
        from test_helpers import (
            post_bankruptcy_event,
            setup_active_heloc_with_balance,
        )
        borrower, _, _, heloc, _ = setup_active_heloc_with_balance(
            draw_amount_cents=500_000,
        )
        # Accrue interest before defaulting.
        from test_helpers import advance_clock_days
        advance_clock_days(days=30)
        run_billing_cycle_sweep()
        # Now drive into DEFAULT via bankruptcy.
        post_bankruptcy_event(borrower["id"])
        h = get_heloc(
            heloc["id"], make_borrower_headers(borrower["id"]),
        )
        assert h["status"] == "DEFAULT"
        expected = (
            h["principal_balance_cents"]
            + h["accrued_interest_cents"]
        )
        assert h["minimum_payment_due_cents"] == expected


# ===========================================================================
# §3.4 minimum_payment_due in PENDING / CLOSED
# ===========================================================================
class TestMinimumPaymentTerminalVariants:

    def test_minimum_payment_in_closed_is_zero(self, api):
        """PRD §3.4: "When the HELOC is in PENDING or CLOSED, the
        minimum is zero."
        """
        borrower, _, _, closed_heloc = setup_heloc_closed_no_balance()
        assert closed_heloc["status"] == "CLOSED"
        h = get_heloc(
            closed_heloc["id"],
            make_borrower_headers(borrower["id"]),
        )
        assert h["minimum_payment_due_cents"] == 0


# ===========================================================================
# §3.4 Payments rejected on CLOSED
# ===========================================================================
class TestPaymentClosedRejection:

    def test_payment_on_closed_heloc_rejected(self, api):
        """PRD §3.4: "Payments are accepted while the HELOC is in
        DRAW, REPAY, or DEFAULT; they are not accepted on a CLOSED
        HELOC, which yields ERR_HELOC_CLOSED."
        """
        borrower, _, _, closed_heloc = setup_heloc_closed_no_balance()
        resp = api.create_payment(
            closed_heloc["id"],
            create_payment_payload(amount_cents=10_000),
            make_borrower_headers(borrower["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_HELOC_CLOSED.value)


# ===========================================================================
# §3.4 Principal cannot go negative
# ===========================================================================
class TestPrincipalClampedNonNegative:

    def test_principal_balance_clamped_to_zero_on_overpayment(
        self, api,
    ):
        """PRD §3.4: "its principal_balance_cents is reduced by the
        principal component but never permitted to drop below zero:
        if the principal component would otherwise drive the balance
        negative, the balance is clamped to zero."

        Construct a HELOC with small principal + small accrued, then
        send a payment whose principal_component would over-shoot
        the outstanding principal. The balance must clamp to 0 and
        not go negative.
        """
        borrower, _, _, heloc = setup_heloc_with_accrued_interest(
            draw_amount_cents=20_000,  # small principal
            cycles_to_accrue=1,
        )
        accrued = heloc["accrued_interest_cents"]
        principal = heloc["principal_balance_cents"]
        # Over-pay by 5_000 so principal_component would be
        # principal + 5_000 if not clamped.
        over_payment = accrued + principal + 5_000
        post_payment(
            heloc["id"], amount_cents=over_payment,
            headers=make_borrower_headers(borrower["id"]),
        )
        h = get_heloc(
            heloc["id"], make_borrower_headers(borrower["id"]),
        )
        # principal_balance_cents MUST be 0 (clamped, not negative).
        assert h["principal_balance_cents"] == 0, (
            f"PRD §3.4 clamp: principal_balance_cents must clamp to "
            f"0, never go negative; got "
            f"{h['principal_balance_cents']}"
        )
