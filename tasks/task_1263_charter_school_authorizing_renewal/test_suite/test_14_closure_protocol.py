"""Closure protocol: stepwise advance, the student-transition gate, and
placement state (PRD §3.7)."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    create_open_school, create_closure_plan, add_student_transition,
    make_staff_headers, api_client,
)

STAFF = make_staff_headers("staff_1")


class TestClosureStepwiseStudentGateToClosed:
    def test_full_stepwise_advance_gated_by_student_transitions(self, api):
        """PRD §3.7: "From `TRANSITION_IN_PROGRESS` it reaches
        `RECORDS_COMPLETE` only when zero student transitions remain in
        `PENDING` or `PLACED` (`ERR_STUDENTS_NOT_TRANSITIONED`)."
        PRD §3.7: "From `RECORDS_COMPLETE` it reaches `CLOSED`, and that final
        step closes the school itself: the school moves `CLOSING` → `CLOSED`,
        any contract still `ACTIVE` is moved to `REVOKED`, and every
        intervention notice still open — `DRAFT` or `ISSUED` — becomes `MOOT`."

        Design: Corner/state_machines/sm_closure_stepwise_student_gate_to_closed
        """
        ctx = create_open_school(school_name="SM Closure Academy",
                                 applicant_id="applicant_s11")
        plan = create_closure_plan(ctx["school"]["id"], reason="VOLUNTARY",
                                   closure_date="2027-06-30T00:00:00Z",
                                   board_id="board_2")
        assert plan["status"] == "INITIATED"
        school = validate_success(api.get_school(ctx["school"]["id"], STAFF), 200)
        assert school["status"] == "CLOSING"
        t1 = add_student_transition(plan["id"], student_ref="stu_close_1")
        t2 = add_student_transition(plan["id"], student_ref="stu_close_2")

        step1 = validate_success(api.advance_closure_plan(plan["id"], STAFF), 200)
        assert step1["status"] == "TRANSITION_IN_PROGRESS"

        # Gate: two students still PENDING.
        res = api.advance_closure_plan(plan["id"], STAFF)
        validate_error(res, ApiErrorId.ERR_STUDENTS_NOT_TRANSITIONED,
                       expected_status=409)

        for transition, destination in ((t1, "District Elementary 12"),
                                        (t2, "District Middle 4")):
            placed = validate_success(
                api.place_student_transition(transition["id"],
                                             {"destination_school": destination},
                                             STAFF), 200)
            assert placed["status"] == "PLACED"
            sent = validate_success(
                api.records_sent_student_transition(transition["id"], STAFF), 200)
            assert sent["status"] == "RECORDS_SENT"

        step2 = validate_success(api.advance_closure_plan(plan["id"], STAFF), 200)
        assert step2["status"] == "RECORDS_COMPLETE"
        step3 = validate_success(api.advance_closure_plan(plan["id"], STAFF), 200)
        assert step3["status"] == "CLOSED"

        school_after = validate_success(api.get_school(ctx["school"]["id"], STAFF), 200)
        assert school_after["status"] == "CLOSED"


class TestStudentPlaceTwiceRejected:
    def test_place_on_placed_transition_rejected(self, api):
        """PRD §3.7: "Placement names a non-empty `destination_school`
        (missing values draw `ERR_INVALID_REQUEST`) and moves the transition
        `PENDING` → `PLACED`, recording the destination; a transition not
        `PENDING` draws `ERR_TRANSITION_INVALID_STATE`."

        Design: Corner/state_machines/sm_student_place_twice_rejected
        """
        ctx = create_open_school(school_name="SM Twice Academy",
                                 applicant_id="applicant_s12")
        plan = create_closure_plan(ctx["school"]["id"], reason="VOLUNTARY",
                                   closure_date="2027-06-30T00:00:00Z",
                                   board_id="board_2")
        transition = add_student_transition(plan["id"], student_ref="stu_twice")
        placed = validate_success(
            api.place_student_transition(transition["id"],
                                         {"destination_school": "Original Destination"},
                                         STAFF), 200)
        assert placed["status"] == "PLACED"

        res = api.place_student_transition(transition["id"],
                                           {"destination_school": "Other School"}, STAFF)
        validate_error(res, ApiErrorId.ERR_TRANSITION_INVALID_STATE,
                       expected_status=409)
        transitions = validate_success(
            api.list_student_transitions(plan["id"], STAFF), 200)
        assert transitions[0]["status"] == "PLACED"
        assert transitions[0]["destination_school"] == "Original Destination"
