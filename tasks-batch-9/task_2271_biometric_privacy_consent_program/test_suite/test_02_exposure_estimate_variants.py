"""The two damages theories priced by an exposure estimate.

The same three violation rows are priced twice: once stacked per violation, once
capped per aggrieved person.
"""

from test_helpers import (
    assert_cents,
    assert_program_state,
    assert_two_decimal_value,
    draft_exposure_assessment,
    exposure_units_scenario,
    read_program,
)


def test_stacked_variant_prices_every_violation_row_independently(api):
    """Two negligent rows and one reckless row stack to 875,000 cents.

    PRD §3.9: "Otherwise, under the `PER_VIOLATION_STACKED` variant — the
    plaintiff theory that each unconsented collection event is its own violation
    — `base_cents` is the negligent unit count multiplied by the state profile's
    `per_violation_negligent_cents`, plus the reckless unit count multiplied by
    its `per_violation_reckless_cents`; every violation row is priced
    independently, so one individual with both an unconsented collection and a
    post-revocation collection contributes the full sum with no per-person
    ceiling."

    Illinois prices a negligent violation at 100,000 cents and a reckless one at
    500,000 cents, so the base is 2 x 100,000 + 1 x 500,000 = 700,000 cents; the
    scoped point carries a consent gap, so the multiplier is 1.25 and Illinois
    grants no cure period, giving 700,000 x 1.25 = 875,000 cents.

    Design: Difficulty/dual_variant_calc/pra_exposure_stacked_vs_subject_capped_divergence
    """
    ctx = exposure_units_scenario(api)

    assessment = draft_exposure_assessment(api, ctx, variant="PER_VIOLATION_STACKED")

    assert assessment["variant"] == "PER_VIOLATION_STACKED"
    assert assessment["negligent_unit_count"] == 2, "two SOLICITED rows are negligent units"
    assert assessment["reckless_unit_count"] == 1, "the REVOKED row with no live accommodation is reckless"
    assert_cents(assessment["base_cents"], 700000, "base_cents")
    assert_two_decimal_value(assessment["notice_gap_multiplier"], 1.25, "notice_gap_multiplier")
    assert_two_decimal_value(assessment["cure_credit_pct"], 0.00, "cure_credit_pct")
    assert_cents(assessment["exposure_cents"], 875000, "exposure_cents")
    assert assessment["status"] == "DRAFT"
    assert_program_state(read_program(api, ctx["program_id"]), pra_exposure_cents=0)


def test_capped_variant_clips_each_subject_at_three_thousand_dollars(api):
    """The same rows priced per aggrieved person come to 500,000 cents.

    PRD §3.9: "Under the `PER_SUBJECT_CAPPED` variant — the defence theory that
    recovery is capped per aggrieved person — each data subject contributing at
    least one row to either bucket is priced separately: that subject's own base
    is the count of their negligent rows multiplied by
    `per_violation_negligent_cents` plus the count of their reckless rows
    multiplied by `per_violation_reckless_cents`, and each subject's base is then
    clipped at 300,000 cents (US$3,000.00) before the per-subject figures are
    summed into `base_cents`."

    EMP-0001 carries one negligent and one reckless row, so its own base of
    600,000 cents is clipped to 300,000; EMP-0002 carries one negligent row worth
    100,000; the base is therefore 400,000 cents and the figure 400,000 x 1.25 =
    500,000 cents.

    Design: Difficulty/dual_variant_calc/pra_exposure_stacked_vs_subject_capped_divergence
    """
    ctx = exposure_units_scenario(api)

    assessment = draft_exposure_assessment(api, ctx, variant="PER_SUBJECT_CAPPED")

    assert assessment["variant"] == "PER_SUBJECT_CAPPED"
    assert assessment["negligent_unit_count"] == 2
    assert assessment["reckless_unit_count"] == 1
    assert_cents(assessment["base_cents"], 400000, "base_cents")
    assert_two_decimal_value(assessment["notice_gap_multiplier"], 1.25, "notice_gap_multiplier")
    assert_two_decimal_value(assessment["cure_credit_pct"], 0.00, "cure_credit_pct")
    assert_cents(assessment["exposure_cents"], 500000, "exposure_cents")
    assert assessment["status"] == "DRAFT"


def test_capped_variant_is_strictly_cheaper_on_identical_consent_data(api):
    """Both variants priced from one state of the world diverge by 375,000 cents.

    PRD §3.9: "Identical consent data therefore yields a strictly lower figure
    under the capped variant whenever any single subject's base exceeds the cap."

    EMP-0001's uncapped base of 600,000 cents exceeds the 300,000-cent cap, so
    the stacked figure of 875,000 cents and the capped figure of 500,000 cents
    differ by 375,000 cents.

    Design: Difficulty/dual_variant_calc/pra_exposure_stacked_vs_subject_capped_divergence
    """
    ctx = exposure_units_scenario(api)

    stacked = draft_exposure_assessment(api, ctx, variant="PER_VIOLATION_STACKED")
    capped = draft_exposure_assessment(api, ctx, variant="PER_SUBJECT_CAPPED")

    assert_cents(stacked["exposure_cents"], 875000, "stacked exposure_cents")
    assert_cents(capped["exposure_cents"], 500000, "capped exposure_cents")
    assert stacked["exposure_cents"] - capped["exposure_cents"] == 375000, (
        "the per-subject cap must remove exactly 375,000 cents from this data"
    )
    assert capped["negligent_unit_count"] == stacked["negligent_unit_count"], (
        "the unit counts are variant-independent"
    )
    assert capped["reckless_unit_count"] == stacked["reckless_unit_count"], (
        "the unit counts are variant-independent"
    )
