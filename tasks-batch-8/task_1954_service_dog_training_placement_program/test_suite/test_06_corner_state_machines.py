"""Corner queue: state machine valid/invalid transitions and terminal
lockdowns (PRD §2.6, §3.1, §3.4, §3.5, §3.7, §3.8, §3.9)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_approved_raiser,
    create_cleared_dog,
    create_dog_payload,
    create_screening_payload,
    create_applicant_payload,
    create_assessment_payload,
    make_applicant_headers,
    make_evaluator_headers,
    make_puppy_raiser_headers,
    make_trainer_headers,
    setup_enrolled_pair,
    setup_graduated_partnership,
    start_class_in_session,
    validate_error,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]
COORD_B = TEST_USERS["coordinator_b_headers"]
ADMIN = TEST_USERS["program_admin_headers"]
TD = TEST_USERS["training_director_headers"]
VET = TEST_USERS["veterinarian_headers"]


class TestDeniedApplicantTerminalLockdown:
    """Corner/state_machines/denied_applicant_terminal_lockdown."""

    def test_begin_review_on_denied_rejected(self, api):
        """PRD §2.6: "8. **Terminal lockdown** — no transition fires out of a
        terminal state (`ERR_ALREADY_TERMINAL`, HTTP 409)."
        PRD §3.1: "the applicant lands in the terminal state `DENIED`."

        Design: Corner/state_machines/denied_applicant_terminal_lockdown
        """
        applicant = validate_success(
            api.create_applicant(create_applicant_payload(), COORD),
            expected_status=201,
        )
        validate_success(api.begin_review(applicant["id"], COORD))
        validate_success(
            api.deny_applicant(applicant["id"], {"denial_reason": "x"}, COORD)
        )
        resp = api.begin_review(applicant["id"], COORD)
        validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL)
        applicant_now = validate_success(api.get_applicant(applicant["id"], COORD))
        assert applicant_now["application_status"] == "DENIED"


class TestApproveFromSubmittedRejected:
    """Corner/state_machines/approve_from_submitted_rejected."""

    def test_approve_requires_in_review(self, api):
        """PRD §3.1: "An `IntakeCoordinator` approving an applicant enforces
        two checks in order: the applicant must currently be `IN_REVIEW`
        (otherwise `ERR_INVALID_STATE`), and at least one of the applicant's
        assessments must be `FINALIZED_ACCEPTED` (otherwise
        `ERR_ASSESSMENT_REQUIRED`)."

        From SUBMITTED, approve fails even with a FINALIZED_ACCEPTED
        assessment; no waitlist entry is created.

        Design: Corner/state_machines/approve_from_submitted_rejected
        """
        applicant = validate_success(
            api.create_applicant(create_applicant_payload(), COORD),
            expected_status=201,
        )
        assessment = validate_success(
            api.create_assessment(
                applicant["id"], create_assessment_payload(), COORD
            ),
            expected_status=201,
        )
        validate_success(
            api.finalize_assessment(
                assessment["id"], {"outcome": "FINALIZED_ACCEPTED"}, COORD
            )
        )
        resp = api.approve_applicant(applicant["id"], COORD)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        entries = validate_success(
            api.list_applicant_waitlist_entries(applicant["id"], COORD)
        )
        assert entries == [] or len(entries) == 0


class TestScreeningDoubleSubmitRejected:
    """Corner/state_machines/screening_double_submit_rejected."""

    def test_submit_on_cleared_screening_rejected(self, api):
        """PRD §3.5: "Both screening outcomes are terminal; a screening in
        `DRAFT` is the only submittable state."
        PRD §2.6: "8. **Terminal lockdown** — no transition fires out of a
        terminal state (`ERR_ALREADY_TERMINAL`, HTTP 409)."

        Design: Corner/state_machines/screening_double_submit_rejected
        """
        dog = validate_success(
            api.create_dog(create_dog_payload(), ADMIN), expected_status=201
        )
        validate_success(api.begin_screening(dog["id"], VET))
        screening = validate_success(
            api.create_screening(dog["id"], create_screening_payload(), VET),
            expected_status=201,
        )
        validate_success(api.submit_screening(screening["id"], VET))
        resp = api.submit_screening(screening["id"], VET)
        validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL)
        screening_now = validate_success(api.get_screening(screening["id"], VET))
        assert screening_now["status"] == "CLEARED"
        dog_now = validate_success(api.get_dog(dog["id"], TD))
        assert dog_now["status"] == "CLEARED"


class TestClassCompleteBlockedByOpenEnrollment:
    """Corner/state_machines/class_complete_blocked_by_open_enrollment."""

    def test_complete_with_enrolled_enrollment_rejected(self, api):
        """PRD §3.7: "Completing the class moves `GRADUATION_REVIEW` to the
        terminal `COMPLETED` and requires every enrollment to be in
        `GRADUATED`, `FAILED`, or `WITHDRAWN` (otherwise `ERR_INVALID_STATE`)."

        Design: Corner/state_machines/class_complete_blocked_by_open_enrollment
        """
        ctx = setup_enrolled_pair()
        clazz = start_class_in_session(ctx["clazz"])
        validate_success(
            api.set_clock({"to_iso8601": "2026-10-16T00:00:00Z"}, ADMIN)
        )
        validate_success(api.begin_graduation_review(clazz["id"], TD))
        resp = api.complete_class(clazz["id"], TD)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        clazz_now = validate_success(api.get_class(clazz["id"], TD))
        assert clazz_now["status"] == "GRADUATION_REVIEW"


class TestRaiserHiatusWithActiveDogRejected:
    """Corner/state_machines/raiser_hiatus_with_active_dog_rejected."""

    def test_hiatus_with_dog_rejected(self, api):
        """PRD §3.4: "A raiser in `APPROVED` or `ACTIVE` whose
        `current_dog_count` is 0 may be placed `ON_HIATUS` — by a
        `ProgramAdmin`, or by the raiser themselves acting on their own
        profile (otherwise `ERR_OWNERSHIP_SCOPE`)."

        An ACTIVE raiser fostering one dog violates the 0-dog precondition
        (not a declared from-state for the transition) -> ERR_INVALID_STATE.

        Design: Corner/state_machines/raiser_hiatus_with_active_dog_rejected
        """
        raiser = create_approved_raiser(foster_capacity=2)
        dog = create_cleared_dog()
        validate_success(
            api.create_raiser_placement(
                dog["id"], {"puppy_raiser_id": raiser["id"]}, TD
            ),
            expected_status=201,
        )
        resp = api.hiatus_raiser(raiser["id"], make_puppy_raiser_headers(raiser["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        raiser_now = validate_success(api.get_puppy_raiser(raiser["id"], ADMIN))
        assert raiser_now["status"] == "ACTIVE"


class TestSupportRequestReopenCycle:
    """Corner/state_machines/support_request_reopen_cycle."""

    def test_full_cycle_with_reopen(self, api):
        """PRD §3.9: "A `TrainingDirector` triages an `OPEN` request, moving
        it to `TRIAGED` and setting `priority` from the payload. Starting work
        moves from `TRIAGED` or `REOPENED` to `IN_PROGRESS` and assigns a
        trainer ... Resolution — by a `TrainingDirector`, or by the assigned
        `Trainer` themselves ... — moves `IN_PROGRESS` to `RESOLVED` with a
        `resolution_note` and stamps `resolved_at` from the logical clock."
        PRD §3.9: "Reopening moves the request to `REOPENED` and clears
        `resolved_at` to null, after which a `TrainingDirector` can start it
        again under the same rules as a triaged request. Alternatively, a
        `TrainingDirector` closes a `RESOLVED` request outright."

        OPEN -> TRIAGED -> IN_PROGRESS -> RESOLVED -> REOPENED ->
        IN_PROGRESS -> RESOLVED -> CLOSED.

        Design: Corner/state_machines/support_request_reopen_cycle
        """
        ctx = setup_graduated_partnership()
        applicant_h = make_applicant_headers(ctx["applicant"]["id"])
        sr = validate_success(
            api.create_support_request(
                ctx["partnership"]["id"],
                {"category": "BEHAVIOR", "description": "barking at carts",
                 "severity": "HIGH"},
                applicant_h,
            ),
            expected_status=201,
        )
        assert sr["status"] == "OPEN"
        triaged = validate_success(
            api.triage_support_request(sr["id"], {"priority": "HIGH"}, TD)
        )
        assert triaged["status"] == "TRIAGED"
        assert triaged["priority"] == "HIGH"
        started = validate_success(
            api.start_support_request(
                sr["id"], {"assigned_trainer_id": ctx["trainer"]["id"]}, TD
            )
        )
        assert started["status"] == "IN_PROGRESS"
        resolved = validate_success(
            api.resolve_support_request(
                sr["id"],
                {"resolution_note": "counter-conditioning plan"},
                make_trainer_headers(ctx["trainer"]["id"]),
            )
        )
        assert resolved["status"] == "RESOLVED"
        assert resolved["resolved_at"] is not None
        reopened = validate_success(api.reopen_support_request(sr["id"], applicant_h))
        assert reopened["status"] == "REOPENED"
        assert reopened["resolved_at"] is None
        restarted = validate_success(
            api.start_support_request(
                sr["id"], {"assigned_trainer_id": ctx["trainer"]["id"]}, TD
            )
        )
        assert restarted["status"] == "IN_PROGRESS"
        resolved2 = validate_success(
            api.resolve_support_request(
                sr["id"],
                {"resolution_note": "follow-up session done"},
                make_trainer_headers(ctx["trainer"]["id"]),
            )
        )
        assert resolved2["status"] == "RESOLVED"
        assert resolved2["resolved_at"] is not None
        closed = validate_success(api.close_support_request(sr["id"], TD))
        assert closed["status"] == "CLOSED"


class TestRecertRemediationDoubleFailSuspends:
    """Corner/state_machines/recert_remediation_double_fail_suspends."""

    def test_fail_fail_path_suspends_partnership(self, api):
        """PRD §3.8: "A `FAIL` from `SCHEDULED` moves the recertification to
        `REMEDIATION` and stamps `completed_on`. A `FAIL` from `REMEDIATION`
        moves it to the terminal `FAILED_FINAL`, stamps `completed_on`, and
        suspends the partnership."

        Design: Corner/state_machines/recert_remediation_double_fail_suspends
        """
        ctx = setup_graduated_partnership()
        partnership = ctx["partnership"]
        evaluator = ctx["evaluator"]
        current = validate_success(api.get_partnership(partnership["id"], TD))
        recert = validate_success(
            api.create_recertification(
                partnership["id"],
                {
                    "scheduled_on": "2027-10-20",
                    "evaluator_id": evaluator["id"],
                    "expected_partnership_version": current["version"],
                },
                TD,
            ),
            expected_status=201,
        )
        eval_h = make_evaluator_headers(evaluator["id"])
        first = validate_success(
            api.record_recert_result(recert["id"], {"outcome": "FAIL"}, eval_h)
        )
        assert first["status"] == "REMEDIATION"
        mid = validate_success(api.get_partnership(partnership["id"], TD))
        assert mid["status"] == "ACTIVE"
        second = validate_success(
            api.record_recert_result(recert["id"], {"outcome": "FAIL"}, eval_h)
        )
        assert second["status"] == "FAILED_FINAL"
        after = validate_success(api.get_partnership(partnership["id"], TD))
        assert after["status"] == "SUSPENDED"
