"""Impact-fee arithmetic: credit stacking order, the affordable-basis
exemption, per-category rounding order, and dollar conservation."""
import pytest

from test_helpers import (
    COMMERCIAL_ODD_CENT_RATES,
    assert_assessment,
    assert_assessment_conservation,
    category_line,
    get_application,
    get_single_assessment,
    setup_submitted_application,
)

CREDIT_PROJECT = {
    "land_use_type": "RESIDENTIAL",
    "dwelling_units": 100,
    "affordable_units": 10,
    "floor_area_sqft": 0,
    "prior_use_basis": {"TRANSPORTATION": 20},
}


class TestCreditStacking:
    def test_provisional_total_and_transportation_line(self, api):
        """PRD 3.3: "Each category's gross fee is its effective basis multiplied
        by its rate. Two credits then stack, in a fixed order. The prior-use
        credit for a category is the smaller of two quantities: the project's
        `prior_use_basis` entry for that category multiplied by the category
        rate, or the category gross itself". "The improvement credit for a
        category is the smaller of the application's `improvement_credits`
        entry for that category — the dollar value of approved in-lieu
        improvements, which an applicant may optionally declare on the
        application — or the gross that remains after the prior-use credit, so
        the two credits together can never exceed the gross".
        PRD 3.3: "The assessment exposes the per-category arithmetic as
        `category_lines`, each line carrying its `category`, `gross`,
        `prior_use_credit`, `improvement_credit`, and `net`".

        TRANSPORTATION: gross 90×3200=288000.00, prior min(20×3200, gross)=
        64000.00, improvement min(50000, 224000)=50000.00, net 174000.00; the
        five nets sum to 993000.00.

        Design: Difficulty/combinatorial_formula/impact_fee_multi_input_credit_stacking
        """
        ctx = setup_submitted_application(
            project_overrides=CREDIT_PROJECT,
            application_overrides={
                "application_type": "PLANNED_DEVELOPMENT",
                "improvement_credits": {"TRANSPORTATION": 50000.00},
            },
        )
        app = get_application(ctx["application"]["id"], ctx["applicant_headers"])
        assert app["provisional_fee_total"] == pytest.approx(993000.00, abs=0.005), (
            f"provisional total must be 993000.00, got {app['provisional_fee_total']}"
        )

        assessment = get_single_assessment(
            app["id"], ctx["applicant_headers"], variant="PROVISIONAL"
        )
        assert_assessment(assessment)
        line = category_line(assessment, "TRANSPORTATION")
        assert line["gross"] == pytest.approx(288000.00, abs=0.005)
        assert line["prior_use_credit"] == pytest.approx(64000.00, abs=0.005)
        assert line["improvement_credit"] == pytest.approx(50000.00, abs=0.005)
        assert line["net"] == pytest.approx(174000.00, abs=0.005)

    def test_affordable_exemption_is_category_conditional_and_credit_caps(self, api):
        """PRD 3.3: "Residential projects receive an affordable-housing
        exemption in exactly two categories, TRANSPORTATION and PARKS, where
        the effective basis is `dwelling_units` minus `affordable_units` rather
        than the full unit count." — FIRE keeps the full 100-unit basis.
        PRD 3.3: "The improvement credit for a category is the smaller of the
        application's `improvement_credits` entry for that category — the
        dollar value of approved in-lieu improvements, which an applicant may
        optionally declare on the application — or the gross that remains after
        the prior-use credit, so the two credits together can never exceed the
        gross".

        Design: Difficulty/combinatorial_formula/impact_fee_multi_input_credit_stacking
        """
        ctx = setup_submitted_application(
            project_overrides=CREDIT_PROJECT,
            application_overrides={
                "application_type": "PLANNED_DEVELOPMENT",
                "improvement_credits": {"TRANSPORTATION": 300000.00},
            },
        )
        assessment = get_single_assessment(
            ctx["application"]["id"], ctx["applicant_headers"], variant="PROVISIONAL"
        )

        parks = category_line(assessment, "PARKS")
        assert parks["gross"] == pytest.approx(189000.00, abs=0.005), (
            f"PARKS uses the exempt basis 90×2100=189000, got {parks['gross']}"
        )
        fire = category_line(assessment, "FIRE")
        assert fire["gross"] == pytest.approx(80000.00, abs=0.005), (
            f"FIRE is not exempt and uses the full basis 100×800=80000, "
            f"got {fire['gross']}"
        )

        trans = category_line(assessment, "TRANSPORTATION")
        # The credit caps at the gross remaining after prior use: 224000.00.
        assert trans["improvement_credit"] == pytest.approx(224000.00, abs=0.005), (
            f"improvement credit caps at gross-minus-prior (224000), "
            f"got {trans['improvement_credit']}"
        )
        assert trans["net"] == pytest.approx(0.00, abs=0.005)
        assert assessment["net_total"] == pytest.approx(819000.00, abs=0.005), (
            f"total must be 0+189000+80000+260000+290000=819000, "
            f"got {assessment['net_total']}"
        )


class TestCommercialRoundingOrder:
    def _commercial_assessment(self, api):
        ctx = setup_submitted_application(
            project_overrides={
                "land_use_type": "COMMERCIAL",
                "dwelling_units": 0,
                "affordable_units": 0,
                "floor_area_sqft": 1004,
                "prior_use_basis": {},
            },
            rates=COMMERCIAL_ODD_CENT_RATES,
        )
        assessment = get_single_assessment(
            ctx["application"]["id"], ctx["applicant_headers"], variant="PROVISIONAL"
        )
        return ctx, assessment

    def test_net_total_rounds_per_category_then_sums(self, api):
        """PRD 2.6: "impact-fee assessments round each category's net to cents
        first and only then sum the rounded category nets into the assessment
        total. Summing unrounded nets and rounding once at the end is not
        equivalent and is not acceptable."
        PRD 3.3: "a `COMMERCIAL` project contributes its `floor_area_sqft`
        divided by 1,000".

        1004 sqft at odd-cent FIRE/WATER rates: per-category-then-sum yields
        12928.10; the forbidden sum-then-round order would yield 12928.11.

        Design: Difficulty/combinatorial_formula/impact_fee_commercial_rounding_order
        """
        ctx, assessment = self._commercial_assessment(api)
        assert assessment["net_total"] == pytest.approx(12928.10, abs=0.001), (
            f"net_total must be 12928.10 (round per category then sum), "
            f"got {assessment['net_total']}"
        )
        app = get_application(ctx["application"]["id"], ctx["applicant_headers"])
        assert app["provisional_fee_total"] == pytest.approx(12928.10, abs=0.001)

    def test_category_lines_show_individual_rounding(self, api):
        """PRD 2.6: "every dollar figure the API stores or returns — fee rates,
        category gross and credit amounts, assessment totals, payment amounts,
        late fees, outstanding balances — is expressed with exactly 2 decimal
        places using round-half-up rounding."

        FIRE raw 1.004×951.05 = 954.8542 rounds to 954.85; WATER raw
        1.004×3125.55 = 3138.0522 rounds to 3138.05 — each line is rounded
        before the sum.

        Design: Difficulty/combinatorial_formula/impact_fee_commercial_rounding_order
        """
        _ctx, assessment = self._commercial_assessment(api)
        fire = category_line(assessment, "FIRE")
        water = category_line(assessment, "WATER")
        assert fire["net"] == pytest.approx(954.85, abs=0.001), (
            f"FIRE net must round to 954.85, got {fire['net']}"
        )
        assert water["net"] == pytest.approx(3138.05, abs=0.001), (
            f"WATER net must round to 3138.05, got {water['net']}"
        )
        transportation = category_line(assessment, "TRANSPORTATION")
        sewer = category_line(assessment, "SEWER")
        assert transportation["net"] == pytest.approx(5421.60, abs=0.001)
        assert sewer["net"] == pytest.approx(3413.60, abs=0.001)


def test_assessment_net_equals_gross_minus_credits_conservation(api):
    """PRD 3.3: "Each category's net is its gross minus both credits" and the
    assessment "sums the columns into `gross_total`, `prior_use_credit_total`,
    and `improvement_credit_total`".

    On the credit-bearing fixture the conserved equation reads exactly
    993000.00 == 1107000.00 − 64000.00 − 50000.00.

    Design: Difficulty/compensating_invariant/fee_assessment_net_equals_gross_minus_credits_conservation
    """
    ctx = setup_submitted_application(
        project_overrides=CREDIT_PROJECT,
        application_overrides={"improvement_credits": {"TRANSPORTATION": 50000.00}},
    )
    assessment = get_single_assessment(
        ctx["application"]["id"], ctx["applicant_headers"], variant="PROVISIONAL"
    )
    assert_assessment(assessment)
    assert assessment["gross_total"] == pytest.approx(1107000.00, abs=0.005)
    assert assessment["prior_use_credit_total"] == pytest.approx(64000.00, abs=0.005)
    assert assessment["improvement_credit_total"] == pytest.approx(50000.00, abs=0.005)
    assert assessment["net_total"] == pytest.approx(993000.00, abs=0.005)
    assert_assessment_conservation(assessment)
