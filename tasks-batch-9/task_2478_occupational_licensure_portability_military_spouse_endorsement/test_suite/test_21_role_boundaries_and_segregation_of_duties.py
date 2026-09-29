"""Who may act, and on whose rows: four operations reserved to a single role, the
entity-backed ownership clause that binds an applicant to their own file, and the
segregation anchor that bars a scope reviewer from signing the same licence."""

import pytest

from test_helpers import (
    ANALYST_HEADERS,
    APP_DENIED,
    APP_DRAFT,
    APP_UNDER_REVIEW,
    ANALYST_USER_ID,
    DECISION_APPROVE,
    DECISION_DENY,
    DEPUTY_HEADERS,
    DISCIPLINE_CLEAR,
    OVERALL_IN_PROGRESS,
    SCOPE_EQUIVALENT,
    ApiErrorId,
    assert_application_fields,
    assert_evaluation_fields,
    credential_payload,
    decision_payload,
    make_applicant_headers,
    make_deputy_headers,
    make_evaluator_headers,
    profession_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

DUAL_ROLE_USER_ID = "dual_1"
SECOND_DEPUTY_USER_ID = "dep_9"


@pytest.fixture
def an_applicant_and_no_professions(setup):
    """One applicant so the caller identity resolves, and an empty profession registry."""
    applicant = setup.applicant(full_name="Mira Solis")
    return {"ap_id": applicant["id"]}


@pytest.fixture
def file_whose_scope_review_the_analyst_signed(setup):
    """A nursing endorsement under review whose scope review was recorded by anl_1."""
    profession = setup.profession()
    applicant = setup.applicant(full_name="Noor Farah")
    credential = setup.credential(
        applicant["id"],
        license_number="OK-17001",
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
def evaluation_resolved_on_both_dimensions(setup):
    """A nursing evaluation with the analyst's scope opinion and the assigned reviewer's
    CLEAR finding both recorded, awaiting only finalisation."""
    profession = setup.profession()
    applicant = setup.applicant(full_name="Ove Lindqvist")
    credential = setup.credential(
        applicant["id"],
        license_number="OK-17002",
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
    evaluator = setup.evaluator(full_name="Pilar Adeniyi", profession_code="RN")
    setup.review_assignment(
        evaluator["id"], application["id"], "2026-08-01T00:00:00Z", "2026-08-20T00:00:00Z"
    )
    setup.discipline_finding(evaluation["id"], evaluator["id"], DISCIPLINE_CLEAR)
    return {
        "app_id": application["id"],
        "eval_id": evaluation["id"],
        "evr_id": evaluator["id"],
    }


@pytest.fixture
def draft_file_nobody_else_may_submit(setup):
    """A nursing endorsement still in DRAFT at version 1 with an empty ledger."""
    profession = setup.profession()
    applicant = setup.applicant(full_name="Quinn Delacroix")
    credential = setup.credential(
        applicant["id"],
        license_number="OK-17003",
        scope_elements=["ASSESS", "TREAT", "SUPERVISE"],
        practice_hours=1200,
        issued_at="2020-05-01T00:00:00Z",
    )
    application = setup.application(applicant["id"], profession["id"], credential["id"])
    return {"app_id": application["id"]}


@pytest.fixture
def file_scope_reviewed_by_a_dual_role_officer(setup):
    """A nursing endorsement under review whose scope review carries the user identifier
    dual_1, an operator who also holds board authority."""
    profession = setup.profession()
    applicant = setup.applicant(full_name="Rania Haddad")
    credential = setup.credential(
        applicant["id"],
        license_number="OK-17004",
        # the profession nominates PRESCRIBE as critical, so an admissible
        # EQUIVALENT scope opinion requires the credential to grant it
        scope_elements=["ASSESS", "TREAT", "PRESCRIBE", "SUPERVISE"],
        practice_hours=1200,
        issued_at="2020-05-01T00:00:00Z",
    )
    application = setup.application(applicant["id"], profession["id"], credential["id"])
    setup.submit(application["id"], applicant["id"])
    evaluation = setup.evaluation(application["id"], credential["id"])
    setup.scope_review(evaluation["id"], SCOPE_EQUIVALENT, user_id=DUAL_ROLE_USER_ID)
    return {"app_id": application["id"]}


@pytest.fixture
def two_applicants_without_credentials(setup):
    """Two unrelated applicants, neither of whom has filed a credential."""
    first = setup.applicant(full_name="Sven Aaltonen")
    second = setup.applicant(full_name="Tova Bergstrom")
    return {"ap_p": first["id"], "ap_q": second["id"]}


class TestOperationsReservedToOneRole:
    def test_an_applicant_may_not_register_a_profession(
        self, api, an_applicant_and_no_professions
    ):
        """PRD §4: "Register a regulated profession with its scope requirements, processing
        standard and fee schedule | AgencyAdmin |"  PRD §2.8: "Authorisation — the caller's
        role appears in the endpoint's authorised-role list. `ERR_UNAUTHORIZED`, 403.
        Applies to every endpoint."  PRD §2.2: "Role reach, in narrative terms: an
        `AgencyAdmin` configures professions and compacts, performs applicant intake, posts
        national-database findings and resolves them, records exam results, registers
        evaluators, runs the permit expiry sweep and drives the logical clock."

        Design: Corner/rbac/applicant_cannot_create_profession
        """
        env = an_applicant_and_no_professions
        response = api.create_profession(
            profession_payload(), make_applicant_headers(env["ap_id"])
        )

        validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value, 403)
        assert response.json()["response_type"] == "error"
        assert "id" not in response.json()["data"]

    def test_an_analyst_may_not_sign_the_board_decision_they_prepared(
        self, api, file_whose_scope_review_the_analyst_signed, setup
    ):
        """PRD §2.8: "Authorisation — the caller's role appears in the endpoint's
        authorised-role list. `ERR_UNAUTHORIZED`, 403. Applies to every endpoint."  PRD §4:
        "Board deputy approves or denies the application; approval mints a License and
        converts any ACTIVE permit | BoardDeputy |"  PRD §2.8: "The system therefore
        evaluates checks in one fixed global order and the **first** violated check decides
        the response; no later check can mask an earlier one, and no earlier success excuses
        a later failure."

        Design: Corner/rbac/licensing_analyst_cannot_issue_board_decision
        """
        env = file_whose_scope_review_the_analyst_signed
        response = api.issue_decision(
            env["app_id"],
            decision_payload(DECISION_APPROVE, memo="analyst overreach"),
            ANALYST_HEADERS,
        )

        validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value, 403)

        assert_application_fields(
            setup.read_application(env["app_id"]),
            status=APP_UNDER_REVIEW,
            decided_at=None,
            decided_by_user_id=None,
            scope_reviewed_by_user_id=ANALYST_USER_ID,
        )

    def test_the_assigned_reviewer_may_not_finalise_the_evaluation_they_worked(
        self, api, evaluation_resolved_on_both_dimensions, setup
    ):
        """PRD §4: "Finalize the evaluation: computes the equivalency score and the
        examination-waiver decision | LicensingAnalyst |"  PRD §2.2: "An `Evaluator` records
        the national-database disciplinary finding on evaluations they are assigned to."
        PRD §3.5: "Finalisation is the analyst's closing act along `IN_PROGRESS → COMPLETE`,
        and it requires that `overall_status` be `IN_PROGRESS` with `finalized_at` null,
        that both parallel dimensions be resolved to something other than `PENDING`, and
        that the parent application be in `UNDER_REVIEW` or `DEFICIENT`."

        Design: Corner/rbac/evaluator_cannot_finalize_evaluation
        """
        env = evaluation_resolved_on_both_dimensions
        response = api.finalize_evaluation(
            env["eval_id"], {}, make_evaluator_headers(env["evr_id"])
        )

        validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value, 403)

        assert_evaluation_fields(
            setup.read_evaluation(env["eval_id"]),
            overall_status=OVERALL_IN_PROGRESS,
            finalized_at=None,
            equivalency_score=None,
        )
        assert_application_fields(
            setup.read_application(env["app_id"]), fee_balance_cents=48000
        )

    def test_even_a_board_deputy_may_not_submit_a_file_for_the_applicant(
        self, api, draft_file_nobody_else_may_submit, setup
    ):
        """PRD §4: "Submit a DRAFT application: runs pathway eligibility, freezes the fee
        assessment and starts the processing clock | Applicant |"  PRD §2.2: "An `Applicant`
        opens, submits, cures and pays for their own applications and files their own
        credentials and training records."  PRD §2.8: "Authorisation — the caller's role
        appears in the endpoint's authorised-role list. `ERR_UNAUTHORIZED`, 403. Applies to
        every endpoint."

        Design: Corner/rbac/board_deputy_cannot_submit_application_on_behalf_of_applicant
        """
        env = draft_file_nobody_else_may_submit
        response = api.submit_application(env["app_id"], {}, DEPUTY_HEADERS)

        validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value, 403)

        assert_application_fields(
            setup.read_application(env["app_id"]),
            status=APP_DRAFT,
            submitted_at=None,
            version=1,
        )
        assert setup.ledger_meta(env["app_id"])["total_count"] == 0


class TestSegregationOfDuties:
    def test_the_officer_who_formed_the_scope_opinion_may_not_decide_the_file(
        self, api, file_scope_reviewed_by_a_dual_role_officer, setup
    ):
        """PRD §2.11: "When a `BoardDeputy` later issues the decision, their `X-User-ID` is
        compared against that stamp, and if the two are equal the decision is refused with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."  PRD §2.11: "The comparison is on user
        identifier alone, not on role, so an operator who acted as an analyst on a file is
        barred from deciding it even when they legitimately hold board authority."  PRD
        §2.8: "Segregation of duties — `X-User-ID` must differ from the application's
        `scope_reviewed_by_user_id`. `ERR_SEGREGATION_OF_DUTIES`, 403. Applies to the board
        decision, for both `APPROVE` and `DENY`."

        Design: Corner/rbac/same_user_id_cannot_scope_review_and_then_decide
        """
        env = file_scope_reviewed_by_a_dual_role_officer
        response = api.issue_decision(
            env["app_id"],
            decision_payload(DECISION_DENY, memo="self review"),
            make_deputy_headers(DUAL_ROLE_USER_ID),
        )

        validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)

        assert_application_fields(
            setup.read_application(env["app_id"]),
            status=APP_UNDER_REVIEW,
            decided_at=None,
            scope_reviewed_by_user_id=DUAL_ROLE_USER_ID,
        )

    def test_a_second_deputy_untouched_by_the_review_closes_the_same_file(
        self, api, file_scope_reviewed_by_a_dual_role_officer
    ):
        """PRD §2.11: "The officer who forms the scope-of-practice opinion may not be the
        officer who signs the licence."  PRD §3.9: "`DENY` requires nothing further. It
        drives `UNDER_REVIEW → DENIED`, sets `decided_at` to the logical clock and
        `decided_by_user_id` to the acting `X-User-ID`, computes `processing_elapsed_days`
        and `processing_standard_met`, revokes every `ACTIVE` temporary permit of the
        application with `revocation_reason_code` `APPLICATION_DENIED` and its full fee
        reversal, releases every `ASSIGNED` review assignment, and increments the
        application's `version`."

        Design: Corner/rbac/same_user_id_cannot_scope_review_and_then_decide
        """
        env = file_scope_reviewed_by_a_dual_role_officer
        denied = validate_success(
            api.issue_decision(
                env["app_id"],
                decision_payload(DECISION_DENY, memo="scope insufficient"),
                make_deputy_headers(SECOND_DEPUTY_USER_ID),
            ),
            200,
        )

        assert_application_fields(
            denied,
            status=APP_DENIED,
            decided_by_user_id=SECOND_DEPUTY_USER_ID,
            decided_at="2026-08-01T00:00:00Z",
            scope_reviewed_by_user_id=DUAL_ROLE_USER_ID,
        )


class TestEntityBackedOwnership:
    def test_an_applicant_may_not_file_a_credential_under_another_applicants_record(
        self, api, two_applicants_without_credentials
    ):
        """PRD §2.2: "An `Applicant` may only file credentials and training records against
        their own applicant record, may only open, submit, cure and pay for their own
        applications, and on any read may only be shown rows that belong to them."  PRD
        §2.8: "Ownership — an entity-backed caller may only act on its own rows.
        `ERR_OWNERSHIP_VIOLATION`, 403."  PRD §4: "File an out-of-state credential with its
        granted scope-of-practice elements | Applicant, AgencyAdmin |"

        Design: Corner/rbac/applicant_cannot_add_credential_under_another_applicant
        """
        env = two_applicants_without_credentials
        response = api.create_credential(
            env["ap_q"],
            credential_payload(license_number="OK-17005"),
            make_applicant_headers(env["ap_p"]),
        )

        validate_error(response, ApiErrorId.ERR_OWNERSHIP_VIOLATION.value, 403)

        _rows_q, meta_q = validate_paginated(
            api.list_credentials(env["ap_q"], make_applicant_headers(env["ap_q"]), None)
        )
        assert meta_q["total_count"] == 0
        _rows_p, meta_p = validate_paginated(
            api.list_credentials(env["ap_p"], make_applicant_headers(env["ap_p"]), None)
        )
        assert meta_p["total_count"] == 0
