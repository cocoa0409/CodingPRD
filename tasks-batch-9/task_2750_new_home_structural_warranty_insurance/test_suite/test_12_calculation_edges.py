"""Calculation edges: obligation boundaries, anniversary arithmetic, premium
band constants, risk-score caps and clamps, the loss-ratio population, the
deductible clamp and the two independent half-up rounding sites of the
settlement waterfall.

Every test builds its world from scratch against a freshly restarted server
with an empty database, so no test depends on another's residue.
"""

import pytest

from test_helpers import (
    ADJUSTER_USER_ID,
    SECOND_ADJUSTER_USER_ID,
    INSURER_PERIOD_INSTANT,
    assert_claim,
    assert_claim_money_conserved,
    assert_calendar_date,
    assert_coverage_capacity_conserved,
    assert_coverage_term,
    assert_loss_monitor,
    assert_money_cents,
    assert_policy,
    authorize_reserve,
    adjudicate_claim,
    create_approved_builder,
    create_builder_under_review,
    enroll_policy,
    file_claim,
    find_term,
    investigate_claim,
    pay_claim,
    read_claim,
    read_coverage_term,
    read_coverage_terms,
    read_loss_monitor,
    read_policy,
    route_claim,
    set_clock,
    setup_active_policy,
    setup_approved_builder_and_owner,
    setup_insurer_arm_claim,
    validate_paginated,
)


# ==========================================================================
# Table 3 Calculations / the obligation boundary date
# ==========================================================================
def test_the_obligation_boundary_date_is_builder_obligated_and_the_next_day_is_insurer_backed():
    """The obligation boundary is a closed upper bound on the builder's arm.

    PRD Section 3.6: "When the `reported_date` is on or before the policy's
    `builder_obligation_end_date`, the `obligor` is `BUILDER`; when it falls
    after that date, the `obligor` is `INSURER`."

    PRD Section 3.6: "a claim reported on exactly the last day of the
    obligation period belongs to the builder, and only the following day
    crosses over to the carrier."

    PRD Section 3.3: "The same anniversary arithmetic, applied with the
    builder's `obligation_period_years` of 2, yields
    `builder_obligation_end_date` on the policy — which is therefore the same
    calendar date as the systems term's `end_date`, and is the boundary that
    decides who answers for a claim."

    Design: Corner/Table 3 Calculations/the_obligation_boundary_date_is_builder_obligated_and_the_next_day_is_insurer_backed
    """
    scenario = setup_active_policy()
    policy = scenario["policy"]
    assert policy["builder_obligation_end_date"] == "2028-08-14"

    # The boundary day itself.
    set_clock("2028-08-14T09:00:00Z")
    claim_a = file_claim(
        policy["id"], scenario["homeowner"]["id"],
        coverage_type="STRUCTURAL", defect_category="WATER_INTRUSION",
        claimed_amount_cents=1_000_000,
    )
    assert claim_a["reported_date"] == "2028-08-14"
    assert claim_a["obligor"] == "BUILDER"

    # One day later.
    set_clock("2028-08-15T09:00:00Z")
    claim_b = file_claim(
        policy["id"], scenario["homeowner"]["id"],
        coverage_type="STRUCTURAL", defect_category="WATER_INTRUSION",
        claimed_amount_cents=1_000_000,
    )
    assert claim_b["reported_date"] == "2028-08-15"
    assert claim_b["obligor"] == "INSURER"

    # Both resolve to the same in-force structural BASE term, so nothing but
    # the reported date differs between the two rows.
    structural_term = scenario["structural_term"]
    assert claim_a["coverage_term_id"] == structural_term["id"]
    assert claim_b["coverage_term_id"] == structural_term["id"]

    for claim in (claim_a, claim_b):
        assert_claim(claim)
        assert claim["status"] == "SUBMITTED"
        assert claim["reserve_cents"] == 0
        assert claim["net_payable_cents"] == 0
        assert_claim_money_conserved(claim)


def test_the_epoch_sweep_elapses_the_systems_term_only_once_the_clock_passes_its_end_date():
    """The systems term shares the obligation boundary date, so it survives the
    sweep on that date and elapses on the next one.

    PRD Section 3.4: "Every coverage term whose `status` is `OPEN` and whose
    `end_date` falls before the new clock date transitions to the terminal
    `ELAPSED`."

    PRD Section 3.4: "The response reports the clock's new value as
    `current_utc` together with `expired_policy_count`, the number of policies
    moved to `EXPIRED`, and `elapsed_term_count`, the number of terms moved to
    `ELAPSED`."

    Design: Corner/Table 3 Calculations/the_obligation_boundary_date_is_builder_obligated_and_the_next_day_is_insurer_backed
    """
    scenario = setup_active_policy()
    assert scenario["workmanship_term"]["end_date"] == "2027-08-14"
    assert scenario["systems_term"]["end_date"] == "2028-08-14"

    # Only the workmanship term, which ended a year earlier, is swept.
    first_sweep = set_clock("2028-08-14T09:00:00Z")
    assert first_sweep["elapsed_term_count"] == 1
    assert read_coverage_term(scenario["workmanship_term"]["id"])["status"] == "ELAPSED"
    assert read_coverage_term(scenario["systems_term"]["id"])["status"] == "OPEN"

    # The systems term's end_date now falls before the clock date.
    second_sweep = set_clock("2028-08-15T09:00:00Z")
    assert second_sweep["elapsed_term_count"] == 1
    assert read_coverage_term(scenario["systems_term"]["id"])["status"] == "ELAPSED"
    assert read_coverage_term(scenario["structural_term"]["id"])["status"] == "OPEN"
    assert read_policy(scenario["policy"]["id"])["coverage_status"] == "ACTIVE"


# ==========================================================================
# Table 3 Calculations / the leap-day anniversary special case
# ==========================================================================
def test_a_leap_day_closing_rolls_every_base_term_end_back_to_february_27():
    """A 29 February closing lands every base term end on 27 February, because
    the month-end fallback happens before the one-day step back.

    PRD Section 3.3: "Their `end_date` values are derived by an anniversary
    rule: take the closing date, advance the year by the term's length in years
    while keeping the same month and day, and then step back one day."

    PRD Section 3.3: "The anniversary rule has exactly one special case: when
    the closing date is 29 February and the target year is not a leap year, the
    anniversary falls back to the last day of that month in the target year
    before the one-day step back is applied."

    PRD Section 3.3: "The same anniversary arithmetic, applied with the
    builder's `obligation_period_years` of 2, yields
    `builder_obligation_end_date` on the policy — which is therefore the same
    calendar date as the systems term's `end_date`, and is the boundary that
    decides who answers for a claim."

    Design: Corner/Table 3 Calculations/a_leap_day_closing_rolls_every_base_term_end_back_to_february_27
    """
    scenario = setup_approved_builder_and_owner(clock="2028-02-29T10:00:00Z")
    policy = enroll_policy(
        scenario["builder"]["id"], scenario["homeowner"]["id"],
        purchase_price_cents=5_000_000, closing_date="2028-02-29",
    )
    assert_policy(policy)
    assert policy["closing_date"] == "2028-02-29"
    assert policy["coverage_start_date"] == "2028-02-29"

    terms = read_coverage_terms(policy["id"])
    workmanship = find_term(terms, "WORKMANSHIP")
    systems = find_term(terms, "SYSTEMS")
    structural = find_term(terms, "STRUCTURAL")

    for term in (workmanship, systems, structural):
        assert_coverage_term(term)
        assert term["term_kind"] == "BASE"
        assert term["start_date"] == "2028-02-29"
        assert_calendar_date(term["end_date"])

    # 2029, 2030 and 2038 are all common years, so each anniversary falls back
    # to 28 February and then steps back one further day.
    assert workmanship["end_date"] == "2029-02-27"
    assert systems["end_date"] == "2030-02-27"
    assert structural["end_date"] == "2038-02-27"

    # The two-year obligation window shares the systems term's end date.
    assert policy["builder_obligation_end_date"] == "2030-02-27"


def test_a_leap_day_enrollment_prices_and_limits_its_three_base_terms():
    """At the purchase-price floor the class C band prices each component
    independently and the percentage limits stay under their caps.

    PRD Section 3.3: "`limit_cents` for the workmanship term is 10 percent of
    the purchase price, rounded half up to whole cents, but never more than
    2,000,000 cents — a twenty-thousand-dollar ceiling."

    PRD Section 3.3: "For the systems term it is 25 percent of the purchase
    price, rounded half up to whole cents, but never more than 6,000,000
    cents."

    PRD Section 3.3: "For the structural term it is the full
    `purchase_price_cents` with no cap at all."

    PRD Section 3.3: "Finally, `premium_cents` is the sum of the three
    independently rounded component integers plus the surcharge, added as exact
    integers."

    Design: Corner/Table 3 Calculations/a_leap_day_closing_rolls_every_base_term_end_back_to_february_27
    """
    scenario = setup_approved_builder_and_owner(clock="2028-02-29T10:00:00Z")
    assert scenario["builder"]["risk_class"] == "C"
    policy = enroll_policy(
        scenario["builder"]["id"], scenario["homeowner"]["id"],
        purchase_price_cents=5_000_000, closing_date="2028-02-29",
    )

    terms = read_coverage_terms(policy["id"])
    assert find_term(terms, "WORKMANSHIP")["limit_cents"] == 500_000
    assert find_term(terms, "SYSTEMS")["limit_cents"] == 1_250_000
    assert find_term(terms, "STRUCTURAL")["limit_cents"] == 5_000_000
    for term in terms:
        assert_coverage_capacity_conserved(term)

    assert policy["premium_component_workmanship_cents"] == 6_390
    assert policy["premium_component_systems_cents"] == 9_585
    assert policy["premium_component_structural_cents"] == 24_406
    assert policy["state_surcharge_cents"] == 4_500
    assert policy["premium_cents"] == 44_881
    assert_money_cents(policy["premium_cents"], "premium_cents")


# ==========================================================================
# Table 3 Calculations / the risk band drives rate and loading together
# ==========================================================================
def test_risk_class_selects_both_the_base_rate_and_the_structural_loading():
    """Moving one band changes every component: the workmanship and systems
    components move with the base rate alone, the structural component with the
    base rate and the loading together.

    PRD Section 3.3: "Each risk band carries a **base rate in basis points** —
    38 for class `A`, 52 for class `B`, 71 for class `C` and 95 for class `D` —
    and a **structural loading multiplier** of 1.00 for class `A`, 1.10 for
    class `B`, 1.25 for class `C` and 1.45 for class `D`."

    PRD Section 3.3: "`premium_component_workmanship_cents` is the purchase
    price multiplied by the workmanship share of 0.18, multiplied by the band's
    base rate in basis points, divided by 10,000, and rounded half up to a
    whole number of cents."

    PRD Section 3.3: "`premium_component_structural_cents` is computed from the
    structural share of 0.55 and then multiplied by the band's structural
    loading, with the rounding to whole cents performed exactly once, **after**
    the loading has been applied — rounding before the loading is wrong, and so
    is skipping the loading."

    Design: Corner/Table 3 Calculations/risk_class_selects_both_the_base_rate_and_the_structural_loading_at_enrollment
    """
    scenario = setup_approved_builder_and_owner()
    class_c_builder = scenario["builder"]
    assert float(class_c_builder["risk_score"]) == pytest.approx(45.00, abs=1e-9)
    assert class_c_builder["risk_class"] == "C"

    class_b_builder = create_approved_builder(
        company_name="Marlowe Residential", financial_strength_tier="TIER_2",
    )
    assert float(class_b_builder["risk_score"]) == pytest.approx(37.00, abs=1e-9)
    assert class_b_builder["risk_class"] == "B"

    homeowner_id = scenario["homeowner"]["id"]
    class_c_policy = enroll_policy(
        class_c_builder["id"], homeowner_id,
        purchase_price_cents=5_000_000, street_address="12 Juniper Way",
    )
    class_b_policy = enroll_policy(
        class_b_builder["id"], homeowner_id,
        purchase_price_cents=5_000_000, street_address="14 Juniper Way",
    )

    assert class_c_policy["risk_class_at_enrollment"] == "C"
    assert class_c_policy["premium_component_workmanship_cents"] == 6_390
    assert class_c_policy["premium_component_systems_cents"] == 9_585
    assert class_c_policy["premium_component_structural_cents"] == 24_406
    assert class_c_policy["premium_cents"] == 44_881

    assert class_b_policy["risk_class_at_enrollment"] == "B"
    assert class_b_policy["premium_component_workmanship_cents"] == 4_680
    assert class_b_policy["premium_component_systems_cents"] == 7_020
    assert class_b_policy["premium_component_structural_cents"] == 15_730
    assert class_b_policy["premium_cents"] == 31_930

    # Both homes sit in TX, so the surcharge is not what separates them.
    assert class_c_policy["state_surcharge_cents"] == 4_500
    assert class_b_policy["state_surcharge_cents"] == 4_500


def test_only_the_state_surcharge_changes_when_the_home_state_changes():
    """The surcharge is selected by the home's own state and is added as an
    exact integer, leaving the three rated components untouched.

    PRD Section 3.3: "`state_surcharge_cents` is a flat charge selected by the
    home's own `state_code`: 4,500 cents in `TX`, 9,500 cents in `FL`, 2,500
    cents in `CO`, nothing at all in `AZ`, and 1,500 cents in `NC`."

    PRD Section 3.3: "Finally, `premium_cents` is the sum of the three
    independently rounded component integers plus the surcharge, added as exact
    integers."

    Design: Corner/Table 3 Calculations/risk_class_selects_both_the_base_rate_and_the_structural_loading_at_enrollment
    """
    scenario = setup_approved_builder_and_owner()
    builder_id = scenario["builder"]["id"]
    homeowner_id = scenario["homeowner"]["id"]

    texas_policy = enroll_policy(
        builder_id, homeowner_id, purchase_price_cents=5_000_000,
        state_code="TX", street_address="12 Juniper Way",
    )
    colorado_policy = enroll_policy(
        builder_id, homeowner_id, purchase_price_cents=5_000_000,
        state_code="CO", street_address="480 Aspen Grove Rd",
    )

    for field in ("premium_component_workmanship_cents",
                  "premium_component_systems_cents",
                  "premium_component_structural_cents"):
        assert texas_policy[field] == colorado_policy[field]

    assert colorado_policy["premium_component_workmanship_cents"] == 6_390
    assert colorado_policy["premium_component_systems_cents"] == 9_585
    assert colorado_policy["premium_component_structural_cents"] == 24_406
    assert colorado_policy["state_surcharge_cents"] == 2_500
    assert colorado_policy["premium_cents"] == 42_881
    assert texas_policy["premium_cents"] == 44_881


# ==========================================================================
# Table 3 Calculations / the risk-score caps and the 0..100 clamp
# ==========================================================================
def test_capped_volume_and_tenure_inputs_plateau_the_risk_score():
    """Once volume and tenure are past their caps, further inputs move nothing:
    125 homes and ten years score exactly the same as 500 homes and fifty
    years, while a file just under both caps scores lower.

    PRD Section 3.1: "Compute a **volume factor** by dividing the effective home
    volume by 25 and discarding any fractional part, multiplying that whole
    number of 25-home buckets by 8 points per bucket, and capping the result at
    40 points; then add one quarter of that capped volume factor to the running
    total, so a builder closing 300 homes contributes the maximum, which is 40
    capped points weighted down to 10 points of score."

    PRD Section 3.1: "Subtract a **tenure credit** of 2 points for each full
    year in business, capped at 20 points, so anything past a decade of
    operation earns the same credit."

    PRD Section 3.1: "Both intake transitions write `risk_score` and
    `risk_class` and set `risk_basis` to `INITIAL_UNDERWRITING`, and both
    advance the builder's `version` by 1."

    Design: Corner/Table 3 Calculations/capped_volume_and_tenure_inputs_plateau_the_risk_score_and_the_clamp_holds_at_100
    """
    at_the_caps = create_builder_under_review(
        company_name="Ridgeline Builders", years_in_business=10,
        homes_closed_last_year=125, claims_history_score=30,
        financial_strength_tier="TIER_1",
    )
    far_past_the_caps = create_builder_under_review(
        company_name="Summit Volume Homes", years_in_business=50,
        homes_closed_last_year=500, claims_history_score=30,
        financial_strength_tier="TIER_1",
    )
    just_under_the_caps = create_builder_under_review(
        company_name="Foothill Craft Homes", years_in_business=9,
        homes_closed_last_year=75, claims_history_score=30,
        financial_strength_tier="TIER_1",
    )

    # 50 + 35 history - 20 tenure - 15 tier + 10 weighted volume.
    assert float(at_the_caps["risk_score"]) == pytest.approx(60.00, abs=1e-9)
    assert float(far_past_the_caps["risk_score"]) == pytest.approx(60.00, abs=1e-9)
    # Three whole buckets weighted to 6, and 18 points of tenure credit.
    assert float(just_under_the_caps["risk_score"]) == pytest.approx(58.00, abs=1e-9)

    for builder in (at_the_caps, far_past_the_caps, just_under_the_caps):
        assert builder["risk_class"] == "C"
        assert builder["risk_basis"] == "INITIAL_UNDERWRITING"
        assert builder["underwriting_status"] == "UNDER_REVIEW"


def test_the_risk_score_clamp_holds_at_one_hundred_and_bands_into_class_d(
    api, underwriting_officer_headers
):
    """An input set whose raw arithmetic overshoots 100 is clamped to exactly
    100.00, which bands into class D and is visible through the risk_class
    filter alongside the class C files.

    PRD Section 3.1: "Clamp the resulting figure so that it is never below 0 and
    never above 100, and round it half up to two decimal places; that is
    `risk_score`."

    PRD Section 3.1: "`risk_class` is then a band on the rounded score, with
    each band's lower bound inclusive and its upper bound exclusive: class `A`
    for a score below 25.00, class `B` for a score from 25.00 up to but not
    including 45.00, class `C` for a score from 45.00 up to but not including
    65.00, and class `D` for a score of 65.00 or higher."

    PRD Section 2.6: "Builder files are filterable by `underwriting_status`,
    `risk_class` and `monitoring_posture`"

    Design: Corner/Table 3 Calculations/capped_volume_and_tenure_inputs_plateau_the_risk_score_and_the_clamp_holds_at_100
    """
    for overrides in (
        {"company_name": "Ridgeline Builders", "years_in_business": 10,
         "homes_closed_last_year": 125},
        {"company_name": "Summit Volume Homes", "years_in_business": 50,
         "homes_closed_last_year": 500},
        {"company_name": "Foothill Craft Homes", "years_in_business": 9,
         "homes_closed_last_year": 75},
    ):
        create_builder_under_review(
            claims_history_score=30, financial_strength_tier="TIER_1", **overrides
        )

    # 50 + 50 history + 10 weighted volume - 0 tenure - 0 tier = 110, clamped.
    clamped = create_builder_under_review(
        company_name="Hazard Homes LLC", years_in_business=0,
        homes_closed_last_year=500, claims_history_score=0,
        financial_strength_tier="TIER_3",
    )
    assert float(clamped["risk_score"]) == pytest.approx(100.00, abs=1e-9)
    assert clamped["risk_class"] == "D"
    assert clamped["risk_basis"] == "INITIAL_UNDERWRITING"

    class_c_rows, class_c_meta = validate_paginated(
        api.list_builders(underwriting_officer_headers, {"risk_class": "C"})
    )
    assert class_c_meta["total_count"] == 3
    assert all(row["risk_class"] == "C" for row in class_c_rows)

    class_d_rows, class_d_meta = validate_paginated(
        api.list_builders(underwriting_officer_headers, {"risk_class": "D"})
    )
    assert class_d_meta["total_count"] == 1
    assert class_d_rows[0]["id"] == clamped["id"]


# ==========================================================================
# Table 3 Calculations / who is in the loss-ratio numerator
# ==========================================================================
def test_the_loss_ratio_numerator_excludes_builder_obligated_claims_and_keeps_terminal_ones():
    """Two identically sized claims on one home: the builder-obligated one never
    enters the numerator, and the insurer-backed one stays in it after it closes
    paid, because closing moves the money from reserve to paid without dropping
    the claim.

    PRD Section 3.2: "The numerator, `incurred_loss_cents`, is the sum of
    `reserve_cents` plus `paid_cents` over every claim filed against any policy
    of this builder whose `obligor` is `INSURER`, with **no claim-status filter
    whatsoever** — closed claims count exactly as open ones do."

    PRD Section 3.2: "Claims still obligated to the builder are excluded
    outright, which is why flipping a claim's `obligor` to `INSURER` raises the
    figure."

    PRD Section 3.2: "The denominator, `earned_premium_cents`, is the sum of
    `premium_cents` over the builder's policies that are **both** in a coverage
    state of `ACTIVE` or `EXPIRED` **and** in a premium state of `PAID`;
    policies still in `PENDING_ENROLLMENT` and policies that were `VOIDED` are
    excluded, and so is an in-force policy whose premium was never paid."

    PRD Section 3.2: "`open_claim_count` is the number of claims on any policy
    of this builder whose `status` is not one of the six terminal claim states,
    namely `CLOSED_REPAIRED`, `CLOSED_PAID`, `CLOSED_SETTLED`, `CLOSED_AWARDED`,
    `CLOSED_DENIED_FINAL` and `SUSPENDED_NO_LIMIT`."

    PRD Section 3.8: "It closes the claim when the claim is `APPROVED` and its
    `paid_cents` after this payment equals its `net_payable_cents`, advancing
    `APPROVED → CLOSED_PAID`."

    Design: Corner/Table 3 Calculations/the_loss_ratio_numerator_excludes_builder_obligated_claims_and_keeps_terminal_ones
    """
    scenario = setup_active_policy()
    policy_id = scenario["policy"]["id"]
    owner_id = scenario["homeowner"]["id"]
    builder_id = scenario["builder"]["id"]
    assert scenario["policy"]["premium_cents"] == 363_894

    # The builder's arm: reported inside the obligation period.
    builder_arm = file_claim(policy_id, owner_id, claimed_amount_cents=2_187_500)
    investigate_claim(builder_arm["id"], 0.80)
    route_claim(builder_arm["id"])
    builder_arm = read_claim(builder_arm["id"])
    assert builder_arm["obligor"] == "BUILDER"
    assert builder_arm["status"] == "BUILDER_OBLIGATION_NOTICE"
    assert builder_arm["gross_adjusted_cents"] == 1_750_000
    assert builder_arm["deductible_applied_cents"] == 0
    assert builder_arm["net_payable_cents"] == 1_610_000

    # The carrier's arm: the same claimed amount and ratio, reported later.
    set_clock(INSURER_PERIOD_INSTANT)
    insurer_arm = file_claim(policy_id, owner_id, claimed_amount_cents=2_187_500)
    investigate_claim(insurer_arm["id"], 0.80)
    route_claim(insurer_arm["id"])
    insurer_arm = read_claim(insurer_arm["id"])
    assert insurer_arm["obligor"] == "INSURER"
    assert insurer_arm["status"] == "INSURER_ADJUDICATION"
    assert insurer_arm["deductible_applied_cents"] == 100_000
    assert insurer_arm["net_payable_cents"] == 1_518_000
    assert insurer_arm["reserve_cents"] == 1_518_000

    # Only the carrier's claim is in the numerator.
    before = read_loss_monitor(builder_id)
    assert_loss_monitor(before)
    assert before["earned_premium_cents"] == 363_894
    assert before["incurred_loss_cents"] == 1_518_000
    assert float(before["loss_ratio"]) == pytest.approx(4.1715, abs=1e-9)
    assert before["monitoring_posture"] == "FROZEN"
    assert before["open_claim_count"] == 2

    # Close the carrier's claim paid in full.
    adjudicate_claim(insurer_arm["id"], "APPROVE", adjuster_user_id=ADJUSTER_USER_ID)
    pay_claim(insurer_arm["id"], 1_518_000,
              adjuster_user_id=SECOND_ADJUSTER_USER_ID)
    insurer_arm = read_claim(insurer_arm["id"])
    assert insurer_arm["status"] == "CLOSED_PAID"
    assert insurer_arm["paid_cents"] == 1_518_000
    assert insurer_arm["reserve_cents"] == 0
    assert insurer_arm["incurred_authorized_cents"] == 1_518_000
    assert_claim_money_conserved(insurer_arm)

    # The money simply moved from reserve to paid: the numerator is unchanged
    # even though the claim is now terminal and out of the open count.
    after = read_loss_monitor(builder_id)
    assert after["incurred_loss_cents"] == 1_518_000
    assert float(after["loss_ratio"]) == pytest.approx(4.1715, abs=1e-9)
    assert after["monitoring_posture"] == "FROZEN"
    assert after["open_claim_count"] == 1


# ==========================================================================
# Table 3 Calculations / the WATCH floor on the rounded ratio
# ==========================================================================
def test_the_watch_floor_is_not_reached_one_cent_below_the_rounded_ratio():
    """A reserve of 236,512 cents against 363,894 cents of earned premium rounds
    to 0.6499, one ten-thousandth below the WATCH floor, so the posture stays
    OPEN.

    PRD Section 2.5: "A builder's `loss_ratio` carries 4 decimal places, and the
    band comparison that assigns `monitoring_posture` is likewise made against
    the already-rounded ratio."

    PRD Section 3.2: "`monitoring_posture` is a band on the rounded ratio with
    lower bounds inclusive: `OPEN` below 0.6500, `WATCH` from 0.6500 up to but
    not including 0.9000, `RESTRICTED` from 0.9000 up to but not including
    1.2000, and `FROZEN` at 1.2000 or above."

    PRD Section 3.8: "On success the claim's `reserve_cents` becomes exactly the
    authorised `amount_cents`, and its `incurred_authorized_cents` becomes the
    sum of its existing `paid_cents`, its existing `released_cents` and that same
    authorised amount."

    Design: Corner/Table 3 Calculations/the_watch_floor_is_reached_at_the_exact_rounded_ratio_and_not_one_cent_below
    """
    scenario = setup_insurer_arm_claim(claimed_amount_cents=500_000,
                                       substantiation_ratio=1.00)
    claim = scenario["claim"]
    builder_id = scenario["builder"]["id"]

    assert claim["gross_adjusted_cents"] == 500_000
    assert claim["deductible_applied_cents"] == 100_000
    assert claim["betterment_cents"] == 0
    assert claim["net_payable_cents"] == 400_000
    assert claim["reserve_cents"] == 400_000

    opening = read_loss_monitor(builder_id)
    assert opening["earned_premium_cents"] == 363_894
    assert float(opening["loss_ratio"]) == pytest.approx(1.0992, abs=1e-9)
    assert opening["monitoring_posture"] == "RESTRICTED"

    # Create, investigate, route: three mutations, so version 3.
    assert claim["version"] == 3
    entry = authorize_reserve(claim["id"], 236_512, entry_type="ADJUSTMENT",
                              expected_claim_version=3)
    assert entry["balance_after_reserve_cents"] == 236_512
    assert entry["balance_after_paid_cents"] == 0

    below = read_loss_monitor(builder_id)
    assert below["incurred_loss_cents"] == 236_512
    assert float(below["loss_ratio"]) == pytest.approx(0.6499, abs=1e-9)
    assert below["monitoring_posture"] == "OPEN"


def test_the_watch_floor_is_reached_at_the_exact_rounded_ratio():
    """One cent more takes the same quotient over the rounding midpoint to
    0.6500, and the inclusive lower bound puts the builder in WATCH.

    PRD Section 2.5: "Rates, ratios and scores are decimal numbers with a pinned
    number of decimal places, and every rounding in this document is **round
    half up** — a value exactly at the midpoint rounds away from zero, so 0.125
    at two decimal places becomes 0.13."

    PRD Section 3.2: "The ratio itself is the numerator divided by the
    denominator, rounded half up to four decimal places"

    PRD Section 3.2: "`monitoring_posture` is a band on the rounded ratio with
    lower bounds inclusive: `OPEN` below 0.6500, `WATCH` from 0.6500 up to but
    not including 0.9000, `RESTRICTED` from 0.9000 up to but not including
    1.2000, and `FROZEN` at 1.2000 or above."

    Design: Corner/Table 3 Calculations/the_watch_floor_is_reached_at_the_exact_rounded_ratio_and_not_one_cent_below
    """
    scenario = setup_insurer_arm_claim(claimed_amount_cents=500_000,
                                       substantiation_ratio=1.00)
    claim = scenario["claim"]
    builder_id = scenario["builder"]["id"]
    assert claim["version"] == 3

    # One cent below the floor first, so the two ratios are compared on one
    # builder whose earned premium never changes.
    authorize_reserve(claim["id"], 236_512, entry_type="ADJUSTMENT",
                      expected_claim_version=3)
    assert read_loss_monitor(builder_id)["monitoring_posture"] == "OPEN"

    claim = read_claim(claim["id"])
    assert claim["version"] == 4
    entry = authorize_reserve(claim["id"], 236_513, entry_type="ADJUSTMENT",
                              expected_claim_version=4)
    assert entry["balance_after_reserve_cents"] == 236_513

    at_the_floor = read_loss_monitor(builder_id)
    assert at_the_floor["incurred_loss_cents"] == 236_513
    assert float(at_the_floor["loss_ratio"]) == pytest.approx(0.6500, abs=1e-9)
    assert at_the_floor["monitoring_posture"] == "WATCH"


# ==========================================================================
# Table 3 Calculations / the deductible clamp floors net payable at zero
# ==========================================================================
def test_the_standard_deductible_is_clamped_to_a_small_substantiated_loss():
    """A substantiated loss exactly equal to the 100,000-cent schedule is fully
    absorbed: the deductible applied is the loss, not the schedule, and net
    payable floors at zero instead of going negative.

    PRD Section 3.7: "`deductible_applied_cents` is 0 under the
    builder-obligation variant. Under the insurer-backed variant it is the
    smaller of the scheduled deductible and `gross_adjusted_cents` — a small
    substantiated loss is fully absorbed by the deductible rather than producing
    a negative figure."

    PRD Section 3.7: "The deductible schedule is selected by the claim's
    `designated_structural` flag: 250,000 cents when the flag is true, and
    100,000 cents when it is false."

    PRD Section 3.7: "The betterment percentage is selected from that
    **provisional net, before betterment is subtracted**: nothing at all when the
    provisional net is below 500,000 cents, 5 percent when it is from 500,000
    cents up to but not including 1,500,000 cents, and 8 percent when it is
    1,500,000 cents or more."

    Design: Corner/Table 3 Calculations/the_deductible_is_clamped_to_the_substantiated_loss_so_net_payable_floors_at_zero
    """
    scenario = setup_insurer_arm_claim(claimed_amount_cents=100_000,
                                       substantiation_ratio=1.00)
    claim = scenario["claim"]

    assert claim["obligor"] == "INSURER"
    assert claim["status"] == "INSURER_ADJUDICATION"
    assert claim["designated_structural"] is False
    assert claim["gross_adjusted_cents"] == 100_000
    assert claim["deductible_applied_cents"] == 100_000
    assert claim["betterment_cents"] == 0
    assert claim["net_payable_cents"] == 0
    assert claim["reserve_cents"] == 0
    assert_claim_money_conserved(claim)

    monitor = read_loss_monitor(scenario["builder"]["id"])
    assert monitor["incurred_loss_cents"] == 0
    assert float(monitor["loss_ratio"]) == pytest.approx(0.0000, abs=1e-9)
    assert monitor["monitoring_posture"] == "OPEN"


def test_the_structural_deductible_is_clamped_to_the_substantiated_loss():
    """A designated structural claim of 200,000 cents draws the 250,000-cent
    schedule, and the clamp takes the applied deductible down to the loss itself.

    PRD Section 3.7: "Under the insurer-backed variant it is the smaller of the
    scheduled deductible and `gross_adjusted_cents` — a small substantiated loss
    is fully absorbed by the deductible rather than producing a negative figure."

    PRD Section 3.7: "The report's own `designated_structural` verdict requires
    **all three** of the following to hold at once: `load_bearing_affected` is
    true; at least one entry in `affected_elements` is a load-bearing element,
    meaning one of `FOOTING`, `FOUNDATION_WALL`, `BEAM`, `LOAD_BEARING_WALL`,
    `ROOF_TRUSS` or `SLAB`; and the `deflection_ratio` is 0.0033 or greater, the
    threshold value itself qualifying."

    PRD Section 3.7: "The deductible schedule is selected by the claim's
    `designated_structural` flag: 250,000 cents when the flag is true, and
    100,000 cents when it is false."

    Design: Corner/Table 3 Calculations/the_deductible_is_clamped_to_the_substantiated_loss_so_net_payable_floors_at_zero
    """
    scenario = setup_insurer_arm_claim(
        claimed_amount_cents=200_000, substantiation_ratio=1.00,
        assessments=[{
            "affected_elements": ["FOUNDATION_WALL"],
            "deflection_ratio": 0.0040,
            "load_bearing_affected": True,
        }],
    )
    claim = scenario["claim"]

    assert claim["obligor"] == "INSURER"
    assert claim["status"] == "INSURER_ADJUDICATION"
    assert claim["designated_structural"] is True
    assert claim["gross_adjusted_cents"] == 200_000
    # The clamp bites: 200,000 rather than the 250,000-cent structural schedule.
    assert claim["deductible_applied_cents"] == 200_000
    assert claim["betterment_cents"] == 0
    assert claim["net_payable_cents"] == 0
    assert claim["reserve_cents"] == 0
    assert_claim_money_conserved(claim)


# ==========================================================================
# Table 3 Calculations / half-up rounding at two independent waterfall steps
# ==========================================================================
def test_half_up_rounding_at_step_six_turns_a_half_cent_betterment_upward():
    """The betterment on a provisional net of 1,000,010 cents is exactly
    50,000.5 cents, which rounds away from zero to 50,001 and leaves 950,009.

    PRD Section 2.5: "Rates, ratios and scores are decimal numbers with a pinned
    number of decimal places, and every rounding in this document is **round
    half up** — a value exactly at the midpoint rounds away from zero, so 0.125
    at two decimal places becomes 0.13."

    PRD Section 3.7: "`betterment_cents` is the provisional net multiplied by
    that percentage, rounded half up to whole cents."

    PRD Section 3.7: "The betterment percentage is selected from that
    **provisional net, before betterment is subtracted**: nothing at all when the
    provisional net is below 500,000 cents, 5 percent when it is from 500,000
    cents up to but not including 1,500,000 cents, and 8 percent when it is
    1,500,000 cents or more."

    Design: Corner/Table 3 Calculations/half_up_rounding_is_applied_at_step_one_and_step_six_independently
    """
    scenario = setup_insurer_arm_claim(claimed_amount_cents=1_100_010,
                                       substantiation_ratio=1.00)
    claim = scenario["claim"]

    # Step 1 is exact here, so only step 6 does any rounding.
    assert claim["gross_adjusted_cents"] == 1_100_010
    assert claim["deductible_applied_cents"] == 100_000
    assert claim["betterment_cents"] == 50_001
    assert claim["net_payable_cents"] == 950_009
    assert claim["reserve_cents"] == 950_009
    assert claim["incurred_authorized_cents"] == 950_009
    assert_claim_money_conserved(claim)


def test_half_up_rounding_at_step_one_turns_a_half_cent_gross_upward():
    """Half of 1,100,011 cents is exactly 550,005.5, which rounds up to 550,006;
    the provisional net that follows is below the betterment floor, so step 6
    rounds nothing at all.

    PRD Section 3.7: "`gross_adjusted_cents` is the `claimed_amount_cents`
    multiplied by the `substantiation_ratio`, rounded half up to whole cents."

    PRD Section 2.5: "Rates, ratios and scores are decimal numbers with a pinned
    number of decimal places, and every rounding in this document is **round
    half up** — a value exactly at the midpoint rounds away from zero, so 0.125
    at two decimal places becomes 0.13."

    PRD Section 3.7: "The betterment percentage is selected from that
    **provisional net, before betterment is subtracted**: nothing at all when the
    provisional net is below 500,000 cents, 5 percent when it is from 500,000
    cents up to but not including 1,500,000 cents, and 8 percent when it is
    1,500,000 cents or more."

    Design: Corner/Table 3 Calculations/half_up_rounding_is_applied_at_step_one_and_step_six_independently
    """
    scenario = setup_insurer_arm_claim(claimed_amount_cents=1_100_011,
                                       substantiation_ratio=0.50)
    claim = scenario["claim"]

    assert float(claim["substantiation_ratio"]) == pytest.approx(0.50, abs=1e-9)
    assert claim["gross_adjusted_cents"] == 550_006
    assert claim["deductible_applied_cents"] == 100_000
    # A provisional net of 450,006 cents sits below the 500,000-cent floor.
    assert claim["betterment_cents"] == 0
    assert claim["net_payable_cents"] == 450_006
    assert claim["reserve_cents"] == 450_006
    assert_claim_money_conserved(claim)
