"""The evaluation's two independent dimensions and its derived overall status, plus the
two compensating actions that refuse to fire a second time."""

import pytest

from test_helpers import (
    ANALYST_HEADERS,
    ANALYST_USER_ID,
    AWARD_AWARDED,
    AWARD_REVOKED,
    DEPUTY_HEADERS,
    DISCIPLINE_CLEAR,
    OVERALL_COMPLETE,
    OVERALL_IN_PROGRESS,
    PERMIT_REVOKED,
    REVIEW_PENDING,
    SCOPE_DEFICIENT,
    ApiErrorId,
    assert_application_fields,
    assert_evaluation_fields,
    assert_permit_fields,
    discipline_finding_payload,
    make_evaluator_headers,
    permit_revocation_payload,
    scope_review_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

WITHDRAWAL = "APPLICANT_WITHDREW"


@pytest.fixture
def open_evaluation_with_a_booked_reviewer(setup):
    """A nursing file under review whose evaluation still has both dimensions PENDING,
    with a reviewer already booked so the discipline finding can land."""
    profession = setup.profession()
    applicant = setup.applicant(full_name="Mona Iqbal")
    credential = setup.credential(applicant["id"], license_number="OK-12007")
    application = setup.application(applicant["id"], profession["id"], credential["id"])
    setup.submit(application["id"], applicant["id"])
    evaluation = setup.evaluation(application["id"], credential["id"])
    evaluator = setup.evaluator(full_name="Oona Lahti", profession_code="RN")
    setup.review_assignment(
        evaluator["id"], application["id"], "2026-08-01T00:00:00Z", "2026-08-20T00:00:00Z"
    )
    return {
        "ap_id": applicant["id"],
        "app_id": application["id"],
        "eval_id": evaluation["id"],
        "evr_id": evaluator["id"],
    }


@pytest.fixture
def finalized_evaluation(setup, open_evaluation_with_a_booked_reviewer):
    """The same file with its evaluation resolved DEFICIENT_SCOPE / CLEAR and finalised
    at the startup instant, scoring 65.00 with no waiver."""
    env = open_evaluation_with_a_booked_reviewer
    setup.scope_review(env["eval_id"], SCOPE_DEFICIENT)
    setup.discipline_finding(env["eval_id"], env["evr_id"])
    setup.finalize(env["eval_id"])
    return env


@pytest.fixture
def revoked_permit(setup):
    """A settled nursing file whose bridging permit has already been revoked once at the
    applicant's own request."""
    profession = setup.profession()
    applicant = setup.applicant(full_name="Sami Toure")
    credential = setup.credential(applicant["id"], license_number="OK-12010")
    application = setup.application(applicant["id"], profession["id"], credential["id"])
    setup.submit(application["id"], applicant["id"])
    setup.pay(application["id"], applicant["id"], 48000)
    setup.evaluation(application["id"], credential["id"])
    permit = setup.permit(application["id"], "2026-08-01T00:00:00Z")
    setup.revoke_permit(permit["id"], WITHDRAWAL)
    return {"app_id": application["id"], "permit_id": permit["id"]}


@pytest.fixture
def revoked_credit_award(setup):
    """A veteran's submitted nursing file whose single credit award has already been
    revoked, returning the hours to the requirement."""
    profession = setup.profession()
    applicant = setup.applicant(full_name="Tariq Haile", military_status="VETERAN")
    credential = setup.credential(applicant["id"], license_number="OK-12011")
    record = setup.training_record(
        applicant["id"], documented_hours=133, source_document="JST-RN-133"
    )
    application = setup.application(applicant["id"], profession["id"], credential["id"])
    setup.submit(application["id"], applicant["id"])
    award = setup.credit_award(application["id"], record["id"])
    setup.revoke_credit_award(award["id"])
    return {"app_id": application["id"], "award_id": award["id"]}


class TestParallelReviewDimensions:
    def test_writing_the_scope_opinion_leaves_the_database_check_pending(
        self, api, open_evaluation_with_a_booked_reviewer, setup
    ):
        """PRD §3.5: "An evaluation advances along two dimensions that move
        independently of one another on the same row."  PRD §3.5: "Either outcome,
        `PENDING → EQUIVALENT` or `PENDING → DEFICIENT_SCOPE`, stamps the acting
        `X-User-ID` onto the evaluation's `reviewed_by_user_id` and onto the parent
        application's `scope_reviewed_by_user_id`, increments both the evaluation's
        `version` and the application's `version`, and recomputes `overall_status` —
        which stays `IN_PROGRESS`, because finalisation has not happened."  PRD §3.5:
        "The scope comparison itself is computed immediately at creation, not deferred to
        finalisation: `matched_scope_elements` lists those of the profession's
        `required_scope_elements` that also appear in the credential's `scope_elements`,
        and `missing_scope_elements` lists those that do not, both reported in the
        profession's own registration order."

        Design: Corner/state_machines/evaluation_parallel_dimensions_advance_independently
        """
        env = open_evaluation_with_a_booked_reviewer
        evaluation = validate_success(
            api.record_scope_review(
                env["eval_id"],
                scope_review_payload(SCOPE_DEFICIENT, note="PRESCRIBE missing"),
                ANALYST_HEADERS,
            ),
            200,
        )

        assert_evaluation_fields(
            evaluation,
            scope_review_status=SCOPE_DEFICIENT,
            discipline_review_status=REVIEW_PENDING,
            overall_status=OVERALL_IN_PROGRESS,
            finalized_at=None,
            matched_scope_elements=["ASSESS", "TREAT", "SUPERVISE"],
            missing_scope_elements=["PRESCRIBE"],
            reviewed_by_user_id=ANALYST_USER_ID,
        )
        assert_application_fields(
            setup.read_application(env["app_id"]), scope_reviewed_by_user_id=ANALYST_USER_ID
        )

    def test_both_dimensions_resolved_is_still_not_complete_until_finalisation(
        self, api, open_evaluation_with_a_booked_reviewer, setup
    ):
        """PRD §3.5: "`overall_status` is a pure function of three things on the row: it
        is `COMPLETE` exactly when `scope_review_status` is not `PENDING`,
        `discipline_review_status` is not `PENDING`, and `finalized_at` is not null, and
        it is `IN_PROGRESS` in every other case."  PRD §3.5: "Because `finalized_at` is
        one of the three conjuncts, resolving both dimensions is necessary but not
        sufficient — the analyst must still finalise."

        Design: Corner/state_machines/evaluation_overall_status_recomputed_when_second_dimension_lands
        """
        env = open_evaluation_with_a_booked_reviewer
        setup.scope_review(env["eval_id"], SCOPE_DEFICIENT)

        after_second_dimension = validate_success(
            api.record_discipline_finding(
                env["eval_id"],
                discipline_finding_payload(DISCIPLINE_CLEAR, ["NPDB"]),
                make_evaluator_headers(env["evr_id"]),
            ),
            200,
        )
        assert_evaluation_fields(
            after_second_dimension,
            scope_review_status=SCOPE_DEFICIENT,
            discipline_review_status=DISCIPLINE_CLEAR,
            overall_status=OVERALL_IN_PROGRESS,
            finalized_at=None,
        )

        finalised = validate_success(
            api.finalize_evaluation(env["eval_id"], {}, ANALYST_HEADERS), 200
        )
        assert_evaluation_fields(
            finalised,
            overall_status=OVERALL_COMPLETE,
            finalized_at="2026-08-01T00:00:00Z",
        )

    def test_an_unwaived_examination_leaves_the_whole_assessment_standing(
        self, finalized_evaluation, setup
    ):
        """PRD §3.5: "When and only when the waiver is granted, the seat fee the
        applicant was assessed at submission must come back."  PRD §3.5: "Finally,
        multiply the raw figure by 100, subtract the penalty, round the result half up to
        two decimal places, and clamp it into the closed range from 0.00 through 100.00 —
        the clamp is applied after the penalty, so a heavily penalised score floors at
        0.00 rather than going negative."

        Design: Corner/state_machines/evaluation_overall_status_recomputed_when_second_dimension_lands
        """
        env = finalized_evaluation

        assert_evaluation_fields(
            setup.read_evaluation(env["eval_id"]),
            equivalency_score=65.00,
            exam_waiver_granted=False,
        )
        assert_application_fields(
            setup.read_application(env["app_id"]), fee_balance_cents=48000
        )
        assert setup.ledger_meta(env["app_id"])["total_count"] == 2

    def test_a_finalised_evaluation_refuses_a_second_scope_opinion(
        self, api, finalized_evaluation, setup
    ):
        """PRD §3.5: "Recording it supplies a `decision` of either `EQUIVALENT` or
        `DEFICIENT_SCOPE` and an optional `note`, and requires that
        `scope_review_status` still be `PENDING`, that `finalized_at` still be null, and
        that the parent application be in `UNDER_REVIEW` or `DEFICIENT`."  PRD §2.8:
        "Evaluation write state — the evaluation has no `finalized_at` yet and the
        dimension being written is still `PENDING`; finalisation additionally requires
        both dimensions to be non-`PENDING`. `ERR_EVALUATION_ALREADY_FINALIZED`, 409.
        Applies to scope review, disciplinary finding and finalisation."

        Design: Corner/state_machines/scope_review_after_finalize_rejected
        """
        env = finalized_evaluation
        response = api.record_scope_review(
            env["eval_id"], scope_review_payload("EQUIVALENT"), ANALYST_HEADERS
        )

        validate_error(response, ApiErrorId.ERR_EVALUATION_ALREADY_FINALIZED.value, 409)
        assert_evaluation_fields(
            setup.read_evaluation(env["eval_id"]),
            scope_review_status=SCOPE_DEFICIENT,
            equivalency_score=65.00,
            exam_waiver_granted=False,
            overall_status=OVERALL_COMPLETE,
        )


class TestCompensatingActionsRefuseToRepeat:
    def test_revoking_an_already_revoked_permit_appends_no_second_reversal(
        self, api, revoked_permit, setup
    ):
        """PRD §3.8: "Revoking a permit that is not `ACTIVE` is refused with
        `ERR_PERMIT_NOT_ACTIVE`."  PRD §2.8: "Permit state — the targeted temporary
        permit is `ACTIVE`. `ERR_PERMIT_NOT_ACTIVE`, 409. Applies to permit revocation."

        Design: Corner/state_machines/permit_revoke_twice_second_call_rejected
        """
        env = revoked_permit
        response = api.revoke_temporary_permit(
            env["permit_id"], permit_revocation_payload(WITHDRAWAL), DEPUTY_HEADERS
        )

        validate_error(response, ApiErrorId.ERR_PERMIT_NOT_ACTIVE.value, 409)

        permits = setup.read_permits(env["app_id"])
        assert len(permits) == 1
        assert_permit_fields(
            permits[0],
            status=PERMIT_REVOKED,
            revoked_at="2026-08-01T00:00:00Z",
            revocation_reason_code=WITHDRAWAL,
        )
        assert setup.ledger_meta(env["app_id"])["total_count"] == 5
        assert_application_fields(setup.read_application(env["app_id"]), fee_balance_cents=0)

    def test_revoking_an_already_revoked_award_does_not_subtract_the_hours_twice(
        self, api, revoked_credit_award, setup
    ):
        """PRD §3.7: "Revoking an already-revoked award is refused with
        `ERR_CREDIT_AWARD_ALREADY_REVOKED`."  PRD §2.8: "Compensating-action state — the
        targeted credit award is still `AWARDED`, and the targeted disciplinary record
        still has `resolved` false. `ERR_CREDIT_AWARD_ALREADY_REVOKED` and
        `ERR_DISCIPLINARY_RECORD_ALREADY_RESOLVED` respectively, both 409."

        Design: Corner/state_machines/credit_award_revoke_on_already_revoked_rejected
        """
        env = revoked_credit_award
        response = api.revoke_credit_award(env["award_id"], {}, ANALYST_HEADERS)

        validate_error(response, ApiErrorId.ERR_CREDIT_AWARD_ALREADY_REVOKED.value, 409)

        award = setup.read_credit_award(env["award_id"])
        assert award["status"] == AWARD_REVOKED
        assert award["awarded_hours"] == 99.8
        assert_application_fields(
            setup.read_application(env["app_id"]),
            requirement_hours_satisfied=0.0,
            requirement_hours_remaining=240.0,
        )
        _rows, meta = validate_paginated(
            api.list_credit_awards(
                ANALYST_HEADERS, {"application_id": env["app_id"], "status": AWARD_AWARDED}
            )
        )
        assert meta["total_count"] == 0
