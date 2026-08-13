"""Pricing claims (PRD §2.6, §3.3): quoted vs final total variants, tiered
emergency labor with program discount, and the pinned per-component
rounding order."""
import pytest

from test_helpers import (
    TEST_USERS,
    create_assembly_order,
    create_coupling,
    create_customer,
    create_reel,
    build_assembly_order,
    complete_assembly_order,
    confirm_assembly_order,
    record_pressure_test,
    tag_assembly_order,
    get_customer,
    validate_success,
)


class TestQuotedVsFinalPricing:
    def test_quoted_total_fixed_at_creation_uses_estimated_labor(self, api):
        """PRD §3.3: "The result lands in `quoted_total_cents`, computed from `estimated_labor_minutes` and fixed at creation. Its sibling, `final_total_cents`, stays null until the order completes — it will use the same formula with `actual_labor_minutes` in place of the estimate, so the two totals diverge whenever the recorded labor differs from the quoted labor."

        quoted = hose 5m x 800c (4000) + 2 couplings x 1200c (2400) + labor 30min x 150c (4500) = 10900.

        Design: Difficulty/dual_variant_calc/assembly_price_provisional_vs_final
        """
        cust = create_customer(name="Acme Hydraulics")
        reel = create_reel(hose_sku="PARK-387-8", hose_diameter_in=0.5,
                           working_pressure_psi=3000, price_per_meter_cents=800,
                           initial_length_mm=50000)
        coup = create_coupling(coupling_sku="1CA43-8-8", size_in=0.5,
                               unit_price_cents=1200, initial_on_hand_qty=10)

        order = create_assembly_order(
            cust["id"], reel["id"],
            cut_length_mm=5000, required_working_pressure_psi=2000,
            crimp_diameter_spec_mm=25.0, estimated_labor_minutes=30,
            lines=[{"coupling_id": coup["id"], "quantity": 2}])

        assert order["status"] == "DRAFT"
        assert order["material_hose_cents"] == 4000
        assert order["material_couplings_cents"] == 2400
        assert order["quoted_total_cents"] == 10900, (
            f"Expected quoted 10900, got {order['quoted_total_cents']}")
        assert order["final_total_cents"] is None, (
            "final_total_cents must stay null until the order completes")

    def test_final_total_uses_actual_labor_at_completion(self, api):
        """PRD §3.5: "The moment of completion computes `final_total_cents` using the formula of §3.3 with `actual_labor_minutes` in place of the estimate, and the pinned rounding order applies unchanged."
        PRD §3.3: "Its sibling, `final_total_cents`, stays null until the order completes — it will use the same formula with `actual_labor_minutes` in place of the estimate, so the two totals diverge whenever the recorded labor differs from the quoted labor."

        final = 4000 hose + 2400 couplings + labor 40min x 150c (6000) = 12400; quoted stays 10900.

        Design: Difficulty/dual_variant_calc/assembly_price_provisional_vs_final
        """
        cust = create_customer(name="Acme Hydraulics")
        reel = create_reel(hose_sku="PARK-387-8", hose_diameter_in=0.5,
                           working_pressure_psi=3000, price_per_meter_cents=800,
                           initial_length_mm=50000)
        coup = create_coupling(coupling_sku="1CA43-8-8", size_in=0.5,
                               unit_price_cents=1200, initial_on_hand_qty=10)
        order = create_assembly_order(
            cust["id"], reel["id"],
            cut_length_mm=5000, required_working_pressure_psi=2000,
            crimp_diameter_spec_mm=25.0, estimated_labor_minutes=30,
            lines=[{"coupling_id": coup["id"], "quantity": 2}])

        confirm_assembly_order(order["id"])
        build_assembly_order(order["id"], measured_crimp_diameter_mm=25.1,
                             actual_labor_minutes=40)
        record_pressure_test(order["id"], test_pressure_psi=4000, result="PASSED")
        tag_assembly_order(order["id"], "TAG-DV1")
        completed = complete_assembly_order(order["id"])

        assert completed["status"] == "COMPLETED"
        assert completed["final_total_cents"] == 12400, (
            f"Expected final 12400, got {completed['final_total_cents']}")
        assert completed["quoted_total_cents"] == 10900, (
            "quoted_total_cents was fixed at creation and must not move")
        assert completed["final_total_cents"] != completed["quoted_total_cents"]


class TestEmergencyTieredPricingWithDiscount:
    def _setup_active_program_customer(self):
        cust = create_customer(name="RushWorks", program_enrolled=True,
                               program_discount_pct=0.10,
                               inspection_interval_days=90)
        reel = create_reel(hose_sku="PARK-787-20", hose_diameter_in=1.25,
                           working_pressure_psi=5000, price_per_meter_cents=1500,
                           initial_length_mm=50000)
        coup = create_coupling(coupling_sku="1C643-20-20", size_in=1.25,
                               unit_price_cents=3000, initial_on_hand_qty=5)
        return cust, reel, coup

    def test_emergency_order_quote_combines_tier_multiplier_and_discount(self, api):
        """PRD §3.3: "The labor rate per minute comes off the reel's `hose_diameter_in`: 150 cents per minute when the diameter is no more than half an inch, 200 cents per minute when it is greater than half an inch but no more than one inch, and 260 cents per minute when it exceeds one inch."
        PRD §3.3: "The labor component multiplies the minutes by that rate and, for an emergency build, additionally by one and a half, rounding half up to whole cents."
        PRD §3.3: "Following the pinned order of §2.6, the subtotal sums these four components, and when the customer's `program_status` is `ACTIVE` a discount equal to the subtotal multiplied by the customer's `program_discount_pct`, rounded half up, comes off; otherwise the discount is zero."
        PRD §3.7: "Finally, `program_status` derives from enrollment and the strict score: `NONE` when the customer is not enrolled, `ACTIVE` when enrolled with a strict score of at least 70, and `PROBATION` otherwise."

        subtotal = 4500 hose + 3000 coupling + round_half_up(20 x 260 x 1.5) labor (7800) = 15300;
        discount = round_half_up(15300 x 0.10) = 1530; quoted = 13770.

        Design: Difficulty/combinatorial_formula/emergency_tiered_pricing_with_discount
        """
        cust, reel, coup = self._setup_active_program_customer()
        # No assets -> strict score reads 100.00 -> enrolled customer is ACTIVE.
        assert get_customer(cust["id"])["program_status"] == "ACTIVE"

        order = create_assembly_order(
            cust["id"], reel["id"],
            cut_length_mm=3000, required_working_pressure_psi=3000,
            crimp_diameter_spec_mm=41.0, estimated_labor_minutes=20,
            is_emergency=True,
            lines=[{"coupling_id": coup["id"], "quantity": 1}])

        assert order["status"] == "DRAFT"
        assert order["quoted_total_cents"] == 13770, (
            f"Expected quoted 13770, got {order['quoted_total_cents']}")

    def test_non_emergency_twin_quote_excludes_the_multiplier(self, api):
        """PRD §3.3: "The labor component multiplies the minutes by that rate and, for an emergency build, additionally by one and a half, rounding half up to whole cents."
        PRD §3.3: "Following the pinned order of §2.6, the subtotal sums these four components, and when the customer's `program_status` is `ACTIVE` a discount equal to the subtotal multiplied by the customer's `program_discount_pct`, rounded half up, comes off; otherwise the discount is zero."

        Same inputs without is_emergency: labor 20 x 260 = 5200; subtotal 12700; discount 1270; quoted = 11430.

        Design: Difficulty/combinatorial_formula/emergency_tiered_pricing_with_discount
        """
        cust, reel, coup = self._setup_active_program_customer()

        order = create_assembly_order(
            cust["id"], reel["id"],
            cut_length_mm=3000, required_working_pressure_psi=3000,
            crimp_diameter_spec_mm=41.0, estimated_labor_minutes=20,
            is_emergency=False,
            lines=[{"coupling_id": coup["id"], "quantity": 1}])

        assert order["quoted_total_cents"] == 11430, (
            f"Expected quoted 11430 without the emergency multiplier, "
            f"got {order['quoted_total_cents']}")


class TestPinnedComponentRounding:
    def _setup_rounding_order(self):
        cust = create_customer(name="RoundTrip LLC")
        reel = create_reel(hose_sku="PARK-387-8R", hose_diameter_in=0.5,
                           working_pressure_psi=3000, price_per_meter_cents=750,
                           initial_length_mm=1334)
        coup = create_coupling(coupling_sku="10643-8-8", size_in=0.5,
                               unit_price_cents=1000, initial_on_hand_qty=5)
        order = create_assembly_order(
            cust["id"], reel["id"],
            cut_length_mm=1001, required_working_pressure_psi=2000,
            crimp_diameter_spec_mm=25.0, estimated_labor_minutes=10,
            lines=[{"coupling_id": coup["id"], "quantity": 1}])
        return cust, reel, coup, order

    def test_final_total_uses_pinned_per_component_rounding(self, api):
        """PRD §2.6: "Where a computed component could land on a fraction of a cent, it is rounded half up to whole cents — and, critically, each component is rounded on its own before any summation takes place."
        PRD §2.6: "The rounding order is pinned. First, the hose material component is rounded to whole cents. Coupling line totals are exact integer cents by construction and require no rounding. Third, the labor component is rounded. Fourth, the waste surcharge is rounded. The subtotal is then the plain integer sum of those four components, with no further rounding."
        PRD §2.6: "Rounding only the final sum — skipping the per-component rounding — yields different cents whenever the hose and waste components both carry fractional cents, and that alternative is not permitted."

        hose round_half_up(1001/1000 x 750) = 751; waste round_half_up(333/1000 x 750) = 250;
        labor 10 x 150 = 1500; coupling 1000; final = 751 + 1000 + 1500 + 250 = 3501.

        Design: Difficulty/combinatorial_formula/invoice_component_rounding_order_pinned
        """
        cust, reel, coup, order = self._setup_rounding_order()
        confirm_assembly_order(order["id"])
        build_assembly_order(order["id"], measured_crimp_diameter_mm=25.0,
                             actual_labor_minutes=10)
        record_pressure_test(order["id"], test_pressure_psi=4000, result="PASSED")
        tag_assembly_order(order["id"], "TAG-RND1")
        completed = complete_assembly_order(order["id"])

        assert completed["material_hose_cents"] == 751
        assert completed["waste_surcharge_cents"] == 250
        assert completed["final_total_cents"] == 3501, (
            f"Expected final 3501 from pinned per-component rounding, "
            f"got {completed['final_total_cents']}")

    def test_confirm_scraps_sub_meter_remnant_and_recomputes_waste(self, api):
        """PRD §3.3: "A remnant greater than zero but shorter than one meter is written off in full: it is added to the reel's `scrap_length_mm`, recorded on the order as `scrap_charged_mm`, and billed through the waste surcharge, which is recomputed from the freshly recorded scrap."
        PRD §3.3: "The reel's `remaining_length_mm` is debited by the cut length plus whatever was scrapped, and its status is recomputed against the ladder — `DEPLETED` below one meter, `LOW` below twenty meters, otherwise `AVAILABLE`."

        reel 1334mm, cut 1001mm -> remnant 333mm scrapped; remaining 0 -> DEPLETED;
        order scrap_charged_mm 333, waste_surcharge_cents 250.

        Design: Difficulty/combinatorial_formula/invoice_component_rounding_order_pinned
        """
        cust, reel, coup, order = self._setup_rounding_order()
        confirmed = confirm_assembly_order(order["id"])

        assert confirmed["status"] == "CONFIRMED"
        assert confirmed["scrap_charged_mm"] == 333
        assert confirmed["waste_surcharge_cents"] == 250
        assert confirmed["material_hose_cents"] == 751

        reel_after = api.get_reel(reel["id"], TEST_USERS["shop_manager_headers"])
        reel_data = validate_success(reel_after, 200)
        assert reel_data["remaining_length_mm"] == 0
        assert reel_data["scrap_length_mm"] == 333
        assert reel_data["status"] == "DEPLETED"


class TestLaborTierSelection:
    def test_mid_diameter_reel_uses_mid_labor_rate(self, api):
        """PRD §3.3: "The labor rate per minute comes off the reel's `hose_diameter_in`: 150 cents per minute when the diameter is no more than half an inch, 200 cents per minute when it is greater than half an inch but no more than one inch, and 260 cents per minute when it exceeds one inch."

        dia 0.75in (> 0.5, <= 1.0) selects 200c/min; quoted = hose 2m x 1000c (2000) + labor 10min x 200c (2000) = 4000 (customer not enrolled, no discount).

        Design: Corner/calculations/labor_tier_mid_rate_applied
        """
        cust = create_customer(name="TierCo")
        reel = create_reel(hose_sku="PARK-387-12", hose_diameter_in=0.75,
                           working_pressure_psi=3000, price_per_meter_cents=1000,
                           initial_length_mm=50000)

        order = create_assembly_order(
            cust["id"], reel["id"],
            cut_length_mm=2000, required_working_pressure_psi=2000,
            crimp_diameter_spec_mm=27.0, estimated_labor_minutes=10)

        assert order["material_hose_cents"] == 2000
        assert order["quoted_total_cents"] == 4000, (
            f"Expected quoted 4000 from the MID labor tier, "
            f"got {order['quoted_total_cents']}")
