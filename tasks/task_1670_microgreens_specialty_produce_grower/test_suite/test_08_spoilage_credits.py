"""Spoilage credits: the two pricing variants, the customer credit-balance
invariant under approve/reject, and the fiscal guard at approval."""
from test_helpers import (
    ApiErrorId,
    advance_batch_to,
    assert_spoilage_credit,
    create_approved_food_safety_plan,
    create_crop_plan,
    create_listed_variety,
    create_released_seed_lot,
    create_spoilage_credit_payload,
    get_customer,
    get_plan_batch,
    log_sanitation,
    setup_delivered_stop,
    sow_crop_plan,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import GROWER, OPS


class TestPricingVariants:
    def _delivered_after_overweight_harvest(self, api):
        """A delivered 2.4 kg line @800 c/kg whose variety's single crop plan
        harvested 52.0 kg against a 40.0 kg base (harvest/overweight ratio
        1.30: cap factor 1.00, overweight excess 0.20, adjustment 0.80)."""
        create_approved_food_safety_plan()
        variety = create_listed_variety(name="Red Amaranth",
                                        listed_price_cents_per_kg=800,
                                        days_to_harvest=10,
                                        expected_yield_grams_per_tray=20000)
        lot = create_released_seed_lot(variety["id"], seeds_on_hand_grams=500)
        plan = create_crop_plan(variety["id"], planned_tray_count=2,
                                seed_grams_required=20)
        assert plan["base_harvest_kg"] == 40.0
        sow_crop_plan(plan["id"], plan["version"], lot["id"])
        batch = advance_batch_to(get_plan_batch(plan["id"])["id"], "READY")
        log_sanitation(batch["id"])
        validate_success(api.harvest_tray_batch(batch["id"], 52.0, GROWER))
        # Harvest precedes the order, so the whole yield is surplus; the line
        # below is fulfilled administratively at delivery time.
        return setup_delivered_stop(variety=variety, qty_kg=2.4,
                                    min_stop_subtotal_cents=1000)

    def test_original_paper_credit_priced_as_invoiced(self, api):
        """PRD §3.7: "Under `ORIGINAL_PAPER`, the credit is priced exactly as
        invoiced: `credit_cents` is the `credit_qty_kg` multiplied by the order
        line's `unit_price_cents_per_kg`, rounded half-up to whole cents."
        PRD §3.7: "The credit starts `PENDING`, its `credit_cents` is computed
        per the variant"

        Design: Difficulty/dual_variant_calc/spoilage_credit_original_paper_vs_post_harvest_pricing
        """
        ws = self._delivered_after_overweight_harvest(api)
        payload = create_spoilage_credit_payload(
            ws["stop"]["id"], ws["order_item"]["id"], 1.0, "ORIGINAL_PAPER")
        credit = validate_success(api.create_spoilage_credit(payload, OPS), 201)
        assert_spoilage_credit(credit)
        assert credit["status"] == "PENDING"
        assert credit["credit_cents"] == 800, (
            "1.0 kg at the invoiced 800 c/kg, rounded half-up")

    def test_post_harvest_pricing_credit_uses_capped_unit_price(self, api):
        """PRD §3.7: "First, the plan's harvest ratio is computed as the total
        `harvested_kg` across the crop plan's `HARVESTED` tray batches divided
        by the plan's `base_harvest_kg`; the plan cap factor is 1.00 when that
        ratio is at least 0.70, and 0.85 when the harvest fell short of seventy
        percent of plan."
        PRD §3.7: "Second, the variety's overweight ratio — the plan's harvested
        kilograms for the variety divided by the plan's base for that variety —
        is compared against a ten-percent allowance: the overweight excess is
        the amount by which the ratio exceeds 1.10, floored at zero, and the
        price-adjustment factor is one minus that excess, with the excess capped
        so it never counts more than 0.25."
        PRD §3.7: "Third, the capped unit price is the line's
        `unit_price_cents_per_kg` multiplied by the plan cap factor and by the
        price-adjustment factor. Only then is the capped unit price multiplied
        by the `credit_qty_kg`, with a single round half-up to whole cents at
        the very end."

        Design: Difficulty/dual_variant_calc/spoilage_credit_original_paper_vs_post_harvest_pricing
        """
        ws = self._delivered_after_overweight_harvest(api)
        payload = create_spoilage_credit_payload(
            ws["stop"]["id"], ws["order_item"]["id"], 1.0, "POST_HARVEST_PRICING")
        credit = validate_success(api.create_spoilage_credit(payload, OPS), 201)
        assert_spoilage_credit(credit)
        # ratio 52/40 = 1.30 >= 0.70 -> cap 1.00; excess 0.20 -> adjustment 0.80;
        # capped unit price 800 * 1.00 * 0.80 = 640; 1.0 kg -> 640.
        assert credit["credit_cents"] == 640, (
            "Post-harvest pricing: 800 * 1.00 * 0.80 = 640 for 1.0 kg")

        paper = validate_success(api.create_spoilage_credit(
            create_spoilage_credit_payload(
                ws["stop"]["id"], ws["order_item"]["id"], 1.0, "ORIGINAL_PAPER"),
            OPS), 201)
        assert credit["credit_cents"] != paper["credit_cents"], (
            "The two variants price the same spoilage differently")
        assert credit["credit_cents"] < paper["credit_cents"], (
            "Post-harvest pricing can only be lower than the original-paper figure")


class TestCreditBalanceInvariant:
    def _delivered_stop_with_line(self, api):
        return setup_delivered_stop(name="Amaranth2", qty_kg=2.4,
                                    listed_price_cents_per_kg=800,
                                    days_to_harvest=10,
                                    expected_yield_grams_per_tray=20000,
                                    min_stop_subtotal_cents=100)

    def test_approved_credit_posts_to_customer_balance(self, api):
        """PRD §3.7: "An approved credit posts its `credit_cents` onto the
        customer's `credit_balance_cents`, and when the credited quantity equals
        the line's full delivered quantity, the order line's `fulfillment` moves
        to `CREDITED`."
        PRD §3.5: "The customer's `credit_balance_cents` starts at zero — it
        only ever grows through resolved spoilage credits, §3.7"

        Design: Difficulty/compensating_invariant/spoilage_credit_approve_reject_conserves_customer_balance
        """
        ws = self._delivered_stop_with_line(api)
        assert get_customer(ws["customer"]["id"])["credit_balance_cents"] == 0

        credit = validate_success(api.create_spoilage_credit(
            create_spoilage_credit_payload(
                ws["stop"]["id"], ws["order_item"]["id"], 0.6, "ORIGINAL_PAPER"),
            OPS), 201)
        assert credit["credit_cents"] == 480  # 0.6 kg * 800 c/kg

        approved = validate_success(api.approve_spoilage_credit(credit["id"], OPS))
        assert approved["status"] == "APPROVED"

        customer_after = get_customer(ws["customer"]["id"])
        assert customer_after["credit_balance_cents"] == 480, (
            "balance after approve == balance before + credit_cents")

    def test_rejected_credit_leaves_customer_balance_unchanged(self, api):
        """PRD §3.7: "A rejected credit simply moves to `REJECTED`."
        PRD §3.5: "The customer's `credit_balance_cents` starts at zero — it
        only ever grows through resolved spoilage credits, §3.7"

        Design: Difficulty/compensating_invariant/spoilage_credit_approve_reject_conserves_customer_balance
        """
        ws = self._delivered_stop_with_line(api)
        # First credit approved: balance moves to 480.
        credit1 = validate_success(api.create_spoilage_credit(
            create_spoilage_credit_payload(
                ws["stop"]["id"], ws["order_item"]["id"], 0.6, "ORIGINAL_PAPER"),
            OPS), 201)
        validate_success(api.approve_spoilage_credit(credit1["id"], OPS))
        assert get_customer(ws["customer"]["id"])["credit_balance_cents"] == 480

        # Second identical credit rejected: the balance is conserved.
        credit2 = validate_success(api.create_spoilage_credit(
            create_spoilage_credit_payload(
                ws["stop"]["id"], ws["order_item"]["id"], 0.6, "ORIGINAL_PAPER"),
            OPS), 201)
        rejected = validate_success(api.reject_spoilage_credit(credit2["id"], OPS))
        assert rejected["status"] == "REJECTED"

        customer_after = get_customer(ws["customer"]["id"])
        assert customer_after["credit_balance_cents"] == 480, (
            "A rejected credit posts nothing to the balance")


class TestCreditFiscalGuard:
    def test_approve_credit_exceeding_delivered_qty_rejected(self, api):
        """PRD §3.7: "Approval is fiscally guarded: the `credit_qty_kg` must not
        exceed the delivered quantity of the credited order line, or the
        approval is rejected with `ERR_CREDIT_EXCEEDS_DELIVERY`."

        Design: Corner/validations/credit_exceeds_delivery_returns_422
        """
        ws = setup_delivered_stop(name="Parsley", crop_category="SPECIALTY_HERB",
                                  qty_kg=1.0, listed_price_cents_per_kg=2000,
                                  days_to_harvest=21,
                                  expected_yield_grams_per_tray=4000,
                                  min_order_grams=100,
                                  min_stop_subtotal_cents=100)
        credit = validate_success(api.create_spoilage_credit(
            create_spoilage_credit_payload(
                ws["stop"]["id"], ws["order_item"]["id"], 5.0, "ORIGINAL_PAPER"),
            OPS), 201)

        resp = api.approve_spoilage_credit(credit["id"], OPS)
        validate_error(resp, ApiErrorId.ERR_CREDIT_EXCEEDS_DELIVERY)

        customer_after = get_customer(ws["customer"]["id"])
        assert customer_after["credit_balance_cents"] == 0, (
            "A rejected approval posts nothing")
