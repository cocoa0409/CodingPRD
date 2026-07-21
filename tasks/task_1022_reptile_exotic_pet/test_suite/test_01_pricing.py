"""Sale pricing and feeder shipment cost calculations (dual-variant + combinatorial)."""
from test_helpers import (
    validate_success, get_success_data,
    make_customer_headers, make_store_manager_headers, TEST_USERS,
    setup_available_animal, create_customer, create_draft_sale,
    setup_verified_permit, create_feeder_batch, create_subscription,
)

_SALES = TEST_USERS["sales_associate_headers"]


class TestSalePriceDualVariant:
    def test_sale_price_dual_variant_provisional_and_final(self, api):
        """PRD §3.4: "a loyalty component — 0% for `STANDARD`, 5% for `SILVER`, 10% for `GOLD` — applies **only to the final price computed at confirmation**, not to the provisional draft price."
        PRD §3.4: "The provisional variant stored at draft omits the loyalty term entirely (loyalty is only granted once a sale is confirmed and permit-checked); the final variant stored at confirmation includes it."

        Design: Difficulty/dual_variant_calc/sale_price_provisional_vs_final
        """
        _, animal = setup_available_animal(
            api,
            species_overrides={"is_regulated": False, "permit_class": "NONE",
                               "min_quarantine_days": 0, "warranty_days": 30},
            animal_overrides={"list_price_cents": 20000, "acquisition_cost_cents": 8000},
        )
        customer = create_customer(api, loyalty_tier="GOLD", email="gold-dual@x.com")
        sale = create_draft_sale(api, animal["id"], customer["id"], sold_at_expo=False)
        # provisional: base 20000, no surcharge (NONE), no loyalty at draft -> 20000
        assert sale["provisional_price_cents"] == 20000
        confirmed = validate_success(api.confirm_sale(sale["id"], headers=_SALES))
        # final: base 20000, GOLD 10% discount -> 20000 - 2000 = 18000
        assert confirmed["sale_price_cents"] == 18000
        assert confirmed["provisional_price_cents"] != confirmed["sale_price_cents"]

    def test_provisional_omits_loyalty_and_final_price_unset_before_confirm(self, api):
        """PRD §3.4: "Drafting stamps `created_by_user_id` with the associate's `X-User-ID` and computes a **provisional price**, stored in `provisional_price_cents`, while `sale_price_cents`, `confirmed_at`, and `warranty_expires_at` remain empty."

        Design: Difficulty/dual_variant_calc/sale_price_provisional_vs_final
        """
        _, animal = setup_available_animal(
            api,
            animal_overrides={"list_price_cents": 20000, "acquisition_cost_cents": 8000},
        )
        customer = create_customer(api, loyalty_tier="GOLD", email="gold-draft@x.com")
        sale = create_draft_sale(api, animal["id"], customer["id"], sold_at_expo=False)
        # GOLD would give 18000 if applied; provisional omits loyalty -> 20000
        assert sale["provisional_price_cents"] == 20000
        assert sale["sale_price_cents"] in (None, 0) or sale.get("sale_price_cents") is None


class TestWarrantyRefundDualVariant:
    def _fulfilled_sale(self, api, list_price, warranty_days=30, email="wr@x.com"):
        _, animal = setup_available_animal(
            api,
            species_overrides={"warranty_days": warranty_days, "min_quarantine_days": 0},
            animal_overrides={"list_price_cents": list_price, "acquisition_cost_cents": 5000},
        )
        customer = create_customer(api, loyalty_tier="STANDARD", email=email)
        sale = get_success_data(api.create_sale(
            {"animal_id": animal["id"], "customer_id": customer["id"]}, headers=_SALES))
        get_success_data(api.confirm_sale(sale["id"], headers=_SALES))
        get_success_data(api.fulfill_sale(sale["id"], headers=_SALES))
        return customer, sale

    def test_early_death_refund_is_prorated_by_remaining_days(self, api):
        """PRD §3.5: "for an `EARLY_DEATH` claim the refund is prorated by remaining coverage — the remaining days are the whole-day ceiling of the interval from the current clock to `warranty_expires_at`, floored at zero, and the refund is `sale_price_cents` multiplied by those remaining days divided by the species' `warranty_days`, rounded half up to whole cents."

        Design: Difficulty/dual_variant_calc/warranty_refund_doa_vs_early_death
        """
        customer, sale = self._fulfilled_sale(api, 18000, email="ed@x.com")
        # confirmed at default clock 2026-07-01, warranty 30d -> expires 2026-07-31
        get_success_data(api.set_clock("2026-07-16T00:00:00Z",
                                       headers=TEST_USERS["store_manager_headers"]))
        cust = make_customer_headers(customer["id"])
        claim = get_success_data(api.create_warranty_claim(
            sale["id"], {"claim_type": "EARLY_DEATH", "reason": "died week 2"}, headers=cust))
        approved = validate_success(api.approve_claim(
            claim["id"], headers=make_store_manager_headers("mgr-approve")))
        # remaining_days = ceil(2026-07-31 - 2026-07-16) = 15 ; 18000 * 15/30 = 9000
        assert approved["refund_cents"] == 9000
        assert approved["status"] == "APPROVED"

    def test_doa_refund_is_full_sale_price(self, api):
        """PRD §3.5: "for a `DOA` claim the refund is the full `sale_price_cents` regardless of elapsed time"

        Design: Difficulty/dual_variant_calc/warranty_refund_doa_vs_early_death
        """
        customer, sale = self._fulfilled_sale(api, 18000, email="doa@x.com")
        cust = make_customer_headers(customer["id"])
        claim = get_success_data(api.create_warranty_claim(
            sale["id"], {"claim_type": "DOA", "reason": "arrived dead"}, headers=cust))
        approved = validate_success(api.approve_claim(
            claim["id"], headers=make_store_manager_headers("mgr-approve")))
        assert approved["refund_cents"] == 18000
        assert approved["status"] == "APPROVED"


class TestSalePriceCombinatorial:
    def _regulated_available(self, api, email):
        species, animal = setup_available_animal(
            api,
            species_overrides={"is_regulated": True, "permit_class": "CLASS_III",
                               "min_quarantine_days": 0, "warranty_days": 30},
            animal_overrides={"list_price_cents": 20000, "acquisition_cost_cents": 8000},
        )
        customer = create_customer(api, loyalty_tier="SILVER", email=email)
        permit = setup_verified_permit(api, customer["id"], permit_class="CLASS_III")
        return animal, customer, permit

    def test_confirm_combines_surcharge_loyalty_and_expo_discount(self, api):
        """PRD §3.4: "A regulated surcharge is then computed as the base multiplied by the surcharge rate for the species' `permit_class` — 0% for `NONE`, 5% for `CLASS_I`, 10% for `CLASS_II`, and 15% for `CLASS_III` — with that product rounded half up to whole cents."
        PRD §3.4: "an expo component of 8% applies whenever `sold_at_expo` is true, and a loyalty component — 0% for `STANDARD`, 5% for `SILVER`, 10% for `GOLD` — applies **only to the final price computed at confirmation"

        Design: Difficulty/combinatorial_formula/sale_price_tiered_surcharge_and_discount_mode_a
        """
        animal, customer, permit = self._regulated_available(api, "combo-a@x.com")
        sale = create_draft_sale(api, animal["id"], customer["id"],
                                 permit_id=permit["id"], sold_at_expo=True)
        confirmed = validate_success(api.confirm_sale(sale["id"], headers=_SALES))
        # base 20000; surcharge round(20000*0.15)=3000; disc_pct=0.05+0.08=0.13;
        # discount round(23000*0.13)=2990; gross=20000+3000-2990=20010; floor 8000 -> 20010
        assert confirmed["sale_price_cents"] == 20010
        assert confirmed["status"] == "CONFIRMED"

    def test_provisional_applies_surcharge_and_expo_without_loyalty(self, api):
        """PRD §3.4: "The discount amount is the sum of the base and the surcharge, multiplied by that combined discount percentage, rounded half up to whole cents. The gross price is the base plus the surcharge minus the discount."
        PRD §3.4: "The provisional variant stored at draft omits the loyalty term entirely (loyalty is only granted once a sale is confirmed and permit-checked)"

        Design: Difficulty/combinatorial_formula/sale_price_tiered_surcharge_and_discount_mode_a
        """
        animal, customer, permit = self._regulated_available(api, "combo-b@x.com")
        sale = create_draft_sale(api, animal["id"], customer["id"],
                                 permit_id=permit["id"], sold_at_expo=True)
        # provisional disc_pct = expo 0.08 only (no SILVER loyalty at draft);
        # surcharge 3000; discount round(23000*0.08)=1840; gross=20000+3000-1840=21160
        assert sale["provisional_price_cents"] == 21160


class TestShipmentCostCombinatorial:
    def _two_batch_subscription(self, api, email):
        b1 = create_feeder_batch(api, feeder_type="CRICKET", size="MEDIUM",
                                 quantity_on_hand=10, unit_price_cents=50,
                                 expiry_date="2026-07-10T00:00:00Z")
        b2 = create_feeder_batch(api, feeder_type="CRICKET", size="MEDIUM",
                                 quantity_on_hand=30, unit_price_cents=50,
                                 expiry_date="2026-07-20T00:00:00Z")
        customer = create_customer(api, email=email)
        sub = create_subscription(api, customer["id"], feeder_type="CRICKET",
                                  size="MEDIUM", quantity_per_shipment=24, cadence_days=14)
        return b1, b2, sub

    def test_shipment_cost_rounds_per_line_before_summing(self, api):
        """PRD §3.6: "The per-unit cost for a line is the batch's `unit_price_cents` multiplied by the size multiplier — 1.00 for `SMALL`, 1.25 for `MEDIUM`, 1.50 for `LARGE` — rounded half up to whole cents; each line's cost is that per-unit price times the line's quantity, and the shipment's `shipment_cost_cents` is the sum of the line costs (each unit price is rounded before multiplying and summing, never summing first)."

        Design: Difficulty/combinatorial_formula/shipment_cost_round_per_line_mode_b
        """
        b1, b2, sub = self._two_batch_subscription(api, "ship-cost@x.com")
        shipment = validate_success(api.create_shipment(sub["id"], headers=_SALES),
                                    expected_status=201)
        # unit = round(50*1.25)=round(62.5)=63; line1=10*63=630, line2=14*63=882; sum=1512
        assert shipment["shipment_cost_cents"] == 1512

    def test_shipment_waterfall_depletes_earliest_expiry_batch_first(self, api):
        """PRD §3.6: "The waterfall fills the earliest-expiry batch fully before moving to the next" "As stock is drawn down, each batch's `quantity_on_hand` is decremented and any batch reaching 0 flips from `AVAILABLE` to `DEPLETED"

        Design: Difficulty/combinatorial_formula/shipment_cost_round_per_line_mode_b
        """
        b1, b2, sub = self._two_batch_subscription(api, "ship-waterfall@x.com")
        validate_success(api.create_shipment(sub["id"], headers=_SALES), expected_status=201)
        after_b1 = get_success_data(api.get_feeder_batch(b1["id"], headers=_SALES))
        after_b2 = get_success_data(api.get_feeder_batch(b2["id"], headers=_SALES))
        # b1 (earliest expiry) fully drained: 10 -> 0 DEPLETED; b2: 30 - 14 = 16
        assert after_b1["quantity_on_hand"] == 0
        assert after_b1["status"] == "DEPLETED"
        assert after_b2["quantity_on_hand"] == 16
