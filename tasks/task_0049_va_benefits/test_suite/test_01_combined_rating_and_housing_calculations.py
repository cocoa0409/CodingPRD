"""Combined-rating and housing-allowance calculations.

Difficulty queue: dual_variant_calc and combinatorial_formula instances, plus
the calculations-section corner instances they reuse.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    get_success_data,
    TEST_USERS,
    make_veteran_headers,
    create_veteran,
    create_school,
    create_rated_claim,
    create_granted_claim,
    submit_enrollment,
    certify_enrollment,
    update_veteran_payload,
)

ADMIN = TEST_USERS["claims_admin_headers"]
RATER = TEST_USERS["rating_specialist_headers"]
SCO = TEST_USERS["school_official_headers"]


# ─── dual_variant_calc / combined_rating_provisional_vs_finalized ─────────

def test_provisional_rating_set_at_rate_finalized_zero_until_grant(api):
    """PRD §3.4: "What rating does do is refresh the veteran's
    `provisional_combined_rating_pct` using the provisional variant of the
    combined-rating computation, which folds this claim's proposed condition
    ratings in alongside the veteran's already service-connected ratings."
    PRD §3.6: "ratings of 50 and 30 yield 100 × 0.5 = 50 disability with 50
    efficiency remaining, then 50 × 0.3 = 15 more with 35 remaining, for a raw
    total of 65, which snaps to 70 — not the 80 a naive sum would produce."

    Design: Difficulty/dual_variant_calc/combined_rating_provisional_vs_finalized
    """
    vet = create_veteran(total_active_duty_days=1200)
    create_rated_claim(
        vet["id"],
        [{"diagnostic_code": "5260", "proposed_rating_pct": 50},
         {"diagnostic_code": "6260", "proposed_rating_pct": 30}],
    )
    before = validate_success(api.get_veteran(vet["id"], ADMIN), 200)
    assert before["provisional_combined_rating_pct"] == 70, (
        f"provisional should be 70 at RATED, got {before['provisional_combined_rating_pct']}"
    )
    assert before["combined_rating_pct"] == 0, (
        "combined_rating_pct must stay 0 until grant"
    )


def test_combined_rating_finalized_on_grant(api):
    """PRD §3.4: "the veteran's `combined_rating_pct` is recomputed by the
    combined-rating algorithm over the veteran's entire set of service-connected
    conditions."
    PRD §3.6: "ratings of 50 and 30 yield 100 × 0.5 = 50 disability with 50
    efficiency remaining, then 50 × 0.3 = 15 more with 35 remaining, for a raw
    total of 65, which snaps to 70 — not the 80 a naive sum would produce."

    Design: Difficulty/dual_variant_calc/combined_rating_provisional_vs_finalized
    """
    vet = create_veteran(total_active_duty_days=1200)
    create_granted_claim(
        vet["id"],
        [{"diagnostic_code": "5260", "proposed_rating_pct": 50},
         {"diagnostic_code": "6260", "proposed_rating_pct": 30}],
    )
    after = validate_success(api.get_veteran(vet["id"], ADMIN), 200)
    assert after["combined_rating_pct"] == 70, (
        f"combined_rating_pct should be 70 after grant, got {after['combined_rating_pct']}"
    )


# ─── dual_variant_calc / housing_allowance_estimated_vs_finalized ─────────

def test_estimated_mha_uses_tier_at_submission(api):
    """PRD §3.11: "At submission the server computes the enrollment's
    `rate_of_pursuit_pct` and, using the estimated variant of the
    housing-allowance computation, an `estimated_mha_cents` based on the
    veteran's GI Bill tier as of submission."
    PRD §3.11: "a full-time basis is formed by scaling the school's
    `monthly_housing_rate_cents` by the veteran's `gi_bill_tier_pct` as a
    fraction of one hundred and rounding that to whole cents with round-half-up;
    then that basis is scaled by the `rate_of_pursuit_pct` as a fraction of one
    hundred and again rounded to whole cents with round-half-up."

    Design: Difficulty/dual_variant_calc/housing_allowance_estimated_vs_finalized
    """
    # tier 90 at submission (950 days), full-time enrollment (rop=100), rate 200000.
    vet = create_veteran(total_active_duty_days=950)
    school = create_school(monthly_housing_rate_cents=200000)
    enr = submit_enrollment(
        vet["id"], school["id"], credit_hours=12, full_time_credit_hours=12
    )
    assert enr["estimated_mha_cents"] == 180000, (
        f"estimated_mha at tier 90 should be 180000, got {enr['estimated_mha_cents']}"
    )


def test_finalized_mha_uses_tier_at_certification(api):
    """PRD §3.12: "The `monthly_housing_allowance_cents` is computed via the
    finalized housing-allowance variant using the current `gi_bill_tier_pct` and
    the freshly computed `rate_of_pursuit_pct`."
    PRD §3.11: "The estimated variant computed at submission uses the same
    arithmetic but draws the tier and pursuit figures as of submission, so the
    estimate may differ from the finalized figure if the tier changes between
    submission and certification."

    Design: Difficulty/dual_variant_calc/housing_allowance_estimated_vs_finalized
    """
    vet = create_veteran(total_active_duty_days=950)
    school = create_school(monthly_housing_rate_cents=200000)
    enr = submit_enrollment(
        vet["id"], school["id"], credit_hours=12, full_time_credit_hours=12
    )
    # Edit service days up to 1200 -> tier 100 before certification.
    get_success_data(
        api.update_veteran(
            vet["id"],
            update_veteran_payload(vet["version"], total_active_duty_days=1200),
            ADMIN,
        )
    )
    fresh = get_success_data(api.get_enrollment(enr["id"], ADMIN))
    certified = validate_success(
        api.certify_enrollment(
            enr["id"], {"expected_enrollment_version": fresh["version"]}, SCO
        ),
        200,
    )
    assert certified["estimated_mha_cents"] == 180000, (
        "estimated stays at the tier-90 submission figure"
    )
    assert certified["monthly_housing_allowance_cents"] == 200000, (
        f"finalized MHA at tier 100 should be 200000, got "
        f"{certified['monthly_housing_allowance_cents']}"
    )


# ─── combinatorial_formula / combined_rating_bilateral_nonlinear ──────────
# Mode (a): non-linear nested product over >=3 ratings.

def test_combined_rating_nonlinear_three_ratings(api):
    """PRD §2.8: "A 50 percent rating followed by a 30 percent rating does not
    yield 80 percent; it yields a smaller figure because each successive
    disability is taken only from the *efficiency that remains* after the prior
    ones."
    PRD §3.6: "begin with a remaining efficiency of 100; for each rating in turn,
    the disability it contributes equals the remaining efficiency multiplied by
    that rating expressed as a fraction of one hundred, and the remaining
    efficiency is then reduced by exactly that contributed amount."

    Design: Difficulty/combinatorial_formula/combined_rating_bilateral_nonlinear
    """
    vet = create_veteran(total_active_duty_days=1200)
    create_granted_claim(
        vet["id"],
        [{"diagnostic_code": "5237", "proposed_rating_pct": 70},
         {"diagnostic_code": "5260", "proposed_rating_pct": 50},
         {"diagnostic_code": "6260", "proposed_rating_pct": 30}],
    )
    after = validate_success(api.get_veteran(vet["id"], ADMIN), 200)
    assert after["combined_rating_pct"] == 90, (
        f"ratings [70,50,30] combine to 90, not 150 capped, got "
        f"{after['combined_rating_pct']}"
    )


def test_combined_rating_not_a_linear_sum(api):
    """PRD §2.8: "The system therefore never sums rating percentages."
    PRD §3.6: "After all ratings are consumed, the raw total disability is 100
    minus whatever efficiency remains."

    Design: Difficulty/combinatorial_formula/combined_rating_bilateral_nonlinear
    """
    vet = create_veteran(total_active_duty_days=1200)
    create_granted_claim(
        vet["id"],
        [{"diagnostic_code": "5237", "proposed_rating_pct": 70},
         {"diagnostic_code": "5260", "proposed_rating_pct": 50},
         {"diagnostic_code": "6260", "proposed_rating_pct": 30}],
    )
    after = validate_success(api.get_veteran(vet["id"], ADMIN), 200)
    assert after["combined_rating_pct"] != 100, (
        "non-linear combine of [70,50,30] is 90, never the naive-sum cap of 100"
    )
    assert after["combined_rating_pct"] == 90


# ─── combinatorial_formula / housing_allowance_round_then_scale_order ─────
# Mode (b): pinned two-step rounding order.

def test_housing_allowance_round_then_scale_order(api):
    """PRD §3.11: "When it is greater than fifty, the allowance is computed in
    two pinned rounding steps: first, a full-time basis is formed by scaling the
    school's `monthly_housing_rate_cents` by the veteran's `gi_bill_tier_pct` as
    a fraction of one hundred and rounding that to whole cents with
    round-half-up; then that basis is scaled by the `rate_of_pursuit_pct` as a
    fraction of one hundred and again rounded to whole cents with round-half-up."
    PRD §3.11: "The `rate_of_pursuit_pct` is one hundred times the `credit_hours`
    divided by the `full_time_credit_hours`, taken to a whole percentage with
    round-half-up."

    Design: Difficulty/combinatorial_formula/housing_allowance_round_then_scale_order
    """
    # tier 80 (800 days), rate 200000, 9/12 credit hours -> rop 75.
    vet = create_veteran(total_active_duty_days=800)
    school = create_school(monthly_housing_rate_cents=200000)
    enr = submit_enrollment(
        vet["id"], school["id"], credit_hours=9, full_time_credit_hours=12
    )
    certified = validate_success(
        api.certify_enrollment(
            enr["id"], {"expected_enrollment_version": enr["version"]}, SCO
        ),
        200,
    )
    assert certified["rate_of_pursuit_pct"] == 75, (
        f"rop for 9/12 should be 75, got {certified['rate_of_pursuit_pct']}"
    )
    assert certified["monthly_housing_allowance_cents"] == 120000, (
        f"MHA at tier 80, rop 75 should be 120000, got "
        f"{certified['monthly_housing_allowance_cents']}"
    )


def test_rate_of_pursuit_whole_percent_round_half_up(api):
    """PRD §3.11: "The `rate_of_pursuit_pct` is one hundred times the
    `credit_hours` divided by the `full_time_credit_hours`, taken to a whole
    percentage with round-half-up."

    Design: Difficulty/combinatorial_formula/housing_allowance_round_then_scale_order
    """
    vet = create_veteran(total_active_duty_days=800)
    school = create_school(monthly_housing_rate_cents=200000)
    enr = submit_enrollment(
        vet["id"], school["id"], credit_hours=9, full_time_credit_hours=12
    )
    certified = validate_success(
        api.certify_enrollment(
            enr["id"], {"expected_enrollment_version": enr["version"]}, SCO
        ),
        200,
    )
    assert certified["rate_of_pursuit_pct"] == 75


# ─── Corner / calculations ────────────────────────────────────────────────

def test_gi_bill_tier_at_90_day_boundary(api):
    """PRD §3.10: "At least 90 days but fewer than 365 earns 50 percent. Fewer
    than 90 days earns 0 percent, meaning no eligibility."
    PRD §3.10: "Each threshold is inclusive at its lower bound, so a veteran with
    exactly 365 days lands at 60 percent."

    Design: Corner/calculations/gi_bill_tier_at_90_day_boundary
    """
    v89 = create_veteran(total_active_duty_days=89)
    v90 = create_veteran(total_active_duty_days=90)
    assert v89["gi_bill_tier_pct"] == 0, (
        f"89 days -> tier 0, got {v89['gi_bill_tier_pct']}"
    )
    assert v90["gi_bill_tier_pct"] == 50, (
        f"90 days -> tier 50, got {v90['gi_bill_tier_pct']}"
    )


def test_gi_bill_disability_discharge_short_circuit(api):
    """PRD §3.10: "There is a special-case short-circuit: a veteran who was
    `discharged_for_service_disability` and served at least thirty active-duty
    days qualifies for the full 100 percent tier outright, regardless of total
    days."

    Design: Corner/calculations/gi_bill_disability_discharge_short_circuit
    """
    vet = create_veteran(
        total_active_duty_days=40, discharged_for_service_disability=True
    )
    assert vet["gi_bill_tier_pct"] == 100, (
        f"40 days with disability discharge -> tier 100, got {vet['gi_bill_tier_pct']}"
    )


def test_monthly_compensation_alone_at_50(api):
    """PRD §3.8: "50 pays 109,900 cents".
    PRD §3.8: "When the combined rating is strictly below thirty, the monthly
    compensation is exactly that base amount and no dependent additions are made
    at all".

    Design: Corner/calculations/monthly_compensation_alone_at_50
    """
    vet = create_veteran(total_active_duty_days=1095)
    create_granted_claim(vet["id"], [{"proposed_rating_pct": 50}])
    after = validate_success(api.get_veteran(vet["id"], ADMIN), 200)
    assert after["combined_rating_pct"] == 50
    assert after["monthly_compensation_cents"] == 109900, (
        f"single 50% condition, no dependents -> 109900, got "
        f"{after['monthly_compensation_cents']}"
    )


def test_yellow_ribbon_match_school_cap_binds(api):
    """PRD §3.12: "The school's contribution is the smaller of half that
    uncovered amount and the school's `yellow_ribbon_max_contribution_cents`,
    rounded to whole cents with round-half-up; the VA matches the school's
    contribution dollar-for-dollar, so the `yellow_ribbon_match_cents` stored on
    the enrollment equals that rounded school contribution."

    Design: Corner/calculations/yellow_ribbon_match_school_cap_binds
    """
    vet = create_veteran(total_active_duty_days=1095)
    school = create_school(
        is_public=False,
        monthly_housing_rate_cents=200000,
        yellow_ribbon_participant=True,
        yellow_ribbon_max_contribution_cents=300000,
        yellow_ribbon_slots_total=1,
    )
    enr = submit_enrollment(
        vet["id"], school["id"],
        credit_hours=12, full_time_credit_hours=12,
        tuition_charged_cents=800000, requests_yellow_ribbon=True,
    )
    certified = validate_success(
        api.certify_enrollment(
            enr["id"], {"expected_enrollment_version": enr["version"]}, SCO
        ),
        200,
    )
    # half of 800000 = 400000 > cap 300000 -> cap binds.
    assert certified["yellow_ribbon_match_cents"] == 300000, (
        f"YR match should bind to cap 300000, got {certified['yellow_ribbon_match_cents']}"
    )


def test_yellow_ribbon_not_eligible_below_100_tier(api):
    """PRD §3.12: "Only a veteran at the full 100 percent GI Bill tier is Yellow
    Ribbon eligible; if the veteran's `gi_bill_tier_pct` is anything other than
    100, the match is 0."
    PRD §3.11: "a full-time basis is formed by scaling the school's
    `monthly_housing_rate_cents` by the veteran's `gi_bill_tier_pct` as a
    fraction of one hundred and rounding that to whole cents with round-half-up;
    then that basis is scaled by the `rate_of_pursuit_pct` as a fraction of one
    hundred and again rounded to whole cents with round-half-up."

    Design: Corner/calculations/yellow_ribbon_not_eligible_below_100_tier
    """
    vet = create_veteran(total_active_duty_days=800)  # tier 80
    school = create_school(
        is_public=False,
        monthly_housing_rate_cents=200000,
        yellow_ribbon_participant=True,
        yellow_ribbon_max_contribution_cents=300000,
        yellow_ribbon_slots_total=1,
    )
    enr = submit_enrollment(
        vet["id"], school["id"],
        credit_hours=12, full_time_credit_hours=12,
        tuition_charged_cents=400000, requests_yellow_ribbon=True,
    )
    certified = validate_success(
        api.certify_enrollment(
            enr["id"], {"expected_enrollment_version": enr["version"]}, SCO
        ),
        200,
    )
    assert certified["yellow_ribbon_match_cents"] == 0, (
        "tier-80 veteran is not YR eligible -> match 0"
    )
    # MHA: tier 80, full-time (rop 100) -> 160000.
    assert certified["monthly_housing_allowance_cents"] == 160000, (
        f"MHA at tier 80, rop 100 should be 160000, got "
        f"{certified['monthly_housing_allowance_cents']}"
    )
