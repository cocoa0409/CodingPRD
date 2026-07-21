"""Combinatorial enrollment pricing and installment allocation (queue-A difficulty rule 2)."""
from test_helpers import (
    validate_success, OPERATOR,
    setup_open_departure, make_plan,
    create_enrollment_payload,
)


class TestEnrollmentPriceCombination:
    """Design: Difficulty/combinatorial_formula/enrollment_price_earlybird_addons_insurance_mode_a"""

    def test_price_combines_earlybird_addons_and_insurance(self, api):
        """PRD §3.3: "The locked price is the gross, minus the early-bird discount, plus
        the total of the add-ons, plus the insurance premium."
        PRD §3.3: "a single room adds 40000 cents, an excursion adds 12000 cents, and a
        STEM lab adds 8000 cents" and "the basic tier adds 9900 cents and the premium
        tier adds 19900 cents".

        Design: Difficulty/combinatorial_formula/enrollment_price_earlybird_addons_insurance_mode_a
        """
        # clock 2026-07-15 <= early_bird_cutoff 2026-08-01 -> discount 25000.
        ctx = setup_open_departure(api, clock="2026-07-15T00:00:00Z", price_per_traveler_cents=250000)
        payload = create_enrollment_payload(
            ctx["departure"]["id"], traveler_name="Cal Vez", traveler_gender="NONBINARY",
            add_ons=["EXCURSION", "STEM_LAB"], insurance_opted=True, insurance_tier="PREMIUM",
        )
        data = validate_success(api.create_enrollment(payload, OPERATOR), expected_status=201)
        # 250000 - 25000 + (12000 + 8000) + 19900 = 264900
        assert data["price_locked_cents"] == 264900

    def test_price_persists_after_create(self, api):
        """PRD §3.3: "At creation the system computes and stores price_locked_cents; any
        price supplied by the client is ignored."
        PRD §3.3: "The locked price is the gross, minus the early-bird discount, plus the
        total of the add-ons, plus the insurance premium."

        Design: Difficulty/combinatorial_formula/enrollment_price_earlybird_addons_insurance_mode_a
        """
        ctx = setup_open_departure(api, clock="2026-07-15T00:00:00Z", price_per_traveler_cents=250000)
        payload = create_enrollment_payload(
            ctx["departure"]["id"], traveler_name="Cal Vez", traveler_gender="NONBINARY",
            add_ons=["EXCURSION", "STEM_LAB"], insurance_opted=True, insurance_tier="PREMIUM",
            price_locked_cents=999,  # client-supplied price must be ignored
        )
        created = validate_success(api.create_enrollment(payload, OPERATOR), expected_status=201)
        fetched = validate_success(api.get_enrollment(created["id"], OPERATOR))
        assert fetched["price_locked_cents"] == 264900


class TestInstallmentSplit:
    """Design: Difficulty/combinatorial_formula/installment_split_floor_then_remainder_to_earliest_mode_b"""

    def _make_plan_over_271900(self, api):
        # clock 2026-08-15 is after early_bird_cutoff -> no discount.
        # add_ons [EXCURSION]=12000, insurance BASIC=9900 -> 250000 + 12000 + 9900 = 271900.
        ctx = setup_open_departure(api, clock="2026-08-15T00:00:00Z", price_per_traveler_cents=250000)
        payload = create_enrollment_payload(
            ctx["departure"]["id"], traveler_name="Dee Kay", traveler_gender="FEMALE",
            add_ons=["EXCURSION"], insurance_opted=True, insurance_tier="BASIC",
        )
        enr = validate_success(api.create_enrollment(payload, OPERATOR), expected_status=201)
        assert enr["price_locked_cents"] == 271900
        return make_plan(api, enr["id"], enr["version"], installment_count=3)

    def test_installment_amounts_floor_then_remainder_to_earliest(self, api):
        """PRD §3.4: "The base amount for each installment is the financed remainder divided
        by the installment count, taken as the integer floor. The leftover cents — the
        financed remainder minus the base times the count — are distributed one cent each to
        the earliest installments: the first installment receives an extra cent, then the
        second, and so on, until the leftover is exhausted."

        Design: Difficulty/combinatorial_formula/installment_split_floor_then_remainder_to_earliest_mode_b
        """
        plan = self._make_plan_over_271900(api)
        # financed = 271900 - 30000 = 241900; 241900 // 3 = 80633, remainder 1 -> [80634, 80633, 80633]
        assert plan["installment_amounts"] == [80634, 80633, 80633]

    def test_installment_amounts_sum_with_no_drift(self, api):
        """PRD §3.4: "The installment amounts always sum to exactly the financed remainder."
        PRD §3.4: "The plan's total_cents is fixed at creation to equal the enrollment's
        price_locked_cents."

        Design: Difficulty/combinatorial_formula/installment_split_floor_then_remainder_to_earliest_mode_b
        """
        plan = self._make_plan_over_271900(api)
        assert plan["total_cents"] == 271900
        assert sum(plan["installment_amounts"]) == 241900
