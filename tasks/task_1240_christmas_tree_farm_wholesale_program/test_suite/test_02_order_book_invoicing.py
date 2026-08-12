"""Wholesale order book: creation defaults, invoice tiers, credit enforcement."""
from test_helpers import (
    ApiErrorId,
    FM,
    OWNER,
    create_buyer,
    create_draft_order,
    get_success_data,
    setup_booking_season,
    submit_order,
    validate_error,
    validate_success,
    api_client,
    make_buyer_headers,
)


class TestOrderCreationDefaults:
    def test_order_born_draft_with_zero_allocation(self, api):
        """PRD §3.3: "Orders are born `DRAFT` with `allocated_qty` at zero;
        creation outside `BOOKING` is refused with `ERR_POSTURE_FORBIDS`."

        Design: Corner/state_machines/order_create_initial_state_draft
        """
        ctx = setup_booking_season(H_6_7=50)
        buyer = create_buyer()
        order = create_draft_order(
            ctx["season"]["id"], buyer["id"], species="NOBLE_FIR",
            height_class="H_5_6", quantity=12, unit_price_cents=300,
        )
        assert order["status"] == "DRAFT"
        assert order["allocated_qty"] == 0
        assert order["version"] == 1

    def test_invoice_fields_null_until_submit(self, api):
        """PRD §3.3: "All three invoice fields are null until the order is
        submitted."

        Design: Corner/state_machines/order_create_initial_state_draft
        """
        ctx = setup_booking_season(H_6_7=50)
        buyer = create_buyer()
        order = create_draft_order(
            ctx["season"]["id"], buyer["id"], quantity=12, unit_price_cents=300,
        )
        assert order["invoice_subtotal_cents"] is None
        assert order["invoice_discount_cents"] is None
        assert order["invoice_total_cents"] is None
        assert order.get("submitted_at") is None


class TestInvoiceTierBoundary:
    def test_quantity_100_earns_three_percent(self, api):
        """PRD §3.3: "A volume tier is selected by quantity: five percent off
        when at least 200 trees are ordered, eight percent when at least 500,
        three percent when at least 100, and no discount below 100 — each
        threshold inclusive."

        Design: Corner/calculations/invoice_tier_boundary_quantity_100
        """
        ctx = setup_booking_season(H_6_7=500)
        buyer = create_buyer()
        order = create_draft_order(
            ctx["season"]["id"], buyer["id"], quantity=100, unit_price_cents=500,
        )
        submitted = submit_order(order["id"], buyer["id"])
        assert submitted["discount_pct_applied"] == 0.03
        assert submitted["invoice_subtotal_cents"] == 50000
        assert submitted["invoice_discount_cents"] == 1500
        assert submitted["invoice_total_cents"] == 48500

    def test_quantity_99_earns_no_discount(self, api):
        """PRD §3.3: "A volume tier is selected by quantity: five percent off
        when at least 200 trees are ordered, eight percent when at least 500,
        three percent when at least 100, and no discount below 100 — each
        threshold inclusive."

        Design: Corner/calculations/invoice_tier_boundary_quantity_100
        """
        ctx = setup_booking_season(H_6_7=500)
        buyer = create_buyer()
        order = create_draft_order(
            ctx["season"]["id"], buyer["id"], quantity=99, unit_price_cents=500,
        )
        submitted = submit_order(order["id"], buyer["id"])
        assert submitted["discount_pct_applied"] == 0
        assert submitted["invoice_subtotal_cents"] == 49500
        assert submitted["invoice_discount_cents"] == 0
        assert submitted["invoice_total_cents"] == 49500


class TestInvoiceRoundingOrder:
    def test_discount_computed_from_rounded_subtotal(self, api):
        """PRD §3.3: "The chosen fraction is recorded in `discount_pct_applied`,
        and `invoice_discount_cents` is that fraction multiplied by the
        *rounded subtotal*, rounded half-up to whole cents — never a single
        rounding of the net product."

        Design: Difficulty/combinatorial_formula/order_invoice_tier_discount_rounding_order
        """
        ctx = setup_booking_season(H_6_7=500)
        buyer = create_buyer()
        order = create_draft_order(
            ctx["season"]["id"], buyer["id"], species="DOUGLAS_FIR",
            height_class="H_6_7", quantity=250, unit_price_cents=437,
        )
        submitted = submit_order(order["id"], buyer["id"])
        assert submitted["invoice_subtotal_cents"] == 109250  # 250 * 437
        assert submitted["discount_pct_applied"] == 0.05  # 250 >= 200 inclusive
        # round_half_up(109250 * 0.05) = round_half_up(5462.5) = 5463
        assert submitted["invoice_discount_cents"] == 5463

    def test_invoice_total_uses_pinned_rounding_order(self, api):
        """PRD §2.9: "Two orderings are pinned and must not be rearranged: an
        order's volume discount is computed from the already-rounded subtotal
        (never by rounding the net-of-discount product in one step), and a
        harvest ticket's piece total is computed as the per-line product
        rounded half-up first and then summed across lines (never by summing
        raw products and rounding once)."
        PRD §3.3: "The `invoice_total_cents` is the subtotal minus the
        discount."

        Design: Difficulty/combinatorial_formula/order_invoice_tier_discount_rounding_order
        """
        ctx = setup_booking_season(H_6_7=500)
        buyer = create_buyer()
        order = create_draft_order(
            ctx["season"]["id"], buyer["id"], species="DOUGLAS_FIR",
            height_class="H_6_7", quantity=250, unit_price_cents=437,
        )
        submitted = submit_order(order["id"], buyer["id"])
        # 109250 - 5463 = 103787; the forbidden one-step rounding
        # round_half_up(250 * 437 * 0.95) = 103788 differs by one cent.
        assert submitted["invoice_total_cents"] == 103787
        assert submitted["status"] == "SUBMITTED"


class TestCreditLimitBoundary:
    def test_submit_at_exact_credit_limit_accepted(self, api):
        """PRD §3.3: "The credit check follows: the buyer's current
        `exposure_cents` plus this order's `invoice_total_cents` must not exceed
        the buyer's `credit_limit_cents`, with a sum exactly equal to the limit
        permitted; a breach is rejected with `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP
        422)."

        Design: Corner/validations/credit_limit_inclusive_boundary
        """
        ctx = setup_booking_season(H_6_7=500)
        buyer = create_buyer(name="Tight Credit Co", credit_limit_cents=48500)
        order = create_draft_order(
            ctx["season"]["id"], buyer["id"], quantity=100, unit_price_cents=500,
        )
        submitted = submit_order(order["id"], buyer["id"])
        assert submitted["status"] == "SUBMITTED"  # 48500 <= 48500 inclusive
        buyer_now = get_success_data(api.get_buyer_account(buyer["id"], OWNER))
        assert buyer_now["exposure_cents"] == 48500

    def test_submit_beyond_credit_limit_rejected(self, api):
        """PRD §3.3: "The credit check follows: the buyer's current
        `exposure_cents` plus this order's `invoice_total_cents` must not exceed
        the buyer's `credit_limit_cents`, with a sum exactly equal to the limit
        permitted; a breach is rejected with `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP
        422)."
        PRD §3.3: "A buyer's `exposure_cents` is a computed figure: the sum of
        `invoice_total_cents` over exactly that buyer's orders sitting in
        `SUBMITTED` or `ALLOCATED` — orders in `DRAFT`, `CLOSED`, `CANCELLED`,
        or `EXPIRED` contribute nothing."

        Design: Corner/validations/credit_limit_inclusive_boundary
        """
        ctx = setup_booking_season(H_6_7=500)
        buyer = create_buyer(name="Tight Credit Co", credit_limit_cents=48500)
        o1 = create_draft_order(
            ctx["season"]["id"], buyer["id"], quantity=100, unit_price_cents=500,
        )
        submit_order(o1["id"], buyer["id"])
        o2 = create_draft_order(
            ctx["season"]["id"], buyer["id"], quantity=100, unit_price_cents=500,
        )
        resp = api.submit_order(o2["id"], make_buyer_headers(buyer["id"]))
        validate_error(resp, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED)
        order2 = get_success_data(api.get_order(o2["id"], FM))
        assert order2["status"] == "DRAFT", "rejected submit leaves order DRAFT"
        buyer_now = get_success_data(api.get_buyer_account(buyer["id"], OWNER))
        assert buyer_now["exposure_cents"] == 48500


class TestSubmitGatedByBuyerStanding:
    def _setup_on_credit_hold(self):
        ctx = setup_booking_season(H_6_7=100)
        buyer = create_buyer()
        standing = get_success_data(
            api_client.set_buyer_standing(buyer["id"], "CREDIT_HOLD", OWNER)
        )
        assert standing["standing"] == "CREDIT_HOLD"
        order = create_draft_order(
            ctx["season"]["id"], buyer["id"], quantity=10, unit_price_cents=400,
        )
        return ctx, buyer, order

    def test_credit_hold_blocks_submit(self, api):
        """PRD §3.3: "Submission requires the season still in `BOOKING` and the
        buyer in `GOOD_STANDING` — a buyer on hold or closed is rejected with
        `ERR_BUYER_CREDIT_HOLD` (HTTP 422)."

        Design: Difficulty/cross_entity_state_dependency/order_submit_gated_by_buyer_standing
        """
        _ctx, buyer, order = self._setup_on_credit_hold()
        resp = api.submit_order(order["id"], make_buyer_headers(buyer["id"]))
        validate_error(resp, ApiErrorId.ERR_BUYER_CREDIT_HOLD)
        order_now = get_success_data(api.get_order(order["id"], FM))
        assert order_now["status"] == "DRAFT"

    def test_restored_standing_unblocks_same_order(self, api):
        """PRD §3.3: "Submission requires the season still in `BOOKING` and the
        buyer in `GOOD_STANDING` — a buyer on hold or closed is rejected with
        `ERR_BUYER_CREDIT_HOLD` (HTTP 422)."
        PRD §3.3: "The owner may move a buyer between `GOOD_STANDING` and
        `CREDIT_HOLD` at will by naming the `to_standing` target, and may move
        a buyer to `CLOSED` — terminal — only when that buyer holds no order in
        `DRAFT`, `SUBMITTED`, or `ALLOCATED`, failing with `ERR_INVALID_STATE`
        otherwise."

        Design: Difficulty/cross_entity_state_dependency/order_submit_gated_by_buyer_standing
        """
        _ctx, buyer, order = self._setup_on_credit_hold()
        resp = api.submit_order(order["id"], make_buyer_headers(buyer["id"]))
        validate_error(resp, ApiErrorId.ERR_BUYER_CREDIT_HOLD)
        get_success_data(
            api_client.set_buyer_standing(buyer["id"], "GOOD_STANDING", OWNER)
        )
        submitted = submit_order(order["id"], buyer["id"])
        assert submitted["status"] == "SUBMITTED"
        buyer_now = get_success_data(api.get_buyer_account(buyer["id"], OWNER))
        assert buyer_now["exposure_cents"] == 4000  # 10 * 400, no tier
