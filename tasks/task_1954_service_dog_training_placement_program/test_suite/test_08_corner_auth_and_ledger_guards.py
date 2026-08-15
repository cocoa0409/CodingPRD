"""Corner queue: authentication/authorization/ownership violations, ledger
segregation of duties, fiscal minimum, approval and refund guards
(PRD §2.1, §2.6, §3.1, §3.3)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    build_user_headers,
    create_applicant_payload,
    create_approved_raiser,
    create_assessment_payload,
    create_certified_trainer,
    create_cleared_dog,
    create_contribution_payload,
    create_waitlisted_applicant,
    make_applicant_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]
COORD_B = TEST_USERS["coordinator_b_headers"]
ADMIN = TEST_USERS["program_admin_headers"]
TD = TEST_USERS["training_director_headers"]
VET = TEST_USERS["veterinarian_headers"]


class TestUnauthenticatedMissingHeaders:
    """Corner/validations/unauthenticated_missing_headers_returns_401."""

    def test_undeclared_role_rejected(self, api):
        """PRD §2.1: "When either header is missing, or the role value is not
        one of the declared roles, the request is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/unauthenticated_missing_headers_returns_401
        """
        resp = api.list_applicants(build_user_headers("anon-1", "Anonymous"))
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestRoleNotPermitted:
    """Corner/validations/role_not_permitted_returns_403."""

    def test_veterinarian_cannot_create_applicant(self, api):
        """PRD §2.1: "When the role is declared but is not listed among the
        roles authorized for the endpoint, the request is rejected with
        `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4: POST /api/applicants is authorized for IntakeCoordinator and
        ProgramAdmin only.

        Design: Corner/validations/role_not_permitted_returns_403
        """
        resp = api.create_applicant(create_applicant_payload(), VET)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        data, _meta = validate_paginated(api.list_applicants(COORD))
        assert len(data) == 0


class TestOwnershipScopeViolation:
    """Corner/validations/ownership_scope_violation_returns_403."""

    def test_other_applicants_resubmit_rejected(self, api):
        """PRD §3.1: "The applicant themselves then resubmits, which returns
        the application from `NEEDS_INFO` to `IN_REVIEW`; a resubmission by
        anyone other than that applicant is rejected with
        `ERR_OWNERSHIP_SCOPE`."

        Design: Corner/validations/ownership_scope_violation_returns_403
        """
        applicant_a = validate_success(
            api.create_applicant(create_applicant_payload(), COORD),
            expected_status=201,
        )
        validate_success(api.begin_review(applicant_a["id"], COORD))
        validate_success(
            api.request_info(
                applicant_a["id"], {"info_request_note": "need docs"}, COORD
            )
        )
        applicant_b = validate_success(
            api.create_applicant(create_applicant_payload(), COORD),
            expected_status=201,
        )
        resp = api.resubmit_applicant(
            applicant_a["id"], make_applicant_headers(applicant_b["id"])
        )
        validate_error(resp, ApiErrorId.ERR_OWNERSHIP_SCOPE)
        a_now = validate_success(api.get_applicant(applicant_a["id"], COORD))
        assert a_now["application_status"] == "NEEDS_INFO"


class TestContributionReceiveSod:
    """Corner/validations/contribution_receive_sod_same_operator_rejected."""

    def test_creator_cannot_receive_own_pledge(self, api):
        """PRD §3.3: "Marking a contribution received is a second, segregated
        act: an `IntakeCoordinator` receives a `PLEDGED` contribution, and the
        receiving operator must differ from `created_by_user_id` — when the
        same operator attempts both acts, the receive is rejected with
        `ERR_SOD_CONFLICT` (HTTP 409)."

        Design: Corner/validations/contribution_receive_sod_same_operator_rejected
        """
        applicant, _entry = create_waitlisted_applicant(
            track="FACILITY", income_cents=12_000_000
        )
        contribution = validate_success(
            api.create_contribution(
                applicant["id"],
                create_contribution_payload(amount_cents=100_000),
                COORD,
            ),
            expected_status=201,
        )
        assert contribution["created_by_user_id"] == "coord-a"
        resp = api.receive_contribution(contribution["id"], COORD)
        validate_error(resp, ApiErrorId.ERR_SOD_CONFLICT)
        now = validate_success(api.get_contribution(contribution["id"], COORD))
        assert now["status"] == "PLEDGED"


class TestContributionBelowMinimum:
    """Corner/validations/contribution_below_minimum_unshadowed."""

    def test_amount_below_100_rejected(self, api):
        """PRD §3.3: "The amount must be at least 100 cents; anything less is
        rejected with `ERR_CONTRIBUTION_BELOW_MINIMUM` (HTTP 422)."

        A 50-cent contribution on an active WAITLISTED applicant surfaces the
        fiscal minimum.

        Design: Corner/validations/contribution_below_minimum_unshadowed
        """
        applicant, _entry = create_waitlisted_applicant(
            track="FACILITY", income_cents=12_000_000
        )
        resp = api.create_contribution(
            applicant["id"],
            create_contribution_payload(amount_cents=50),
            COORD,
        )
        validate_error(resp, ApiErrorId.ERR_CONTRIBUTION_BELOW_MINIMUM)


class TestApproveWithoutAcceptedAssessment:
    """Corner/validations/approve_without_accepted_assessment_rejected."""

    def test_only_rejected_assessment_blocks_approve(self, api):
        """PRD §3.1: "An `IntakeCoordinator` approving an applicant enforces
        two checks in order: the applicant must currently be `IN_REVIEW`
        (otherwise `ERR_INVALID_STATE`), and at least one of the applicant's
        assessments must be `FINALIZED_ACCEPTED` (otherwise
        `ERR_ASSESSMENT_REQUIRED`)."

        Design: Corner/validations/approve_without_accepted_assessment_rejected
        """
        applicant = validate_success(
            api.create_applicant(create_applicant_payload(), COORD),
            expected_status=201,
        )
        validate_success(api.begin_review(applicant["id"], COORD))
        assessment = validate_success(
            api.create_assessment(
                applicant["id"],
                create_assessment_payload(home_environment_score=2),
                COORD,
            ),
            expected_status=201,
        )
        validate_success(
            api.finalize_assessment(
                assessment["id"], {"outcome": "FINALIZED_REJECTED"}, COORD
            )
        )
        resp = api.approve_applicant(applicant["id"], COORD)
        validate_error(resp, ApiErrorId.ERR_ASSESSMENT_REQUIRED)
        now = validate_success(api.get_applicant(applicant["id"], COORD))
        assert now["application_status"] == "IN_REVIEW"


class TestRecertWindowEnforced:
    """Corner/validations/recert_window_enforced."""

    def test_scheduled_45_days_before_due_rejected(self, api):
        """PRD §3.8: "Two checks guard the schedule in order: `scheduled_on`
        must fall within the window from 30 days before `recert_due_at` to 30
        days after it, inclusive — outside the window is `ERR_RECERT_WINDOW`."

        recert_due_at 2027-10-16 -> window opens 2027-09-16; 2027-09-01 is 45
        days before due and is rejected.

        Design: Corner/validations/recert_window_enforced
        """
        from test_helpers import setup_graduated_partnership
        ctx = setup_graduated_partnership()
        partnership = ctx["partnership"]
        evaluator = ctx["evaluator"]
        current = validate_success(api.get_partnership(partnership["id"], TD))
        resp = api.create_recertification(
            partnership["id"],
            {
                "scheduled_on": "2027-09-01",
                "evaluator_id": evaluator["id"],
                "expected_partnership_version": current["version"],
            },
            TD,
        )
        validate_error(resp, ApiErrorId.ERR_RECERT_WINDOW)
        recerts = validate_success(
            api.list_partnership_recertifications(partnership["id"], TD)
        )
        assert len(recerts) == 0


class TestRaiserPlacementRequiresClearedOrRecalled:
    """Corner/validations/raiser_placement_requires_cleared_or_recalled_state."""

    def test_second_placement_on_placed_dog_rejected(self, api):
        """PRD §3.6: "A `TrainingDirector` creates a raiser placement for a
        dog in `CLEARED` or `RECALLED` — any other dog status is
        `ERR_INVALID_STATE`."

        Design: Corner/validations/raiser_placement_requires_cleared_or_recalled_state
        """
        r1 = create_approved_raiser()
        r2 = create_approved_raiser(experience_score=60)
        dog = create_cleared_dog()
        validate_success(
            api.create_raiser_placement(
                dog["id"], {"puppy_raiser_id": r1["id"]}, TD
            ),
            expected_status=201,
        )
        resp = api.create_raiser_placement(
            dog["id"], {"puppy_raiser_id": r2["id"]}, TD
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        r2_now = validate_success(api.get_puppy_raiser(r2["id"], ADMIN))
        assert r2_now["current_dog_count"] == 0


class TestEvaluatorNotCertifiedUnshadowed:
    """Corner/validations/evaluator_not_certified_unshadowed."""

    def test_non_certified_evaluator_rejected(self, api):
        """PRD §3.7: "the referenced evaluator — which is the acting
        `Evaluator`'s own `X-User-ID`, recorded as `evaluator_id` — must be a
        `Trainer` with `pat_certified` true and status `CERTIFIED` (otherwise
        `ERR_EVALUATOR_NOT_CERTIFIED`)."

        The evaluator here is CERTIFIED but pat_certified false and is not the
        dog's primary trainer, so no segregation-of-duties violation shadows
        the qualification failure.

        Design: Corner/validations/evaluator_not_certified_unshadowed
        """
        from test_helpers import setup_in_session_enrollment, make_evaluator_headers
        ctx = setup_in_session_enrollment()
        not_pat = create_certified_trainer(pat_certified=False)
        resp = api.create_pat(
            ctx["enrollment"]["id"],
            {"scheduled_at": "2026-10-01T10:00:00Z"},
            make_evaluator_headers(not_pat["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_EVALUATOR_NOT_CERTIFIED)
        pats = validate_success(
            api.list_enrollment_pats(ctx["enrollment"]["id"], TD)
        )
        assert len(pats) == 0


class TestPatAttemptCap:
    """Corner/validations/pat_attempt_cap_after_two_live_tests."""

    def test_third_attempt_rejected(self, api):
        """PRD §3.7: "the attempt cap allows fewer than 2 non-`INVALIDATED`
        tests already existing for the enrollment — a third attempt is
        rejected with `ERR_PAT_ATTEMPTS_EXHAUSTED`."

        PAT1 SCORED_PASS plus PAT2 SCHEDULED blocks a third create.

        Design: Corner/validations/pat_attempt_cap_after_two_live_tests
        """
        from test_helpers import (
            PAT_PERFECT_SCORES,
            create_certified_trainer,
            make_evaluator_headers,
            setup_in_session_enrollment,
        )
        ctx = setup_in_session_enrollment()
        evaluator = create_certified_trainer(pat_certified=True)
        eval_h = make_evaluator_headers(evaluator["id"])
        pat1 = validate_success(
            api.create_pat(
                ctx["enrollment"]["id"],
                {"scheduled_at": "2026-10-01T10:00:00Z"},
                eval_h,
            ),
            expected_status=201,
        )
        validate_success(
            api.score_pat(pat1["id"], {"exercise_scores": PAT_PERFECT_SCORES}, eval_h)
        )
        pat2 = validate_success(
            api.create_pat(
                ctx["enrollment"]["id"],
                {"scheduled_at": "2026-10-05T10:00:00Z"},
                eval_h,
            ),
            expected_status=201,
        )
        assert pat2["attempt_number"] == 2
        resp = api.create_pat(
            ctx["enrollment"]["id"],
            {"scheduled_at": "2026-10-08T10:00:00Z"},
            eval_h,
        )
        validate_error(resp, ApiErrorId.ERR_PAT_ATTEMPTS_EXHAUSTED)
        enrollment = validate_success(api.get_enrollment(ctx["enrollment"]["id"], TD))
        assert enrollment["status"] == "ENROLLED"


class TestInvalidateFreesAttemptNumbering:
    """Corner/validations/invalidate_frees_attempt_numbering."""

    def test_invalidated_test_excluded_from_count(self, api):
        """PRD §3.7: "A `TrainingDirector` may also invalidate a `SCHEDULED`
        test by supplying a `reason`, moving it to `INVALIDATED`; invalidated
        tests do not count toward the two-attempt cap."
        PRD §3.7: "A scheduled test is `SCHEDULED`, with `exercise_scores`
        empty and `attempt_number` computed as 1 plus the count of prior
        non-`INVALIDATED` tests for the enrollment."

        Design: Corner/validations/invalidate_frees_attempt_numbering
        """
        from test_helpers import (
            create_certified_trainer,
            make_evaluator_headers,
            setup_in_session_enrollment,
        )
        ctx = setup_in_session_enrollment()
        evaluator = create_certified_trainer(pat_certified=True)
        eval_h = make_evaluator_headers(evaluator["id"])
        p1 = validate_success(
            api.create_pat(
                ctx["enrollment"]["id"],
                {"scheduled_at": "2026-10-01T10:00:00Z"},
                eval_h,
            ),
            expected_status=201,
        )
        assert p1["attempt_number"] == 1
        invalidated = validate_success(
            api.invalidate_pat(p1["id"], {"reason": "venue lost power"}, TD)
        )
        assert invalidated["status"] == "INVALIDATED"
        p2 = validate_success(
            api.create_pat(
                ctx["enrollment"]["id"],
                {"scheduled_at": "2026-10-02T10:00:00Z"},
                eval_h,
            ),
            expected_status=201,
        )
        assert p2["attempt_number"] == 1, (
            "invalidated first test is excluded from the attempt count"
        )
