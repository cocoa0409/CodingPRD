"""The application's own state machine: where a file starts, what crossing the
submission gate does in one call, and the four ways a transition asked for from the
wrong state is refused."""

import pytest

from test_helpers import (
    ANALYST_HEADERS,
    APP_APPROVED,
    APP_DRAFT,
    APP_SUBMITTED,
    APP_UNDER_REVIEW,
    DECISION_APPROVE,
    DECISION_DENY,
    DEPUTY_HEADERS,
    DEPUTY_HEADERS_2,
    DEPUTY_USER_ID,
    ENTRY_ASSESSMENT,
    ENTRY_WAIVER_CREDIT,
    MEMO_ASSESSMENT,
    MEMO_WAIVER_CREDIT,
    MILITARY_VETERAN,
    SCOPE_EQUIVALENT,
    ApiErrorId,
    application_payload,
    assert_application_fields,
    assert_ledger_signature,
    assert_license_number,
    assert_memo,
    decision_payload,
    make_applicant_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

RD_PROFESSION = {
    "profession_code": "RD",
    "title": "Registered Dietitian",
    "required_scope_elements": ["ASSESS", "TREAT", "PRESCRIBE", "SUPERVISE"],
    "critical_scope_elements": [],
    "required_practice_hours": 2000,
    "requirement_hours_total": 100.0,
    "exam_waiver_min_score": 70.00,
    "jurisprudence_exam_required": False,
    "universal_recognition_min_residency_months": 12,
    "standard_processing_days": 90,
    "base_fee_cents": 40000,
    "endorsement_fee_cents": 6000,
    "exam_fee_cents": 6000,
    "jurisprudence_fee_cents": 0,
    "permit_fee_cents": 5000,
    "expedite_surcharge_pct": 0.10,
}


@pytest.fixture
def frame_for_one_nurse(setup):
    """One RN profession and one applicant holding a verified ACTIVE credential, ready
    to open a file."""
    profession = setup.profession()
    applicant = setup.applicant(full_name="Fritz Baum")
    credential = setup.credential(applicant["id"], license_number="OK-12001")
    return {
        "prof_id": profession["id"],
        "ap_id": applicant["id"],
        "cred_id": credential["id"],
    }


@pytest.fixture
def draft_endorsement(setup, frame_for_one_nurse):
    """One RN endorsement application freshly opened and never submitted."""
    application = setup.application(
        frame_for_one_nurse["ap_id"],
        frame_for_one_nurse["prof_id"],
        frame_for_one_nurse["cred_id"],
    )
    return {**frame_for_one_nurse, "app_id": application["id"]}


@pytest.fixture
def approved_dietitian(setup):
    """A veteran's dietitian file carried all the way to APPROVED by board deputy
    dep_1, with a licence minted and nothing owing."""
    profession = setup.profession(**RD_PROFESSION)
    applicant = setup.applicant(full_name="Kofi Mensah", military_status=MILITARY_VETERAN)
    credential = setup.credential(
        applicant["id"],
        license_number="OK-12006",
        practice_hours=800,
        issued_at="2022-02-01T00:00:00Z",
    )
    record = setup.training_record(
        applicant["id"], documented_hours=200, source_document="JST-RD-200"
    )
    application = setup.application(applicant["id"], profession["id"], credential["id"])
    setup.submit(application["id"], applicant["id"])
    award = setup.credit_award(application["id"], record["id"])
    evaluation = setup.evaluation(application["id"], credential["id"])
    setup.scope_review(evaluation["id"], SCOPE_EQUIVALENT)
    evaluator = setup.evaluator(full_name="Lise Aubert", profession_code="RD")
    setup.review_assignment(
        evaluator["id"], application["id"], "2026-08-01T00:00:00Z", "2026-08-20T00:00:00Z"
    )
    setup.discipline_finding(evaluation["id"], evaluator["id"])
    setup.finalize(evaluation["id"])
    setup.pay_off(application["id"], applicant["id"])
    setup.decide(application["id"], DECISION_APPROVE, DEPUTY_HEADERS)
    return {
        "app_id": application["id"],
        "eval_id": evaluation["id"],
        "award_id": award["id"],
    }


class TestSubmissionGate:
    def test_a_new_application_opens_in_draft_with_no_cycles_and_no_decision(
        self, api, frame_for_one_nurse
    ):
        """PRD §3.4: "A newly opened application is in `DRAFT`. Its `submitted_at`,
        `review_deadline_at` and `decided_at` are all null, its
        `processing_standard_met` is null, its `processing_elapsed_days` is 0, its
        `deficiency_cycle_count` is 0, its `statutory_waiver_pct` is 0.00, its
        `gross_total_cents` and `fee_balance_cents` are 0, its `national_exam_passed`
        and `jurisprudence_exam_passed` are both false, its `scope_reviewed_by_user_id`
        and `decided_by_user_id` are both null, its `requirement_hours_satisfied` is 0.0
        and its `requirement_hours_remaining` starts equal to the profession's full
        `requirement_hours_total`."  PRD §2.4: "`version` is an integer that starts at 1
        when the row is created and increments by exactly one on every mutation of that
        row."

        Design: Corner/state_machines/application_initial_state_is_draft_on_create
        """
        env = frame_for_one_nurse
        application = validate_success(
            api.create_application(
                application_payload(env["ap_id"], env["prof_id"], env["cred_id"]),
                make_applicant_headers(env["ap_id"]),
            ),
            201,
        )

        assert_application_fields(
            application,
            status=APP_DRAFT,
            deficiency_cycle_count=0,
            decided_at=None,
            decided_by_user_id=None,
            version=1,
        )

    def test_crossing_the_gate_stamps_the_clock_and_appends_the_assessment_pair(
        self, api, draft_endorsement, setup
    ):
        """PRD §3.4: "Crossing the gate freezes the money and starts the clock. The
        application's `submitted_at` is set to the logical clock and its `status` becomes
        `SUBMITTED`."  PRD §3.4: "Two ledger entries are then appended, in a pinned
        order: first an `ASSESSMENT` entry whose `amount_cents` is the positive
        `gross_total_cents` and whose `memo` is `submit assessment`, then a
        `WAIVER_CREDIT` entry whose `amount_cents` is the negative of the waiver credit
        and whose `memo` is `statutory waiver credit`."  PRD §4: "Every other operation,
        including all reads, all lifecycle transitions on an existing resource, all
        compensating actions, the ops sweep and the clock control, returns `200 OK`."

        Design: Corner/state_machines/submit_from_draft_moves_to_submitted_and_assesses_fees
        """
        env = draft_endorsement
        submitted = validate_success(
            api.submit_application(env["app_id"], {}, make_applicant_headers(env["ap_id"])), 200
        )

        assert_application_fields(
            submitted,
            status=APP_SUBMITTED,
            submitted_at="2026-08-01T00:00:00Z",
            review_deadline_at="2026-10-30T00:00:00Z",
            gross_total_cents=48000,
            statutory_waiver_pct=0.00,
            fee_balance_cents=48000,
            version=2,
        )

        ledger = setup.read_ledger(env["app_id"])
        assert_ledger_signature(
            ledger, [(ENTRY_ASSESSMENT, 48000), (ENTRY_WAIVER_CREDIT, 0)]
        )
        assert_memo(ledger[0], MEMO_ASSESSMENT)
        assert_memo(ledger[1], MEMO_WAIVER_CREDIT)

    def test_submitting_a_second_time_neither_moves_the_file_nor_bills_it_again(
        self, api, draft_endorsement, setup
    ):
        """PRD §3.4: "Submission is the gate, and it is the applicant's own action along
        `DRAFT → SUBMITTED`. Eight conditions must hold. The application must still be in
        `DRAFT`."  PRD §2.8: "Application from-state — the application is in a state this
        operation permits. Submitting requires `DRAFT`; curing requires `DEFICIENT`;
        recording a deficiency and issuing a board decision require `UNDER_REVIEW`;
        opening the credential evaluation requires `SUBMITTED`; permit issuance,
        exam-result recording, credit-award creation and credit-award revocation require
        the application to be in `SUBMITTED`, `UNDER_REVIEW` or `DEFICIENT`;
        review-assignment creation likewise requires `SUBMITTED`, `UNDER_REVIEW` or
        `DEFICIENT`. `ERR_APPLICATION_NOT_REVIEWABLE`, 409."

        Design: Corner/state_machines/submit_twice_second_call_rejected
        """
        env = draft_endorsement
        setup.submit(env["app_id"], env["ap_id"])

        response = api.submit_application(
            env["app_id"], {}, make_applicant_headers(env["ap_id"])
        )

        validate_error(response, ApiErrorId.ERR_APPLICATION_NOT_REVIEWABLE.value, 409)
        assert_application_fields(
            setup.read_application(env["app_id"]),
            status=APP_SUBMITTED,
            version=2,
            fee_balance_cents=48000,
        )
        assert setup.ledger_meta(env["app_id"])["total_count"] == 2


class TestTransitionsRefusedFromTheWrongState:
    def test_the_board_cannot_decide_a_file_that_was_never_submitted(
        self, api, draft_endorsement, setup
    ):
        """PRD §3.9: "The terminal act belongs to a `BoardDeputy`, who supplies a
        `decision` of either `APPROVE` or `DENY` and an optional `memo`. Both branches
        require the application to be in `UNDER_REVIEW` and both are subject to the
        segregation-of-duties comparison of §2.11."

        Design: Corner/state_machines/decision_on_draft_application_rejected
        """
        env = draft_endorsement
        response = api.issue_decision(
            env["app_id"], decision_payload(DECISION_APPROVE, memo="premature"), DEPUTY_HEADERS
        )

        validate_error(response, ApiErrorId.ERR_APPLICATION_NOT_REVIEWABLE.value, 409)
        assert_application_fields(
            setup.read_application(env["app_id"]), status=APP_DRAFT, decided_at=None
        )
        _rows, meta = validate_paginated(
            api.list_licenses(ANALYST_HEADERS, {"application_id": env["app_id"]})
        )
        assert meta["total_count"] == 0

    def test_curing_a_file_that_was_never_found_deficient_is_refused(
        self, api, draft_endorsement, setup
    ):
        """PRD §3.9: "The applicant closes a revision cycle themselves, driving
        `DEFICIENT → UNDER_REVIEW` on their own application with the caller's
        `X-User-ID` matching `applicant_id`."  PRD §2.8: "Application from-state — the
        application is in a state this operation permits. Submitting requires `DRAFT`;
        curing requires `DEFICIENT`; recording a deficiency and issuing a board decision
        require `UNDER_REVIEW`; opening the credential evaluation requires `SUBMITTED`;
        permit issuance, exam-result recording, credit-award creation and credit-award
        revocation require the application to be in `SUBMITTED`, `UNDER_REVIEW` or
        `DEFICIENT`; review-assignment creation likewise requires `SUBMITTED`,
        `UNDER_REVIEW` or `DEFICIENT`. `ERR_APPLICATION_NOT_REVIEWABLE`, 409."

        Design: Corner/state_machines/cure_without_prior_deficiency_rejected
        """
        env = draft_endorsement
        setup.submit(env["app_id"], env["ap_id"])
        setup.evaluation(env["app_id"], env["cred_id"])

        response = api.cure_application(
            env["app_id"], {}, make_applicant_headers(env["ap_id"])
        )

        validate_error(response, ApiErrorId.ERR_APPLICATION_NOT_REVIEWABLE.value, 409)
        assert_application_fields(
            setup.read_application(env["app_id"]),
            status=APP_UNDER_REVIEW,
            deficiency_cycle_count=0,
        )

    def test_an_approved_file_cannot_be_reopened_by_a_second_decision(
        self, api, approved_dietitian, setup
    ):
        """PRD §3.9: "An approval that clears all of that drives `UNDER_REVIEW →
        APPROVED`, sets `decided_at` and `decided_by_user_id`, computes
        `processing_elapsed_days` and `processing_standard_met`, and then sets off a
        chain of three linked effects, each caused by the one before it."  PRD §3.9: "Its
        `license_number` is minted as the profession's `profession_code`, then a hyphen,
        then a zero-padded six-digit mint sequence; the sequence advances by one for each
        licence row in `created_at` ascending order and begins at `000001`."

        Design: Corner/state_machines/decision_on_approved_application_rejected
        """
        env = approved_dietitian
        response = api.issue_decision(
            env["app_id"],
            decision_payload(DECISION_DENY, memo="reversal attempt"),
            DEPUTY_HEADERS_2,
        )

        validate_error(response, ApiErrorId.ERR_APPLICATION_NOT_REVIEWABLE.value, 409)
        assert_application_fields(
            setup.read_application(env["app_id"]),
            status=APP_APPROVED,
            decided_by_user_id=DEPUTY_USER_ID,
            fee_balance_cents=0,
            processing_standard_met=True,
            processing_elapsed_days=0,
            requirement_hours_satisfied=100.0,
            requirement_hours_remaining=0.0,
        )

        licenses, meta = validate_paginated(
            api.list_licenses(ANALYST_HEADERS, {"application_id": env["app_id"]})
        )
        assert meta["total_count"] == 1
        assert_license_number(licenses[0]["license_number"], "RD", 1)
        assert setup.read_credit_award(env["award_id"])["awarded_hours"] == 150.0
