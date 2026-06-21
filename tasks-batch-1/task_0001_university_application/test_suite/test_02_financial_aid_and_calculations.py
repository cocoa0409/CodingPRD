"""Financial Aid Profile, EFC calculation variants, composite-score calculations.

Covers Difficulty Rule 1 (dual_variant_calc) and Rule 2 (combinatorial_formula
composite_score instance) plus Corner calculation canonicals.
"""
import pytest

from test_helpers import (
    TEST_USERS,
    create_applicant,
    create_financial_aid_profile_payload,
    make_applicant_headers,
    set_clock,
    setup_ready_to_submit_application,
    setup_submitted_application,
    validate_error,
    validate_success,
)


def test_efc_fafsa_zero_assets_canonical_calc(api):
    """PRD §3.4: "the server subtracts a per-person shelter allowance — 8000
    dollars, or 800,000 cents, per person in the household — from
    household_income_cents, multiplied by household_size."
    PRD §3.4: "The adjusted income is then multiplied by a 22 % income-assessment
    rate (0.22) to produce a base contribution; the multiplication's result is
    rounded to a whole cent using round-half-up."

    Design: Corner/calculations/efc_fafsa_zero_assets_canonical_calc_passes
    """
    applicant = create_applicant(email="efc1@u.edu", gpa_unweighted=3.0, residency="IN_STATE")
    payload = create_financial_aid_profile_payload(
        applicant["id"], profile_type="FAFSA",
        household_income_cents=12_000_000, household_size=3,
    )
    fap = validate_success(
        api.create_financial_aid_profile(payload, make_applicant_headers(applicant["id"])),
        expected_status=201,
    )
    # adjusted = 12000000 - 3*800000 = 9600000; base = round(9600000*0.22) = 2112000
    assert fap["expected_family_contribution_cents"] == 2_112_000


def test_efc_high_income_zero_after_shelter_caps_at_zero(api):
    """PRD §3.4: "If the result is negative, it is floored to zero, producing
    an adjusted income in cents."

    Design: Corner/calculations/efc_high_income_zero_after_shelter_caps_at_zero
    """
    applicant = create_applicant(email="efc_low@u.edu", gpa_unweighted=3.0, residency="IN_STATE")
    payload = create_financial_aid_profile_payload(
        applicant["id"], profile_type="FAFSA",
        household_income_cents=2_000_000, household_size=5,
    )
    fap = validate_success(
        api.create_financial_aid_profile(payload, make_applicant_headers(applicant["id"])),
        expected_status=201,
    )
    # adjusted = max(0, 2000000 - 5*800000) = 0; base = round(0*0.22) = 0
    assert fap["expected_family_contribution_cents"] == 0


def test_efc_fafsa_vs_css_profile_diverge_on_identical_income(api):
    """PRD §3.4: "This rounded base is what a FAFSA profile reports as its
    expected_family_contribution_cents — even if the FAFSA row somehow carried
    a positive declared_assets_cents (which the validation in §3.3 should
    already have rejected), the FAFSA variant ignores it and contributes zero
    from assets."
    PRD §3.4: "The CSS_PROFILE variant adds an asset component on top. The
    server multiplies declared_assets_cents by a 5 % asset-assessment rate
    (0.05), rounds that product to a whole cent using round-half-up, and sums
    the rounded asset contribution with the already-rounded base."
    PRD §3.4: "A CSS Profile applicant with identical income and household
    size always reports a strictly higher contribution than a FAFSA applicant
    whenever declared_assets_cents is greater than zero."

    Design: Difficulty/dual_variant_calc/efc_fafsa_vs_css_profile_diverge_on_identical_income
    """
    a_fafsa = create_applicant(email="fafsa@u.edu", gpa_unweighted=3.50,
                               sat_total=1300, residency="IN_STATE")
    a_css = create_applicant(email="css@u.edu", gpa_unweighted=3.50,
                             sat_total=1300, residency="IN_STATE")
    fap_fafsa = validate_success(
        api.create_financial_aid_profile(
            create_financial_aid_profile_payload(
                a_fafsa["id"], profile_type="FAFSA",
                household_income_cents=8_000_000, household_size=4,
                declared_assets_cents=0,
            ),
            make_applicant_headers(a_fafsa["id"]),
        ),
        expected_status=201,
    )
    fap_css = validate_success(
        api.create_financial_aid_profile(
            create_financial_aid_profile_payload(
                a_css["id"], profile_type="CSS_PROFILE",
                household_income_cents=8_000_000, household_size=4,
                declared_assets_cents=5_000_000,
            ),
            make_applicant_headers(a_css["id"]),
        ),
        expected_status=201,
    )
    # FAFSA: adjusted = 8000000 - 4*800000 = 4800000; base = round(4800000*0.22) = 1056000
    assert fap_fafsa["expected_family_contribution_cents"] == 1_056_000
    # CSS_PROFILE: income base 1056000 + round(5000000*0.05)=250000 = 1306000
    assert fap_css["expected_family_contribution_cents"] == 1_306_000
    # And CSS strictly greater than FAFSA on same income/household when assets > 0
    assert (
        fap_css["expected_family_contribution_cents"]
        > fap_fafsa["expected_family_contribution_cents"]
    )


def test_efc_fafsa_vs_css_dual_variant_pinned_rounding(api):
    """PRD §3.4: "The rounding order is pinned: the income component is rounded
    first, the asset component is rounded second, and the sum of two integers
    is the final expected_family_contribution_cents."

    Design: Difficulty/dual_variant_calc/efc_fafsa_vs_css_profile_diverge_on_identical_income
    """
    applicant = create_applicant(email="css2@u.edu", gpa_unweighted=3.0, residency="IN_STATE")
    fap = validate_success(
        api.create_financial_aid_profile(
            create_financial_aid_profile_payload(
                applicant["id"], profile_type="CSS_PROFILE",
                household_income_cents=8_000_000, household_size=4,
                declared_assets_cents=5_000_000,
            ),
            make_applicant_headers(applicant["id"]),
        ),
        expected_status=201,
    )
    # Same canonical inputs from above; CSS contribution must equal 1,306,000 cents.
    assert fap["expected_family_contribution_cents"] == 1_306_000


def test_composite_with_sat_canonical_pinned_rounding(api):
    """PRD §3.5: "The four normalized scores are blended with fixed weights:
    the GPA normalized score is weighted 0.40, the SAT normalized score is
    weighted 0.20, the essay score is weighted 0.15, and the recommendation
    score is weighted 0.25."
    PRD §3.5: "Per-component rounding precedes summation in a pinned order:
    each component is multiplied by its weight and the product is rounded
    half-up to two decimal places to yield that component's term; the four
    terms are then summed; and the sum itself is rounded half-up to two
    decimal places to produce the final composite_score."

    Design: Difficulty/dual_variant_calc/composite_with_sat_vs_test_optional_diverge_on_same_applicant_data
    """
    set_clock("2026-09-01T00:00:00Z")
    applicant, school, app = setup_ready_to_submit_application(
        email_suffix="cw", gpa=3.80, sat_total=1400, residency="IN_STATE",
        num_essays=3, rec_ratings=[5, 4],
    )
    set_clock("2026-09-15T00:00:00Z")
    submitted = validate_success(
        api.submit_application(app["id"], make_applicant_headers(applicant["id"])),
        expected_status=200,
    )
    # gpa_norm=95.00; sat_norm=round((1400-400)/1200*100,2)=83.33;
    # essay_score=min(100,3*20)=60.00; rec_avg=4.5 → rec_score=90.00
    # gpa_term=34.00, sat_term=16.67, essay_term=9.00, rec_term=22.50 → 82.17? recompute
    # Let me recompute: 34.00 + 16.67 + 9.00 + 22.50 = 82.17  — wait scaffold says 86.17!
    # 95*0.40 = 38.00 (not 34) — yes 95 * 0.40 = 38.00. gpa_term=38.00.
    # 38.00 + 16.67 + 9.00 + 22.50 = 86.17
    assert submitted["composite_score"] == pytest.approx(86.17, abs=0.001)


def test_composite_test_optional_variant_canonical(api):
    """PRD §3.5: "the second component normalizes the applicant's sat_total: if
    sat_total is null (the test-optional path), the SAT normalized value
    defaults to the neutral 50.00".
    PRD §3.5: "The test-optional variant — where sat_total is null and the SAT
    component takes the neutral 50.00 — produces a different composite_score
    than a real SAT for the same applicant unless the applicant's hypothetical
    SAT would normalize to exactly 50.00; a 1400 SAT yields an SAT normalized
    of 83.33 and an SAT term of 16.67, where a null SAT yields an SAT term of
    10.00, a 6.67-point swing on the same applicant."

    Design: Difficulty/dual_variant_calc/composite_with_sat_vs_test_optional_diverge_on_same_applicant_data
    """
    set_clock("2026-09-01T00:00:00Z")
    applicant, school, app = setup_ready_to_submit_application(
        email_suffix="co", gpa=3.80, sat_total=None, residency="IN_STATE",
        num_essays=3, rec_ratings=[5, 4],
    )
    set_clock("2026-09-15T00:00:00Z")
    submitted = validate_success(
        api.submit_application(app["id"], make_applicant_headers(applicant["id"])),
        expected_status=200,
    )
    # Same gpa/essays/recs as previous; sat_term = 50.00*0.20 = 10.00
    # 38.00 + 10.00 + 9.00 + 22.50 = 79.50
    assert submitted["composite_score"] == pytest.approx(79.50, abs=0.001)


def test_composite_per_component_rounding_order_pinned(api):
    """PRD §3.5: "Per-component rounding precedes summation in a pinned order:
    each component is multiplied by its weight and the product is rounded
    half-up to two decimal places to yield that component's term; the four
    terms are then summed; and the sum itself is rounded half-up to two
    decimal places to produce the final composite_score."
    PRD §3.5: "Summing the unrounded weighted products first and rounding once
    at the end produces a different second decimal in some inputs and is not
    the contract."

    Design: Difficulty/combinatorial_formula/composite_score_per_component_rounding_order_pinned
    """
    set_clock("2026-09-01T00:00:00Z")
    applicant, school, app = setup_ready_to_submit_application(
        email_suffix="round", gpa=3.40, sat_total=1200, residency="IN_STATE",
        num_essays=2, rec_ratings=[3, 3],
    )
    set_clock("2026-09-15T00:00:00Z")
    submitted = validate_success(
        api.submit_application(app["id"], make_applicant_headers(applicant["id"])),
        expected_status=200,
    )
    # gpa_norm=85.00 → gpa_term=34.00; sat_norm=round((1200-400)/1200*100,2)=66.67 → sat_term=round(13.334,2)=13.33
    # essay_score=min(100,2*20)=40.00 → essay_term=6.00; rec_avg=3.0 → rec_score=60.00 → rec_term=15.00
    # Pinned: 34.00 + 13.33 + 6.00 + 15.00 = 68.33
    assert submitted["composite_score"] == pytest.approx(68.33, abs=0.001)


def test_composite_recomputed_on_recommendation_submit(api):
    """PRD §3.5: "The composite_score is recomputed not only at submit but at
    four other moments: when a recommendation for the matching
    (applicant_id, school_id) flips from INVITED to SUBMITTED (the
    recommender's rating enters the average)".

    Design: Difficulty/combinatorial_formula/composite_score_per_component_rounding_order_pinned
    """
    set_clock("2026-09-01T00:00:00Z")
    applicant, school, submitted = setup_submitted_application(
        email_suffix="comp_re", gpa=3.40, sat_total=1200, residency="IN_STATE",
        rec_ratings=[3, 3],
    )
    initial = submitted["composite_score"]
    # Add a third recommendation with rating 5; rec_avg becomes (3+3+5)/3 ≈ 3.667 → rec_score=73.33
    # gpa_term=34.00; sat_term=13.33; essay_term=6.00; rec_term=round(73.33*0.25,2)=18.33
    # total = 71.66
    inv = validate_success(
        api.create_recommendation_request(
            {
                "applicant_id": applicant["id"],
                "school_id": school["id"],
                "recommender_email": "r3@late.edu",
            },
            make_applicant_headers(applicant["id"]),
        ),
        expected_status=201,
    )
    validate_success(
        api.submit_recommendation_request(
            inv["id"], 5, TEST_USERS["platform_admin_headers"]
        ),
        expected_status=200,
    )
    after = validate_success(
        api.get_application(submitted["id"], make_applicant_headers(applicant["id"])),
        expected_status=200,
    )
    assert after["composite_score"] != pytest.approx(initial, abs=0.001)
    # Per pinned per-component round: rec_term = round(round((3+3+5)/3/5*100,2)*0.25,2)
    # rec_score = round(73.333... ,2) = 73.33; rec_term = round(73.33*0.25,2) = round(18.3325,2) = 18.33
    expected = 34.00 + 13.33 + 6.00 + 18.33
    assert after["composite_score"] == pytest.approx(expected, abs=0.001)


def test_fafsa_with_assets_disallowed(api):
    """PRD §3.3: "any FAFSA profile that arrives with a non-zero
    declared_assets_cents (whether on create or on update) is rejected with
    ERR_FAFSA_DISALLOWS_ASSETS."

    Design: Corner/validations/fafsa_with_assets_disallowed
    """
    applicant = create_applicant(email="fafx@u.edu", gpa_unweighted=3.0, residency="IN_STATE")
    payload = create_financial_aid_profile_payload(
        applicant["id"], profile_type="FAFSA",
        household_income_cents=8_000_000, household_size=4,
        declared_assets_cents=100_000,
    )
    res = api.create_financial_aid_profile(payload, make_applicant_headers(applicant["id"]))
    validate_error(res, "ERR_FAFSA_DISALLOWS_ASSETS")
