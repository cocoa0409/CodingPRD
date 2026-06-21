"""Pricing engine: work-order pricing aggregation, disposal-fee brackets, road-hazard
premium, mileage-warranty dual-variant proration, and special-order deposit.

All money is integer cents; round-half-up is applied exactly once per the PRD's pinned
calculation order (PRD §2.5, §3.2-§3.4, §3.8, §3.9).
"""
import pytest
from test_helpers import (
    api_client,
    validate_success,
    validate_paginated,
    get_success_data,
    TEST_USERS,
    create_customer, create_vehicle, create_tire_model, create_fitment_rule,
    create_work_order, add_tire_line, add_service_line, approve_order,
    setup_customer_vehicle_tire, setup_approved_order_with_tire_line,
    setup_submitted_mileage_claim, setup_special_order,
)
import test_helpers.factories as F

ADVISOR = TEST_USERS["service_advisor_headers"]
INV = TEST_USERS["inventory_manager_headers"]


# ---------------------------------------------------------------------------
# Rule 1 — dual-variant calculations across different entity domains
# ---------------------------------------------------------------------------
class TestMileageProrationDualVariant:
    def test_mileage_based_variant_credit_value(self, api):
        """PRD §3.9: "Under the mileage-based variant, the used fraction is the claim's
        `miles_driven` divided by the model's `mileage_warranty_miles`, the remaining
        fraction is one minus that used fraction, the per-tire credit is the model's
        current `unit_price_cents` multiplied by the remaining fraction and rounded half
        up to a whole cent, and `prorated_credit_cents` is that per-tire credit multiplied
        by the `claim_quantity` — rounding the per-tire figure first and only then
        multiplying by quantity."
        PRD §3.9: "the system always applies the mileage-based variant."

        orig 14999, warranty 60000, miles 30000 -> remaining 1/2 ->
        per_tire round_half_up(7499.5)=7500, qty 4 -> 30000.

        Design: Difficulty/dual_variant_calc/mileage_proration_mileage_vs_tread_basis
        """
        customer, vehicle, tire, wo, line, claim = setup_submitted_mileage_claim(
            measured_tread_32nds=2, miles_driven=30000, payout_method="STORE_CREDIT",
            claim_quantity=4,
            tire_overrides={"unit_price_cents": 14999, "mileage_warranty_miles": 60000,
                            "original_tread_32nds": 10, "stock_qty": 10},
        )
        data = validate_success(api.approve_mileage_claim(claim["id"], ADVISOR))
        assert data["status"] == "APPROVED"
        assert data["prorated_credit_cents"] == 30000, (
            f"mileage-based credit expected 30000, got {data['prorated_credit_cents']}")

    def test_mileage_based_credit_persists_on_fetch(self, api):
        """PRD §3.9: "On approval the system computes the payout into `prorated_credit_cents`
        and moves the claim's `status` from `SUBMITTED` to `APPROVED`".
        PRD §3.9: "the per-tire credit is the model's current `unit_price_cents` multiplied
        by the remaining fraction and rounded half up to a whole cent, and
        `prorated_credit_cents` is that per-tire credit multiplied by the `claim_quantity`".

        Design: Difficulty/dual_variant_calc/mileage_proration_mileage_vs_tread_basis
        """
        customer, vehicle, tire, wo, line, claim = setup_submitted_mileage_claim(
            measured_tread_32nds=2, miles_driven=30000, payout_method="STORE_CREDIT",
            claim_quantity=4,
            tire_overrides={"unit_price_cents": 14999, "mileage_warranty_miles": 60000,
                            "original_tread_32nds": 10, "stock_qty": 10},
        )
        validate_success(api.approve_mileage_claim(claim["id"], ADVISOR))
        fetched = validate_success(api.get_mileage_claim(claim["id"], ADVISOR))
        assert fetched["prorated_credit_cents"] == 30000
        assert fetched["status"] == "APPROVED"


class TestRoadHazardPremiumPctVsFloor:
    def test_floor_branch_wins_for_low_priced_tire(self, api):
        """PRD §3.4: "The premium for one covered line is the larger of two amounts. The
        first is a percentage term: the line's `extended_cents` multiplied by the
        road-hazard rate of 12 percent, rounded half up to a whole cent. The second is a
        per-tire floor: the line's `quantity` multiplied by a floor of 1200 cents per tire.
        The line's `premium_cents` is the greater of the rounded percentage term and the
        floor".

        unit 8000, qty 1: pct=round_half_up(8000*0.12)=960, floor=1*1200=1200 -> 1200.

        Design: Difficulty/dual_variant_calc/road_hazard_premium_pct_vs_floor_on_workorder
        """
        customer, vehicle, tire, wo, line, approved = setup_approved_order_with_tire_line(
            quantity=1, road_hazard_opted=True, grade="APPROVED_PLUS",
            tire_overrides={"unit_price_cents": 8000, "mileage_warranty_miles": 0,
                            "original_tread_32nds": 9, "stock_qty": 4},
        )
        assert approved["road_hazard_premium_cents"] == 1200, (
            f"floor (1200) should win, got {approved['road_hazard_premium_cents']}")
        assert approved["parts_subtotal_cents"] == 8000

    def test_floor_branch_premium_on_warranty_record(self, api):
        """PRD §3.4: "at approval, for each committed `TIRE` line that opted in, the system
        creates a `RoadHazardWarranty` recording the covered `work_order_line_id` and the
        snapshot `tire_model_id`, sets its `covered_quantity` equal to the covered line's
        `quantity`, computes its `premium_cents`, and moves it from `PENDING` to `ACTIVE`".
        PRD §3.4: "The line's `premium_cents` is the greater of the rounded percentage term
        and the floor".

        Design: Difficulty/dual_variant_calc/road_hazard_premium_pct_vs_floor_on_workorder
        """
        customer, vehicle, tire, wo, line, approved = setup_approved_order_with_tire_line(
            quantity=1, road_hazard_opted=True, grade="APPROVED_PLUS",
            tire_overrides={"unit_price_cents": 8000, "mileage_warranty_miles": 0,
                            "original_tread_32nds": 9, "stock_qty": 4},
        )
        resp = api.list_road_hazard_warranties(ADVISOR, params={"work_order_line_id": line["id"]})
        warranties, _ = validate_paginated(resp)
        assert len(warranties) == 1
        assert warranties[0]["premium_cents"] == 1200
        assert warranties[0]["status"] == "ACTIVE"
        assert warranties[0]["covered_quantity"] == 1


# ---------------------------------------------------------------------------
# Rule 2 — combinatorial formulas across different modes
# ---------------------------------------------------------------------------
class TestWorkOrderPricingCombinatorial:
    def test_parts_disposal_road_hazard_aggregation_mode_b(self, api):
        """PRD §3.2: "for each line that is not `VOID`, the system sets `extended_cents` to
        the line's `unit_price_cents_snapshot` multiplied by its `quantity`".
        PRD §3.2: "`parts_subtotal_cents` is the sum of `extended_cents` over `TIRE` lines".
        PRD §3.4: "The order's `road_hazard_premium_cents` is the sum of these per-line
        premiums".

        Tire unit 14999 qty 4 -> parts 59996; disposal at 4 tires = 4*350 = 1400;
        road-hazard pct=round_half_up(59996*0.12)=7200 > floor 4*1200=4800 -> 7200.
        (service_subtotal/tax/total_due depend on unspecified service rates and are not
        asserted — PRD does not name MOUNT_BALANCE/ALIGNMENT prices.)

        Design: Difficulty/combinatorial_formula/work_order_pricing_per_line_round_then_tax_order_mode_b
        """
        customer, vehicle, tire = setup_customer_vehicle_tire(
            tire_overrides={"unit_price_cents": 14999, "mileage_warranty_miles": 30000,
                            "original_tread_32nds": 10, "stock_qty": 20})
        wo = create_work_order(customer["id"], vehicle["id"])
        add_tire_line(wo, tire["id"], quantity=4, road_hazard_opted=True)
        add_service_line(wo, "MOUNT_BALANCE", quantity=4)
        add_service_line(wo, "ALIGNMENT", quantity=1)
        approved = approve_order(wo)
        assert approved["parts_subtotal_cents"] == 59996
        assert approved["disposal_fee_cents"] == 1400
        assert approved["road_hazard_premium_cents"] == 7200

    def test_tax_is_single_round_over_taxable_base(self, api):
        """PRD §3.2: "`tax_cents` is that taxable base multiplied by the tax rate of 8.25
        percent, rounded half up to a whole cent in this single rounding step."
        PRD §3.2: "the taxable base is `parts_subtotal_cents` plus `service_subtotal_cents`
        only — disposal fees and road-hazard premiums are not taxable".

        With only TIRE lines (no service lines), taxable base == parts. tire unit 14999 qty 4
        -> parts 59996, taxable 59996, tax round_half_up(59996*0.0825=4949.67)=4950.

        Design: Difficulty/combinatorial_formula/work_order_pricing_per_line_round_then_tax_order_mode_b
        """
        customer, vehicle, tire, wo, line, approved = setup_approved_order_with_tire_line(
            quantity=4,
            tire_overrides={"unit_price_cents": 14999, "mileage_warranty_miles": 30000,
                            "original_tread_32nds": 10, "stock_qty": 20})
        assert approved["parts_subtotal_cents"] == 59996
        assert approved["tax_cents"] == 4950, f"got {approved['tax_cents']}"

    def test_disposal_fee_marginal_brackets_nine_tires(self, api):
        """PRD §3.3: "Concretely, `disposal_fee_cents` is the smaller of `n` and four,
        multiplied by 350 cents; plus the part of `n` lying between five and eight inclusive
        — that is, `n` minus four, clamped to lie between zero and four — multiplied by 250
        cents; plus any tires past the eighth — that is, `n` minus eight when positive,
        otherwise zero — multiplied by 150 cents."

        n=9 (qty 5 + qty 4): 4*350 + 4*250 + 1*150 = 1400+1000+150 = 2550.

        Design: Difficulty/combinatorial_formula/disposal_fee_marginal_bracket_tiered_mode_a
        """
        customer, vehicle, tire = setup_customer_vehicle_tire(
            tire_overrides={"unit_price_cents": 10000, "mileage_warranty_miles": 50000,
                            "original_tread_32nds": 12, "stock_qty": 20})
        wo = create_work_order(customer["id"], vehicle["id"])
        add_tire_line(wo, tire["id"], quantity=5)
        add_tire_line(wo, tire["id"], quantity=4)
        approved = approve_order(wo)
        assert approved["disposal_fee_cents"] == 2550, f"got {approved['disposal_fee_cents']}"
        assert approved["parts_subtotal_cents"] == 90000

    def test_disposal_nine_tires_tax_over_parts(self, api):
        """PRD §3.2: "`tax_cents` is that taxable base multiplied by the tax rate of 8.25
        percent, rounded half up to a whole cent in this single rounding step."
        PRD §3.3: "This figure becomes the order's `disposal_fee_cents` and is excluded from
        the taxable base."

        parts 90000 (9 tires @ 10000), no service: taxable 90000,
        tax round_half_up(90000*0.0825=7425.0)=7425.

        Design: Difficulty/combinatorial_formula/disposal_fee_marginal_bracket_tiered_mode_a
        """
        customer, vehicle, tire = setup_customer_vehicle_tire(
            tire_overrides={"unit_price_cents": 10000, "mileage_warranty_miles": 50000,
                            "original_tread_32nds": 12, "stock_qty": 20})
        wo = create_work_order(customer["id"], vehicle["id"])
        add_tire_line(wo, tire["id"], quantity=5)
        add_tire_line(wo, tire["id"], quantity=4)
        approved = approve_order(wo)
        assert approved["tax_cents"] == 7425, f"got {approved['tax_cents']}"


# ---------------------------------------------------------------------------
# Corner — calculations section
# ---------------------------------------------------------------------------
class TestSpecialOrderDeposit:
    def test_deposit_pct_branch(self, api):
        """PRD §3.8: "the goods value is the tire model's `unit_price_cents` multiplied by
        the `requested_quantity`; the percentage term is that goods value multiplied by the
        deposit rate of 25 percent, rounded half up to a whole cent; and `deposit_cents` is
        the greater of that rounded percentage term and a minimum deposit of 2000 cents."

        goods=14999*4=59996, 25%=14999 > 2000 -> 14999.

        Design: Corner/calculations/special_order_deposit_pct_branch
        """
        customer, vehicle, tire = setup_customer_vehicle_tire(
            tire_overrides={"unit_price_cents": 14999, "stock_qty": 0})
        wo = create_work_order(customer["id"], vehicle["id"])
        line = add_tire_line(wo, tire["id"], quantity=4)
        so = validate_success(api.create_special_order(
            F.create_special_order_payload(line["id"], tire["id"], requested_quantity=4),
            ADVISOR), expected_status=201)
        assert so["deposit_cents"] == 14999

    def test_deposit_min_floor_branch(self, api):
        """PRD §3.8: "`deposit_cents` is the greater of that rounded percentage term and a
        minimum deposit of 2000 cents."

        goods=5000*1=5000, 25%=1250 < 2000 -> 2000.

        Design: Corner/calculations/special_order_deposit_min_floor_branch
        """
        customer, vehicle, tire = setup_customer_vehicle_tire(
            tire_overrides={"unit_price_cents": 5000, "stock_qty": 0})
        wo = create_work_order(customer["id"], vehicle["id"])
        line = add_tire_line(wo, tire["id"], quantity=1)
        so = validate_success(api.create_special_order(
            F.create_special_order_payload(line["id"], tire["id"], requested_quantity=1),
            ADVISOR), expected_status=201)
        assert so["deposit_cents"] == 2000


class TestDisposalFeeBracketBoundary:
    def test_exactly_four_tires_first_bracket_only(self, api):
        """PRD §3.3: "The first four tires are charged 350 cents each; tires five through
        eight are charged 250 cents each; the ninth tire and every tire beyond it are charged
        150 cents each."

        n=4: 4*350 = 1400 (second bracket not yet engaged).

        Design: Corner/calculations/disposal_fee_at_bracket_boundary_four_tires
        """
        customer, vehicle, tire, wo, line, approved = setup_approved_order_with_tire_line(
            quantity=4, tire_overrides={"unit_price_cents": 10000, "stock_qty": 10})
        assert approved["disposal_fee_cents"] == 1400


class TestMileageVariantSelection:
    def test_system_uses_mileage_based_even_when_wear_linear(self, api):
        """PRD §3.9: "the system always applies the mileage-based variant."
        PRD §3.9: "the per-tire credit is the model's current `unit_price_cents` multiplied
        by the remaining fraction and rounded half up to a whole cent, and
        `prorated_credit_cents` is that per-tire credit multiplied by the `claim_quantity`".

        orig 20000, warranty 50000, miles 10000 -> remaining 0.8 ->
        per_tire round_half_up(16000)=16000, qty 1 -> 16000.

        Design: Corner/calculations/mileage_proration_variant_selection_mileage_based
        """
        customer, vehicle, tire, wo, line, claim = setup_submitted_mileage_claim(
            measured_tread_32nds=2, miles_driven=10000, payout_method="REFUND",
            claim_quantity=1,
            tire_overrides={"unit_price_cents": 20000, "mileage_warranty_miles": 50000,
                            "original_tread_32nds": 10, "stock_qty": 8})
        data = validate_success(api.approve_mileage_claim(claim["id"], ADVISOR))
        assert data["prorated_credit_cents"] == 16000


class TestStoreCreditPayout:
    def test_pay_store_credit_claim_credits_customer(self, api):
        """PRD §3.9: "Finally, the advisor pays an `APPROVED` claim, moving its `status` to
        `PAID`. If the claim's `payout_method` is `STORE_CREDIT`, the customer who owns the
        claimed line's work order has their `store_credit_cents` credited by
        `prorated_credit_cents`."

        prorated 16000 -> customer store_credit_cents becomes 16000.

        Design: Corner/calculations/store_credit_payout_credits_customer_balance
        """
        customer, vehicle, tire, wo, line, claim = setup_submitted_mileage_claim(
            measured_tread_32nds=2, miles_driven=10000, payout_method="STORE_CREDIT",
            claim_quantity=1,
            tire_overrides={"unit_price_cents": 20000, "mileage_warranty_miles": 50000,
                            "original_tread_32nds": 10, "stock_qty": 8})
        validate_success(api.approve_mileage_claim(claim["id"], ADVISOR))
        paid = validate_success(api.pay_mileage_claim(claim["id"], ADVISOR))
        assert paid["status"] == "PAID"
        fetched = validate_success(api.get_customer(customer["id"], ADVISOR))
        assert fetched["store_credit_cents"] == 16000
