"""Payment computation: PLC vs ARC-CO variants, reference-price trigger,
sequestration split, and immediate consistency (PRD §3.8, §2.2)."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_enrollment,
    assert_payment_split_integrity,
    setup_certified_enrollment,
    setup_payment_computed_enrollment,
    validate_success,
)


@pytest.fixture
def specialist(county_specialist_headers):
    return county_specialist_headers


class TestPlcVsArcCoDivergence:
    def test_plc_payment_with_price_below_reference(self, api, specialist):
        """PRD §3.8: "The reference prices are $4.10 per bushel for `CORN`,
        $9.00 for `SOYBN`, and $5.50 for `WHEAT`. The effective price is the
        lesser of the supplied `national_my_price` and the commodity's loan
        rate. The payment rate is the greater of zero and the reference price
        minus the effective price. The base payment is the payment rate
        multiplied by the enrollment's `aph_yield_bu_per_acre`, multiplied by
        the base acres on the enrollment, multiplied by the statutory payment
        factor of 0.85." and "The `sequestration_cents` amount is the
        post-limitation payment multiplied by 5.7 percent, rounded half-up to
        two decimal places. The net `computed_payment_cents` is the
        post-limitation payment minus the sequestration, rounded half-up to two
        decimal places."

        PLC derivation: rate 4.10-3.50 = 0.60; base 0.60 x 180.0 x 100 x 0.85
        = 9180.00; sequestration round(9180 x 0.057, 2) = 523.26; net 8656.74
        -> 865674 cents.

        Design: Difficulty/dual_variant_calc/plc_vs_arc_co_same_data_divergent_payment
        """
        ctx = setup_payment_computed_enrollment(
            election_code="PLC", compute_inputs={"national_my_price": 3.50}
        )
        enrollment = ctx["enrollment"]
        assert_enrollment(enrollment)
        assert enrollment["computed_payment_cents"] == 865674, (
            f"PLC net payment must be 865674 cents, got "
            f"{enrollment['computed_payment_cents']}"
        )
        assert enrollment["sequestration_cents"] == 52326

    def test_arc_co_payment_zero_when_county_revenue_covers_guarantee(
        self, api, specialist
    ):
        """PRD §3.8: "Under `ARC_CO` — Agriculture Risk Coverage, county option —
        the guarantee is 86 percent of the supplied `benchmark_revenue`. Actual
        revenue is the supplied `county_actual_yield` multiplied by
        `national_my_price`. The payment rate is the lesser of ten percent of
        the benchmark revenue and the greater of zero and the guarantee minus
        actual revenue — the rate is capped at ten percent of benchmark." and
        "ARC-CO keys off revenue (yield times price) where PLC keys off price
        alone, so the same farm data can produce a payment under one program and
        zero under the other when the price is low but county yield is high."

        ARC-CO derivation on identical acreage/yield inputs: guarantee
        0.86 x 760.00 = 653.60; actual 190.0 x 3.50 = 665.00; rate
        min(76.00, max(0, 653.60-665.00)) = 0 -> payment 0, diverging from
        PLC's 865674 cents on the same farm data.

        Design: Difficulty/dual_variant_calc/plc_vs_arc_co_same_data_divergent_payment
        """
        ctx = setup_payment_computed_enrollment(
            election_code="ARC_CO",
            compute_inputs={
                "national_my_price": 3.50,
                "county_actual_yield": 190.0,
                "benchmark_revenue": 760.00,
            },
        )
        enrollment = ctx["enrollment"]
        assert enrollment["computed_payment_cents"] == 0, (
            f"ARC-CO payment must be zero when county revenue covers the "
            f"guarantee, got {enrollment['computed_payment_cents']}"
        )
        assert enrollment["sequestration_cents"] == 0


class TestPlcFormulaShape:
    def test_plc_full_formula_multi_input(self, api, specialist):
        """PRD §3.8: "The payment rate is the greater of zero and the reference
        price minus the effective price. The base payment is the payment rate
        multiplied by the enrollment's `aph_yield_bu_per_acre`, multiplied by
        the base acres on the enrollment, multiplied by the statutory payment
        factor of 0.85." and "The attributable amount is the base payment
        multiplied by the membership's `share_percent` divided by 100. The cap
        is the producer's `payment_limitation_cap_cents` converted to dollars"

        APH 200.0, base 50.00, price 3.50: rate 0.60; base 0.60 x 200.0 x 50 x
        0.85 = 5100.00; attributable 5100.00 (100% share, below the $125,000
        cap); sequestration round(5100 x 0.057, 2) = 290.70; net 4809.30 ->
        480930 cents.

        Design: Difficulty/combinatorial_formula/plc_formula_multi_input_nonlinear
        """
        ctx = setup_payment_computed_enrollment(
            base_acres=50.00,
            planted_acres=50.00,
            yields=(200.0,) * 5,
            compute_inputs={"national_my_price": 3.50},
        )
        enrollment = ctx["enrollment"]
        assert enrollment["computed_payment_cents"] == 480930, (
            f"PLC net payment must be 480930 cents, got "
            f"{enrollment['computed_payment_cents']}"
        )
        assert enrollment["sequestration_cents"] == 29070, (
            f"sequestration must be 29070 cents, got "
            f"{enrollment['sequestration_cents']}"
        )

    def test_plc_payment_zero_when_price_above_reference(self, api, specialist):
        """PRD §3.8: "The payment rate is the greater of zero and the reference
        price minus the effective price." and "Identical acreage and yield
        inputs produce a non-zero payment when the effective price is below the
        reference price, and a zero payment at or above it."

        Design: Difficulty/combinatorial_formula/plc_formula_multi_input_nonlinear
        """
        ctx = setup_payment_computed_enrollment(
            compute_inputs={"national_my_price": 4.50}
        )
        assert ctx["enrollment"]["computed_payment_cents"] == 0, (
            f"price 4.50 above reference 4.10 must zero the payment, got "
            f"{ctx['enrollment']['computed_payment_cents']}"
        )


class TestReferencePriceConstant:
    def test_plc_payment_zero_at_reference_price(self, api, specialist):
        """PRD §3.8: "The reference prices are $4.10 per bushel for `CORN`,
        $9.00 for `SOYBN`, and $5.50 for `WHEAT`." and "Identical acreage and
        yield inputs produce a non-zero payment when the effective price is
        below the reference price, and a zero payment at or above it."

        Design: Corner/calculations/plc_payment_uses_reference_price_constant
        """
        ctx = setup_payment_computed_enrollment(
            compute_inputs={"national_my_price": 4.10}
        )
        assert ctx["enrollment"]["computed_payment_cents"] == 0, (
            f"effective price equal to reference price must zero the payment, "
            f"got {ctx['enrollment']['computed_payment_cents']}"
        )


class TestImmediateConsistency:
    def test_computed_fields_visible_in_same_response(self, api, specialist):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data
        field."
        PRD §3.8: "The `sequestration_cents` amount is the post-limitation
        payment multiplied by 5.7 percent, rounded half-up to two decimal
        places. The net `computed_payment_cents` is the post-limitation payment
        minus the sequestration, rounded half-up to two decimal places. Both
        fields are set on the enrollment by the computation."

        Design: Corner/consistency_model/computed_fields_visible_in_same_response
        """
        ctx = setup_certified_enrollment()
        resp = api.compute_payment(
            ctx["enrollment"]["id"], {"national_my_price": 3.50}, specialist
        )
        enrollment = validate_success(resp, 200)
        assert_enrollment(enrollment)
        assert enrollment["computed_payment_cents"] == 865674, (
            f"compute-payment response must carry computed_payment_cents "
            f"865674, got {enrollment['computed_payment_cents']}"
        )
        assert enrollment["sequestration_cents"] == 52326, (
            f"compute-payment response must carry sequestration_cents 52326, "
            f"got {enrollment['sequestration_cents']}"
        )
        assert (
            enrollment["computed_payment_cents"] + enrollment["sequestration_cents"]
            == 918000
        ), "net plus sequestration must reconstruct the post-limitation gross"
        assert_payment_split_integrity(enrollment)
