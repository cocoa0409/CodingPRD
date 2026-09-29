"""Assessment QA rework, condition input rules and the advance-to-decision gate.

Enhanced review turns on two authored artefacts — the cumulative impact
assessment and the permit conditions hung off it — and on the gate that will not
let a file leave review until both the assessment and the comment period are done.
"""

from test_helpers import (
    APP_ENHANCED_REVIEW,
    ANALYST_HEADERS,
    ApiErrorId,
    ASSESSMENT_ACCEPTED,
    ASSESSMENT_DRAFT,
    CONDITION_ADDITIONAL_CONTROL,
    CONDITION_MONITORING,
    CONDITION_VOIDED,
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    METHOD_REFINED,
    PLAN_OPEN,
    QA_USER_ID,
    add_condition,
    assert_amount,
    assert_amounts,
    assert_field,
    assert_no_content,
    assert_page,
    assert_ratio,
    assert_rejected,
    assessment_payload,
    condition_payload,
    find_assessment,
    find_condition,
    open_plan,
    qa_return_assessment,
    read_application,
    read_plan,
    revise_assessment_payload,
    submit_assessment_for_qa,
    validate_success,
)


class TestAssessmentQaRework:
    """PRD §3.3 lets a returned assessment be revised onto another method."""

    def test_returned_assessment_revised_to_refined_recomputes_the_index(
        self, api, app_a_screening_assessment
    ):
        """Revising onto `REFINED` re-runs the whole pinned index computation.

        PRD §3.3: "An analyst closes the cycle by **revising** a `RETURNED`
        assessment, moving it `RETURNED → DRAFT`, re-stamping `author_user_id`
        with the reviser's `X-User-ID`, and recomputing the index against the
        current method inputs (`method`, `dispersion_factor` and
        `receptor_distance_m` may all be re-supplied) and the area's current
        scores."
        PRD §3.3: "for `REFINED` a distance decay is chosen first — 1.00 when
        `receptor_distance_m` is at most 300 metres, otherwise 0.75 when it is at
        most 800 metres, otherwise 0.50 — and `exposure_factor` is
        `dispersion_factor` multiplied by that decay, rounded half up to four
        decimals."
        PRD §3.3: "`disproportionate_flag` is true when `cumulative_impact_index`
        is **at least 70.00**."

        Design: Corner/state_machines/assessment_returned_then_revised_to_refined_recomputes_index
        """
        state = app_a_screening_assessment
        before = find_assessment(api, state["app_id"], state["assessment_id"])
        assert_amount(
            before.get("cumulative_impact_index"), 81.82, "cumulative_impact_index"
        )
        assert_field(before, "disproportionate_flag", True)

        submit_assessment_for_qa(api, state)
        qa_return_assessment(api, state, note="Submit dispersion modelling")

        response = api.revise_assessment(
            state["assessment_id"],
            revise_assessment_payload(
                method=METHOD_REFINED, dispersion_factor=0.60, receptor_distance_m=500
            ),
            ANALYST_HEADERS,
        )

        revised = validate_success(response)
        assert_field(revised, "status", ASSESSMENT_DRAFT)
        assert_field(revised, "method", METHOD_REFINED)
        assert_field(revised, "qa_user_id", QA_USER_ID)
        assert_field(revised, "disproportionate_flag", False)
        assert_field(revised, "data_confidence", CONFIDENCE_HIGH)
        assert_ratio(revised.get("exposure_factor"), 0.4500, "exposure_factor")
        assert_amounts(
            revised,
            {
                "baseline_burden_score": 74.03,
                "cumulative_impact_index": 65.32,
            },
        )

    def test_refined_assessment_without_dispersion_inputs_is_rejected(
        self, api, area_k_screened
    ):
        """`REFINED` needs both modelling inputs, so neither one is optional.

        PRD §3.3: "`REFINED` is used when dispersion modelling has been submitted,
        and it requires **both** `dispersion_factor` (a modelled attenuation
        between 0.10 and 1.00 inclusive) and `receptor_distance_m` (the whole
        number of metres to the nearest sensitive receptor, at least 0); a refined
        assessment missing either input is refused with
        `ERR_REFINED_INPUTS_REQUIRED`."

        Design: Corner/errors/refined_assessment_without_dispersion_inputs_rejected
        """
        state = area_k_screened
        response = api.create_assessment(
            assessment_payload(
                permit_application_id=state["app_id"],
                expected_application_version=state["v_screen"],
                method=METHOD_REFINED,
            ),
            ANALYST_HEADERS,
        )

        assert_rejected(response, ApiErrorId.REFINED_INPUTS_REQUIRED)

        application = read_application(api, state["app_id"])
        assert_field(application, "version", state["v_screen"])
        assert_amount(
            application.get("pre_mitigation_index"), 0.00, "pre_mitigation_index"
        )
        assert_page(
            api.list_application_assessments(state["app_id"], ANALYST_HEADERS),
            expected_rows=0,
            expected_total=0,
            expected_has_more=False,
        )


class TestConditionInputRules:
    """PRD §3.6 makes each condition family's extra input mandatory."""

    def test_monitoring_condition_without_frequency_is_rejected(
        self, api, area_k_screened
    ):
        """A monitoring condition must say how often the monitoring happens.

        PRD §3.6: "Both of those requirements are strict: a monitoring condition
        without `monitoring_frequency`, or a community-benefit condition without
        `benefit_value_usd`, is refused with `ERR_CONDITION_INPUTS_REQUIRED`."

        Design: Corner/validations/monitoring_condition_without_frequency_rejected
        """
        state = area_k_screened
        response = api.create_permit_condition(
            condition_payload(
                permit_application_id=state["app_id"],
                condition_type=CONDITION_MONITORING,
                reduction_tpy=10.00,
                enforceable=True,
                expected_application_version=state["v_screen"],
            ),
            ANALYST_HEADERS,
        )

        assert_rejected(response, ApiErrorId.CONDITION_INPUTS_REQUIRED)

        application = read_application(api, state["app_id"])
        assert_amount(
            application.get("total_mitigation_credit_tpy"),
            0.00,
            "total_mitigation_credit_tpy",
        )
        assert_field(application, "version", state["v_screen"])
        assert_page(
            api.list_application_conditions(state["app_id"], ANALYST_HEADERS),
            expected_rows=0,
            expected_total=0,
            expected_has_more=False,
        )


class TestConditionVoiding:
    """PRD §3.6 makes voiding a soft delete that rolls the arithmetic back."""

    def test_condition_delete_voids_the_row_and_restores_the_residual(
        self, api, area_k_assessment_accepted
    ):
        """The row survives as `VOIDED` and the residual climbs back to the index.

        PRD §3.6: "Voiding a condition moves it `ACTIVE → VOIDED`, recomputes the
        same two figures and increments the application's `version` by 1; voiding
        an already-voided condition is refused with
        `ERR_INVALID_CONDITION_STATE`."
        PRD §3.6: "Voided conditions are excluded from the sum entirely."
        PRD §3.6: "Finally, `residual_impact_index` is `pre_mitigation_index`
        multiplied by one minus the effective reduction, rounded half up to two
        decimals."

        Design: Corner/endpoints/condition_delete_voids_the_row_and_restores_the_residual
        """
        state = area_k_assessment_accepted
        condition = add_condition(
            api, state, CONDITION_ADDITIONAL_CONTROL, reduction_tpy=5.00, enforceable=True
        )
        with_condition = read_application(api, state["app_id"])
        assert_amounts(
            with_condition,
            {
                "pre_mitigation_index": 7.50,
                "total_mitigation_credit_tpy": 5.00,
                "residual_impact_index": 5.63,
            },
        )

        response = api.void_permit_condition(condition["id"], ANALYST_HEADERS)

        assert_no_content(response)

        voided = find_condition(api, state["app_id"], condition["id"])
        assert_field(voided, "status", CONDITION_VOIDED)
        assert_amount(voided.get("credit_tpy"), 5.00, "credit_tpy")

        application = read_application(api, state["app_id"])
        assert_amounts(
            application,
            {
                "total_mitigation_credit_tpy": 0.00,
                "residual_impact_index": 7.50,
                "pre_mitigation_index": 7.50,
            },
        )
        rows = assert_page(
            api.list_application_conditions(state["app_id"], ANALYST_HEADERS),
            expected_rows=1,
            expected_total=1,
            expected_has_more=False,
        )
        assert_field(rows[0], "status", CONDITION_VOIDED)


class TestAdvanceToDecisionGate:
    """PRD §3.2 holds an enhanced file in review until the plan is closed."""

    def test_advance_to_decision_is_blocked_while_the_plan_is_open(
        self, api, area_k_assessment_accepted
    ):
        """An accepted assessment is not enough while the comment period runs.

        PRD §3.2: "An `ENHANCED_REVIEW` application moves `ENHANCED_REVIEW →
        PENDING_DECISION` only when its governing cumulative impact assessment
        exists and is `ACCEPTED` — otherwise `ERR_ASSESSMENT_NOT_ACCEPTED` — and
        only when the application's non-cancelled participation plan is `CLOSED`
        — otherwise `ERR_PARTICIPATION_NOT_CLOSED`."
        PRD §3.3: "`data_confidence` is `LOW` when the area has no qualifying
        indicators at all — an `active_indicator_count` of 0 — or when the area's
        `data_status` is `STALE`; otherwise it is `HIGH`."

        Design: Corner/validations/advance_to_decision_blocked_while_plan_still_open
        """
        state = area_k_assessment_accepted
        open_plan(api, state, comment_start_date="2026-08-01")

        response = api.advance_to_decision(state["app_id"], ANALYST_HEADERS)

        assert_rejected(response, ApiErrorId.PARTICIPATION_NOT_CLOSED)

        assert_field(read_application(api, state["app_id"]), "status", APP_ENHANCED_REVIEW)

        assessment = find_assessment(api, state["app_id"], state["assessment_id"])
        assert_field(assessment, "status", ASSESSMENT_ACCEPTED)
        assert_field(assessment, "data_confidence", CONFIDENCE_LOW)
        assert_amount(
            assessment.get("cumulative_impact_index"), 7.50, "cumulative_impact_index"
        )

        assert_field(read_plan(api, state["plan_id"]), "status", PLAN_OPEN)
