"""Letters of recommendation: routing, capacity, reroute loop, submission gate.

PRD §3.5 (letter routing machine), §3.4 (submission gate on linked letters).
"""
import pytest

from test_helpers import (
    TEST_USERS, ApiErrorId, assert_rec_request, complete_milestone,
    create_advisor, create_application, create_application_with_milestones,
    create_pathway, create_rec_request, create_student, create_teacher,
    get_teacher, make_advisor_headers, make_student_headers,
    make_teacher_headers, setup_student_with_active_plan,
    transition_application, transition_rec_request, validate_error,
    validate_success,
)

ADMIN = TEST_USERS["district_admin_headers"]
DUE = "2026-06-01T00:00:00Z"


class TestRerouteCycle:
    """Difficulty instance: REQUESTED -> DECLINED -> REQUESTED loop with
    reroute_count and teacher capacity as loop-carried state."""

    def _setup_declined_request(self):
        advisor = create_advisor(full_name="R Adv", max_caseload=50)
        t1 = create_teacher(full_name="T One", department="ELA")
        t2 = create_teacher(full_name="T Two", department="MATH")
        student = create_student(student_ref="R001", grade_level=12,
                                 advisor_id=advisor["id"])
        rr = create_rec_request(student, t1["id"], due_at=DUE)
        transition_rec_request(rr["id"], make_teacher_headers(t1["id"]),
                               "DECLINED")
        return advisor, t1, t2, student, rr

    def test_reroute_restores_requested_and_repoints_teacher(self, api):
        """PRD §3.5: "the student's advisor may reroute a `DECLINED` request
        back to `REQUESTED` by supplying a `new_teacher_id`, optionally
        extending the `due_at` in the same payload." PRD §3.5: "A successful
        reroute rewrites `teacher_id` to the new teacher, increments
        `reroute_count` by 1, and raises the new teacher's
        `open_request_count` by 1."

        Design: Difficulty/non_linear_state_machine/rec_request_reroute_cycle
        """
        advisor, t1, t2, student, rr = self._setup_declined_request()
        resp = api.transition_recommendation_request(
            rr["id"], {"to_status": "REQUESTED", "new_teacher_id": t2["id"]},
            make_advisor_headers(advisor["id"]))
        rerouted = validate_success(resp)
        assert_rec_request(rerouted)
        assert rerouted["status"] == "REQUESTED"
        assert rerouted["reroute_count"] == 1
        assert rerouted["teacher_id"] == t2["id"]

    def test_reroute_moves_open_request_count_between_teachers(self, api):
        """PRD §3.5: "declining moves it to `DECLINED` and decrements the
        count by 1." PRD §3.5: "A successful reroute rewrites `teacher_id` to
        the new teacher, increments `reroute_count` by 1, and raises the new
        teacher's `open_request_count` by 1."

        Design: Difficulty/non_linear_state_machine/rec_request_reroute_cycle
        """
        advisor, t1, t2, student, rr = self._setup_declined_request()
        transition_rec_request(
            rr["id"], make_advisor_headers(advisor["id"]), "REQUESTED",
            new_teacher_id=t2["id"])
        assert get_teacher(t1["id"])["open_request_count"] == 0
        assert get_teacher(t2["id"])["open_request_count"] == 1


class TestSubmissionGateOnLetters:
    """Difficulty instance: READY->SUBMITTED gated on linked letter state."""

    def _setup_ready_app_with_accepted_letter(self):
        ctx = setup_student_with_active_plan()
        student = ctx["student"]
        teacher = create_teacher(full_name="G Tee", department="ELA")
        app, seeded = create_application_with_milestones(student)
        for m in seeded:
            complete_milestone(m["id"], student)
        rr = create_rec_request(student, teacher["id"], due_at=DUE,
                                application_id=app["id"])
        transition_rec_request(rr["id"], make_teacher_headers(teacher["id"]),
                               "ACCEPTED")
        transition_application(app["id"], student, "READY")
        return ctx, teacher, app, rr

    def test_submit_blocked_while_letter_accepted(self, api):
        """PRD §3.4: "From `READY`, submission additionally requires that no
        recommendation request linked to the application through its
        `application_id` remains in `REQUESTED` or `ACCEPTED`; outstanding
        letters block with `ERR_PENDING_REC_LETTERS`".

        Design: Difficulty/cross_entity_state_dependency/application_submit_blocked_by_pending_letter
        """
        ctx, teacher, app, rr = self._setup_ready_app_with_accepted_letter()
        resp = api.transition_application(
            app["id"], {"to_status": "SUBMITTED"},
            make_student_headers(ctx["student"]["id"]))
        validate_error(resp, ApiErrorId.ERR_PENDING_REC_LETTERS)
        after = validate_success(api.get_application(app["id"], ADMIN))
        assert after["submission_status"] == "READY"

    def test_submit_succeeds_after_letter_submitted(self, api):
        """PRD §3.5: "Once a letter is written, the routed teacher submits it:
        `ACCEPTED` to `SUBMITTED` stamps `submitted_at` and decrements the
        teacher's `open_request_count` by 1." PRD §3.4: "A successful
        submission stamps `submitted_at` with the current clock and fires the
        one cross-dimension effect: `decision_status` moves from `NONE` to
        `PENDING`."

        Design: Difficulty/cross_entity_state_dependency/application_submit_blocked_by_pending_letter
        """
        ctx, teacher, app, rr = self._setup_ready_app_with_accepted_letter()
        student = ctx["student"]
        transition_rec_request(rr["id"], make_teacher_headers(teacher["id"]),
                               "SUBMITTED")
        submitted = validate_success(
            api.transition_application(app["id"], {"to_status": "SUBMITTED"},
                                       make_student_headers(student["id"])))
        assert submitted["submission_status"] == "SUBMITTED"
        assert submitted["decision_status"] == "PENDING"
        assert submitted["submitted_at"] is not None


class TestLetterCreationGates:
    def test_teacher_capacity_at_max_returns_409(self, api):
        """PRD §3.5: "The teacher must exist (else `ERR_NOT_FOUND`), must be
        `ACTIVE` (else `ERR_INVALID_STATE`), and must have headroom — an
        `open_request_count` strictly below `max_active_letters`, with
        equality rejecting as `ERR_TEACHER_CAPACITY_EXCEEDED`."

        Design: Corner/validations/teacher_capacity_at_max_returns_409
        """
        advisor = create_advisor(max_caseload=10)
        teacher = create_teacher(full_name="TC Tee", max_active_letters=1)
        s1 = create_student(student_ref="TC1", advisor_id=advisor["id"])
        s2 = create_student(student_ref="TC2", demographic_group="GROUP_B",
                            advisor_id=advisor["id"])
        create_rec_request(s1, teacher["id"], due_at=DUE)
        assert get_teacher(teacher["id"])["open_request_count"] == 1

        resp = api.create_recommendation_request(
            s2["id"], {"teacher_id": teacher["id"], "due_at": DUE},
            make_student_headers(s2["id"]))
        validate_error(resp, ApiErrorId.ERR_TEACHER_CAPACITY_EXCEEDED)

    def test_cross_student_reference_on_rec_returns_409(self, api):
        """PRD §3.5: "The link must stay inside the family: an
        `application_id` belonging to a different student is rejected with
        `ERR_CROSS_STUDENT_REFERENCE`."

        Design: Corner/validations/cross_student_reference_on_rec_returns_409
        """
        ctx = setup_student_with_active_plan()
        advisor = ctx["advisor"]
        s1 = ctx["student"]
        teacher = create_teacher(full_name="CS Tee")
        app1 = create_application(s1)
        s2 = create_student(student_ref="CS2", demographic_group="GROUP_B",
                            advisor_id=advisor["id"])

        resp = api.create_recommendation_request(
            s2["id"],
            {"teacher_id": teacher["id"], "due_at": DUE,
             "application_id": app1["id"]},
            make_student_headers(s2["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CROSS_STUDENT_REFERENCE)

    def test_inactive_teacher_rec_create_returns_409(self, api):
        """PRD §3.5: "The teacher must exist (else `ERR_NOT_FOUND`), must be
        `ACTIVE` (else `ERR_INVALID_STATE`)". PRD §3.1: "a later configuration
        update may revise `department`, `max_active_letters`, or flip `status`
        between `ACTIVE` and `INACTIVE`".

        Design: Corner/validations/inactive_teacher_rec_create_returns_409
        """
        advisor = create_advisor(max_caseload=10)
        teacher = create_teacher(full_name="IT Tee")
        validate_success(api.patch_teacher(teacher["id"],
                                           {"status": "INACTIVE"}, ADMIN))
        student = create_student(student_ref="IT1", advisor_id=advisor["id"])

        resp = api.create_recommendation_request(
            student["id"], {"teacher_id": teacher["id"], "due_at": DUE},
            make_student_headers(student["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_teacher_accept_not_routed_returns_403(self, api):
        """PRD §3.5: "Either response attempted by anyone other than the
        teacher named in the request's `teacher_id` is rejected with
        `ERR_REQUEST_NOT_ROUTED_TO_YOU`."

        Design: Corner/validations/teacher_accept_not_routed_returns_403
        """
        advisor = create_advisor(max_caseload=10)
        t1 = create_teacher(full_name="NR T1", department="ELA")
        t2 = create_teacher(full_name="NR T2", department="MATH")
        student = create_student(student_ref="NR1", advisor_id=advisor["id"])
        rr = create_rec_request(student, t1["id"], due_at=DUE)

        resp = api.transition_recommendation_request(
            rr["id"], {"to_status": "ACCEPTED"},
            make_teacher_headers(t2["id"]))
        validate_error(resp, ApiErrorId.ERR_REQUEST_NOT_ROUTED_TO_YOU)
        after = validate_success(
            api.get_recommendation_request(rr["id"], ADMIN))
        assert after["status"] == "REQUESTED"
