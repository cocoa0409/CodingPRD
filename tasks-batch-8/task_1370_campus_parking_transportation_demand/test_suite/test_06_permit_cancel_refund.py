"""Permit cancellation, refund schedule, and compensating seat/revenue effects."""
from test_helpers import (
    ApiErrorId,
    cancel_permit,
    create_allocation,
    create_fund,
    create_lot,
    get_allocation,
    get_fund,
    get_incentive_account,
    get_permit,
    purchase_permit,
    set_clock,
    setup_account_with_credit,
    setup_patron_with_permit,
    validate_error,
    validate_success,
)


class TestProratedRefund:
    def test_refund_prorated_after_term_start(self, api, admin_headers):
        """PRD §3.5.1: "The prorated share is `fee_paid_cents` multiplied by
        `remaining_days` and divided by `total_days`, rounded half-up to the
        nearest integer cent." and "`refund_cents` is the prorated share minus
        `500` cents of administrative fee, floored at zero."
        PRD §3.5.2: "On cancellation, the fund's `permit_revenue_cents`
        decreases by `refund_cents`."

        Design: Corner/calculations/refund_prorated_after_term_start
        """
        fund = create_fund()
        ctx = setup_patron_with_permit(name="R", plate="R111", campus_role="STUDENT",
                                       lot_code="LR")
        set_clock("2026-09-28T00:00:00Z")

        resp = api.cancel_permit(ctx["permit"]["id"], admin_headers)
        cancelled = validate_success(resp, 200)
        assert cancelled["status"] == "CANCELLED"
        # valid_from 2026-08-03 .. valid_to 2026-11-22 -> 112 total days;
        # today 2026-09-28 is consumed, 55 days remain.
        # round_half_up(84000 * 55 / 112) = 41250; 41250 - 500 = 40750.
        assert cancelled["refund_cents"] == 40750, (
            f"prorated refund must be 40750, got {cancelled['refund_cents']}"
        )
        fund_after = get_fund(fund["id"])
        assert fund_after["permit_revenue_cents"] == 43250, (
            f"fund keeps 84000 - 40750 = 43250, got {fund_after['permit_revenue_cents']}"
        )


class TestCancelTerminalLockdown:
    def test_cancel_already_cancelled_permit_rejected(self, api, admin_headers):
        """PRD §3.5: "A permit may be cancelled by its owning `Commuter` or by
        a `ParkingAdmin` while its status is `ACTIVE` or `SUSPENDED`; any
        other status is rejected with `ERR_PERMIT_NOT_ACTIVE` (HTTP 409)."
        PRD §3.5.1: "If `today` is strictly before the permit's `valid_from`,
        `refund_cents` is the full `fee_paid_cents` with no administrative
        fee."

        Design: Corner/state_machines/cancel_already_cancelled_permit_rejected
        """
        ctx = setup_patron_with_permit(name="G", plate="G111", campus_role="STUDENT",
                                       lot_code="LG")
        first = cancel_permit(ctx["permit"]["id"])
        assert first["refund_cents"] == 84000  # pre-term full refund

        resp = api.cancel_permit(ctx["permit"]["id"], admin_headers)
        validate_error(resp, ApiErrorId.ERR_PERMIT_NOT_ACTIVE, 409)
        after = get_permit(ctx["permit"]["id"])
        assert after["status"] == "CANCELLED"
        assert after["refund_cents"] == 84000, (
            "a rejected second cancel must not recompute the refund"
        )


class TestPurchaseCancelCompensation:
    def _setup(self):
        # The fund must exist before the purchase so its ledger observes the
        # fee_paid cash event (PRD §3.10: balances "start at 0" at creation
        # and thereafter track cash events).
        fund = create_fund()
        ctx = setup_patron_with_permit(name="G", plate="G111", campus_role="STUDENT",
                                       quota=3, lot_code="LG")
        return ctx, fund

    def test_cancel_restores_allocation_seat(self, api):
        """PRD §3.5.2: "On cancellation, the fund's `permit_revenue_cents`
        decreases by `refund_cents`. The allocation's `allocated_count`
        decrements by `1`, its status is re-evaluated, and its `version`
        increments."
        PRD §3.2: "after any mutation that leaves the sum strictly below
        `quota`, it flips back to `OPEN`."

        Design: Difficulty/compensating_invariant/purchase_cancel_restores_allocation_seats
        """
        ctx, _ = self._setup()
        alloc_id = ctx["allocation"]["id"]
        mid = get_allocation(alloc_id)
        assert mid["allocated_count"] == 1, (
            f"purchase must consume one seat, got {mid['allocated_count']}"
        )

        cancelled = cancel_permit(ctx["permit"]["id"])
        assert cancelled["status"] == "CANCELLED"

        end = get_allocation(alloc_id)
        assert end["allocated_count"] == 0, (
            f"the compensating cancel must release the seat, got {end['allocated_count']}"
        )
        assert end["status"] == "OPEN", (
            f"0 of 3 seats used must leave the allocation OPEN, got {end['status']}"
        )

    def test_full_refund_zeroes_fund_permit_revenue(self, api):
        """PRD §3.5.1: "If `today` is strictly before the permit's
        `valid_from`, `refund_cents` is the full `fee_paid_cents` with no
        administrative fee."
        PRD §3.10: "`permit_revenue_cents` increases by `fee_paid_cents` at
        every permit purchase and waitlist claim, and decreases by
        `refund_cents` at every permit cancellation."

        Design: Difficulty/compensating_invariant/purchase_cancel_restores_allocation_seats
        """
        ctx, fund = self._setup()
        assert ctx["permit"]["fee_paid_cents"] == 84000, (
            f"full-term purchase at the default clock costs 84000, "
            f"got {ctx['permit']['fee_paid_cents']}"
        )

        cancelled = cancel_permit(ctx["permit"]["id"])
        # Clock is still 2026-08-01 < valid_from 2026-08-03 -> full refund.
        assert cancelled["refund_cents"] == 84000, (
            f"pre-valid_from cancel refunds fee_paid in full, got {cancelled['refund_cents']}"
        )

        fund_after = get_fund(fund["id"])
        assert fund_after["permit_revenue_cents"] == 0, (
            f"84000 in and 84000 out must leave zero drift, "
            f"got {fund_after['permit_revenue_cents']}"
        )


class TestCreditRestoration:
    def test_credit_applied_and_restored_on_cancel(self, api):
        """PRD §3.3.3: "If `apply_credit_cents` is supplied,
        `credit_applied_cents` is the smaller of `apply_credit_cents` and
        `fee_total_cents`; otherwise `credit_applied_cents` is `0`." and
        "`fee_paid_cents` is `fee_total_cents` minus `credit_applied_cents`."
        PRD §3.5.1: "In both branches, any `credit_applied_cents` from the
        original purchase is separately restored in full to the patron's
        incentive account `credit_balance_cents` — the credit is never
        prorated and never charged the administrative fee."

        Design: Corner/cross_cutting_complexity_layers/credit_applied_and_restored_on_cancel
        """
        ctx = setup_account_with_credit(name="M", blocks=1)  # credit 2500
        lot = create_lot(lot_code="LM", name="Lot M")
        allocation = create_allocation(lot["id"], eligible_roles=["STAFF"], quota=5)

        permit = purchase_permit(
            ctx["patron"]["id"], allocation["id"], "M111",
            apply_credit_cents=2500, as_commuter=True,
        )
        assert permit["credit_applied_cents"] == 2500, (
            f"the full requested credit applies, got {permit['credit_applied_cents']}"
        )
        assert permit["fee_paid_cents"] == 81500, (
            f"84000 - 2500 = 81500, got {permit['fee_paid_cents']}"
        )
        mid_account = get_incentive_account(ctx["account"]["id"])
        assert mid_account["credit_balance_cents"] == 0, (
            f"applied credit is debited, got {mid_account['credit_balance_cents']}"
        )

        cancelled = cancel_permit(permit["id"], patron_id=ctx["patron"]["id"])
        assert cancelled["refund_cents"] == 81500, (
            f"pre-valid_from cancel refunds fee_paid 81500, got {cancelled['refund_cents']}"
        )
        end_account = get_incentive_account(ctx["account"]["id"])
        assert end_account["credit_balance_cents"] == 2500, (
            f"applied credit must be restored in full, got {end_account['credit_balance_cents']}"
        )
