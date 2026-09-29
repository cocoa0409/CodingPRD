"""The substantive gates an approval must clear one at a time — a finalised evaluation,
credited hours, the profession's jurisprudence demand — and the temporal bound that keeps a
practice permit from starting before the clock."""

import pytest

from test_helpers import (
    ADMIN_HEADERS,
    ANALYST_HEADERS,
    APP_APPROVED,
    APP_UNDER_REVIEW,
    DEPUTY_HEADERS,
    DISCIPLINE_CLEAR,
    EXAM_JURISPRUDENCE,
    LICENSE_ACTIVE,
    OVERALL_COMPLETE,
    OVERALL_IN_PROGRESS,
    SCOPE_EQUIVALENT,
    ApiErrorId,
    assert_application_fields,
    assert_evaluation_fields,
    assert_instant_equals,
    assert_license_number,
    decision_payload,
    exam_result_payload,
    temporary_permit_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

OCCUPATIONAL_THERAPIST = {
    "profession_code": "OT",
    "title": "Occupational Therapist",
    "required_scope_elements": ["EVAL", "TREAT"],
    "critical_scope_elements": [],
    "required_practice_hours": 1000,
    "requirement_hours_total": 60.0,
    "exam_waiver_min_score": 99.00,
    "jurisprudence_exam_required": False,
    "universal_recognition_min_residency_months": 12,
    "standard_processing_days": 90,
    "base_fee_cents": 18000,
    "endorsement_fee_cents": 5000,
    "exam_fee_cents": 4000,
    "jurisprudence_fee_cents": 0,
    "permit_fee_cents": 3000,
    "expedite_surcharge_pct": 0.10,
}

MASSAGE_THERAPIST = {
    "profession_code": "LMT",
    "title": "Licensed Massage Therapist",
    "required_scope_elements": ["EVAL", "TREAT"],
    "critical_scope_elements": [],
    "required_practice_hours": 1000,
    "requirement_hours_total": 60.0,
    "exam_waiver_min_score": 70.00,
    "jurisprudence_exam_required": True,
    "universal_recognition_min_residency_months": 12,
    "standard_processing_days": 60,
    "base_fee_cents": 15000,
    "endorsement_fee_cents": 5000,
    "exam_fee_cents": 4000,
    "jurisprudence_fee_cents": 5000,
    "permit_fee_cents": 3000,
    "expedite_surcharge_pct": 0.10,
}


@pytest.fixture
def half_reviewed_nursing_file(setup):
    """A submitted nursing endorsement whose evaluation carries an analyst's scope opinion
    and nothing else, leaving the row IN_PROGRESS."""
    profession = setup.profession()
    applicant = setup.applicant(full_name="Sonia Vlad")
    credential = setup.credential(
        applicant["id"],
        license_number="OK-14011",
        # the profession nominates PRESCRIBE as critical, so an admissible
        # EQUIVALENT scope opinion requires the credential to grant it
        scope_elements=["ASSESS", "TREAT", "PRESCRIBE", "SUPERVISE"],
        practice_hours=1200,
        issued_at="2020-05-01T00:00:00Z",
    )
    application = setup.application(applicant["id"], profession["id"], credential["id"])
    setup.submit(application["id"], applicant["id"])
    evaluation = setup.evaluation(application["id"], credential["id"])
    setup.scope_review(evaluation["id"], SCOPE_EQUIVALENT)
    return {"app_id": application["id"], "eval_id": evaluation["id"]}


@pytest.fixture
def settled_therapy_file_with_no_credited_hours(setup):
    """An occupational-therapy file paid down to zero with a finalised evaluation, but
    holding no service record and therefore no credit award."""
    profession = setup.profession(**OCCUPATIONAL_THERAPIST)
    applicant = setup.applicant(full_name="Timo Rask")
    credential = setup.credential(
        applicant["id"],
        license_number="OK-14012",
        scope_elements=["EVAL", "TREAT"],
        practice_hours=865,
        issued_at="2021-01-01T00:00:00Z",
    )
    application = setup.application(applicant["id"], profession["id"], credential["id"])
    setup.submit(application["id"], applicant["id"])
    setup.pay(application["id"], applicant["id"], 27000)
    evaluation = setup.evaluation(application["id"], credential["id"])
    setup.scope_review(evaluation["id"], SCOPE_EQUIVALENT)
    evaluator = setup.evaluator(full_name="Ulla Grimm", profession_code="OT")
    setup.review_assignment(
        evaluator["id"], application["id"], "2026-08-01T00:00:00Z", "2026-08-20T00:00:00Z"
    )
    setup.discipline_finding(evaluation["id"], evaluator["id"], DISCIPLINE_CLEAR)
    setup.finalize(evaluation["id"])
    return {"app_id": application["id"], "eval_id": evaluation["id"]}


@pytest.fixture
def massage_file_awaiting_only_the_jurisprudence_exam(setup):
    """A massage-therapy file with every approval gate but the jurisprudence demand
    satisfied: hours fully credited, evaluation finalised with the seat-fee waiver granted,
    and the balance settled."""
    profession = setup.profession(**MASSAGE_THERAPIST)
    applicant = setup.applicant(full_name="Vidal Cruz")
    credential = setup.credential(
        applicant["id"],
        license_number="OK-14013",
        scope_elements=["EVAL", "TREAT"],
        practice_hours=400,
        issued_at="2021-01-01T00:00:00Z",
    )
    record = setup.training_record(
        applicant["id"], documented_hours=80, source_document="JST-LMT-80"
    )
    application = setup.application(applicant["id"], profession["id"], credential["id"])
    setup.submit(application["id"], applicant["id"])
    setup.credit_award(application["id"], record["id"])
    evaluation = setup.evaluation(application["id"], credential["id"])
    setup.scope_review(evaluation["id"], SCOPE_EQUIVALENT)
    evaluator = setup.evaluator(full_name="Wanda Krol", profession_code="LMT")
    setup.review_assignment(
        evaluator["id"], application["id"], "2026-08-01T00:00:00Z", "2026-08-20T00:00:00Z"
    )
    setup.discipline_finding(evaluation["id"], evaluator["id"], DISCIPLINE_CLEAR)
    setup.finalize(evaluation["id"])
    setup.pay(application["id"], applicant["id"], 25000)
    return {"app_id": application["id"], "eval_id": evaluation["id"]}


@pytest.fixture
def file_under_review_with_the_clock_moved_on(setup):
    """A nursing endorsement under review with its full 48000-cent balance outstanding,
    read after the logical clock has been wound forward four days to 2026-08-05."""
    profession = setup.profession()
    applicant = setup.applicant(full_name="Yusuf Demir")
    credential = setup.credential(
        applicant["id"],
        license_number="OK-14014",
        scope_elements=["ASSESS", "TREAT", "SUPERVISE"],
        practice_hours=1200,
        issued_at="2020-05-01T00:00:00Z",
    )
    application = setup.application(applicant["id"], profession["id"], credential["id"])
    setup.submit(application["id"], applicant["id"])
    setup.evaluation(application["id"], credential["id"])
    setup.set_clock("2026-08-05T00:00:00Z")
    return {
        "app_id": application["id"],
        "app_version": setup.application_version(application["id"]),
    }


class TestEvaluationCompletenessGate:
    def test_an_evaluation_that_merely_exists_does_not_open_the_approval(
        self, api, half_reviewed_nursing_file, setup
    ):
        """PRD §3.9: "`APPROVE` carries six substantive gates beyond state and segregation
        of duties, and they are evaluated in the order §2.8 fixes."  PRD §2.8: "Evaluation
        completeness — the application's credential evaluation exists and its
        `overall_status` is `COMPLETE`. `ERR_EVALUATION_NOT_COMPLETE`, 422. Applies to a
        board decision of `APPROVE`."  PRD §3.5: "`overall_status` is a pure function of
        three things on the row: it is `COMPLETE` exactly when `scope_review_status` is not
        `PENDING`, `discipline_review_status` is not `PENDING`, and `finalized_at` is not
        null, and it is `IN_PROGRESS` in every other case."

        Design: Corner/validations/evaluation_not_complete_blocks_approval
        """
        env = half_reviewed_nursing_file
        response = api.issue_decision(
            env["app_id"],
            decision_payload(memo="premature approval"),
            DEPUTY_HEADERS,
        )

        validate_error(response, ApiErrorId.ERR_EVALUATION_NOT_COMPLETE.value, 422)

        assert_evaluation_fields(
            setup.read_evaluation(env["eval_id"]),
            overall_status=OVERALL_IN_PROGRESS,
            finalized_at=None,
        )
        assert_application_fields(
            setup.read_application(env["app_id"]),
            status=APP_UNDER_REVIEW,
            decided_at=None,
        )
        _rows, meta = validate_paginated(
            api.list_licenses(ANALYST_HEADERS, {"application_id": env["app_id"]})
        )
        assert meta["total_count"] == 0


class TestRequirementHoursGate:
    def test_a_finalised_evaluation_and_a_clear_balance_still_leave_the_hours_owing(
        self, api, settled_therapy_file_with_no_credited_hours, setup
    ):
        """PRD §2.8: "Requirement hours — the application's `requirement_hours_remaining`
        is exactly 0.0. `ERR_REQUIREMENT_HOURS_UNSATISFIED`, 422. Applies to a board
        decision of `APPROVE`."  PRD §3.4: "`requirement_hours_remaining` is recomputed as
        the profession's `requirement_hours_total` less `requirement_hours_satisfied`, and
        the application's `version` increments by one."  PRD §3.9: "`requirement_hours_remaining`
        must be exactly 0.0 (`ERR_REQUIREMENT_HOURS_UNSATISFIED`)."

        Design: Corner/validations/requirement_hours_unsatisfied_blocks_approval
        """
        env = settled_therapy_file_with_no_credited_hours
        response = api.issue_decision(
            env["app_id"],
            decision_payload(memo="hours not yet credited"),
            DEPUTY_HEADERS,
        )

        validate_error(response, ApiErrorId.ERR_REQUIREMENT_HOURS_UNSATISFIED.value, 422)

        assert_application_fields(
            setup.read_application(env["app_id"]),
            requirement_hours_satisfied=0.0,
            requirement_hours_remaining=60.0,
            fee_balance_cents=0,
            status=APP_UNDER_REVIEW,
            decided_at=None,
        )
        assert_evaluation_fields(
            setup.read_evaluation(env["eval_id"]), overall_status=OVERALL_COMPLETE
        )
        _rows, meta = validate_paginated(
            api.list_licenses(ANALYST_HEADERS, {"application_id": env["app_id"]})
        )
        assert meta["total_count"] == 0


class TestJurisprudenceGate:
    def test_a_profession_that_demands_jurisprudence_refuses_the_last_step(
        self, api, massage_file_awaiting_only_the_jurisprudence_exam, setup
    ):
        """PRD §2.8: "Jurisprudence examination — either the profession's
        `jurisprudence_exam_required` is false, or the application's
        `jurisprudence_exam_passed` is true, or an unexpired reciprocal agreement for this
        profession and the applicant's state has `jurisprudence_waiver_allowed` true.
        `ERR_JURISPRUDENCE_EXAM_REQUIRED`, 422. Applies to a board decision of `APPROVE`."
        PRD §3.5: "`exam_waiver_granted` is true when the computed `equivalency_score` is at
        or above the profession's `exam_waiver_min_score` — the threshold itself grants the
        waiver — **or** when an unexpired reciprocal agreement exists for this profession
        whose `partner_state` equals the applicant's `state_code` and whose
        `exam_waiver_allowed` is true, in which case the compact grants the waiver
        irrespective of the score."

        Design: Corner/validations/jurisprudence_exam_gate_keyed_to_profession_flag
        """
        env = massage_file_awaiting_only_the_jurisprudence_exam
        response = api.issue_decision(
            env["app_id"],
            decision_payload(memo="jurisprudence outstanding"),
            DEPUTY_HEADERS,
        )

        validate_error(response, ApiErrorId.ERR_JURISPRUDENCE_EXAM_REQUIRED.value, 422)

        assert_evaluation_fields(
            setup.read_evaluation(env["eval_id"]),
            equivalency_score=85.00,
            exam_waiver_granted=True,
        )
        assert_application_fields(
            setup.read_application(env["app_id"]),
            requirement_hours_remaining=0.0,
            fee_balance_cents=0,
            jurisprudence_exam_passed=False,
            status=APP_UNDER_REVIEW,
        )

    def test_recording_the_jurisprudence_pass_alone_carries_the_file_to_a_licence(
        self, api, massage_file_awaiting_only_the_jurisprudence_exam, setup
    ):
        """PRD §3.5: "An `exam_kind` of `NATIONAL` writes `passed` into the application's
        `national_exam_passed`; an `exam_kind` of `JURISPRUDENCE` writes it into
        `jurisprudence_exam_passed`."  PRD §3.9: "A new `License` row is created carrying
        the `application_id` it came from and the `profession_id` copied from that
        application, with `status` `ACTIVE` — licences are minted active and are not
        deactivated in this release — an `issued_at` equal to the logical clock, and an
        `expires_at` of `issued_at` advanced by a licence term of 730 days, which is two
        365-day years."  PRD §3.9: "Its `license_number` is minted as the profession's
        `profession_code`, then a hyphen, then a zero-padded six-digit mint sequence; the
        sequence advances by one for each licence row in `created_at` ascending order and
        begins at `000001`."

        Design: Corner/validations/jurisprudence_exam_gate_keyed_to_profession_flag
        """
        env = massage_file_awaiting_only_the_jurisprudence_exam
        validate_success(
            api.record_exam_result(
                env["app_id"],
                exam_result_payload(exam_kind=EXAM_JURISPRUDENCE, passed=True, score=88.00),
                ADMIN_HEADERS,
            ),
            200,
        )
        approved = validate_success(
            api.issue_decision(
                env["app_id"],
                decision_payload(memo="jurisprudence cleared"),
                DEPUTY_HEADERS,
            ),
            200,
        )

        assert_application_fields(
            approved,
            status=APP_APPROVED,
            jurisprudence_exam_passed=True,
            national_exam_passed=False,
            review_deadline_at="2026-09-30T00:00:00Z",
            processing_standard_met=True,
            processing_elapsed_days=0,
        )

        licenses, meta = validate_paginated(
            api.list_licenses(ANALYST_HEADERS, {"application_id": env["app_id"]})
        )
        assert meta["total_count"] == 1
        assert_license_number(licenses[0]["license_number"], "LMT", 1)
        assert licenses[0]["status"] == LICENSE_ACTIVE
        assert_instant_equals(
            licenses[0]["issued_at"], "2026-08-01T00:00:00Z", "licence.issued_at"
        )
        assert_instant_equals(
            licenses[0]["expires_at"], "2028-07-31T00:00:00Z", "licence.expires_at"
        )


class TestPermitTemporalBound:
    def test_a_permit_backdated_before_the_clock_is_refused_on_temporal_grounds(
        self, api, file_under_review_with_the_clock_moved_on, setup
    ):
        """PRD §3.8: "The requested `effective_at` must be at or after the logical clock —
        a permit may start now or in the future but never in the past — failing as
        `ERR_PERMIT_EFFECTIVE_IN_PAST`."  PRD §2.8: "Permit start not in the past — the
        requested `effective_at` is at or after the logical clock.
        `ERR_PERMIT_EFFECTIVE_IN_PAST`, 422. Applies to permit issuance."  PRD §2.8: "The
        system therefore evaluates checks in one fixed global order and the **first**
        violated check decides the response; no later check can mask an earlier one, and no
        earlier success excuses a later failure."

        Design: Corner/validations/permit_effective_in_past_rejected
        """
        env = file_under_review_with_the_clock_moved_on
        response = api.create_temporary_permit(
            temporary_permit_payload(
                env["app_id"], "2026-08-01T00:00:00Z", env["app_version"]
            ),
            ANALYST_HEADERS,
        )

        validate_error(response, ApiErrorId.ERR_PERMIT_EFFECTIVE_IN_PAST.value, 422)

        _permits, permit_meta = validate_paginated(
            api.list_application_permits(env["app_id"], ANALYST_HEADERS, None)
        )
        assert permit_meta["total_count"] == 0
        assert_application_fields(
            setup.read_application(env["app_id"]), fee_balance_cents=48000
        )
        assert setup.ledger_meta(env["app_id"])["total_count"] == 2
