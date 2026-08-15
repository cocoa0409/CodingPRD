"""Complaints, compliance scoring, quality ratings, and interpreter standing."""
from datetime import datetime, timedelta, timezone

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    NON_EXISTENT_UUID,
    adjudicate_complaint,
    assert_complaint,
    complete_request,
    create_active_contract,
    create_assigned_request,
    create_department,
    create_interpreter,
    get_contract,
    get_department,
    get_interpreter,
    make_officer_headers,
    parse_iso8601,
    record_complaint,
    set_clock,
    setup_complaint_cascade_scenario,
    setup_completed_session_with_linked_complaint,
    setup_interpretation_workspace,
    validate_error,
    validate_success,
)

COORDINATOR = TEST_USERS["coordinator_headers"]


class TestSubstantiationCascade:
    def test_third_substantiation_suspends_and_cancels_assigned(self, api):
        """PRD §3.7: "A linked session costs its interpreter a 200-point rating
        event timed at `adjudicated_at`, and if that recomputation drops an
        `ACTIVE` interpreter below 600, the auto-suspension of §3.5 fires with
        its request-cancellation cascade."
        PRD §3.5: "Whenever a recomputation lands below 600 on an `ACTIVE`
        interpreter, the system suspends them automatically — `ACTIVE` →
        `SUSPENDED` — and every `ASSIGNED` request they hold is cancelled, each
        cancellation releasing its `estimated_cost_cents` commitment from the
        interpreter's contract."

        Design: Difficulty/transitive_cascade/complaint_substantiation_suspension_cancellation_release
        """
        sc = setup_complaint_cascade_scenario()
        c1, c2, c3 = (c["id"] for c in sc["complaints"])
        adjudicate_complaint(c1, outcome="SUBSTANTIATED")
        adjudicate_complaint(c2, outcome="SUBSTANTIATED")
        adjudicate_complaint(c3, outcome="SUBSTANTIATED")

        interpreter = get_interpreter(sc["interpreter"]["id"])
        assert interpreter["quality_rating"] == 400, "1000 clamped + 3 x -200"
        assert interpreter["status"] == "SUSPENDED", (
            "the third substantiation drops the rating below 600"
        )
        pending = validate_success(api.get_interpretation_request(
            sc["pending"]["id"], COORDINATOR))
        assert pending["status"] == "CANCELLED", (
            "the suspension cascade cancels the interpreter's ASSIGNED request"
        )
        contract = get_contract(sc["contract"]["id"])
        assert contract["committed_cents"] == 0, "the 1725-cent estimate releases"
        assert contract["spent_cents"] == 5175, (
            "the three completed 1725-cent sessions are unaffected"
        )

    def test_rating_boundary_and_department_posture(self, api):
        """PRD §3.5: "Whenever a recomputation lands below 600 on an `ACTIVE`
        interpreter, the system suspends them automatically"
        PRD §3.1: "a complaint adjudicated `SUBSTANTIATED` costs the department
        150 points, timed at the complaint's `adjudicated_at`"
        PRD §3.1: "The final score then derives `posture`: at least 800 is
        `GOOD_STANDING`, 600 through 799 is `WATCH`, and below 600 is
        `NONCOMPLIANT`."

        Design: Difficulty/transitive_cascade/complaint_substantiation_suspension_cancellation_release
        """
        sc = setup_complaint_cascade_scenario()
        c1, c2, c3 = (c["id"] for c in sc["complaints"])
        interpreter_id = sc["interpreter"]["id"]

        adjudicate_complaint(c1, outcome="SUBSTANTIATED")
        after_one = get_interpreter(interpreter_id)
        assert after_one["quality_rating"] == 800
        assert after_one["status"] == "ACTIVE"

        adjudicate_complaint(c2, outcome="SUBSTANTIATED")
        after_two = get_interpreter(interpreter_id)
        assert after_two["quality_rating"] == 600
        assert after_two["status"] == "ACTIVE", (
            "600 is not below 600 — the suspension threshold is exclusive"
        )

        adjudicate_complaint(c3, outcome="SUBSTANTIATED")
        dept = get_department(sc["department"]["id"])
        assert dept["compliance_score"] == 550, "1000 - 3 x 150"
        assert dept["posture"] == "NONCOMPLIANT"


class TestRefundClawback:
    def test_refund_claws_back_minutes_and_flags_request(self, api):
        """PRD §3.7: "A `REFUND` remedy subtracts the linked request's
        `final_cost_cents` from both the department's `spent_cents` and the
        billing contract's `spent_cents`, sets the request's
        `refund_clawed_back` flag (false on every request until this moment),
        and removes its minutes from the interpreter's monthly tally."

        Design: Difficulty/compensating_invariant/interpreter_minutes_completion_refund_clawback
        """
        sc = setup_completed_session_with_linked_complaint(duration_minutes=130)
        interpreter_id = sc["interpreter"]["id"]
        assert get_interpreter(interpreter_id)["minutes_current_month"] == 130
        assert get_department(sc["department"]["id"])["spent_cents"] == 7590
        assert get_contract(sc["contract"]["id"])["spent_cents"] == 7590

        adjudicate_complaint(sc["complaint"]["id"], outcome="SUBSTANTIATED",
                             remedy="REFUND")

        request = validate_success(api.get_interpretation_request(
            sc["request"]["id"], COORDINATOR))
        assert request["refund_clawed_back"] is True
        assert get_interpreter(interpreter_id)["minutes_current_month"] == 0, (
            "the clawback removes exactly the minutes the completion added"
        )

    def test_refund_restores_dollar_ledgers_and_scores(self, api):
        """PRD §3.7: "A `REFUND` remedy subtracts the linked request's
        `final_cost_cents` from both the department's `spent_cents` and the
        billing contract's `spent_cents`"
        PRD §3.5: "a substantiated complaint linked to one of the interpreter's
        requests costs 200 points, timed at the complaint's `adjudicated_at`."
        PRD §3.1: "a complaint adjudicated `SUBSTANTIATED` costs the department
        150 points, timed at the complaint's `adjudicated_at`"

        Design: Difficulty/compensating_invariant/interpreter_minutes_completion_refund_clawback
        """
        sc = setup_completed_session_with_linked_complaint(duration_minutes=130)
        adjudicate_complaint(sc["complaint"]["id"], outcome="SUBSTANTIATED",
                             remedy="REFUND")

        assert get_department(sc["department"]["id"])["spent_cents"] == 0
        assert get_contract(sc["contract"]["id"])["spent_cents"] == 0
        interpreter = get_interpreter(sc["interpreter"]["id"])
        assert interpreter["quality_rating"] == 800, (
            "completion +5 clamps at the 1000 cap before the -200 lands"
        )
        assert interpreter["status"] == "ACTIVE", "800 is above the 600 floor"
        assert get_department(sc["department"]["id"])["compliance_score"] == 850


class TestRatingReplay:
    def test_rating_stepwise_clamp_at_cap_before_penalty(self, api):
        """PRD §3.5: "Completed sessions earn the interpreter 5 points each,
        timed at the request's `completed_at`; a substantiated complaint linked
        to one of the interpreter's requests costs 200 points, timed at the
        complaint's `adjudicated_at`. Recomputation sorts those events by their
        timestamps in ascending order, breaks ties by the source record's
        `created_at`, starts at 1000, and clamps each running step to the
        0-to-1000 band."

        Design: Corner/calculations/rating_stepwise_clamp_at_cap_before_penalty
        """
        ws = setup_interpretation_workspace(dept_budget=1_000_000,
                                            ceiling_cents=500000,
                                            tier="CERTIFIED",
                                            interpreter_name="Clara Clamp")
        dept_id = ws["department"]["id"]
        interpreter_id = ws["interpreter"]["id"]
        request = create_assigned_request(
            dept_id, modality="PHONE", scheduled_duration_minutes=30,
            scheduled_start="2026-08-01T10:00:00Z")
        complete_request(request["id"], interpreter_id, 30)
        complaint = record_complaint(dept_id, category="POOR_QUALITY",
                                     description="clamp check",
                                     interpretation_request_id=request["id"])

        adjudicate_complaint(complaint["id"], outcome="SUBSTANTIATED")

        interpreter = get_interpreter(interpreter_id)
        # Stepwise clamp: 1000 + 5 is clamped back to 1000 BEFORE the -200
        # lands, yielding exactly 800 — an unclamped accumulator would read 805.
        assert interpreter["quality_rating"] == 800
        assert interpreter["status"] == "ACTIVE"


class TestDismissalBranch:
    def test_dismissed_complaint_has_no_side_effects(self, api):
        """PRD §3.7: "Dismissal stamps `adjudicated_by_user_id` and
        `adjudicated_at` and terminates the complaint with no further effect."

        Design: Corner/state_machines/dismissed_complaint_has_no_side_effects
        """
        dept = create_department(name="Dept Dis", service_area_code="SA-C12",
                                 annual_budget_cents=100000)
        complaint = record_complaint(dept["id"], category="OTHER",
                                     description="unfounded")
        dismissed = adjudicate_complaint(complaint["id"], outcome="DISMISSED")
        assert_complaint(dismissed)
        assert dismissed["status"] == "DISMISSED"
        assert dismissed["remediation_due_at"] is None
        assert dismissed["closed_at"] is None
        assert dismissed["adjudicated_by_user_id"] is not None
        dept_after = get_department(dept["id"])
        assert dept_after["compliance_score"] == 1000, (
            "dismissal records no -150 event"
        )
        assert dept_after["posture"] == "GOOD_STANDING"
        assert dept_after["signage_status"] == "CURRENT"


class TestSignageCascade:
    def test_notice_missing_substantiation_marks_signage_deficient(self, api):
        """PRD §3.7: "A complaint in the `NOTICE_MISSING` category flips the
        department's `signage_status` to `DEFICIENT`."
        PRD §3.7: "Substantiation stamps the same two fields, fixes a
        remediation deadline — `remediation_due_at` set thirty days after
        adjudication — and records an optional `remedy` of `NONE` or `REFUND`"

        Design: Corner/complexity_layers/notice_missing_substantiation_marks_signage_deficient
        """
        dept = create_department(name="Dept Sign", service_area_code="SA-C44",
                                 annual_budget_cents=100000)
        complaint = record_complaint(dept["id"], category="NOTICE_MISSING",
                                     description="no signage at lobby")
        substantiated = adjudicate_complaint(complaint["id"],
                                             outcome="SUBSTANTIATED")
        dept_after = get_department(dept["id"])
        assert dept_after["signage_status"] == "DEFICIENT", (
            "the NOTICE_MISSING cascade flips signage in the same request"
        )
        assert dept_after["compliance_score"] == 850, "single -150 event"
        due = parse_iso8601(substantiated["remediation_due_at"])
        adjudicated = parse_iso8601(substantiated["adjudicated_at"])
        assert due - adjudicated == timedelta(days=30), (
            "remediation_due_at must be exactly thirty days after adjudication"
        )


class TestRemediationWindow:
    def _substantiated_complaint(self, dept_name):
        dept = create_department(name=dept_name, annual_budget_cents=100000)
        complaint = record_complaint(dept["id"], category="OTHER",
                                     description="fixable")
        adjudicate_complaint(complaint["id"], outcome="SUBSTANTIATED")
        return dept, complaint

    def test_close_within_remediation_window_restores_points(self, api):
        """PRD §3.7: "Closing a `SUBSTANTIATED` complaint requires a
        `resolution_note` (its absence is `ERR_VALIDATION`) and stamps
        `closed_at` from the logical clock, landing the complaint in `RESOLVED`.
        A close timed on or before `remediation_due_at` restores 100 compliance
        points at `closed_at`; a late close restores nothing."

        Design: Corner/complexity_layers/close_within_remediation_window_restores_points
        """
        dept, complaint = self._substantiated_complaint("Dept Ontime")
        # Substantiated at the 2026-08-01 startup clock, due 2026-08-31.
        set_clock("2026-08-15T00:00:00Z")
        closed = validate_success(api.close_complaint(
            complaint["id"], {"resolution_note": "fixed within window"},
            make_officer_headers()))
        assert closed["status"] == "RESOLVED"
        assert parse_iso8601(closed["closed_at"]) == datetime(
            2026, 8, 15, tzinfo=timezone.utc)
        assert get_department(dept["id"])["compliance_score"] == 950, (
            "1000 - 150 + 100 for the on-time close"
        )

    def test_close_after_remediation_window_restores_nothing(self, api):
        """PRD §3.7: "A close timed on or before `remediation_due_at` restores
        100 compliance points at `closed_at`; a late close restores nothing."

        Design: Corner/complexity_layers/close_after_remediation_window_restores_nothing
        """
        dept, complaint = self._substantiated_complaint("Dept Late")
        # Substantiated at 2026-08-01 (due 2026-08-31); closed 2026-09-01.
        set_clock("2026-09-01T00:00:00Z")
        closed = validate_success(api.close_complaint(
            complaint["id"], {"resolution_note": "fixed late"},
            make_officer_headers()))
        assert closed["status"] == "RESOLVED"
        assert get_department(dept["id"])["compliance_score"] == 850, (
            "closed_at past remediation_due_at restores no points"
        )


class TestComplaintSegregationOfDuties:
    def test_officer_cannot_adjudicate_own_recorded_complaint(self, api):
        """PRD §3.7: "Complaints enter through the liaison of the affected
        department — again scoped to their own department — or through a
        `ComplianceOfficer` staffing the intake desk."
        PRD §3.7: "Adjudication is ComplianceOfficer-only, and segregation of
        duties forbids the officer who recorded the complaint from adjudicating
        it: a caller whose identity matches `recorded_by_user_id` is refused
        with `ERR_SEGREGATION_OF_DUTIES_VIOLATION`."

        Design: Corner/rbac/officer_cannot_adjudicate_own_recorded_complaint
        """
        dept = create_department(name="Dept Intake", service_area_code="SA-C38",
                                 annual_budget_cents=100000)
        complaint = record_complaint(dept["id"], category="OTHER",
                                     description="self-filed",
                                     officer_id="officer-9")
        assert complaint["recorded_by_user_id"] == "officer-9"

        blocked = api.adjudicate_complaint(
            complaint["id"], {"outcome": "SUBSTANTIATED"},
            make_officer_headers("officer-9"))
        validate_error(blocked, ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION.value)

        substantiated = validate_success(api.adjudicate_complaint(
            complaint["id"], {"outcome": "SUBSTANTIATED"},
            make_officer_headers("officer-7")))
        assert substantiated["status"] == "SUBSTANTIATED"
        assert substantiated["adjudicated_by_user_id"] == "officer-7"


class TestInterpreterStandingCycle:
    def _rostered_interpreter(self):
        contract = create_active_contract(vendor_name="VendorFive",
                                          ceiling_cents=1_000_000)
        interpreter = create_interpreter(contract["id"], full_name="Cyclical Cy",
                                         tier="CERTIFIED")
        return interpreter

    def test_suspend_then_reinstate_status_cycle(self, api):
        """PRD §3.5: "A `ComplianceOfficer` may also suspend an `ACTIVE`
        interpreter by hand; a manual suspension changes only the status and
        does not cancel assigned work. Reinstatement — `SUSPENDED` → `ACTIVE`,
        again ComplianceOfficer-only — resets the `quality_rating` to a
        probationary floor of 600."

        Design: Difficulty/non_linear_state_machine/interpreter_suspension_reinstatement_loop
        """
        interpreter = self._rostered_interpreter()
        suspended = validate_success(api.patch_interpreter(
            interpreter["id"], {"status": "SUSPENDED"}, make_officer_headers()))
        assert suspended["status"] == "SUSPENDED"
        reinstated = validate_success(api.patch_interpreter(
            interpreter["id"], {"status": "ACTIVE"}, make_officer_headers()))
        assert reinstated["status"] == "ACTIVE", (
            "the ACTIVE <-> SUSPENDED cycle must be traversable both ways"
        )

    def test_reinstatement_resets_rating_to_probationary_floor(self, api):
        """PRD §3.5: "Reinstatement — `SUSPENDED` → `ACTIVE`, again
        ComplianceOfficer-only — resets the `quality_rating` to a probationary
        floor of 600."
        PRD §3.5: "New interpreters arrive `ACTIVE` with a `quality_rating` of
        1000"

        Design: Difficulty/non_linear_state_machine/interpreter_suspension_reinstatement_loop
        """
        interpreter = self._rostered_interpreter()
        assert interpreter["quality_rating"] == 1000
        validate_success(api.patch_interpreter(
            interpreter["id"], {"status": "SUSPENDED"}, make_officer_headers()))
        reinstated = validate_success(api.patch_interpreter(
            interpreter["id"], {"status": "ACTIVE"}, make_officer_headers()))
        assert reinstated["quality_rating"] == 600, (
            "reinstatement resets the rating from 1000 to the probationary floor"
        )


class TestComplaintNotFound:
    def test_get_complaint_not_found_returns_404(self, api, coordinator_headers):
        """PRD §2.8: "Each unresolvable reference produces the not-found
        identifier for its own resource type: `ERR_DEPARTMENT_NOT_FOUND`,
        `ERR_ASSESSMENT_NOT_FOUND`, `ERR_DOCUMENT_NOT_FOUND`, `ERR_JOB_NOT_FOUND`,
        `ERR_INTERPRETER_NOT_FOUND`, `ERR_REQUEST_NOT_FOUND`,
        `ERR_CONTRACT_NOT_FOUND`, `ERR_COMPLAINT_NOT_FOUND`, or
        `ERR_PLAN_NOT_FOUND`."

        Design: Corner/errors/get_complaint_not_found_returns_404
        """
        resp = api.get_complaint(NON_EXISTENT_UUID, coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_COMPLAINT_NOT_FOUND.value)
