"""Builder risk scoring: the declared-data pass, the observed-data pass, and
the inclusive class-C band floor.

Every test builds its own world from scratch through PRD-declared endpoints,
because each test runs against a freshly restarted server with an empty
database.
"""

import pytest

from test_helpers import (
    CANONICAL_PREMIUM_CENTS,
    assert_builder,
    assert_policy,
    create_builder_under_review,
    reassessment_payload,
    setup_active_policy,
    validate_success,
)


# ---------------------------------------------------------------------------
# The two scoring variants on one unchanged builder row
# ---------------------------------------------------------------------------
def test_declared_data_intake_scores_the_builder_at_4500_and_prices_class_c(api):
    """PRD 3.1: "Start with a base of 50 points. Add a **history penalty**
    equal to the shortfall of the effective claims score below 100, multiplied
    by 0.50 — a spotless score of 100 adds nothing, a score of 60 adds 20
    points."
    PRD 3.1: "Compute a **volume factor** by dividing the effective home volume
    by 25 and discarding any fractional part, multiplying that whole number of
    25-home buckets by 8 points per bucket, and capping the result at 40 points;
    then add one quarter of that capped volume factor to the running total, so a
    builder closing 300 homes contributes the maximum, which is 40 capped points
    weighted down to 10 points of score."
    PRD 3.1: "Subtract a **tenure credit** of 2 points for each full year in
    business, capped at 20 points, so anything past a decade of operation earns
    the same credit."
    PRD 3.1: "Subtract a **financial strength bonus** of 15 points for `TIER_1`,
    8 points for `TIER_2` and 0 points for `TIER_3`."
    PRD 3.1: "Both intake transitions write `risk_score` and `risk_class` and
    set `risk_basis` to `INITIAL_UNDERWRITING`, and both advance the builder's
    `version` by 1."
    PRD 3.3: "`risk_class_at_enrollment` is a snapshot of the builder's
    `risk_class` taken at that instant, and it is decisive: a later reassessment
    that moves the builder into a worse band **never re-rates an existing
    policy**."

    A builder declaring 5 years in business, 25 homes closed, a third-party
    claims score of 94 and TIER_3 scores 50 + 3 + 2 - 10 - 0 on the declared
    inputs, so the declared pass reads 45.00 and lands in class C.

    Design: Difficulty/dual_variant_calc/builder_risk_score_declared_vs_observed_variant_changes_band
    """
    scenario = setup_active_policy()
    builder = scenario["builder"]

    assert_builder(builder)
    assert builder["claims_history_score"] == 94, (
        "the declared third-party claims score must be stored as supplied"
    )
    assert builder["homes_closed_last_year"] == 25, (
        "the declared home volume must be stored as supplied"
    )
    assert float(builder["risk_score"]) == pytest.approx(45.00, abs=1e-6), (
        f"declared-data score must be 45.00, got {builder['risk_score']}"
    )
    assert builder["risk_class"] == "C", (
        f"a declared-data score of 45.00 is class C, got {builder['risk_class']}"
    )
    assert builder["risk_basis"] == "INITIAL_UNDERWRITING", (
        f"the intake pass sets risk_basis to INITIAL_UNDERWRITING, "
        f"got {builder['risk_basis']}"
    )
    assert builder["underwriting_status"] == "APPROVED"

    policy = scenario["policy"]
    assert_policy(policy)
    assert policy["risk_class_at_enrollment"] == "C", (
        "the enrolled home snapshots the declared-pass band C"
    )
    assert policy["premium_cents"] == CANONICAL_PREMIUM_CENTS, (
        f"a class-C home at 44,500,000 cents in TX prices at "
        f"{CANONICAL_PREMIUM_CENTS}, got {policy['premium_cents']}"
    )


def test_reassessment_on_observed_data_rescores_the_same_row_to_4000_class_b(
    api, underwriting_officer_headers
):
    """PRD 3.2: "The effective claims score is no longer the declared
    `claims_history_score`; it is derived from realised experience as 100 minus
    the builder's `loss_ratio` multiplied by an observed-loss weight of 60,
    rounded half up to two decimal places and then clamped to lie between 0 and
    100 inclusive."
    PRD 3.2: "And the effective home volume is no longer the declared
    `homes_closed_last_year`; it is the count of the builder's policies whose
    `coverage_status` is `ACTIVE` or `EXPIRED`, with `PENDING_ENROLLMENT` and
    `VOIDED` policies excluded."
    PRD 3.2: "Reassessment writes `risk_score` and `risk_class` and sets
    `risk_basis` to `RENEWAL_REASSESSMENT`."
    PRD 3.1: "`risk_class` is then a band on the rounded score, with each band's
    lower bound inclusive and its upper bound exclusive: class `A` for a score
    below 25.00, class `B` for a score from 25.00 up to but not including 45.00,
    class `C` for a score from 45.00 up to but not including 65.00, and class `D`
    for a score of 65.00 or higher."
    PRD 3.2: "When the reassessed `risk_class` comes out as `D` and the builder
    was `APPROVED`, the same request applies `APPROVED → SUSPENDED` — the new
    score, class and `risk_basis` are written first and the suspension is applied
    afterwards, within the one request, and the builder's `version` advances by
    exactly 1 for the whole operation."

    Nothing about the stored row changes between the two passes. With a
    loss_ratio of 0.0000 the observed claims score is a spotless 100, so the
    history penalty vanishes, and with exactly one ACTIVE home the realised
    volume yields no 25-home bucket at all: 50 + 0 + 0 - 10 - 0 reads 40.00 and
    crosses the class-C floor downwards into class B.

    Design: Difficulty/dual_variant_calc/builder_risk_score_declared_vs_observed_variant_changes_band
    """
    scenario = setup_active_policy()
    builder = scenario["builder"]
    declared_score = float(builder["risk_score"])

    assert declared_score == pytest.approx(45.00, abs=1e-6)
    assert builder["risk_class"] == "C"
    assert float(builder["loss_ratio"]) == pytest.approx(0.0000, abs=1e-9), (
        "one ACTIVE and PAID home with no insurer-obligated claim leaves the "
        f"loss ratio at 0.0000, got {builder['loss_ratio']}"
    )

    reassessed = validate_success(
        api.reassess_builder(
            builder["id"], reassessment_payload(), underwriting_officer_headers
        )
    )

    assert_builder(reassessed)
    assert reassessed["claims_history_score"] == 94, (
        "the reassessment restated nothing, so the declared inputs stand"
    )
    assert reassessed["homes_closed_last_year"] == 25
    assert float(reassessed["risk_score"]) == pytest.approx(40.00, abs=1e-6), (
        f"observed-data score must be 40.00, got {reassessed['risk_score']}"
    )
    assert reassessed["risk_class"] == "B", (
        f"a score of 40.00 sits below the 45.00 class-C floor, "
        f"got {reassessed['risk_class']}"
    )
    assert reassessed["risk_basis"] == "RENEWAL_REASSESSMENT", (
        f"the monitoring pass sets risk_basis to RENEWAL_REASSESSMENT, "
        f"got {reassessed['risk_basis']}"
    )
    assert reassessed["underwriting_status"] == "APPROVED", (
        "only a reassessed class of D suspends an approved builder, and this "
        f"row came out class B; got {reassessed['underwriting_status']}"
    )
    assert declared_score - float(reassessed["risk_score"]) == pytest.approx(
        5.00, abs=1e-6
    ), (
        "the declared and observed passes must disagree by exactly 5.00 points "
        "on the same unchanged builder row"
    )


# ---------------------------------------------------------------------------
# The class-C band floor is inclusive to one hundredth of a point
# ---------------------------------------------------------------------------
def test_risk_score_exactly_at_the_class_c_floor_lands_in_class_c(api):
    """PRD 3.1: "`risk_class` is then a band on the rounded score, with each
    band's lower bound inclusive and its upper bound exclusive: class `A` for a
    score below 25.00, class `B` for a score from 25.00 up to but not including
    45.00, class `C` for a score from 45.00 up to but not including 65.00, and
    class `D` for a score of 65.00 or higher."
    PRD 2.5: "A builder's `risk_score` carries 2 decimal places, and the band
    comparison that assigns `risk_class` is made against the already-rounded
    score, never against the unrounded intermediate."
    PRD 3.1: "Both intake transitions write `risk_score` and `risk_class` and
    set `risk_basis` to `INITIAL_UNDERWRITING`, and both advance the builder's
    `version` by 1."

    A claims score of 94 puts the builder exactly on the floor at 45.00. The
    floor value itself belongs to class C, so an exclusive reading of the bound
    — which would report class B — is the falsifier.

    Design: Difficulty/boundary_precision_check/risk_score_exactly_at_class_c_floor_lands_in_class_c
    """
    builder = create_builder_under_review(
        company_name="Boundary Homes At", claims_history_score=94
    )

    assert_builder(builder)
    assert float(builder["risk_score"]) == pytest.approx(45.00, abs=1e-6), (
        f"a claims score of 94 scores exactly 45.00, got {builder['risk_score']}"
    )
    assert builder["risk_class"] == "C", (
        f"45.00 is the inclusive class-C floor, so the band is C, "
        f"got {builder['risk_class']}"
    )
    assert builder["risk_class"] != "B", (
        "an exclusive reading of the 45.00 floor would report class B"
    )
    assert builder["risk_basis"] == "INITIAL_UNDERWRITING"
    assert builder["underwriting_status"] == "UNDER_REVIEW"


def test_risk_score_one_input_unit_below_the_class_c_floor_lands_in_class_b(api):
    """PRD 3.1: "`risk_class` is then a band on the rounded score, with each
    band's lower bound inclusive and its upper bound exclusive: class `A` for a
    score below 25.00, class `B` for a score from 25.00 up to but not including
    45.00, class `C` for a score from 45.00 up to but not including 65.00, and
    class `D` for a score of 65.00 or higher."
    PRD 3.1: "Add a **history penalty** equal to the shortfall of the effective
    claims score below 100, multiplied by 0.50 — a spotless score of 100 adds
    nothing, a score of 60 adds 20 points."
    PRD 3.1: "Clamp the resulting figure so that it is never below 0 and never
    above 100, and round it half up to two decimal places; that is `risk_score`."

    One unit of third-party claims score — 95 rather than 94 — halves the
    history penalty to 2.5 points and lands the otherwise identical builder at
    44.50, one half point under the floor and therefore in class B.

    Design: Difficulty/boundary_precision_check/risk_score_exactly_at_class_c_floor_lands_in_class_c
    """
    builder = create_builder_under_review(
        company_name="Boundary Homes Below", claims_history_score=95
    )

    assert_builder(builder)
    assert float(builder["risk_score"]) == pytest.approx(44.50, abs=1e-6), (
        f"a claims score of 95 scores 44.50, got {builder['risk_score']}"
    )
    assert builder["risk_class"] == "B", (
        f"44.50 sits below the 45.00 class-C floor, got {builder['risk_class']}"
    )
    assert builder["risk_basis"] == "INITIAL_UNDERWRITING"
    assert builder["underwriting_status"] == "UNDER_REVIEW"
