"""Cutting the soil profile: perc holes, the two rate variants, review and supersession."""

import pytest

from test_helpers import (
    ApiErrorId,
    add_perc_hole,
    assert_perc_hole,
    assert_site_evaluation,
    create_approved_site_evaluation,
    create_draft_site_evaluation,
    create_parcel,
    create_submitted_site_evaluation,
    draw_design_from_evaluation,
    refresh_site_evaluation,
    refresh_system_design,
    unique_apn,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_new_evaluation_starts_in_draft_with_no_readings(api, applicant_headers, design_professional_headers):
    """PRD §3.3: "The register stamps `evaluator_user_id` from the acting `X-User-ID`,
    starts the evaluation in `DRAFT` with an empty `perc_holes` array, and computes
    `valid_until` as `evaluated_on` advanced by five years."
    PRD §3.3: "If that set is empty, both `preliminary_perc_rate_min_per_in` and
    `certified_perc_rate_min_per_in` are null."
    PRD §3.3: "it is likewise null while the certified rate itself is null."

    Design: Corner/state_machines/corner_site_evaluation_starts_in_draft_with_empty_perc_holes
    """
    parcel = create_parcel(
        api, headers=applicant_headers, apn=unique_apn("0856-S1"), site_address="32 Draft Drive"
    )
    response = api.create_site_evaluation(
        {
            "parcel_id": parcel["id"],
            "evaluated_on": "2026-04-15T00:00:00Z",
            "soil_group": "LOAMY",
            "depth_to_limiting_layer_in": 48,
        },
        design_professional_headers,
    )
    evaluation = validate_success(response, 201)
    assert_site_evaluation(evaluation)

    assert evaluation["status"] == "DRAFT"
    assert evaluation["revision_round"] == 0
    assert evaluation["perc_holes"] == []
    assert evaluation["preliminary_perc_rate_min_per_in"] is None
    assert evaluation["certified_perc_rate_min_per_in"] is None
    assert evaluation["soil_loading_rate_gpd_per_sqft"] is None
    assert evaluation["valid_until"] == "2031-04-15T00:00:00.000Z"
    assert evaluation["evaluator_user_id"] == "u-dp-1"


def test_resubmitting_an_approved_evaluation_is_an_undeclared_transition(api, applicant_headers, design_professional_headers):
    """PRD §3.3: "Submitting the evaluation for departmental review advances it
    `DRAFT → SUBMITTED`, and only the `DesignProfessional` whose `X-User-ID` matches
    the evaluation's `evaluator_user_id` may do so."
    PRD §2.6: "First, the target resource must currently sit in a state from which the
    requested transition is declared, else `ERR_INVALID_STATE` (HTTP 409); this applies
    to every action operation."

    Design: Corner/state_machines/corner_submit_site_evaluation_from_approved_returns_invalid_state
    """
    parcel = create_parcel(
        api, headers=applicant_headers, apn=unique_apn("0856-S2"), site_address="33 Locked Lane"
    )
    evaluation = create_approved_site_evaluation(api, parcel["id"])
    assert evaluation["status"] == "APPROVED"

    refused = api.submit_site_evaluation(evaluation["id"], design_professional_headers)
    validate_error(refused, ApiErrorId.ERR_INVALID_STATE.value, 409)

    unchanged = refresh_site_evaluation(api, evaluation["id"])
    assert unchanged["status"] == "APPROVED"
    assert unchanged["revision_round"] == 1


def test_submit_without_a_valid_reading_is_refused(api, applicant_headers, design_professional_headers):
    """PRD §3.3: "The submission is refused with `ERR_NO_VALID_PERC_HOLES` unless
    `perc_holes` contains at least one reading marked valid."
    PRD §3.3: "A reading is marked `valid` only when all three of the following hold:
    `presoak_ok` is true, `drop_inches` is greater than zero, and `elapsed_minutes` is
    greater than zero."

    Design: Corner/state_machines/corner_submit_site_evaluation_with_only_failed_presoak_holes_is_rejected
    """
    parcel = create_parcel(
        api, headers=applicant_headers, apn=unique_apn("0856-S3"), site_address="34 Presoak Place"
    )
    evaluation = create_draft_site_evaluation(api, parcel["id"])
    after_hole = add_perc_hole(
        api, evaluation["id"], hole_number=1, drop_inches=6, elapsed_minutes=132, presoak_ok=False
    )
    assert len(after_hole["perc_holes"]) == 1, "an invalid reading is still stored and shown"
    assert_perc_hole(after_hole["perc_holes"][0])
    assert after_hole["perc_holes"][0]["valid"] is False

    refused = api.submit_site_evaluation(evaluation["id"], design_professional_headers)
    validate_error(refused, ApiErrorId.ERR_NO_VALID_PERC_HOLES.value, 422)

    unchanged = refresh_site_evaluation(api, evaluation["id"])
    assert unchanged["status"] == "DRAFT"
    assert unchanged["revision_round"] == 0
    assert unchanged["preliminary_perc_rate_min_per_in"] is None
    assert unchanged["certified_perc_rate_min_per_in"] is None


def test_approving_a_second_evaluation_supersedes_the_first_and_its_designs(api, applicant_headers, ehs_reviewer_headers, records_clerk_headers):
    """PRD §3.3: "When an evaluation enters `APPROVED`, every *other* evaluation on the
    same parcel that was itself `APPROVED` is moved `APPROVED → SUPERSEDED`; the parcel
    may have only one live approved evaluation."
    PRD §3.3: "And because a superseded evaluation can no longer support a design, every
    system design citing one of those newly-superseded evaluations, whose own status is
    `DRAFT`, `UNDER_REVIEW`, `REVISIONS_REQUIRED` or `APPROVED`, is moved to
    `SUPERSEDED` too."

    Design: Corner/state_machines/corner_approving_second_site_evaluation_supersedes_first_and_its_designs
    """
    parcel = create_parcel(
        api,
        headers=applicant_headers,
        apn=unique_apn("0856-S4"),
        site_address="35 Supersede Street",
    )
    first = create_approved_site_evaluation(api, parcel["id"])
    design = draw_design_from_evaluation(api, first["id"])
    assert design["status"] == "DRAFT"

    second = create_submitted_site_evaluation(
        api,
        parcel["id"],
        holes=[{"drop_inches": 6, "elapsed_minutes": 90, "presoak_ok": True}],
        evaluated_on="2026-04-20T00:00:00Z",
        soil_group="LOAMY",
        depth_to_limiting_layer_in=50,
    )

    approved = validate_success(
        api.review_site_evaluation(
            second["id"],
            {"decision": "APPROVE", "review_note": "Newer profile governs"},
            ehs_reviewer_headers,
        ),
        200,
    )
    assert approved["status"] == "APPROVED"
    assert refresh_site_evaluation(api, first["id"])["status"] == "SUPERSEDED"
    assert refresh_system_design(api, design["id"])["status"] == "SUPERSEDED"

    _, meta = validate_paginated(
        api.list_parcel_site_evaluations(parcel["id"], records_clerk_headers)
    )
    assert meta["total_count"] == 2


def test_soil_loading_tier_ceiling_is_inclusive(api, applicant_headers):
    """PRD §3.3: "A certified rate at or below 5 minutes per inch loads at 1.20. Above
    5 and at or below 15, it loads at 0.80. Above 15 and at or below 30, at 0.60."
    PRD §3.3: "The boundaries matter: a certified rate of exactly 15 selects 0.80,
    while 15.01 selects 0.60."

    Design: Corner/calculations/corner_soil_loading_tier_upper_bound_is_inclusive_at_fifteen_min_per_inch
    """
    parcel = create_parcel(
        api, headers=applicant_headers, apn=unique_apn("0856-C2"), site_address="46 Tier Terrace"
    )
    on_boundary = create_draft_site_evaluation(api, parcel["id"])
    above_boundary = create_draft_site_evaluation(
        api, parcel["id"], evaluated_on="2026-04-16T00:00:00Z"
    )

    at_ceiling = add_perc_hole(
        api, on_boundary["id"], hole_number=1, drop_inches=6, elapsed_minutes=90, presoak_ok=True
    )
    just_over = add_perc_hole(
        api, above_boundary["id"], hole_number=1, drop_inches=6, elapsed_minutes=93, presoak_ok=True
    )

    assert at_ceiling["certified_perc_rate_min_per_in"] == pytest.approx(15.0)
    assert at_ceiling["soil_loading_rate_gpd_per_sqft"] == pytest.approx(0.8)
    assert at_ceiling["preliminary_perc_rate_min_per_in"] == pytest.approx(15.0)

    assert just_over["certified_perc_rate_min_per_in"] == pytest.approx(15.5)
    assert just_over["soil_loading_rate_gpd_per_sqft"] == pytest.approx(0.6)


def test_approval_is_refused_for_unacceptably_slow_soil_or_a_shallow_limiting_layer(api, applicant_headers, ehs_reviewer_headers):
    """PRD §3.3: "An approval moves `SUBMITTED → APPROVED`, but only if the soil passes
    two tests: the `certified_perc_rate_min_per_in` must be at or below 120 minutes per
    inch, and `depth_to_limiting_layer_in` must be at least 18 inches. Failing either
    is refused with `ERR_SOIL_UNSUITABLE`."
    PRD §3.3: "A certified rate above 120 minutes per inch — the department's maximum
    percolation rate — means the soil will not accept effluent at all, and the loading
    rate is null; it is likewise null while the certified rate itself is null."

    Design: Corner/calculations/corner_site_evaluation_approval_rejected_for_slow_perc_or_shallow_limiting_layer
    """
    slow_parcel = create_parcel(
        api, headers=applicant_headers, apn=unique_apn("0856-C3A"), site_address="47 Clay Court"
    )
    slow = create_submitted_site_evaluation(
        api,
        slow_parcel["id"],
        holes=[{"drop_inches": 6, "elapsed_minutes": 726, "presoak_ok": True}],
        soil_group="CLAY",
        depth_to_limiting_layer_in=48,
    )
    shallow_parcel = create_parcel(
        api, headers=applicant_headers, apn=unique_apn("0856-C3B"), site_address="48 Bedrock Bend"
    )
    shallow = create_submitted_site_evaluation(
        api, shallow_parcel["id"], soil_group="LOAMY", depth_to_limiting_layer_in=12
    )

    validate_error(
        api.review_site_evaluation(
            slow["id"], {"decision": "APPROVE", "review_note": "Attempted approval"}, ehs_reviewer_headers
        ),
        ApiErrorId.ERR_SOIL_UNSUITABLE.value,
        422,
    )
    validate_error(
        api.review_site_evaluation(
            shallow["id"], {"decision": "APPROVE", "review_note": "Attempted approval"}, ehs_reviewer_headers
        ),
        ApiErrorId.ERR_SOIL_UNSUITABLE.value,
        422,
    )

    slow_now = refresh_site_evaluation(api, slow["id"])
    assert slow_now["certified_perc_rate_min_per_in"] == pytest.approx(121.0)
    assert slow_now["soil_loading_rate_gpd_per_sqft"] is None
    assert slow_now["status"] == "SUBMITTED"

    shallow_now = refresh_site_evaluation(api, shallow["id"])
    assert shallow_now["soil_loading_rate_gpd_per_sqft"] == pytest.approx(0.6)
    assert shallow_now["status"] == "SUBMITTED"


def test_preliminary_mean_and_certified_slowest_hole_diverge(api, applicant_headers):
    """PRD §3.3: "Otherwise `preliminary_perc_rate_min_per_in` is the arithmetic mean of
    those per-hole rates, rounded half up to two decimal places — this is the indicative
    figure shown to the applicant, and one unusually fast hole pulls it down."
    PRD §3.3: "`certified_perc_rate_min_per_in`, on the other hand, is simply the largest
    of those per-hole rates: the slowest hole governs. The certified figure is the only
    one the soil loading tier and the departmental approval gate are permitted to read;
    the mean is never used for sizing."
    PRD §3.3: "Above 15 and at or below 30, at 0.60."

    Design: Difficulty/dual_variant_calc/perc_rate_preliminary_mean_vs_certified_slowest_hole_select_different_loading_tiers
    """
    parcel = create_parcel(
        api,
        headers=applicant_headers,
        apn=unique_apn("0856-DV1"),
        site_address="1 Perc Road",
        water_source="PRIVATE_WELL",
    )
    evaluation = create_approved_site_evaluation(
        api,
        parcel["id"],
        holes=[
            {"drop_inches": 6, "elapsed_minutes": 60, "presoak_ok": True},
            {"drop_inches": 6, "elapsed_minutes": 66, "presoak_ok": True},
            {"drop_inches": 6, "elapsed_minutes": 132, "presoak_ok": True},
        ],
        review_note="Soil profile accepted",
    )

    assert evaluation["preliminary_perc_rate_min_per_in"] == pytest.approx(14.33), (
        "the mean of 10.00, 11.00 and 22.00 rounds half up to 14.33"
    )
    assert evaluation["certified_perc_rate_min_per_in"] == pytest.approx(22.0), (
        "the slowest of the three holes governs the certified rate"
    )
    assert evaluation["soil_loading_rate_gpd_per_sqft"] == pytest.approx(0.6), (
        "the certified 22.00 min/in selects the 0.60 tier, not the 0.80 tier the mean would pick"
    )


def test_rejected_evaluation_resubmits_through_the_revision_loop(api, applicant_headers, design_professional_headers, ehs_reviewer_headers):
    """PRD §3.3: "A `REJECTED` evaluation is not dead. The professional may cut more
    holes, append more readings and submit again — the `REJECTED → SUBMITTED` edge is
    the revision loop, it is unbounded, it enforces the same evaluator-identity and
    valid-hole preconditions, and it recomputes the same derived values and increments
    `revision_round` exactly as the first submission did."
    PRD §3.3: "On success the register recomputes both percolation-rate variants and the
    soil loading rate, and increments `revision_round` by 1 — the counter tracks how many
    times this evaluation has entered review and starts at 0."

    Design: Difficulty/non_linear_state_machine/site_evaluation_reject_then_resubmit_reenters_review_and_bumps_revision_round
    """
    parcel = create_parcel(
        api, headers=applicant_headers, apn=unique_apn("0856-NL1"), site_address="6 Loop Lane"
    )
    evaluation = create_submitted_site_evaluation(api, parcel["id"])
    assert evaluation["revision_round"] == 1

    rejected = validate_success(
        api.review_site_evaluation(
            evaluation["id"],
            {"decision": "REJECT", "review_note": "Second hole required"},
            ehs_reviewer_headers,
        ),
        200,
    )
    assert rejected["status"] == "REJECTED"
    assert rejected["revision_round"] == 1

    add_perc_hole(
        api, evaluation["id"], hole_number=2, drop_inches=6, elapsed_minutes=90, presoak_ok=True
    )
    resubmitted = validate_success(
        api.submit_site_evaluation(evaluation["id"], design_professional_headers), 200
    )
    assert resubmitted["status"] == "SUBMITTED"

    approved = validate_success(
        api.review_site_evaluation(
            evaluation["id"],
            {"decision": "APPROVE", "review_note": "Accepted on resubmission"},
            ehs_reviewer_headers,
        ),
        200,
    )
    assert approved["status"] == "APPROVED"
    assert approved["revision_round"] == 2, (
        "the evaluation entered review twice, so the counter reads 2 rather than 1"
    )


def test_revision_loop_recomputes_both_rate_variants_and_overwrites_the_note(api, applicant_headers, design_professional_headers, ehs_reviewer_headers):
    """PRD §3.3: "Review is recorded by an `EnvironmentalHealthSpecialist` as a
    `decision` of either `APPROVE` or `REJECT`, with an optional `review_note` free-text
    explanation that is stored on the evaluation and overwrites whatever note the
    previous review left; before the first review it is null."
    PRD §3.3: "Note the rounding order — each hole's rate is rounded to two decimals
    first, and the mean of those already-rounded values is then rounded to two decimals
    again."

    Design: Difficulty/non_linear_state_machine/site_evaluation_reject_then_resubmit_reenters_review_and_bumps_revision_round
    """
    parcel = create_parcel(
        api, headers=applicant_headers, apn=unique_apn("0856-NL1B"), site_address="6 Loop Lane"
    )
    evaluation = create_submitted_site_evaluation(api, parcel["id"])
    assert evaluation["review_note"] is None, "there is no note before the first review"

    validate_success(
        api.review_site_evaluation(
            evaluation["id"],
            {"decision": "REJECT", "review_note": "Second hole required"},
            ehs_reviewer_headers,
        ),
        200,
    )
    add_perc_hole(
        api, evaluation["id"], hole_number=2, drop_inches=6, elapsed_minutes=90, presoak_ok=True
    )
    validate_success(api.submit_site_evaluation(evaluation["id"], design_professional_headers), 200)
    approved = validate_success(
        api.review_site_evaluation(
            evaluation["id"],
            {"decision": "APPROVE", "review_note": "Accepted on resubmission"},
            ehs_reviewer_headers,
        ),
        200,
    )

    assert approved["preliminary_perc_rate_min_per_in"] == pytest.approx(18.5), (
        "the mean of the 22.00 and 15.00 hole rates"
    )
    assert approved["certified_perc_rate_min_per_in"] == pytest.approx(22.0)
    assert approved["review_note"] == "Accepted on resubmission"
