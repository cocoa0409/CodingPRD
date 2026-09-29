"""Deriving a ladder model's load requirements from its duty class, length,
family and rail material."""

from test_helpers import (
    api_client,
    assert_product_derivations,
    create_product_payload,
    validate_success,
)
from test_helpers import TEST_USERS

ENGINEER = TEST_USERS["design_engineer_headers"]


class TestSafetyFactorAddersAndCap:
    def test_mobile_scaffold_tower_fiberglass_safety_factor_is_clamped_to_the_ceiling(self):
        """PRD §3.1: "Add the product-family bonus: nothing for `STEP_LADDER`,
        `EXTENSION_LADDER`, or `PLATFORM_LADDER`, one tenth for
        `ARTICULATED_LADDER`, and one quarter for `MOBILE_SCAFFOLD_TOWER`."
        PRD §3.1: "Whichever is smaller — that sum or the hard ceiling of 4.60 —
        becomes `safety_factor`, rounded half up to two decimal places."
        PRD §3.1: "`rated_load_lb` is 200 pounds for `TYPE_III`, 225 for
        `TYPE_II`, 250 for `TYPE_I`, 300 for `TYPE_IA`, and 375 for `TYPE_IAA`."

        Design: Difficulty/combinatorial_formula/duty_rating_safety_factor_capped_and_uncapped
        """
        payload = create_product_payload(
            product_type="MOBILE_SCAFFOLD_TOWER",
            material="FIBERGLASS_PULTRUSION",
            duty_rating="TYPE_IAA",
            working_length_ft=28.0,
        )
        data = validate_success(api_client.create_product(payload, ENGINEER), 201)

        # Four length steps (0.60) plus the tower bonus (0.25) plus the
        # fiberglass adder (0.05) sum to 4.90, which the ceiling clamps to 4.60.
        assert_product_derivations(
            data,
            expected_rated_load_lb=375,
            expected_safety_factor=4.60,
            expected_required_test_load_lb=1725.00,
            expected_required_pull_force_lbf=562.50,
            expected_max_allowed_deflection_in=1.867,
        )

    def test_extension_ladder_fiberglass_safety_factor_stays_below_the_ceiling(self):
        """PRD §3.1: "Start from a base safety factor of 4.00. Add fifteen
        hundredths for each length step counted in step two."
        PRD §3.1: "Add five hundredths when `material` is
        `FIBERGLASS_PULTRUSION`, and nothing for the other two materials."
        PRD §3.1: "`required_test_load_lb` is `rated_load_lb` multiplied by the
        already-rounded `safety_factor`, the product rounded half up to two
        decimal places; this is the load a qualifying static test must reach."

        Design: Difficulty/combinatorial_formula/duty_rating_safety_factor_capped_and_uncapped
        """
        payload = create_product_payload(
            product_type="EXTENSION_LADDER",
            material="FIBERGLASS_PULTRUSION",
            duty_rating="TYPE_IA",
            working_length_ft=24.0,
        )
        data = validate_success(api_client.create_product(payload, ENGINEER), 201)

        # Three length steps (0.45) plus the fiberglass adder (0.05) reach 4.50,
        # which is below the ceiling and therefore survives unclamped.
        assert_product_derivations(
            data,
            expected_rated_load_lb=300,
            expected_safety_factor=4.50,
            expected_required_test_load_lb=1350.00,
            expected_required_pull_force_lbf=450.00,
            expected_max_allowed_deflection_in=1.600,
        )


class TestLengthStepBoundary:
    def test_twelve_foot_ladder_buys_no_length_step(self):
        """PRD §3.1: "Rounding up means a twelve-foot ladder buys no step at all,
        while a ladder of twelve feet and one tenth already buys a full step, and
        a twenty-foot ladder buys two."
        PRD §3.1: "`max_allowed_deflection_in` is `working_length_ft` converted to
        inches by multiplying by twelve, then divided by the span divisor of 180,
        the result rounded half up to three decimal places; this is the deflection
        ceiling for a passing load test."

        Design: Difficulty/boundary_precision_check/working_length_exactly_twelve_feet_adds_no_step
        """
        payload = create_product_payload(
            product_type="STEP_LADDER",
            material="ALUMINUM_EXTRUSION",
            duty_rating="TYPE_II",
            working_length_ft=12.0,
        )
        data = validate_success(api_client.create_product(payload, ENGINEER), 201)

        assert_product_derivations(
            data,
            expected_rated_load_lb=225,
            expected_safety_factor=4.00,
            expected_required_test_load_lb=900.00,
            expected_required_pull_force_lbf=337.50,
            expected_max_allowed_deflection_in=0.800,
        )

    def test_twelve_and_a_half_foot_ladder_buys_a_full_length_step(self):
        """PRD §3.1: "Rounding up means a twelve-foot ladder buys no step at all,
        while a ladder of twelve feet and one tenth already buys a full step, and
        a twenty-foot ladder buys two."
        PRD §3.1: "Start from a base safety factor of 4.00. Add fifteen hundredths
        for each length step counted in step two."

        Design: Difficulty/boundary_precision_check/working_length_exactly_twelve_feet_adds_no_step
        """
        payload = create_product_payload(
            product_type="STEP_LADDER",
            material="ALUMINUM_EXTRUSION",
            duty_rating="TYPE_II",
            working_length_ft=12.5,
        )
        data = validate_success(api_client.create_product(payload, ENGINEER), 201)

        assert_product_derivations(
            data,
            expected_rated_load_lb=225,
            expected_safety_factor=4.15,
            expected_required_test_load_lb=933.75,
            expected_required_pull_force_lbf=337.50,
            expected_max_allowed_deflection_in=0.833,
        )

    def test_ladder_shorter_than_the_baseline_floors_the_step_count_at_zero(self):
        """PRD §3.1: "Subtract the twelve-foot baseline from `working_length_ft`,
        divide the remainder by four feet, and round the quotient **up** to the
        next whole number; if the result is negative, use zero."

        Design: Difficulty/boundary_precision_check/working_length_exactly_twelve_feet_adds_no_step
        """
        payload = create_product_payload(
            product_type="STEP_LADDER",
            material="ALUMINUM_EXTRUSION",
            duty_rating="TYPE_II",
            working_length_ft=11.9,
        )
        data = validate_success(api_client.create_product(payload, ENGINEER), 201)

        # A negative quotient is floored at zero, so the safety factor stays at
        # the 4.00 base exactly as it does at twelve feet.
        assert_product_derivations(
            data,
            expected_rated_load_lb=225,
            expected_safety_factor=4.00,
            expected_required_test_load_lb=900.00,
            expected_required_pull_force_lbf=337.50,
            expected_max_allowed_deflection_in=0.793,
        )
