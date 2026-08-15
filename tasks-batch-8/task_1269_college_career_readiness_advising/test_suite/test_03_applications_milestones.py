"""College applications, milestones, and decisions.

PRD §3.4 (both state dimensions, milestone gating, dependencies), §2.5
(logical clock), §2.6 (pipeline precedence).
"""
import pytest

from test_helpers import (
    TEST_USERS, ApiErrorId, assert_application, assert_milestone, assert_pct,
    complete_milestone, create_advisor, create_application,
    create_application_with_milestones, create_pathway, create_student,
    get_plan, make_advisor_headers, make_student_headers, set_clock,
    setup_student_with_active_plan, transition_application,
    validate_error, validate_success, waive_milestone,
)

ADMIN = TEST_USERS["district_admin_headers"]
DEADLINE = "2026-06-15T00:00:00Z"


class TestApplicationCreation:
    def test_application_create_autoseeds_milestones(self, api):
        """PRD §3.4: "The application begins with `submission_status` in
        `DRAFT` and `decision_status` in `NONE`, both `submitted_at` and
        `decided_at` unset, and the server auto-seeds three required
        milestones — `ESSAY`, `TRANSCRIPT`, and `FEE_PAYMENT` — each due at
        the application's `deadline_at` and each carrying no dependency, so
        all three arrive `READY` within the create response." PRD §3.4: "an
        application's milestone list is returned in `created_at` ascending
        order."

        Design: Corner/endpoints/application_create_autoseeds_milestones
        """
        ctx = setup_student_with_active_plan()
        student = ctx["student"]
        app = validate_success(
            api.create_application(
                student["id"],
                {"college_name": "State U", "program_type": "TRADE_PROGRAM",
                 "deadline_at": DEADLINE},
                make_student_headers(student["id"]),
            ),
            expected_status=201,
        )
        assert_application(app)
        assert app["submission_status"] == "DRAFT"
        assert app["decision_status"] == "NONE"

        milestones = validate_success(
            api.list_application_milestones(app["id"],
                                            make_student_headers(
                                                student["id"])))
        assert len(milestones) == 3
        for m in milestones:
            assert_milestone(m)
            assert m["required"] is True
            assert m["status"] == "READY"
            assert m["due_at"].startswith("2026-06-15T00:00:00")
            assert m.get("depends_on_milestone_id") in (None,)
        assert {m["kind"] for m in milestones} == {"ESSAY", "TRANSCRIPT",
                                                   "FEE_PAYMENT"}
        created = [m["created_at"] for m in milestones]
        assert created == sorted(created), (
            "the milestone list is returned in created_at ascending order"
        )


class TestMilestoneDependencies:
    def _setup_pending_interview(self, api, ref="MS1"):
        ctx = setup_student_with_active_plan()
        student = ctx["student"]
        app, seeded = create_application_with_milestones(student)
        interview = validate_success(
            api.create_milestone(
                app["id"],
                {"kind": "INTERVIEW", "due_at": "2026-06-01T00:00:00Z",
                 "depends_on_milestone_id": seeded[0]["id"]},
                make_student_headers(student["id"]),
            ),
            expected_status=201,
        )
        return ctx, app, seeded, interview

    def test_milestone_complete_from_pending_returns_409(self, api):
        """PRD §3.4: "That state error deliberately outranks the dependency
        complaint: completing a `PENDING` milestone whose
        `depends_on_milestone_id` has not yet reached `COMPLETED` fails with
        `ERR_MILESTONE_NOT_ACTIONABLE`, never with
        `ERR_PREREQUISITE_INCOMPLETE`."

        Design: Corner/state_machines/milestone_complete_from_pending_returns_409
        """
        ctx, app, seeded, interview = self._setup_pending_interview(api)
        assert interview["status"] == "PENDING"
        resp = api.transition_milestone(
            interview["id"], {"to_status": "COMPLETED"},
            make_student_headers(ctx["student"]["id"]))
        validate_error(resp, ApiErrorId.ERR_MILESTONE_NOT_ACTIONABLE)

    def test_milestone_dependency_bubble_up_to_ready(self, api):
        """PRD §3.4: "when a milestone reaches `COMPLETED`, every dependent
        milestone of the same application waiting in `PENDING` on it moves to
        `READY`." PRD §3.4: "A milestone's downstream chain is inspectable
        through the dependents lookup, which lists every milestone whose
        `depends_on_milestone_id` points at it".

        Design: Corner/state_machines/milestone_dependency_bubble_up_to_ready
        """
        ctx, app, seeded, interview = self._setup_pending_interview(api, ref="MB1")
        student = ctx["student"]
        complete_milestone(seeded[0]["id"], student)

        after = validate_success(
            api.get_milestone(interview["id"],
                              make_student_headers(student["id"])))
        assert after["status"] == "READY"

        dependents = validate_success(
            api.list_milestone_dependents(seeded[0]["id"],
                                          make_student_headers(
                                              student["id"])))
        assert [m["id"] for m in dependents] == [interview["id"]]

    def test_milestone_due_date_past_returns_409(self, api):
        """PRD §3.4: "a student may add a milestone naming its `kind` — one of
        `ESSAY`, `TRANSCRIPT`, `FEE_PAYMENT`, `TEST_SCORES`, `REC_LETTERS`,
        `FAFSA`, `INTERVIEW`, or `OTHER` — its `due_at`, which must lie in the
        future (else `ERR_DUE_DATE_PAST`)"."

        Design: Corner/validations/milestone_due_date_past_returns_409
        """
        ctx = setup_student_with_active_plan()
        student = ctx["student"]
        app = create_application(student)
        resp = api.create_milestone(
            app["id"],
            {"kind": "OTHER", "due_at": "2026-04-01T00:00:00Z"},
            make_student_headers(student["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DUE_DATE_PAST)

    def test_milestone_prerequisite_from_other_application_returns_409(
            self, api):
        """PRD §3.4: "The chain must stay inside the same application and must
        not point at a milestone that is `WAIVED` or `MISSED`; either
        violation is `ERR_PREREQUISITE_INCOMPLETE`."

        Design: Corner/validations/milestone_prerequisite_from_other_application_returns_409
        """
        ctx = setup_student_with_active_plan()
        student = ctx["student"]
        app1, seeded1 = create_application_with_milestones(student)
        app2 = create_application(student, college_name="Tech C",
                                  program_type="COLLEGE_2YR")
        resp = api.create_milestone(
            app2["id"],
            {"kind": "INTERVIEW", "due_at": "2026-06-01T00:00:00Z",
             "depends_on_milestone_id": seeded1[0]["id"]},
            make_student_headers(student["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PREREQUISITE_INCOMPLETE)


class TestReadyGate:
    def test_ready_blocked_by_incomplete_milestone_returns_409(self, api):
        """PRD §3.4: "On the submission dimension, the student moves an
        application from `DRAFT` to `READY` once every milestone with
        `required` set to true stands in `COMPLETED` or `WAIVED`; a required
        milestone in any other state blocks the move with
        `ERR_MILESTONES_INCOMPLETE`".

        Design: Corner/validations/ready_blocked_by_incomplete_milestone_returns_409
        """
        ctx = setup_student_with_active_plan()
        student = ctx["student"]
        advisor_id = ctx["advisor"]["id"]
        app1 = create_application(student)
        app2, seeded2 = create_application_with_milestones(
            student, college_name="Tech C", program_type="COLLEGE_2YR")
        for m in seeded2:
            waive_milestone(m["id"], advisor_id)

        blocked = api.transition_application(
            app1["id"], {"to_status": "READY"},
            make_student_headers(student["id"]))
        validate_error(blocked, ApiErrorId.ERR_MILESTONES_INCOMPLETE)

        allowed = api.transition_application(
            app2["id"], {"to_status": "READY"},
            make_student_headers(student["id"]))
        assert validate_success(allowed)["submission_status"] == "READY", (
            "a WAIVED required milestone satisfies the readiness gate"
        )

    def test_ready_after_deadline_returns_409(self, api):
        """PRD §3.4: "attempting the move after `deadline_at` has passed is
        rejected with `ERR_DEADLINE_PASSED` — on or before the deadline still
        passes."

        Design: Corner/validations/ready_after_deadline_returns_409
        """
        ctx = setup_student_with_active_plan()
        student = ctx["student"]
        app, seeded = create_application_with_milestones(
            student, deadline_at="2026-05-10T00:00:00Z")
        for m in seeded:
            complete_milestone(m["id"], student)
        set_clock("2026-05-12T00:00:00Z")

        resp = api.transition_application(app["id"], {"to_status": "READY"},
                                          make_student_headers(
                                              student["id"]))
        validate_error(resp, ApiErrorId.ERR_DEADLINE_PASSED)


class TestDecisionDimension:
    def test_decision_before_submission_returns_409(self, api):
        """PRD §3.4: "Recording a decision is allowed only while
        `submission_status` is `SUBMITTED` or `CONFIRMED`; any other
        submission state yields `ERR_DECISION_NOT_ALLOWED`, as does an illegal
        decision move."

        Design: Corner/validations/decision_before_submission_returns_409
        """
        ctx = setup_student_with_active_plan()
        app = create_application(ctx["student"])
        resp = api.decide_application(app["id"], {"to_decision": "ACCEPTED"},
                                      ADMIN)
        validate_error(resp, ApiErrorId.ERR_DECISION_NOT_ALLOWED)


class TestStateBeatsDeadline:
    """Difficulty instance: WITHDRAWN application + expired deadline."""

    def _setup_withdrawn_past_deadline(self):
        ctx = setup_student_with_active_plan()
        student = ctx["student"]
        app = create_application(student, deadline_at="2026-05-10T00:00:00Z")
        transition_application(app["id"], student, "WITHDRAWN")
        set_clock("2026-05-20T00:00:00Z")
        return ctx, app

    def test_ready_on_withdrawn_reports_state_error(self, api):
        """PRD §2.6: "When a request violates rules belonging to more than one
        stage, the stage that sits earliest in the pipeline determines the
        reported error; later failures are masked until the earlier one is
        resolved." PRD §2.6 stage 8: "The entity sits in a from-state for the
        requested transition, and terminal lockdown holds. Failures yield
        `ERR_INVALID_STATE`". PRD §2.6 stage
        11 lists `ERR_DEADLINE_PASSED` among the clock-relative rules.

        Design: Difficulty/priority_pair_validation_conflict/ready_after_withdraw_state_beats_deadline
        """
        ctx, app = self._setup_withdrawn_past_deadline()
        resp = api.transition_application(
            app["id"], {"to_status": "READY"},
            make_student_headers(ctx["student"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert resp.json()["data"]["error_id"] != \
            ApiErrorId.ERR_DEADLINE_PASSED.value

    def test_withdrawn_application_unchanged_after_rejected_ready(self, api):
        """PRD §3.4: "`WITHDRAWN` is terminal on the submission dimension."
        PRD §2.4: "The `version` is an integer that starts at 1 when the
        resource is created and increments by exactly 1 on every mutation of
        that resource."

        Design: Difficulty/priority_pair_validation_conflict/ready_after_withdraw_state_beats_deadline
        """
        ctx, app = self._setup_withdrawn_past_deadline()
        before = validate_success(api.get_application(app["id"], ADMIN))
        api.transition_application(app["id"], {"to_status": "READY"},
                                   make_student_headers(
                                       ctx["student"]["id"]))
        after = validate_success(api.get_application(app["id"], ADMIN))
        assert after["submission_status"] == "WITHDRAWN"
        assert after["version"] == before["version"], (
            "a rejected transition is not a mutation"
        )


class TestParallelDimensions:
    """Difficulty instance: submission and decision dimensions evolve
    independently on one Application row."""

    def _setup_submitted_application(self):
        ctx = setup_student_with_active_plan()
        student = ctx["student"]
        app, seeded = create_application_with_milestones(student)
        for m in seeded:
            complete_milestone(m["id"], student)
        transition_application(app["id"], student, "READY")
        transition_application(app["id"], student, "SUBMITTED")
        return ctx, app

    def test_decision_moves_while_submission_stays_submitted(self, api):
        """PRD §3.4: "Applications carry two independent state dimensions on
        one row, and a transition on one dimension never blocks the other
        except where this section states it." PRD §3.4: "A successful
        submission stamps `submitted_at` with the current clock and fires the
        one cross-dimension effect: `decision_status` moves from `NONE` to
        `PENDING`."

        Design: Difficulty/non_linear_state_machine/application_parallel_dimensions
        """
        ctx, app = self._setup_submitted_application()
        decided = validate_success(
            api.decide_application(app["id"], {"to_decision": "WAITLISTED"},
                                   ADMIN))
        assert decided["decision_status"] == "WAITLISTED"
        assert decided["submission_status"] == "SUBMITTED", (
            "the decision move must not touch the submission dimension"
        )
        assert decided["submitted_at"] is not None
        assert decided["decided_at"] is not None

    def test_confirm_then_waitlist_to_accepted(self, api):
        """PRD §3.4: "Confirmation — `SUBMITTED` to `CONFIRMED` — is a
        `DistrictAdmin` act with no further preconditions." PRD §3.4: "from
        `WAITLISTED` the district may later record `ACCEPTED` or `DENIED`."

        Design: Difficulty/non_linear_state_machine/application_parallel_dimensions
        """
        ctx, app = self._setup_submitted_application()
        api.decide_application(app["id"], {"to_decision": "WAITLISTED"}, ADMIN)
        confirmed = validate_success(
            api.transition_application(app["id"], {"to_status": "CONFIRMED"},
                                       ADMIN))
        assert confirmed["submission_status"] == "CONFIRMED"
        assert confirmed["decision_status"] == "WAITLISTED", (
            "the submission move must not touch the decision dimension"
        )
        accepted = validate_success(
            api.decide_application(app["id"], {"to_decision": "ACCEPTED"},
                                   ADMIN))
        assert accepted["decision_status"] == "ACCEPTED"
        final = validate_success(api.get_application(app["id"], ADMIN))
        assert_application(final)
        assert final["submission_status"] == "CONFIRMED"
        assert final["decision_status"] == "ACCEPTED"
        assert final["submitted_at"] is not None
        assert final["decided_at"] is not None
