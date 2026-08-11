"""Registration-request lifecycle, exams, and inquiry workflow tests
(PRD Sections 2.10, 3.4, 3.5, 3.9)."""
from test_helpers import (
    ApiErrorId,
    create_firm,
    create_firm_applicant_request,
    create_submitted_request,
    create_terminated_registration,
    get_exam_requirement,
    get_firm,
    get_request,
    get_termination_filing,
    make_applicant_payload,
    make_registration_request_payload,
    make_user_headers,
    record_exam_result,
    schedule_exam_window,
    set_clock,
    submit_request,
    validate_error,
    validate_success,
    create_applicant,
)


class TestRegistrationLifecycle:
    def test_terminal_state_lockdown_withdrawn(
        self, api, registration_principal_headers, compliance_officer_headers
    ):
        """PRD Section 3.5: "`WITHDRAWN`, `DENIED`, and `TERMINATED` are
        terminal — any further action against a request in one of those states
        is rejected `ERR_INVALID_STATE`."

        Design: Corner/state_machines/terminal_state_lockdown_withdrawn
        """
        firm, applicant, request, _ = create_firm_applicant_request(
            category="RR", jurisdictions=("CA",)
        )
        withdrawn = validate_success(
            api.withdraw_registration_request(
                request["id"], registration_principal_headers
            )
        )
        assert withdrawn["status"] == "WITHDRAWN"

        resp = api.submit_registration_request(
            request["id"], registration_principal_headers
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        after = get_request(request["id"])
        assert after["status"] == "WITHDRAWN"

    def test_invalid_transition_approve_from_deficient(self, api):
        """PRD Section 3.5: "Approval moves `SUBMITTED → APPROVED`" — the
        approval transition is declared only from `SUBMITTED`. PRD Section 2.10
        step 5: "the target entity's current status must permit the requested
        transition, and terminal states accept no further transitions —
        otherwise `ERR_INVALID_STATE` (409)."

        Design: Corner/state_machines/invalid_transition_approve_from_deficient
        """
        ctx = create_submitted_request(
            category="RR", jurisdictions=("CA",), submitter_user_id="rp-it"
        )
        request = ctx["request"]
        resp = api.return_deficient_registration_request(
            request["id"], make_user_headers("co-it", "ComplianceOfficer")
        )
        deficient = validate_success(resp)
        assert deficient["status"] == "DEFICIENT"

        resp = api.approve_registration_request(
            request["id"], make_user_headers("co-it", "ComplianceOfficer")
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_deny_requires_flagged_or_expired(self, api):
        """PRD Section 3.5: "Denial is available only with cause: at least one
        disclosure answer in `review_status` `FLAGGED`, or at least one exam
        requirement in `EXPIRED` status."

        Design: Corner/state_machines/deny_requires_flagged_or_expired
        """
        ctx = create_submitted_request(
            category="RR", jurisdictions=("CA",), submitter_user_id="rp-dn"
        )
        resp = api.deny_registration_request(
            ctx["request"]["id"], make_user_headers("co-dn", "ComplianceOfficer")
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestDeficiencyCycle:
    def test_deficiency_auto_withdraw_below_threshold(self, api):
        """PRD Section 3.5: "The second return therefore leaves the request
        `DEFICIENT` with `deficiency_count` at two, and the third return
        withdraws it."

        Design: Corner/calculations/deficiency_auto_withdraw_below_threshold
        """
        ctx = create_submitted_request(
            category="RR", jurisdictions=("CA",), submitter_user_id="rp-th"
        )
        request = ctx["request"]
        reviewer = make_user_headers("co-th", "ComplianceOfficer")

        first = validate_success(api.return_deficient_registration_request(
            request["id"], reviewer
        ))
        assert first["status"] == "DEFICIENT"
        assert first["deficiency_count"] == 1

        submit_request(request["id"], "rp-th")

        second = validate_success(api.return_deficient_registration_request(
            request["id"], reviewer
        ))
        assert second["status"] == "DEFICIENT"
        assert second["deficiency_count"] == 2

    def test_deficiency_cycle_third_return_auto_withdraws(self, api):
        """PRD Section 3.5: "when the increment makes the count reach three,
        the request does not go back to `DEFICIENT` at all but auto-withdraws,
        landing in `WITHDRAWN`." PRD Section 3.5: "withdrawing a request ...
        flips every `SELECTED` jurisdiction selection to `RELINQUISHED`".

        Design: Difficulty/non_linear_state_machine/registration_request_deficiency_cycle_with_auto_withdraw
        """
        ctx = create_submitted_request(
            category="RR", jurisdictions=("CA",), submitter_user_id="rp-cycle"
        )
        request = ctx["request"]
        reviewer = make_user_headers("co-cycle", "ComplianceOfficer")

        for _ in range(2):
            returned = validate_success(
                api.return_deficient_registration_request(request["id"], reviewer)
            )
            assert returned["status"] == "DEFICIENT"
            submit_request(request["id"], "rp-cycle")

        third = validate_success(
            api.return_deficient_registration_request(request["id"], reviewer)
        )
        assert third["status"] == "WITHDRAWN"
        assert third["deficiency_count"] == 3

        after = get_request(request["id"])
        assert after["status"] == "WITHDRAWN"
        assert after["deficiency_count"] == 3

        sel_id = ctx["selections"]["CA"]["id"]
        sel = validate_success(api.get_jurisdiction_selection(sel_id, make_user_headers("so-read-1", "SystemOperator")))
        assert sel["status"] == "RELINQUISHED"

    def test_deficiency_count_increments_on_each_return(self, api):
        """PRD Section 3.5: "Returning the request deficient moves
        `SUBMITTED → DEFICIENT` and increments `deficiency_count` — with a hard
        stop: when the increment makes the count reach three, the request does
        not go back to `DEFICIENT` at all but auto-withdraws, landing in
        `WITHDRAWN`."

        Design: Difficulty/non_linear_state_machine/registration_request_deficiency_cycle_with_auto_withdraw
        """
        ctx = create_submitted_request(
            category="RR", jurisdictions=("CA",), submitter_user_id="rp-cycle2"
        )
        request = ctx["request"]
        reviewer = make_user_headers("co-cycle2", "ComplianceOfficer")

        r1 = validate_success(
            api.return_deficient_registration_request(request["id"], reviewer)
        )
        assert (r1["status"], r1["deficiency_count"]) == ("DEFICIENT", 1)

        submit_request(request["id"], "rp-cycle2")
        r2 = validate_success(
            api.return_deficient_registration_request(request["id"], reviewer)
        )
        assert (r2["status"], r2["deficiency_count"]) == ("DEFICIENT", 2)

        submit_request(request["id"], "rp-cycle2")
        r3 = validate_success(
            api.return_deficient_registration_request(request["id"], reviewer)
        )
        assert (r3["status"], r3["deficiency_count"]) == ("WITHDRAWN", 3)


class TestExamRequirements:
    def test_exam_requirement_initial_state_and_waiver(
        self, api, compliance_officer_headers
    ):
        """PRD Section 3.4: "Every obligation starts in `REQUIRED` status."
        PRD Section 3.4: "A `ComplianceOfficer` may also waive a requirement
        outright — moving it `REQUIRED → WAIVED` — but only while the parent
        request is still in `DRAFT` or `DEFICIENT`."

        Design: Corner/state_machines/exam_requirement_initial_state_and_waiver
        """
        firm, applicant, request, _ = create_firm_applicant_request(
            category="PRINCIPAL", jurisdictions=("CA",)
        )
        from test_helpers import add_exam_requirement
        req = add_exam_requirement(request["id"], "S24")
        assert req["status"] == "REQUIRED"

        waived = validate_success(
            api.waive_exam_requirement(req["id"], compliance_officer_headers)
        )
        assert waived["status"] == "WAIVED"

    def test_exam_window_out_of_window_result_rejected(
        self, api, system_operator_headers
    ):
        """PRD Section 3.4: "A `result` of `PASS` additionally requires the
        server clock to sit inside the window — at or after `window_start` and
        strictly before `window_end`; a pass recorded outside that span is
        rejected `ERR_TEMPORAL_VIOLATION`."

        Design: Corner/state_machines/exam_window_out_of_window_result_rejected
        """
        firm, applicant, request, _ = create_firm_applicant_request(
            category="RR", jurisdictions=("CA",)
        )
        from test_helpers import add_exam_requirement
        req = add_exam_requirement(request["id"], "SIE")
        set_clock("2026-06-01T00:00:00Z")
        win = schedule_exam_window(
            req["id"], "2026-06-10T00:00:00Z", "2026-06-11T00:00:00Z"
        )
        set_clock("2026-06-11T00:00:00Z")
        resp = api.record_exam_result(
            win["id"], {"result": "PASS"}, system_operator_headers
        )
        validate_error(resp, ApiErrorId.ERR_TEMPORAL_VIOLATION)

    def test_exam_window_gated_by_sie_requirement_state(self, api):
        """PRD Section 3.4: "for any exam other than `SIE`, only once the same
        registration request's `SIE` obligation is already satisfied or in
        progress — that is, in `SCHEDULED`, `PASSED`, or `WAIVED` status, since
        `SIE` is the prerequisite to every top-off exam, with violations
        rejected `ERR_REFERENTIAL_VIOLATION`."

        Design: Difficulty/cross_entity_state_dependency/exam_window_gated_by_sie_requirement_state
        """
        firm, applicant, request, _ = create_firm_applicant_request(
            category="RR", jurisdictions=("CA",)
        )
        from test_helpers import add_exam_requirement
        sie = add_exam_requirement(request["id"], "SIE")
        s7 = add_exam_requirement(request["id"], "S7")
        set_clock("2026-06-10T00:00:00Z")

        # S7 window while SIE is still REQUIRED -> rejected.
        resp = api.create_exam_window(
            {
                "exam_requirement_id": s7["id"],
                "window_start": "2026-06-10T00:00:00Z",
                "window_end": "2026-06-11T00:00:00Z",
            },
            make_user_headers("rp-x2", "RegistrationPrincipal"),
        )
        validate_error(resp, ApiErrorId.ERR_REFERENTIAL_VIOLATION)

        # Schedule SIE (REQUIRED -> SCHEDULED), then S7 is accepted.
        sie_win = schedule_exam_window(
            sie["id"], "2026-06-10T00:00:00Z", "2026-06-11T00:00:00Z"
        )
        assert sie_win["status"] == "SCHEDULED"

        s7_win = schedule_exam_window(
            s7["id"], "2026-06-12T00:00:00Z", "2026-06-13T00:00:00Z"
        )
        assert s7_win["status"] == "SCHEDULED"
        s7_after = get_exam_requirement(s7["id"])
        assert s7_after["status"] == "SCHEDULED"

    def test_exam_window_rejected_after_sie_satisfied_by_waiver(self, api):
        """PRD Section 3.4: "for any exam other than `SIE`, only once the same
        registration request's `SIE` obligation is already satisfied or in
        progress — that is, in `SCHEDULED`, `PASSED`, or `WAIVED` status ...
        with violations rejected `ERR_REFERENTIAL_VIOLATION`." The gate is the
        sibling SIE row's status membership, evaluated at window creation.

        Design: Difficulty/cross_entity_state_dependency/exam_window_gated_by_sie_requirement_state
        """
        firm, applicant, request, _ = create_firm_applicant_request(
            category="RR", jurisdictions=("CA",)
        )
        from test_helpers import add_exam_requirement
        sie = add_exam_requirement(request["id"], "SIE")
        s7 = add_exam_requirement(request["id"], "S7")
        set_clock("2026-06-10T00:00:00Z")

        # While SIE is REQUIRED the S7 window is rejected.
        resp = api.create_exam_window(
            {
                "exam_requirement_id": s7["id"],
                "window_start": "2026-06-10T00:00:00Z",
                "window_end": "2026-06-11T00:00:00Z",
            },
            make_user_headers("rp-x2b", "RegistrationPrincipal"),
        )
        validate_error(resp, ApiErrorId.ERR_REFERENTIAL_VIOLATION)

        # SIE -> WAIVED (parent request is DRAFT) satisfies the gate.
        validate_success(
            api.waive_exam_requirement(
                sie["id"], make_user_headers("co-x2b", "ComplianceOfficer")
            )
        )
        s7_win = schedule_exam_window(
            s7["id"], "2026-06-12T00:00:00Z", "2026-06-13T00:00:00Z"
        )
        assert s7_win["status"] == "SCHEDULED"


class TestExamWindowSlotOccupation:
    def test_exam_window_slot_occupation_disjoint_rejected(self, api):
        """PRD Section 3.4: "Scheduling is only possible while the requirement
        is `REQUIRED`; while another window for the same requirement is
        `SCHEDULED` or `OPEN` — at most one such window per requirement,
        enforced with `ERR_DUPLICATE`". PRD Section 3.4: "On a `result` of
        `FAIL` or `NO_SHOW` the window likewise closes to `USED` with
        `result_recorded` set to the recorded outcome, but the requirement
        cycles back to `REQUIRED`, freeing the principal to schedule a fresh
        window."

        Design: Difficulty/resource_temporal_overlap/exam_window_slot_occupation_disjoint_rejected
        """
        firm, applicant, request, _ = create_firm_applicant_request(
            category="RR", jurisdictions=("CA",)
        )
        from test_helpers import add_exam_requirement
        sie = add_exam_requirement(request["id"], "SIE")
        set_clock("2026-06-01T10:00:00Z")

        w1 = schedule_exam_window(
            sie["id"], "2026-06-01T00:00:00Z", "2026-06-02T00:00:00Z"
        )
        assert w1["status"] == "SCHEDULED"

        # A second, fully disjoint window while W1 is SCHEDULED -> duplicate.
        resp = api.create_exam_window(
            {
                "exam_requirement_id": sie["id"],
                "window_start": "2026-07-01T00:00:00Z",
                "window_end": "2026-07-02T00:00:00Z",
            },
            make_user_headers("rp-o1", "RegistrationPrincipal"),
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE)

        # FAIL closes W1 (USED) and cycles the requirement back to REQUIRED.
        record_exam_result(w1["id"], "FAIL")

        w2 = schedule_exam_window(
            sie["id"], "2026-07-01T00:00:00Z", "2026-07-02T00:00:00Z"
        )
        assert w2["status"] == "SCHEDULED"

    def test_exam_window_slot_released_by_cancel(self, api):
        """PRD Section 3.4: "while another window for the same requirement is
        `SCHEDULED` or `OPEN` — at most one such window per requirement,
        enforced with `ERR_DUPLICATE`". PRD Section 3.4: "A `SCHEDULED` window
        can instead be cancelled by a `RegistrationPrincipal`, which moves the
        window to `CANCELLED` and returns the requirement to `REQUIRED`."

        Design: Difficulty/resource_temporal_overlap/exam_window_slot_occupation_disjoint_rejected
        """
        firm, applicant, request, _ = create_firm_applicant_request(
            category="RR", jurisdictions=("CA",)
        )
        from test_helpers import add_exam_requirement
        sie = add_exam_requirement(request["id"], "SIE")
        set_clock("2026-06-01T10:00:00Z")

        w1 = schedule_exam_window(
            sie["id"], "2026-06-01T00:00:00Z", "2026-06-02T00:00:00Z"
        )
        resp = api.create_exam_window(
            {
                "exam_requirement_id": sie["id"],
                "window_start": "2026-08-01T00:00:00Z",
                "window_end": "2026-08-02T00:00:00Z",
            },
            make_user_headers("rp-o1c", "RegistrationPrincipal"),
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE)

        cancelled = validate_success(
            api.cancel_exam_window(
                w1["id"], make_user_headers("rp-o1c", "RegistrationPrincipal")
            )
        )
        assert cancelled["status"] == "CANCELLED"
        assert get_exam_requirement(sie["id"])["status"] == "REQUIRED"

        w2 = schedule_exam_window(
            sie["id"], "2026-08-01T00:00:00Z", "2026-08-02T00:00:00Z"
        )
        assert w2["status"] == "SCHEDULED"


class TestExamFailCycleAndExpiry:
    def test_exam_fail_cycle_then_exact_expiry(self, api, system_operator_headers):
        """PRD Section 3.4: "On a `result` of `FAIL` or `NO_SHOW` ... the
        requirement cycles back to `REQUIRED`, freeing the principal to
        schedule a fresh window." PRD Section 3.4: "any requirement in
        `PASSED` status whose parent registration request is neither `ACTIVE`
        nor `TERMINATED` and whose `credit_expiry_at` has been reached or
        passed flips to `EXPIRED` — the boundary is inclusive".

        Design: Difficulty/non_linear_state_machine/exam_requirement_fail_cycle_then_exact_expiry
        """
        firm, applicant, request, _ = create_firm_applicant_request(
            category="RR", jurisdictions=("CA",)
        )
        from test_helpers import add_exam_requirement
        sie = add_exam_requirement(request["id"], "SIE")

        set_clock("2026-06-01T10:00:00Z")
        w1 = schedule_exam_window(
            sie["id"], "2026-06-01T00:00:00Z", "2026-06-02T00:00:00Z"
        )
        record_exam_result(w1["id"], "FAIL")
        assert get_exam_requirement(sie["id"])["status"] == "REQUIRED"

        # The FAIL cycle is what permits a second window on the requirement.
        w2 = schedule_exam_window(
            sie["id"], "2026-06-03T00:00:00Z", "2026-06-04T00:00:00Z"
        )
        set_clock("2026-06-03T12:00:00Z")
        record_exam_result(w2["id"], "PASS")

        passed = get_exam_requirement(sie["id"])
        assert passed["status"] == "PASSED"
        assert passed["credit_expiry_at"][:19] == "2026-10-01T12:00:00"

        # One second before expiry: still PASSED (parent request is DRAFT).
        set_clock("2026-10-01T11:59:59Z")
        before = get_exam_requirement(sie["id"])
        assert before["status"] == "PASSED"

        # Exactly at credit_expiry_at: the inclusive boundary flips it.
        set_clock("2026-10-01T12:00:00Z")
        after = get_exam_requirement(sie["id"])
        assert after["status"] == "EXPIRED"

    def test_exam_fail_cycle_resets_and_repasses(self, api):
        """PRD Section 3.4: "On a `result` of `FAIL` or `NO_SHOW` the window
        likewise closes to `USED` with `result_recorded` set to the recorded
        outcome, but the requirement cycles back to `REQUIRED`". PRD Section
        3.4: "On a pass the window closes to `USED` with `result_recorded` set
        to `PASS`, the requirement moves to `PASSED`, its `pass_recorded_at`
        is stamped with the server time, and its `credit_expiry_at` is
        computed as exactly 120 days after `pass_recorded_at`."

        Design: Difficulty/non_linear_state_machine/exam_requirement_fail_cycle_then_exact_expiry
        """
        firm, applicant, request, _ = create_firm_applicant_request(
            category="RR", jurisdictions=("CA",)
        )
        from test_helpers import add_exam_requirement
        sie = add_exam_requirement(request["id"], "SIE")

        set_clock("2026-06-01T10:00:00Z")
        w1 = schedule_exam_window(
            sie["id"], "2026-06-01T00:00:00Z", "2026-06-02T00:00:00Z"
        )
        failed_win = record_exam_result(w1["id"], "FAIL")
        assert failed_win["status"] == "USED"
        assert failed_win["result_recorded"] == "FAIL"
        assert get_exam_requirement(sie["id"])["status"] == "REQUIRED"

        w2 = schedule_exam_window(
            sie["id"], "2026-06-03T00:00:00Z", "2026-06-04T00:00:00Z"
        )
        set_clock("2026-06-03T12:00:00Z")
        passed_win = record_exam_result(w2["id"], "PASS")
        assert passed_win["status"] == "USED"
        assert passed_win["result_recorded"] == "PASS"

        req_after = get_exam_requirement(sie["id"])
        assert req_after["status"] == "PASSED"
        assert req_after["pass_recorded_at"][:19] == "2026-06-03T12:00:00"
        assert req_after["credit_expiry_at"][:19] == "2026-10-01T12:00:00"


class TestExamCreditBoundary:
    def test_exam_credit_expires_at_exact_second(self, api):
        """PRD Section 3.4: "any requirement in `PASSED` status whose parent
        registration request is neither `ACTIVE` nor `TERMINATED` and whose
        `credit_expiry_at` has been reached or passed flips to `EXPIRED` — the
        boundary is inclusive, so a credit expires exactly at the expiry
        instant, not one second later."

        Design: Difficulty/boundary_precision_check/exam_credit_expires_at_exact_second
        """
        firm, applicant, request, _ = create_firm_applicant_request(
            category="RR", jurisdictions=("CA",)
        )
        from test_helpers import add_exam_requirement
        sie = add_exam_requirement(request["id"], "SIE")

        set_clock("2026-06-01T10:00:00Z")
        win = schedule_exam_window(
            sie["id"], "2026-06-01T00:00:00Z", "2026-06-02T00:00:00Z"
        )
        record_exam_result(win["id"], "PASS")
        passed = get_exam_requirement(sie["id"])
        assert passed["credit_expiry_at"][:19] == "2026-09-29T10:00:00"

        # Parent request stays DRAFT, so the expiry sweep applies to it.
        set_clock("2026-09-29T09:59:59Z")
        before = get_exam_requirement(sie["id"])
        assert before["status"] == "PASSED"

        set_clock("2026-09-29T10:00:00Z")
        at = get_exam_requirement(sie["id"])
        assert at["status"] == "EXPIRED"

    def test_exam_credit_locked_once_registration_active(self, api):
        """PRD Section 3.4: "Once a registration has gone `ACTIVE` (or been
        `TERMINATED`), its exam credits are locked in and never expire."
        Contrasted with the expiry rule: "any requirement in `PASSED` status
        whose parent registration request is neither `ACTIVE` nor `TERMINATED`
        and whose `credit_expiry_at` has been reached or passed flips to
        `EXPIRED`".

        Design: Difficulty/boundary_precision_check/exam_credit_expires_at_exact_second
        """
        from test_helpers import create_active_registration
        ctx = create_active_registration(
            category="IA",
            jurisdictions=("CA",),
            approve_date="2026-06-02",
            submitter_user_id="rp-lock-exp",
            reviewer_user_id="co-lock-exp",
        )
        assert ctx["request"]["status"] == "ACTIVE"
        sie = ctx["exams"]["SIE"]

        # Park the clock well past the credit expiry of the passed exams.
        set_clock("2027-06-01T00:00:00Z")
        after = get_exam_requirement(sie["id"])
        assert after["status"] == "PASSED"


class TestDeferredActivation:
    def test_scheduled_deferred_activation_rollover(self, api, system_operator_headers):
        """PRD Section 3.5: "The request moves `APPROVED → ACTIVE` as a system
        transition evaluated when the server clock is set: at the first moment
        of the calendar day following the approval date — precisely, when the
        clock's current date is strictly after the date of `approved_at` — the
        status rolls forward".

        Design: Corner/cross_cutting_layers/scheduled_deferred_activation_rollover
        """
        from test_helpers import (
            create_firm_applicant_request,
            create_fingerprint_submission,
            process_fingerprint,
            pass_exam_requirement,
            submit_request,
        )
        firm, applicant, request, _ = create_firm_applicant_request(
            category="IA", jurisdictions=("CA",)
        )
        fp = create_fingerprint_submission(request["id"])
        process_fingerprint(fp["id"], "CLEARED")
        submit_request(request["id"], "rp-sc")
        from test_helpers import list_exam_requirements
        exams = {r["exam_code"]: r for r in list_exam_requirements(request["id"])}
        for code in ("SIE", "S66"):
            pass_exam_requirement(
                exams[code]["id"],
                "2026-06-01T00:00:00Z",
                "2026-06-03T00:00:00Z",
                pass_clock="2026-06-01T00:00:00Z",
            )
        set_clock("2026-06-02T10:00:00Z")
        approved = validate_success(
            api.approve_registration_request(
                request["id"], make_user_headers("co-sc", "ComplianceOfficer")
            )
        )
        assert approved["status"] == "APPROVED"

        # Same calendar day as the approval: still APPROVED.
        set_clock("2026-06-02T23:59:59Z")
        eod = get_request(request["id"])
        assert eod["status"] == "APPROVED"

        # The next calendar day rolls the request forward to ACTIVE.
        set_clock("2026-06-03T00:00:00Z")
        nxt = get_request(request["id"])
        assert nxt["status"] == "ACTIVE"


class TestInquiryWorkflow:
    def test_inquiry_late_response_rejected(self, api, regulator_headers,
                                            system_operator_headers,
                                            compliance_officer_headers):
        """PRD Section 3.9: "a response filed after `response_due_at` is
        rejected `ERR_TEMPORAL_VIOLATION` — late answers are not accepted."
        PRD Section 2.6: "A regulatory inquiry's `response_due_at` is anchored
        on the inquiry's creation timestamp and runs 15 business days —
        inquiries always use the `REGULATORY` basis".

        Design: Corner/state_machines/inquiry_late_response_rejected
        """
        ctx = create_submitted_request(
            category="RR", jurisdictions=("CA",), submitter_user_id="rp-lt"
        )
        set_clock("2026-08-03T00:00:00Z")  # Monday
        inquiry = validate_success(
            api.create_regulatory_inquiry(
                {
                    "subject_filing_type": "REGISTRATION_REQUEST",
                    "subject_filing_id": ctx["request"]["id"],
                    "inquiry_text": "Regulator seeks clarification on U4 answers.",
                },
                regulator_headers,
            ),
            expected_status=201,
        )
        # 15 business days from 2026-08-03 (Mon) lands on 2026-08-24 (Mon).
        assert inquiry["response_due_at"][:10] == "2026-08-24"

        validate_success(api.route_regulatory_inquiry(inquiry["id"], system_operator_headers))

        set_clock("2026-08-25T00:00:00Z")
        resp = api.respond_regulatory_inquiry(
            inquiry["id"],
            {"response_text": "Late but complete response to the inquiry."},
            compliance_officer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_TEMPORAL_VIOLATION)

    def test_open_inquiry_count_conservation_create_and_route(self, api,
                                                              regulator_headers,
                                                              system_operator_headers):
        """PRD Section 3.9: "recomputes the firm's `open_inquiry_count` — which
        counts inquiries in `OPEN` or `PENDING_RESPONSE`, so a fresh inquiry
        raises it." PRD Section 3.9: "since both states count toward the
        firm's open total, routing leaves `open_inquiry_count` unchanged."

        Design: Difficulty/compensating_invariant/open_inquiry_count_conservation_across_lifecycle
        """
        ctx = create_submitted_request(
            category="RR", jurisdictions=("CA",), submitter_user_id="rp-inv2"
        )
        firm_id = ctx["firm"]["id"]
        assert get_firm(firm_id)["open_inquiry_count"] == 0

        set_clock("2026-08-03T00:00:00Z")
        inquiry = validate_success(
            api.create_regulatory_inquiry(
                {
                    "subject_filing_type": "REGISTRATION_REQUEST",
                    "subject_filing_id": ctx["request"]["id"],
                    "inquiry_text": "Regulator question about the U4 filing content.",
                },
                regulator_headers,
            ),
            expected_status=201,
        )
        assert get_firm(firm_id)["open_inquiry_count"] == 1

        validate_success(api.route_regulatory_inquiry(inquiry["id"], system_operator_headers))
        assert get_firm(firm_id)["open_inquiry_count"] == 1

    def test_open_inquiry_count_conservation_respond_and_close(self, api,
                                                               regulator_headers,
                                                               system_operator_headers,
                                                               compliance_officer_headers):
        """PRD Section 3.9: "A successful response moves the inquiry to
        `RESPONDED`, stores the text, and recomputes `open_inquiry_count` down
        by one, `RESPONDED` being outside the counted set." PRD Section 3.1:
        "it is the number of the firm's regulatory inquiries currently in
        `OPEN` or `PENDING_RESPONSE` status, recomputed on every inquiry
        status change."

        Design: Difficulty/compensating_invariant/open_inquiry_count_conservation_across_lifecycle
        """
        ctx = create_submitted_request(
            category="RR", jurisdictions=("CA",), submitter_user_id="rp-inv2b"
        )
        firm_id = ctx["firm"]["id"]

        set_clock("2026-08-03T00:00:00Z")
        inquiry = validate_success(
            api.create_regulatory_inquiry(
                {
                    "subject_filing_type": "REGISTRATION_REQUEST",
                    "subject_filing_id": ctx["request"]["id"],
                    "inquiry_text": "Regulator question about the filing content.",
                },
                regulator_headers,
            ),
            expected_status=201,
        )
        validate_success(api.route_regulatory_inquiry(inquiry["id"], system_operator_headers))
        assert get_firm(firm_id)["open_inquiry_count"] == 1

        responded = validate_success(
            api.respond_regulatory_inquiry(
                inquiry["id"],
                {"response_text": "Firm response addressing the regulator question fully."},
                compliance_officer_headers,
            )
        )
        assert responded["status"] == "RESPONDED"
        assert get_firm(firm_id)["open_inquiry_count"] == 0

        closed = validate_success(api.close_regulatory_inquiry(inquiry["id"], system_operator_headers))
        assert closed["status"] == "CLOSED"
        assert get_firm(firm_id)["open_inquiry_count"] == 0
