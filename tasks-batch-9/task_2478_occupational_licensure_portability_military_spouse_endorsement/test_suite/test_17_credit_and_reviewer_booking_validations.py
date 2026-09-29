"""Cross-entity gates around crediting service and booking reviewers: whose transcript
may be credited, which reviewer may be booked, how many bookings one reviewer may hold,
and how long a booked reviewer's window stays open."""

import pytest

from test_helpers import (
    ADMIN_HEADERS,
    ANALYST_HEADERS,
    ASSIGNMENT_ASSIGNED,
    DISCIPLINE_CLEAR,
    EVALUATOR_INACTIVE,
    MILITARY_VETERAN,
    OVERALL_IN_PROGRESS,
    REVIEW_PENDING,
    ApiErrorId,
    assert_application_fields,
    assert_assignment_fields,
    assert_evaluation_fields,
    assert_evaluator_fields,
    credit_award_payload,
    discipline_finding_payload,
    make_evaluator_headers,
    review_assignment_payload,
    validate_error,
    validate_paginated,
)

PHYSICAL_THERAPIST = {
    "profession_code": "PT",
    "title": "Physical Therapist",
    "required_scope_elements": ["EVAL", "TREAT"],
    "critical_scope_elements": [],
    "required_practice_hours": 1000,
    "requirement_hours_total": 400.0,
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


@pytest.fixture
def two_veterans_one_file(setup):
    """Veteran P with a submitted physical-therapy file and no service records, alongside
    veteran Q who owns a verified 200-hour service record and no file at all."""
    profession = setup.profession(**PHYSICAL_THERAPIST)
    filer = setup.applicant(full_name="Hana Ozdemir", military_status=MILITARY_VETERAN)
    credential = setup.credential(
        filer["id"],
        license_number="OK-14005",
        scope_elements=["EVAL", "TREAT"],
        practice_hours=400,
        issued_at="2021-01-01T00:00:00Z",
    )
    application = setup.application(filer["id"], profession["id"], credential["id"])
    setup.submit(application["id"], filer["id"])

    stranger = setup.applicant(full_name="Ivo Zanetti", military_status=MILITARY_VETERAN)
    record = setup.training_record(
        stranger["id"], documented_hours=200, source_document="JST-Q-200"
    )
    return {
        "app_id": application["id"],
        "stranger_id": stranger["id"],
        "stranger_tr_id": record["id"],
    }


@pytest.fixture
def nursing_file_and_a_therapy_reviewer(setup):
    """A submitted nursing file and an active reviewer credentialed for physical therapy
    instead."""
    profession = setup.profession()
    applicant = setup.applicant(full_name="Jonas Wirtz")
    credential = setup.credential(
        applicant["id"],
        license_number="OK-14006",
        scope_elements=["ASSESS", "TREAT", "SUPERVISE"],
        practice_hours=1200,
        issued_at="2020-05-01T00:00:00Z",
    )
    application = setup.application(applicant["id"], profession["id"], credential["id"])
    setup.submit(application["id"], applicant["id"])
    evaluator = setup.evaluator(full_name="Kira Solberg", profession_code="PT")
    return {"app_id": application["id"], "evr_id": evaluator["id"]}


@pytest.fixture
def nursing_file_and_a_retired_reviewer(setup):
    """A submitted nursing file and a nursing reviewer who has gone inactive."""
    profession = setup.profession()
    applicant = setup.applicant(full_name="Lena Fournier")
    credential = setup.credential(
        applicant["id"],
        license_number="OK-14007",
        scope_elements=["ASSESS", "TREAT", "SUPERVISE"],
        practice_hours=1200,
        issued_at="2020-05-01T00:00:00Z",
    )
    application = setup.application(applicant["id"], profession["id"], credential["id"])
    setup.submit(application["id"], applicant["id"])
    evaluator = setup.evaluator(
        full_name="Milo Ferrara", profession_code="RN", status=EVALUATOR_INACTIVE
    )
    return {"app_id": application["id"], "evr_id": evaluator["id"]}


@pytest.fixture
def single_slot_reviewer_already_booked(setup):
    """Two unrelated submitted nursing files and one reviewer allowed a single concurrent
    review, already booked onto the first for the first five days of August."""
    profession = setup.profession()
    first = setup.applicant(full_name="Nadia Ruiz")
    first_credential = setup.credential(
        first["id"],
        license_number="OK-14008",
        scope_elements=["ASSESS", "TREAT", "SUPERVISE"],
        practice_hours=1200,
        issued_at="2020-05-01T00:00:00Z",
    )
    first_application = setup.application(
        first["id"], profession["id"], first_credential["id"]
    )
    setup.submit(first_application["id"], first["id"])

    second = setup.applicant(full_name="Oleg Sarkis")
    second_credential = setup.credential(
        second["id"],
        license_number="OK-14009",
        scope_elements=["ASSESS", "TREAT", "SUPERVISE"],
        practice_hours=1200,
        issued_at="2020-05-01T00:00:00Z",
    )
    second_application = setup.application(
        second["id"], profession["id"], second_credential["id"]
    )
    setup.submit(second_application["id"], second["id"])

    evaluator = setup.evaluator(
        full_name="Pia Norling", profession_code="RN", max_concurrent_reviews=1
    )
    assignment = setup.review_assignment(
        evaluator["id"],
        first_application["id"],
        "2026-08-01T00:00:00Z",
        "2026-08-05T00:00:00Z",
    )
    return {
        "evr_id": evaluator["id"],
        "second_app_id": second_application["id"],
        "first_assignment_id": assignment["id"],
    }


@pytest.fixture
def reviewer_whose_window_has_closed(setup):
    """A fresh evaluation waiting on its reviewer, whose booked window ended on 10 August
    while the logical clock now reads the eleventh."""
    profession = setup.profession()
    applicant = setup.applicant(full_name="Quim Estevez")
    credential = setup.credential(
        applicant["id"],
        license_number="OK-14010",
        scope_elements=["ASSESS", "TREAT", "SUPERVISE"],
        practice_hours=1200,
        issued_at="2020-05-01T00:00:00Z",
    )
    application = setup.application(applicant["id"], profession["id"], credential["id"])
    setup.submit(application["id"], applicant["id"])
    evaluation = setup.evaluation(application["id"], credential["id"])
    evaluator = setup.evaluator(full_name="Rui Baptista", profession_code="RN")
    assignment = setup.review_assignment(
        evaluator["id"], application["id"], "2026-08-01T00:00:00Z", "2026-08-10T00:00:00Z"
    )
    setup.set_clock("2026-08-11T00:00:00Z")
    return {
        "eval_id": evaluation["id"],
        "evr_id": evaluator["id"],
        "assignment_id": assignment["id"],
    }


class TestCreditOwnership:
    def test_one_applicants_service_record_cannot_credit_anothers_file(
        self, api, two_veterans_one_file, setup
    ):
        """PRD §3.7: "The application must be in `SUBMITTED`, `UNDER_REVIEW` or
        `DEFICIENT`; the training record must belong to the same applicant as the
        application, failing as `ERR_TRAINING_RECORD_APPLICANT_MISMATCH`; the record's
        `verified` flag must be true, failing as `ERR_TRAINING_RECORD_UNVERIFIED`; and no
        credit award with `status` `AWARDED` may already exist for that pair of application
        and training record, a duplicate being `ERR_TRAINING_RECORD_ALREADY_CREDITED`."
        PRD §2.8: "Training-record ownership match — the training record's `applicant_id`
        equals the application's `applicant_id`. `ERR_TRAINING_RECORD_APPLICANT_MISMATCH`,
        422. Applies to awarding credit."

        Design: Corner/validations/training_record_applicant_mismatch_rejected
        """
        env = two_veterans_one_file
        response = api.create_credit_award(
            credit_award_payload(env["app_id"], env["stranger_tr_id"]), ANALYST_HEADERS
        )

        validate_error(
            response, ApiErrorId.ERR_TRAINING_RECORD_APPLICANT_MISMATCH.value, 422
        )

        records, _meta = validate_paginated(
            api.list_training_records(env["stranger_id"], ADMIN_HEADERS, {"limit": 100})
        )
        stranger_record = next(
            row for row in records if row["id"] == env["stranger_tr_id"]
        )
        assert stranger_record["verified"] is True
        assert stranger_record["applicant_id"] == env["stranger_id"]

        _awards, meta = validate_paginated(
            api.list_credit_awards(ANALYST_HEADERS, {"application_id": env["app_id"]})
        )
        assert meta["total_count"] == 0
        assert_application_fields(
            setup.read_application(env["app_id"]), requirement_hours_satisfied=0.0
        )


class TestReviewerEligibility:
    def test_a_reviewer_credentialed_for_another_profession_may_not_be_booked(
        self, api, nursing_file_and_a_therapy_reviewer, setup
    ):
        """PRD §3.6: "The evaluator's `profession_code` must equal the `profession_code` of
        the application's profession, failing as `ERR_EVALUATOR_PROFESSION_MISMATCH`, and
        the evaluator's `status` must be `ACTIVE`, failing as `ERR_EVALUATOR_INACTIVE`."
        PRD §2.8: "Evaluator profession match — the evaluator's `profession_code` equals the
        `profession_code` of the application's profession.
        `ERR_EVALUATOR_PROFESSION_MISMATCH`, 422. Applies to review-assignment creation."

        Design: Corner/validations/evaluator_profession_mismatch_rejected
        """
        env = nursing_file_and_a_therapy_reviewer
        response = api.create_review_assignment(
            review_assignment_payload(
                env["evr_id"],
                env["app_id"],
                "2026-08-01T00:00:00Z",
                "2026-08-20T00:00:00Z",
                setup.evaluator_version(env["evr_id"]),
            ),
            ANALYST_HEADERS,
        )

        validate_error(response, ApiErrorId.ERR_EVALUATOR_PROFESSION_MISMATCH.value, 422)

        assert_evaluator_fields(
            setup.read_evaluator(env["evr_id"]), version=1, open_assignment_count=0
        )
        _rows, meta = validate_paginated(
            api.list_review_assignments(ANALYST_HEADERS, {"evaluator_id": env["evr_id"]})
        )
        assert meta["total_count"] == 0

    def test_an_inactive_reviewer_may_not_be_booked_even_for_their_own_profession(
        self, api, nursing_file_and_a_retired_reviewer, setup
    ):
        """PRD §2.8: "Evaluator standing — the evaluator's `status` is `ACTIVE`.
        `ERR_EVALUATOR_INACTIVE`, 422. Applies to review-assignment creation."  PRD §2.8:
        "The system therefore evaluates checks in one fixed global order and the **first**
        violated check decides the response; no later check can mask an earlier one, and no
        earlier success excuses a later failure."

        Design: Corner/validations/evaluator_inactive_assignment_rejected
        """
        env = nursing_file_and_a_retired_reviewer
        response = api.create_review_assignment(
            review_assignment_payload(
                env["evr_id"],
                env["app_id"],
                "2026-08-01T00:00:00Z",
                "2026-08-20T00:00:00Z",
                setup.evaluator_version(env["evr_id"]),
            ),
            ANALYST_HEADERS,
        )

        validate_error(response, ApiErrorId.ERR_EVALUATOR_INACTIVE.value, 422)

        assert_evaluator_fields(
            setup.read_evaluator(env["evr_id"]),
            status=EVALUATOR_INACTIVE,
            open_assignment_count=0,
            version=1,
        )
        _rows, meta = validate_paginated(
            api.list_review_assignments(ANALYST_HEADERS, {"evaluator_id": env["evr_id"]})
        )
        assert meta["total_count"] == 0

    def test_a_distant_second_window_still_exhausts_a_single_slot_reviewer(
        self, api, single_slot_reviewer_already_booked, setup
    ):
        """PRD §3.6: "Capacity is the last gate. The evaluator's `open_assignment_count`
        plus the one new booking must not exceed their `max_concurrent_reviews`, or the
        request is refused with `ERR_EVALUATOR_CAPACITY_EXCEEDED`."  PRD §3.6: "That count
        is itself derived rather than stored by hand: it is the number of review
        assignments of that evaluator whose `status` is `ASSIGNED`, with `COMPLETED` and
        `RELEASED` rows excluded."  PRD §2.8: "Evaluator capacity — the evaluator's
        `open_assignment_count` plus one must be at most their `max_concurrent_reviews`.
        `ERR_EVALUATOR_CAPACITY_EXCEEDED`, 409. Applies to review-assignment creation."

        Design: Corner/validations/evaluator_capacity_exceeded_by_aggregate_open_assignments
        """
        env = single_slot_reviewer_already_booked
        response = api.create_review_assignment(
            review_assignment_payload(
                env["evr_id"],
                env["second_app_id"],
                "2026-09-01T00:00:00Z",
                "2026-09-05T00:00:00Z",
                setup.evaluator_version(env["evr_id"]),
            ),
            ANALYST_HEADERS,
        )

        validate_error(response, ApiErrorId.ERR_EVALUATOR_CAPACITY_EXCEEDED.value, 409)

        assert_evaluator_fields(
            setup.read_evaluator(env["evr_id"]),
            open_assignment_count=1,
            max_concurrent_reviews=1,
        )
        rows, meta = validate_paginated(
            api.list_review_assignments(ANALYST_HEADERS, {"evaluator_id": env["evr_id"]})
        )
        assert meta["total_count"] == 1
        assert [row["id"] for row in rows] == [env["first_assignment_id"]]
        assert_assignment_fields(rows[0], status=ASSIGNMENT_ASSIGNED)


class TestReviewWindowLapse:
    def test_a_finding_filed_the_day_after_the_window_closed_is_refused(
        self, api, reviewer_whose_window_has_closed, setup
    ):
        """PRD §3.5: "The write requires that `discipline_review_status` still be
        `PENDING`, that `finalized_at` still be null, that a review assignment exist for
        this evaluation's application whose `evaluator_id` equals the caller's `X-User-ID`
        and whose `status` is `ASSIGNED` — otherwise `ERR_NO_OPEN_REVIEW_ASSIGNMENT` — and
        that the logical clock be at or before that assignment's `window_end_at`, a lapse
        being `ERR_REVIEW_WINDOW_LAPSED`."  PRD §2.8: "Review window still open — the
        logical clock is at or before that assignment's `window_end_at`.
        `ERR_REVIEW_WINDOW_LAPSED`, 422. Applies to recording the disciplinary finding."

        Design: Corner/validations/review_window_lapsed_discipline_finding_rejected
        """
        env = reviewer_whose_window_has_closed
        response = api.record_discipline_finding(
            env["eval_id"],
            discipline_finding_payload(DISCIPLINE_CLEAR, ["NPDB", "NURSYS"]),
            make_evaluator_headers(env["evr_id"]),
        )

        validate_error(response, ApiErrorId.ERR_REVIEW_WINDOW_LAPSED.value, 422)

        assert_assignment_fields(
            setup.read_assignment(env["assignment_id"]),
            status=ASSIGNMENT_ASSIGNED,
            window_end_at="2026-08-10T00:00:00Z",
        )
        assert_evaluation_fields(
            setup.read_evaluation(env["eval_id"]),
            discipline_review_status=REVIEW_PENDING,
            scope_review_status=REVIEW_PENDING,
            overall_status=OVERALL_IN_PROGRESS,
        )
