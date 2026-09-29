"""
Reidentification review: the screening and clearance variants of the same
arithmetic, the risk ceiling on clearance, and the block-reopen-resubmit route.
"""

from test_helpers import (
    PORTAL_ADMIN_HEADERS,
    PRIVACY_DECIDER_HEADERS,
    PRIVACY_DECIDER_USER_ID,
    assert_assessment_derived,
    assert_common_fields,
    assert_money,
    factories,
    fixtures,
    validate_error,
    validate_success,
)

PARCEL_DATASET = {
    "title": "Parcel Ownership Extract",
    "slug": "parcel-ownership",
    "description": "Parcel Ownership Extract published by the department",
    "sensitivity_class": "SENSITIVE",
    "public_demand_score": 60,
    "policy_value_score": 60,
}

# 4 quasi-identifiers, a cell of 6 and a population under 5000.
PARCEL_ASSESSMENT = {
    "declared_quasi_identifier_count": 4,
    "declared_smallest_cell_size": 6,
    "population_size": 4000,
}

INMATE_DATASET = {
    "title": "County Inmate Roster",
    "slug": "inmate-roster",
    "description": "County Inmate Roster published by the department",
    "sensitivity_class": "SENSITIVE",
    "public_demand_score": 55,
    "policy_value_score": 60,
}

# 5 quasi-identifiers and a cell of 4: the 2.0 cell factor doubles the risk.
INMATE_ASSESSMENT = {
    "declared_quasi_identifier_count": 5,
    "declared_smallest_cell_size": 4,
    "population_size": 60000,
}


def test_screening_variant_forces_the_population_factor_to_one(api):
    """At creation the screening pass ignores how small the covered population is.

    The PRD: the screening "variant runs at creation, uses
    `declared_smallest_cell_size` as the cell size, and forces the population factor to
    1.00" and "Its result is stored in `screening_risk_score`, and while the
    assessment's `status` is `DRAFT` the assessment's headline `risk_score` mirrors it."

    Four quasi-identifiers give 32 points, a cell of 6 gives the 1.0 factor and
    `SENSITIVE` gives 1.0, so the screening figure is 32.00 — below the 35.00 line, so
    "`aggregation_required` is true when the score is at least 35.00" leaves it false
    and the geography floor is the coarsest-nothing `BLOCK`.

    Design: Difficulty/dual_variant_calc/reidentification_screening_vs_clearance_flips_aggregation_requirement
    """
    ctx = fixtures.setup_screening_dataset(
        api=api, credit_units=0, dataset_overrides=PARCEL_DATASET
    )
    assessment = fixtures.open_privacy_assessment(
        ctx["dataset_id"], api=api, **PARCEL_ASSESSMENT
    )

    assert assessment["status"] == "DRAFT", f"Expected DRAFT, got {assessment['status']}"
    assert_money(assessment["screening_risk_score"], 32.00, "screening_risk_score")
    assert assessment["clearance_risk_score"] is None, (
        f"clearance_risk_score must stay null before submission, "
        f"got {assessment['clearance_risk_score']!r}"
    )
    assert_assessment_derived(
        assessment,
        risk_score=32.00,
        k_anonymity_k=6,
        aggregation_required=False,
        min_aggregation_geography="BLOCK",
    )


def test_clearance_variant_population_factor_flips_the_aggregation_requirement(api):
    """Submission re-runs the same arithmetic with the 1.25 population factor.

    The PRD: the clearance "variant runs when the assessment is submitted, uses
    `verified_smallest_cell_size` — the figure the reviewer measured on the actual
    extract — as the cell size, and applies a population factor of 1.25 when
    `population_size` is below 5000 and 1.00 otherwise." and "With identical stored
    inputs the two variants can land on opposite sides of the aggregation threshold,
    flipping `aggregation_required` from false to true."

    The reviewer measures the same cell of 6, so only the population factor moves: 32.00
    becomes 40.00. That crosses the 35.00 line, and because "`min_aggregation_geography`
    names the coarsest geography the extract must be rolled up to before publication:
    `COUNTY` when the score is at least 60.00, `TRACT` when the score is at least 35.00
    but below 60.00, and `BLOCK` otherwise", the floor becomes `TRACT`.

    Design: Difficulty/dual_variant_calc/reidentification_screening_vs_clearance_flips_aggregation_requirement
    """
    ctx = fixtures.setup_screening_dataset(
        api=api, credit_units=0, dataset_overrides=PARCEL_DATASET
    )
    assessment = fixtures.open_privacy_assessment(
        ctx["dataset_id"], api=api, **PARCEL_ASSESSMENT
    )
    fixtures.revise_privacy_assessment(
        assessment["id"], api=api, verified_smallest_cell_size=6
    )

    submitted = fixtures.submit_privacy_assessment(assessment["id"], api=api)

    assert submitted["status"] == "SUBMITTED", (
        f"Expected SUBMITTED, got {submitted['status']}"
    )
    assert_money(submitted["screening_risk_score"], 32.00, "screening_risk_score")
    assert_money(submitted["clearance_risk_score"], 40.00, "clearance_risk_score")
    assert_assessment_derived(
        submitted,
        risk_score=40.00,
        k_anonymity_k=6,
        aggregation_required=True,
        min_aggregation_geography="TRACT",
    )
    difference = float(submitted["clearance_risk_score"]) - float(
        submitted["screening_risk_score"]
    )
    assert_money(difference, 8.00, "clearance-minus-screening difference")


def test_clear_refused_at_or_above_the_risk_ceiling(api):
    """An assessment measured at 80.00 cannot be cleared at all.

    The PRD: "A `CLEAR` decision moves the assessment `SUBMITTED → CLEARED` and
    additionally requires `clearance_risk_score` to be strictly below 60.00; an
    assessment at exactly 60.00 or above cannot be cleared and is refused with
    `ERR_REIDENTIFICATION_RISK_TOO_HIGH`."

    Five quasi-identifiers give the capped 40 points and a verified cell of 4 gives the
    2.0 factor, so the clearance figure is 80.00. The refusal must leave the assessment
    in `SUBMITTED` with that score intact.

    Design: Difficulty/non_linear_state_machine/privacy_assessment_block_reopen_resubmit_clear_cycle
    """
    ctx = fixtures.setup_screening_dataset(
        api=api, credit_units=0, dataset_overrides=INMATE_DATASET
    )
    assessment = fixtures.open_privacy_assessment(
        ctx["dataset_id"], api=api, **INMATE_ASSESSMENT
    )
    fixtures.revise_privacy_assessment(
        assessment["id"], api=api, verified_smallest_cell_size=4
    )
    submitted = fixtures.submit_privacy_assessment(assessment["id"], api=api)
    assert_money(submitted["clearance_risk_score"], 80.00, "clearance_risk_score")

    validate_error(
        api.decide_privacy_assessment(
            assessment["id"], factories.decision_payload("CLEAR"), PRIVACY_DECIDER_HEADERS
        ),
        "ERR_REIDENTIFICATION_RISK_TOO_HIGH",
        422,
    )

    unchanged = validate_success(
        api.get_privacy_assessment(assessment["id"], PORTAL_ADMIN_HEADERS)
    )
    assert unchanged["status"] == "SUBMITTED", (
        f"A refused clearance must leave the assessment SUBMITTED, got {unchanged['status']}"
    )
    assert_money(unchanged["clearance_risk_score"], 80.00, "clearance_risk_score")


def test_reopening_a_blocked_assessment_points_risk_back_at_the_screening_score(api):
    """Blocking then reopening rewinds the clearance pass without discarding the record.

    The PRD: "A `BLOCK` decision moves the assessment `SUBMITTED → BLOCKED`, imposes no
    risk ceiling of its own, and instead requires a `block_reason` in the body — one of
    `RISK_TOO_HIGH`, `AGGREGATION_UNMET` or `REVIEWER_JUDGEMENT` — which is recorded on
    the assessment." and "Reopening it moves it `BLOCKED → DRAFT`, requires the dataset
    to still be in `SCREENING`, and clears `decided_by_user_id`, `block_reason` and
    `clearance_risk_score`, pointing `risk_score` back at `screening_risk_score`."

    Design: Difficulty/non_linear_state_machine/privacy_assessment_block_reopen_resubmit_clear_cycle
    """
    ctx = fixtures.setup_screening_dataset(
        api=api, credit_units=0, dataset_overrides=INMATE_DATASET
    )
    assessment = fixtures.open_privacy_assessment(
        ctx["dataset_id"], api=api, **INMATE_ASSESSMENT
    )
    fixtures.revise_privacy_assessment(
        assessment["id"], api=api, verified_smallest_cell_size=4
    )
    fixtures.submit_privacy_assessment(assessment["id"], api=api)

    blocked = fixtures.block_privacy_assessment(
        assessment["id"], block_reason="RISK_TOO_HIGH", api=api
    )
    assert blocked["status"] == "BLOCKED", f"Expected BLOCKED, got {blocked['status']}"
    assert blocked["block_reason"] == "RISK_TOO_HIGH", (
        f"Expected block_reason RISK_TOO_HIGH, got {blocked['block_reason']}"
    )
    assert blocked["decided_by_user_id"] == PRIVACY_DECIDER_USER_ID, (
        f"The deciding reviewer must be stamped, got {blocked['decided_by_user_id']!r}"
    )

    reopened = fixtures.reopen_privacy_assessment(assessment["id"], api=api)
    assert reopened["status"] == "DRAFT", f"Expected DRAFT, got {reopened['status']}"
    assert reopened["block_reason"] is None, (
        f"Reopening must clear block_reason, got {reopened['block_reason']!r}"
    )
    assert reopened["clearance_risk_score"] is None, (
        f"Reopening must clear clearance_risk_score, got {reopened['clearance_risk_score']!r}"
    )
    assert reopened["decided_by_user_id"] is None, (
        f"Reopening must clear decided_by_user_id, got {reopened['decided_by_user_id']!r}"
    )
    assert_money(reopened["risk_score"], 80.00, "risk_score")
    assert_money(reopened["screening_risk_score"], 80.00, "screening_risk_score")


def test_remeasured_cell_size_carries_the_reopened_assessment_to_cleared(api):
    """The block-reopen-resubmit-clear route ends in a clearance at the lower score.

    The PRD: "The `BLOCKED → DRAFT → SUBMITTED → CLEARED` path is the standard
    remediation route, and it may be walked as many times as the analysis requires."
    Remeasuring the cell at 12 swings the cell-size factor from 2.0 to 0.5, so the
    clearance figure falls from 80.00 to 20.00 — below both the 60.00 ceiling and the
    35.00 aggregation line — and "Clearing freezes `aggregation_required` and
    `min_aggregation_geography` at their clearance-variant values".

    Every persisting step along the route bumps the record: creation, the first
    measurement, the first submission, the block, the reopen, the second measurement,
    the second submission and the clearance leave the assessment at `version` 8, while
    the refused clearance in between changes nothing.

    Design: Difficulty/non_linear_state_machine/privacy_assessment_block_reopen_resubmit_clear_cycle
    """
    ctx = fixtures.setup_screening_dataset(
        api=api, credit_units=0, dataset_overrides=INMATE_DATASET
    )
    assessment = fixtures.open_privacy_assessment(
        ctx["dataset_id"], api=api, **INMATE_ASSESSMENT
    )
    assessment_id = assessment["id"]
    fixtures.revise_privacy_assessment(assessment_id, api=api, verified_smallest_cell_size=4)
    fixtures.submit_privacy_assessment(assessment_id, api=api)
    validate_error(
        api.decide_privacy_assessment(
            assessment_id, factories.decision_payload("CLEAR"), PRIVACY_DECIDER_HEADERS
        ),
        "ERR_REIDENTIFICATION_RISK_TOO_HIGH",
        422,
    )
    fixtures.block_privacy_assessment(assessment_id, block_reason="RISK_TOO_HIGH", api=api)
    fixtures.reopen_privacy_assessment(assessment_id, api=api)

    fixtures.revise_privacy_assessment(assessment_id, api=api, verified_smallest_cell_size=12)
    resubmitted = fixtures.submit_privacy_assessment(assessment_id, api=api)
    assert_money(resubmitted["clearance_risk_score"], 20.00, "clearance_risk_score")
    assert_assessment_derived(
        resubmitted, risk_score=20.00, k_anonymity_k=12, aggregation_required=False
    )

    cleared = fixtures.clear_privacy_assessment(assessment_id, api=api)
    assert cleared["status"] == "CLEARED", f"Expected CLEARED, got {cleared['status']}"
    assert_assessment_derived(
        cleared,
        risk_score=20.00,
        aggregation_required=False,
        min_aggregation_geography="BLOCK",
    )
    assert_common_fields(cleared, expected_version=8)
