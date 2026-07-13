"""The dual-axis sales order: pricing, the parallel payment/fulfillment axes,
inventory reservation and its compensating release, and the shipping guards."""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    setup_completed_run,
    setup_paid_allocated_order,
    create_customer,
    create_order,
    create_tax_removal_payload,
    assert_case_conservation,
)

_SM = TEST_USERS["sales_headers"]
_OC = TEST_USERS["compliance_headers"]


class TestParallelAxes:
    def test_pay_advances_both_axes(self, api):
        """PRD 3.8: "Paying an order ... advances `payment_status` from `UNPAID` to
        `PAID` and, in the same step, advances `fulfillment_status` from `PENDING` to
        `ALLOCATED`, reserving inventory."

        Design: Difficulty/non_linear_state_machine/sales_order_payment_fulfillment_parallel_axes
        """
        ctx = setup_paid_allocated_order(api, cases=4, planned_cases=10, dsp_permit_number="DSP-SO-1")
        assert ctx["order"]["payment_status"] == "PAID"
        assert ctx["order"]["fulfillment_status"] == "ALLOCATED"

    def test_cancel_keeps_paid_then_refund(self, api):
        """PRD 3.8: "Cancelling an order ... moves `fulfillment_status` to `CANCELLED`
        from either `PENDING` or `ALLOCATED`." PRD 3.8: "Refunding is a `SalesManager`
        action that advances `payment_status` from `PAID` to `REFUNDED`; it requires
        that the order be `PAID` and that its `fulfillment_status` already be
        `CANCELLED`".

        Design: Difficulty/non_linear_state_machine/sales_order_payment_fulfillment_parallel_axes
        """
        ctx = setup_paid_allocated_order(api, cases=4, planned_cases=10, dsp_permit_number="DSP-SO-2")
        oid = ctx["order"]["id"]
        cancelled = validate_success(api.cancel_order(oid, _SM))
        assert cancelled["fulfillment_status"] == "CANCELLED"
        assert cancelled["payment_status"] == "PAID"
        refunded = validate_success(api.refund_order(oid, _SM))
        assert refunded["payment_status"] == "REFUNDED"
        assert refunded["fulfillment_status"] == "CANCELLED"


class TestCaseInventoryConservation:
    def test_cancel_restores_cases_available(self, api):
        """PRD 3.8: "If the order was `ALLOCATED`, its reservation is released: the
        run's `cases_reserved` is reduced by `cases`, its `cases_available` is
        increased by `cases`".

        Design: Difficulty/compensating_invariant/case_inventory_conservation_pay_then_cancel
        """
        ctx = setup_paid_allocated_order(api, cases=4, planned_cases=10, dsp_permit_number="DSP-SO-3")
        api.cancel_order(ctx["order"]["id"], _SM)
        run = validate_success(api.get_bottling_run(ctx["bottling_run"]["id"], _SM))
        assert run["cases_available"] == 10

    def test_cancel_conserves_case_totals(self, api):
        """PRD 3.8: "On a successful payment, the run's `cases_available` is reduced by
        `cases` and its `cases_reserved` is increased by `cases`". PRD 3.8: the cancel
        "is the compensating counterpart to payment's reservation."

        Design: Difficulty/compensating_invariant/case_inventory_conservation_pay_then_cancel
        """
        ctx = setup_paid_allocated_order(api, cases=4, planned_cases=10, dsp_permit_number="DSP-SO-4")
        api.cancel_order(ctx["order"]["id"], _SM)
        run = validate_success(api.get_bottling_run(ctx["bottling_run"]["id"], _SM))
        assert run["cases_reserved"] == 0
        assert run["cases_bottled"] == 10
        assert_case_conservation(run)


class TestThreeTierShipTaxDetermined:
    def test_ship_blocked_while_in_bond(self, api):
        """PRD 3.8: "For a `THREE_TIER` order, the referenced run's `tax_status` must
        be `TAX_DETERMINED`, otherwise the shipment is rejected with
        `ERR_NOT_TAX_DETERMINED`".

        Design: Difficulty/cross_entity_state_dependency/three_tier_ship_requires_tax_determined_run
        """
        ctx = setup_paid_allocated_order(api, cases=2, planned_cases=10, channel="THREE_TIER",
                                         dsp_permit_number="DSP-SO-5")
        resp = api.ship_order(ctx["order"]["id"], _SM)
        validate_error(resp, ApiErrorId.ERR_NOT_TAX_DETERMINED.value)

    def test_ship_allowed_after_taxpaid_removal(self, api):
        """PRD 3.6: "A `TAXPAID` removal additionally updates the bond and CBMA ledger:
        the run's `tax_status` becomes `TAX_DETERMINED`". PRD 3.8: "Shipping an
        allocated order ... advances `fulfillment_status` from `ALLOCATED` to `SHIPPED`."

        Design: Difficulty/cross_entity_state_dependency/three_tier_ship_requires_tax_determined_run
        """
        ctx = setup_paid_allocated_order(api, cases=2, planned_cases=10, channel="THREE_TIER",
                                         dsp_permit_number="DSP-SO-6")
        get_success_data(
            api.create_tax_removal(
                create_tax_removal_payload(ctx["bottling_run"]["id"], removal_reason="TAXPAID", removed_cases=3),
                _OC,
            )
        )
        run = validate_success(api.get_bottling_run(ctx["bottling_run"]["id"], _SM))
        assert run["tax_status"] == "TAX_DETERMINED"
        shipped = validate_success(api.ship_order(ctx["order"]["id"], _SM))
        assert shipped["fulfillment_status"] == "SHIPPED"


class TestTaxRemovalAutocancel:
    def _setup_pending_order_on_5case_run(self, api, permit):
        ctx = setup_completed_run(api, dsp_permit_number=permit, planned_cases=5, fill_proof_gallons=10)
        cust = create_customer(api, age_verified=True)
        order = create_order(api, cust["id"], ctx["bottling_run"]["id"], channel="THREE_TIER", cases=2)
        return ctx, order

    def test_taxpaid_removal_sells_out_run(self, api):
        """PRD 3.6: "Every removal reduces the run's on-hand inventory: the run's
        `cases_available` is reduced by `removed_cases` and its `cases_removed` is
        increased by the same amount, and if that brings `cases_available` to zero, the
        run's `inventory_status` becomes `SOLD_OUT`."

        Design: Difficulty/transitive_cascade/taxpaid_removal_sells_out_run_autocancels_pending_order
        """
        ctx, _ = self._setup_pending_order_on_5case_run(api, "DSP-SO-7")
        api.create_tax_removal(
            create_tax_removal_payload(ctx["bottling_run"]["id"], removal_reason="TAXPAID", removed_cases=5),
            _OC,
        )
        run = validate_success(api.get_bottling_run(ctx["bottling_run"]["id"], _SM))
        assert run["cases_available"] == 0
        assert run["inventory_status"] == "SOLD_OUT"

    def test_taxpaid_removal_autocancels_pending_order(self, api):
        """PRD 3.6: "whenever a removal drives a run's `inventory_status` to
        `SOLD_OUT`, every sales order on that run whose `fulfillment_status` is still
        `PENDING` is automatically cancelled, moving each such order's
        `fulfillment_status` to `CANCELLED`."

        Design: Difficulty/transitive_cascade/taxpaid_removal_sells_out_run_autocancels_pending_order
        """
        ctx, order = self._setup_pending_order_on_5case_run(api, "DSP-SO-8")
        api.create_tax_removal(
            create_tax_removal_payload(ctx["bottling_run"]["id"], removal_reason="TAXPAID", removed_cases=5),
            _OC,
        )
        refreshed = validate_success(api.get_sales_order(order["id"], _SM))
        assert refreshed["fulfillment_status"] == "CANCELLED"


class TestOrderPricing:
    def test_cocktail_surcharge_applied(self, api):
        """PRD 3.8: "the `subtotal_cents` is `unit_price_cents` multiplied by `cases`,
        and the `total_cents` is that subtotal plus a cocktail surcharge of 1,200 cents
        when `includes_cocktail` is true".

        Design: Corner/calculations/order_pricing_cocktail_surcharge_applied
        """
        ctx = setup_completed_run(api, dsp_permit_number="DSP-SO-9", planned_cases=10)
        cust = create_customer(api, age_verified=True)
        order = create_order(api, cust["id"], ctx["bottling_run"]["id"], channel="TASTING_ROOM",
                             cases=4, unit_price_cents=5000, includes_cocktail=True)
        assert order["subtotal_cents"] == 20000
        assert order["total_cents"] == 21200


class TestPaymentGuards:
    def test_ship_before_pay_rejected(self, api):
        """PRD 3.8: "Shipping an allocated order ... The order must be `ALLOCATED` and
        its `payment_status` must be `PAID`." PRD 2.1: illegal transitions surface
        `ERR_INVALID_STATE` (409).

        Design: Corner/state_machines/sales_order_ship_before_pay_returns_invalid_state
        """
        ctx = setup_completed_run(api, dsp_permit_number="DSP-SO-10", planned_cases=5, fill_proof_gallons=10)
        cust = create_customer(api, age_verified=True)
        order = create_order(api, cust["id"], ctx["bottling_run"]["id"], channel="THREE_TIER", cases=1)
        resp = api.ship_order(order["id"], _SM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_pay_without_age_verification_forbidden(self, api):
        """PRD 3.8: "the customer's `age_verified` must be true, otherwise it is
        rejected with `ERR_AGE_NOT_VERIFIED`".

        Design: Corner/validations/pay_without_age_verification_returns_forbidden
        """
        ctx = setup_completed_run(api, dsp_permit_number="DSP-SO-11", planned_cases=5, fill_proof_gallons=10)
        cust = create_customer(api, age_verified=False)
        order = create_order(api, cust["id"], ctx["bottling_run"]["id"], channel="THREE_TIER", cases=1)
        resp = api.pay_order(order["id"], _SM)
        validate_error(resp, ApiErrorId.ERR_AGE_NOT_VERIFIED.value)

    def test_club_order_without_release_ineligible(self, api):
        """PRD 3.8: "if the `channel` is `CLUB`, the distillery's
        `club_release_active` must be true and the customer's `club_tier` must not be
        `NONE`, otherwise it is rejected with `ERR_CLUB_NOT_ELIGIBLE`".

        Design: Corner/validations/club_order_without_release_returns_ineligible
        """
        ctx = setup_completed_run(api, dsp_permit_number="DSP-SO-12", planned_cases=5, fill_proof_gallons=10)
        cust = create_customer(api, club_tier="GOLD", age_verified=True)
        order = create_order(api, cust["id"], ctx["bottling_run"]["id"], channel="CLUB", cases=1)
        resp = api.pay_order(order["id"], _SM)
        validate_error(resp, ApiErrorId.ERR_CLUB_NOT_ELIGIBLE.value)

    def test_pay_exceeding_inventory_rejected(self, api):
        """PRD 3.8: "the run must have at least `cases` in `cases_available`, otherwise
        it is rejected with `ERR_INSUFFICIENT_INVENTORY`".

        Design: Corner/validations/pay_exceeds_inventory_returns_insufficient
        """
        ctx = setup_completed_run(api, dsp_permit_number="DSP-SO-13", planned_cases=5, fill_proof_gallons=10)
        cust = create_customer(api, age_verified=True)
        order = create_order(api, cust["id"], ctx["bottling_run"]["id"], channel="THREE_TIER", cases=10)
        resp = api.pay_order(order["id"], _SM)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_INVENTORY.value)
