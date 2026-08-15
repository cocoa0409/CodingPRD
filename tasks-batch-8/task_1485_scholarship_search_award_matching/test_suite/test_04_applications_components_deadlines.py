"""Application/component state machines and the submit deadline gate."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_instant_equal,
    create_donor,
    create_draft_application,
    create_fund,
    create_open_program,
    create_student,
    get_success_data,
    list_reminders,
    make_student_headers,
    set_clock,
    validate_error,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]


def _open_program(**overrides):
    donor = create_donor()
    fund = create_fund()
    return create_open_program(donor["id"], fund["id"], **overrides)


class TestApplicationTerminalStates:
    def test_withdraw_then_submit_rejected(self, api):
        """PRD §3.3: "Withdrawal, available to the student or a coordinator
        from either `DRAFT` or `SUBMITTED` (otherwise `ERR_INVALID_STATE`),
        moves the application to `WITHDRAWN` and suppresses its `SCHEDULED`
        reminders."
        PRD §3.3: "The application must be in `DRAFT` (otherwise
        `ERR_INVALID_STATE`)."
        PRD §3.3: "`NOT_SELECTED`, `WITHDRAWN`, and `EXPIRED` are the
        application's terminal states."

        Design: Corner/state_machines/application_withdraw_then_submit_rejected
        """
        student = create_student()
        program = _open_program()
        app = create_draft_application(student["id"], program["id"], as_student=True)

        withdrawn = validate_success(
            api.withdraw_application(app["id"], make_student_headers(student["id"]))
        )
        assert withdrawn["status"] == "WITHDRAWN"

        resp = api.submit_application(app["id"], make_student_headers(student["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        reminders, meta = list_reminders(app["id"])
        assert meta["total_count"] == 3
        assert all(r["status"] == "SUPPRESSED" for r in reminders), (
            "withdrawal suppresses the whole reminder cadence"
        )

    def test_return_from_draft_rejected(self, api):
        """PRD §3.3: "The correction loop runs through the coordinator's
        return action: a `SUBMITTED` application returns to `DRAFT`, its
        `returned_count` increases by one, and the reminder cadence is
        re-armed against the program's close — again skipping offsets whose
        send times have passed."
        PRD §2.8: "**Own-state** — the target resource's own state permits
        the requested transition; otherwise `ERR_INVALID_STATE`."

        Design: Corner/state_machines/application_return_from_draft_rejected
        """
        student = create_student()
        program = _open_program()
        app = create_draft_application(student["id"], program["id"])

        resp = api.return_application(app["id"], COORD)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        current = validate_success(api.get_application(app["id"], COORD))
        assert current["status"] == "DRAFT"
        assert current["returned_count"] == 0, "no side effects fired"


class TestComponents:
    def test_reject_resubmission_cycle(self, api):
        """PRD §3.3: "Receipt, performed by the student or a coordinator with
        a `content_ref` present (a missing reference fails with
        `ERR_VALIDATION`), moves a component from `PENDING` to `RECEIVED` and
        stamps `received_at`; the same receipt action also moves a `REJECTED`
        component back to `RECEIVED`, forming the resubmission cycle."
        PRD §3.3: "A coordinator then adjudicates: accepting moves `RECEIVED`
        to `ACCEPTED`, rejecting moves `RECEIVED` to `REJECTED`, and waiving
        moves `PENDING` to `WAIVED`."

        Design: Corner/state_machines/component_reject_resubmission_cycle
        """
        student = create_student()
        program = _open_program(required_components=["ESSAY"])
        app = create_draft_application(
            student["id"], program["id"], as_student=True
        )
        student_headers = make_student_headers(student["id"])
        component = validate_success(
            api.add_component(
                app["id"],
                {"component_type": "ESSAY", "required": True},
                student_headers,
            ),
            expected_status=201,
        )
        assert component["status"] == "PENDING"

        received = validate_success(
            api.receive_component(
                component["id"], {"content_ref": "s3://essays/v1.pdf"}, student_headers
            )
        )
        assert received["status"] == "RECEIVED"
        assert_instant_equal(
            received["received_at"], "2026-08-01T00:00:00Z", "first received_at"
        )

        rejected = validate_success(api.reject_component(component["id"], COORD))
        assert rejected["status"] == "REJECTED"

        set_clock("2026-08-05T00:00:00Z")
        received2 = validate_success(
            api.receive_component(
                component["id"], {"content_ref": "s3://essays/v2.pdf"}, student_headers
            )
        )
        assert received2["status"] == "RECEIVED", "REJECTED -> RECEIVED cycle edge"
        assert_instant_equal(
            received2["received_at"], "2026-08-05T00:00:00Z", "received_at refreshes"
        )

        accepted = validate_success(api.accept_component(component["id"], COORD))
        assert accepted["status"] == "ACCEPTED"

    def test_waive_terminal_lockdown(self, api):
        """PRD §3.3: "A coordinator then adjudicates: accepting moves
        `RECEIVED` to `ACCEPTED`, rejecting moves `RECEIVED` to `REJECTED`,
        and waiving moves `PENDING` to `WAIVED`. `ACCEPTED` and `WAIVED` are
        terminal."
        PRD §2.8: "**Own-state** — the target resource's own state permits
        the requested transition; otherwise `ERR_INVALID_STATE`."

        Design: Corner/state_machines/component_waive_terminal_lockdown
        """
        student = create_student()
        program = _open_program()
        app = create_draft_application(student["id"], program["id"])
        component = validate_success(
            api.add_component(
                app["id"],
                {"component_type": "RECOMMENDATION", "required": True},
                COORD,
            ),
            expected_status=201,
        )
        waived = validate_success(api.waive_component(component["id"], COORD))
        assert waived["status"] == "WAIVED"

        resp = api.receive_component(
            component["id"], {"content_ref": "s3://recs/late.pdf"}, COORD
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestSubmitGates:
    def test_submit_with_unaccepted_component_rejected(self, api):
        """PRD §3.3: "Every required component — one whose `required` flag is
        set and whose `component_type` appears in the program's
        `required_components` — must be `ACCEPTED` or `WAIVED` (otherwise
        `ERR_COMPONENT_INCOMPLETE`)."

        Design: Corner/state_machines/submit_with_unaccepted_component_rejected
        """
        student = create_student()
        program = _open_program(required_components=["ESSAY"])
        app = create_draft_application(student["id"], program["id"])
        component = validate_success(
            api.add_component(
                app["id"], {"component_type": "ESSAY", "required": True}, COORD
            ),
            expected_status=201,
        )
        get_success_data(
            api.receive_component(
                component["id"], {"content_ref": "s3://essays/ic.pdf"}, COORD
            )
        )

        # RECEIVED is not enough: the component must be ACCEPTED or WAIVED.
        resp = api.submit_application(app["id"], COORD)
        validate_error(resp, ApiErrorId.ERR_COMPONENT_INCOMPLETE)
        assert validate_success(api.get_application(app["id"], COORD))["status"] == "DRAFT"

        get_success_data(api.accept_component(component["id"], COORD))
        submitted = validate_success(api.submit_application(app["id"], COORD))
        assert submitted["status"] == "SUBMITTED"

    def test_strict_program_submit_ineligible_rejected(self, api):
        """PRD §3.3: "And for a `STRICT` program, the recomputed verified
        score must be above zero (otherwise `ERR_INELIGIBLE_STUDENT`)."
        PRD §3.4: "Under `STRICT`, any hard-criterion miss — GPA below the
        minimum, income above the ceiling, residency mismatch, any required
        tag absent, or the major gate — forces the total score to exactly
        0.00."

        Design: Corner/state_machines/strict_program_submit_ineligible_rejected
        """
        student = create_student(gpa_hundredths=280)
        program = _open_program(match_policy="STRICT")
        app = create_draft_application(student["id"], program["id"])
        assert float(app["provisional_match_score"]) == 0.0, (
            "STRICT zero-gate applies already at provisional scoring (280 < 300)"
        )

        resp = api.submit_application(app["id"], COORD)
        validate_error(resp, ApiErrorId.ERR_INELIGIBLE_STUDENT)
        assert validate_success(api.get_application(app["id"], COORD))["status"] == "DRAFT"

    def test_duplicate_application_rejected(self, api):
        """PRD §3.3: "no other application may already exist for the same
        student-and-program pair in a non-terminal status — that is, in
        `DRAFT`, `SUBMITTED`, `UNDER_REVIEW`, `SELECTED`, `WAITLISTED`, or
        `AWARDED` — otherwise the create is refused with
        `ERR_DUPLICATE_APPLICATION`."

        Design: Corner/validations/validation_duplicate_application_rejected
        """
        s_a = create_student()
        s_b = create_student()
        program = _open_program()
        app_a = create_draft_application(s_a["id"], program["id"])
        assert app_a["status"] == "DRAFT"

        resp = api.create_application(
            {"student_id": s_a["id"], "program_id": program["id"]}, COORD
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_APPLICATION)

        # A different student may still apply to the same program.
        app_b = create_draft_application(s_b["id"], program["id"])
        assert app_b["status"] == "DRAFT"


class TestSubmitDeadlineBoundary:
    CLOSE = "2026-09-01T00:00:00Z"

    def test_submit_one_second_before_close_succeeds(self, api):
        """PRD §3.2: "Submitting an application is allowed strictly while now
        is earlier than `application_close_at`; an attempt at or after the
        close fails with `ERR_DEADLINE_PASSED`."

        Design: Difficulty/boundary_precision_check/submit_at_exact_close_at_rejected
        """
        s_1 = create_student()
        program = _open_program(application_close_at=self.CLOSE)
        app_1 = create_draft_application(s_1["id"], program["id"])

        set_clock("2026-08-31T23:59:59Z")
        submitted = validate_success(api.submit_application(app_1["id"], COORD))
        assert submitted["status"] == "SUBMITTED", (
            "one second before the close passes the strict < gate"
        )

    def test_submit_at_exact_close_rejected(self, api):
        """PRD §3.2: "Submitting an application is allowed strictly while now
        is earlier than `application_close_at`; an attempt at or after the
        close fails with `ERR_DEADLINE_PASSED`."

        Design: Difficulty/boundary_precision_check/submit_at_exact_close_at_rejected
        """
        s_2 = create_student()
        program = _open_program(application_close_at=self.CLOSE)
        app_2 = create_draft_application(s_2["id"], program["id"])

        set_clock(self.CLOSE)
        resp = api.submit_application(app_2["id"], COORD)
        validate_error(resp, ApiErrorId.ERR_DEADLINE_PASSED)
        assert validate_success(api.get_application(app_2["id"], COORD))["status"] == "DRAFT", (
            "equality with the close instant rejects and the application stays DRAFT"
        )
