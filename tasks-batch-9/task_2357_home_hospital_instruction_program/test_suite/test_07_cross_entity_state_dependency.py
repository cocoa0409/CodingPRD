"""Gates that live on a neighbouring row rather than on the row being written.

A case cannot activate until a different entity — its primary assignment — has
been moved by a different actor. A transition plan cannot go out for
coordination while a sibling child of the same case sits suspended. And a plan's
readiness is derived from every coordination child at once, after which
completion answers to nothing but the clock.
"""

from test_helpers import (
    ApiErrorId,
    CLASSROOM_TEACHER,
    CM_HEADERS,
    MIDDLE_IN_HOME_RULE,
    PA_HEADERS,
    accept_assignment,
    acknowledge_pacing_sync,
    api_client,
    finalize_safety_review,
    is_iso8601_timestamp,
    open_pacing_sync,
    open_sped_service_log,
    open_transition_plan,
    propose_assignment,
    read_assignment,
    read_case,
    read_teacher,
    record_safety_review,
    record_sped_delivery_payload,
    register_teacher,
    set_clock,
    setup_active_case,
    setup_eligible_case,
    sped_continuation_payload,
    validate_error,
    validate_success,
)

CERT_WINDOW = {
    "expected_absence_days": 30,
    "certified_start_date": "2026-09-07",
    "certified_end_date": "2026-10-07",
    "signature_date": "2026-09-01",
}

CLEARED_SAFETY_REVIEW = {
    "hazard_findings": ["UNLIT_ACCESS"],
    "escort_available": False,
}

IEP_STUDENT = {
    "student_number": "S-0003",
    "full_name": "Cara Voss",
    "special_ed_status": "IEP",
    "iep_service_minutes_weekly": 300,
}


def _eligible_case_whose_primary_assignment_is_still_proposed() -> dict:
    """An ELIGIBLE case cleared for in-home service in every respect except that its
    PRIMARY assignment is still PROPOSED, with the clock at 2026-09-07T08:00:00Z."""
    bundle = setup_eligible_case(
        rules=[MIDDLE_IN_HOME_RULE], certification=dict(CERT_WINDOW)
    )
    review = record_safety_review(bundle["case"]["id"], **CLEARED_SAFETY_REVIEW)
    bundle["safety_review"] = finalize_safety_review(review["id"])
    teacher = register_teacher()
    bundle["teacher"] = teacher
    bundle["primary_assignment"] = propose_assignment(
        bundle["case"]["id"], "PRIMARY", teacher["id"]
    )
    set_clock("2026-09-07T08:00:00Z")
    bundle["case"] = read_case(bundle["case"]["id"])
    return bundle


def _draft_plan_behind_a_suspended_related_service() -> dict:
    """An ACTIVE IEP case with one PENDING MATH coordination row, one DRAFT plan, and
    its SPEECH continuation log parked at SUSPENDED_PENDING_IEP."""
    bundle = setup_active_case(
        rules=[MIDDLE_IN_HOME_RULE],
        student=dict(IEP_STUDENT),
        certification=dict(CERT_WINDOW),
        safety_review=dict(CLEARED_SAFETY_REVIEW),
    )
    case_id = bundle["case"]["id"]
    bundle["sped_log"] = open_sped_service_log(
        case_id, service_type="SPEECH", required_weekly_minutes=60
    )
    classroom_teacher = register_teacher(**CLASSROOM_TEACHER)
    bundle["classroom_teacher"] = classroom_teacher
    bundle["sync"] = open_pacing_sync(
        case_id,
        classroom_teacher["id"],
        subject="MATH",
        pacing_target_unit="Algebra Unit 3",
        assessment_accommodation="EXTENDED_TIME",
    )
    bundle["plan"] = open_transition_plan(
        case_id,
        target_return_date="2026-10-05",
        reintegration_mode="PARTIAL_DAY_RAMP",
        ramp_weeks=2,
    )
    bundle["sped_log"] = validate_success(
        api_client.change_sped_continuation(
            bundle["sped_log"]["id"],
            sped_continuation_payload(
                "SUSPENDED_PENDING_IEP",
                continuation_reason="Awaiting IEP amendment meeting",
            ),
            CM_HEADERS,
        )
    )
    return bundle


def _coordinated_plan_awaiting_two_acknowledgements() -> dict:
    """An ACTIVE case with two PENDING coordination rows and a plan already sent out
    for coordination, so it sits in CLASSROOM_COORD_PENDING."""
    bundle = setup_active_case(
        rules=[MIDDLE_IN_HOME_RULE],
        certification=dict(CERT_WINDOW),
        safety_review=dict(CLEARED_SAFETY_REVIEW),
    )
    case_id = bundle["case"]["id"]
    classroom_teacher = register_teacher(**CLASSROOM_TEACHER)
    bundle["classroom_teacher"] = classroom_teacher
    bundle["sync_math"] = open_pacing_sync(
        case_id,
        classroom_teacher["id"],
        subject="MATH",
        pacing_target_unit="Algebra Unit 3",
        assessment_accommodation="EXTENDED_TIME",
    )
    bundle["sync_ela"] = open_pacing_sync(
        case_id,
        classroom_teacher["id"],
        subject="ELA",
        pacing_target_unit="Narrative Unit 2",
        assessment_accommodation="ORAL_ADMINISTRATION",
    )
    plan = open_transition_plan(
        case_id,
        target_return_date="2026-10-05",
        reintegration_mode="PARTIAL_DAY_RAMP",
        ramp_weeks=2,
    )
    bundle["plan"] = validate_success(
        api_client.coordinate_transition_plan(plan["id"], CM_HEADERS)
    )
    return bundle


class TestActivationWaitsOnTheAssignmentRow:
    """The gate is the assignment's status, not anything on the case."""

    def test_a_proposed_primary_assignment_does_not_satisfy_activation(self):
        """Activation is refused while the primary assignment is still PROPOSED, and the
        case keeps its pre-activation shape.

        The PRD states: "At least one assignment of the case must have `role` `PRIMARY`
        and `status` `ACTIVE`, or the activation fails with
        `ERR_NO_PRIMARY_ASSIGNMENT`."

        Design: Difficulty/cross_entity_state_dependency/case_activation_gated_on_primary_assignment_reaching_active
        """
        bundle = _eligible_case_whose_primary_assignment_is_still_proposed()
        assert bundle["primary_assignment"]["status"] == "PROPOSED"
        assert bundle["safety_review"]["clearance"] == "CLEARED", (
            "the safety precondition is satisfied, so only the assignment can bite"
        )

        validate_error(
            api_client.activate_case(bundle["case"]["id"], PA_HEADERS),
            ApiErrorId.ERR_NO_PRIMARY_ASSIGNMENT.value,
            422,
        )

        case = read_case(bundle["case"]["id"])
        assert case["service_status"] == "ELIGIBLE"
        assert case["funding_status"] == "NOT_REPORTED", (
            "the funding dimension does not move on a refused activation"
        )
        assert case.get("service_start_date") is None

    def test_the_teacher_s_acceptance_alone_opens_the_gate(self):
        """The identical activation request succeeds once the teacher accepts, with
        nothing on the case having changed in between.

        The PRD states: "A `HomeboundTeacher` whose `X-User-ID` equals the assignment's
        `teacher_id` accepts a `PROPOSED` assignment, moving it `PROPOSED → ACTIVE` and
        stamping `accepted_at` with the clock instant."

        The PRD states: "On a successful acceptance the case's weekly allocation is
        recomputed across its active assignments including the new one, and every
        teacher whose allocation changed has `committed_weekly_minutes` and `over_cap`
        recomputed."

        The PRD states: "Activation advances `service_status` `ELIGIBLE → ACTIVE`, sets
        `service_start_date` to the clock date, refreshes `escort_required` from the
        governing finalized review, moves `funding_status` `NOT_REPORTED → ACCRUING` in
        the same request with `service_gap_minutes` initialized to 0, and increments the
        case's `version` by one."

        Design: Difficulty/cross_entity_state_dependency/case_activation_gated_on_primary_assignment_reaching_active
        """
        bundle = _eligible_case_whose_primary_assignment_is_still_proposed()
        validate_error(
            api_client.activate_case(bundle["case"]["id"], PA_HEADERS),
            ApiErrorId.ERR_NO_PRIMARY_ASSIGNMENT.value,
            422,
        )

        accepted = accept_assignment(
            bundle["primary_assignment"]["id"], bundle["teacher"]["id"]
        )
        assert accepted["status"] == "ACTIVE"
        assert accepted["weekly_committed_minutes"] == 390, (
            "the only active assignment carries the whole weekly entitlement"
        )

        case = validate_success(
            api_client.activate_case(bundle["case"]["id"], PA_HEADERS)
        )
        assert case["service_status"] == "ACTIVE"
        assert case["funding_status"] == "ACCRUING"
        assert case["service_start_date"] == "2026-09-07", (
            "the service start date is the clock date at activation"
        )
        assert case["escort_required"] is False
        assert read_teacher(bundle["teacher"]["id"])["committed_weekly_minutes"] == 390


class TestCoordinationWaitsOnTheRelatedServiceLog:
    """One suspended sibling child blocks two different endpoints."""

    def test_a_suspended_related_service_blocks_coordination_and_delivery_alike(self):
        """While the SPEECH log is suspended, sending the plan out for coordination and
        recording delivered minutes are both refused with the same code.

        The PRD states: "It also requires that no special-education continuation log on
        the case be sitting at `SUSPENDED_PENDING_IEP`; a suspended service blocks
        coordination with `ERR_SPED_SERVICE_SUSPENDED`, on the reasoning that a student
        cannot be planned back into the building while an IEP service is frozen pending
        a meeting."

        The PRD states: "From either `CONTINUED` or `MODIFIED_VIRTUAL` the log may move
        to `SUSPENDED_PENDING_IEP`, which freezes `delivered_cumulative_minutes` — while
        a log is suspended, any attempt to record delivered minutes against it is
        rejected with `ERR_SPED_SERVICE_SUSPENDED` — while `compensatory_minutes_owed`
        keeps accruing with each elapsed week, so the suspension window accumulates as a
        debt."

        Design: Difficulty/cross_entity_state_dependency/transition_plan_coordination_gated_on_sped_service_log_not_suspended
        """
        bundle = _draft_plan_behind_a_suspended_related_service()
        assert bundle["sped_log"]["continuation_status"] == "SUSPENDED_PENDING_IEP"

        validate_error(
            api_client.coordinate_transition_plan(bundle["plan"]["id"], CM_HEADERS),
            ApiErrorId.ERR_SPED_SERVICE_SUSPENDED.value,
            422,
        )
        plan = validate_success(
            api_client.get_transition_plan(bundle["plan"]["id"], CM_HEADERS)
        )
        assert plan["status"] == "DRAFT", "the refused coordination writes nothing"
        assert plan["classroom_ack_count"] == 0

        validate_error(
            api_client.record_sped_delivery(
                bundle["sped_log"]["id"],
                record_sped_delivery_payload(minutes=60, service_date="2026-09-09"),
                CM_HEADERS,
            ),
            ApiErrorId.ERR_SPED_SERVICE_SUSPENDED.value,
            422,
        )
        log = validate_success(
            api_client.get_sped_service_log(bundle["sped_log"]["id"], CM_HEADERS)
        )
        assert log["delivered_cumulative_minutes"] == 0, (
            "the suspension freezes the delivered total"
        )

    def test_returning_the_log_to_continued_releases_the_same_request(self):
        """Once the log is back at CONTINUED the identical coordinate request succeeds
        and the plan picks up its one required acknowledgement.

        The PRD states: "From either `MODIFIED_VIRTUAL` or `SUSPENDED_PENDING_IEP` the
        log may return to `CONTINUED`, which recomputes `compensatory_minutes_owed`
        against the elapsed service weeks so that the suspension window is owed back in
        full."

        The PRD states: "`required_ack_count` is the number of coordination rows for the
        plan's case whose `ack_status` is `PENDING`, `ACKED` or `DISPUTED`;
        `classroom_ack_count` is the number of those rows whose `ack_status` is
        `ACKED`."

        Design: Difficulty/cross_entity_state_dependency/transition_plan_coordination_gated_on_sped_service_log_not_suspended
        """
        bundle = _draft_plan_behind_a_suspended_related_service()
        validate_error(
            api_client.coordinate_transition_plan(bundle["plan"]["id"], CM_HEADERS),
            ApiErrorId.ERR_SPED_SERVICE_SUSPENDED.value,
            422,
        )

        resumed = validate_success(
            api_client.change_sped_continuation(
                bundle["sped_log"]["id"],
                sped_continuation_payload(
                    "CONTINUED", continuation_reason="IEP amendment signed"
                ),
                CM_HEADERS,
            )
        )
        assert resumed["continuation_status"] == "CONTINUED"

        plan = validate_success(
            api_client.coordinate_transition_plan(bundle["plan"]["id"], CM_HEADERS)
        )
        assert plan["status"] == "CLASSROOM_COORD_PENDING"
        assert plan["required_ack_count"] == 1, (
            "the single PENDING coordination row is the one acknowledgement required"
        )
        assert plan["classroom_ack_count"] == 0
        assert read_case(bundle["case"]["id"])["service_status"] == "TRANSITION_PLANNED"


class TestReadinessIsDerivedThenCompletionWaitsOnTheClock:
    """Two children flip the plan to READY; only time lets it complete."""

    def test_readiness_arrives_with_the_second_acknowledgement(self):
        """One of two acknowledgements leaves the plan pending; the second flips it to
        READY inside that same request.

        The PRD states: "A plan in `CLASSROOM_COORD_PENDING` advances to `READY` exactly
        when `required_ack_count` is at least 1, `classroom_ack_count` equals
        `required_ack_count`, and the parent case's `funding_status` is anything other
        than `HELD` — so the plan depends jointly on its coordination children and on
        the case's parallel funding dimension."

        Design: Difficulty/cross_entity_state_dependency/plan_ready_derived_from_all_pacing_acks_then_completion_gated_on_return_date
        """
        bundle = _coordinated_plan_awaiting_two_acknowledgements()
        plan_id = bundle["plan"]["id"]
        assert bundle["plan"]["status"] == "CLASSROOM_COORD_PENDING"
        assert bundle["plan"]["required_ack_count"] == 2
        assert bundle["plan"]["classroom_ack_count"] == 0

        acknowledge_pacing_sync(
            bundle["sync_math"]["id"], bundle["classroom_teacher"]["id"]
        )
        half_way = validate_success(api_client.get_transition_plan(plan_id, CM_HEADERS))
        assert half_way["classroom_ack_count"] == 1
        assert half_way["status"] == "CLASSROOM_COORD_PENDING", (
            "one of two acknowledgements is not readiness"
        )

        acknowledge_pacing_sync(
            bundle["sync_ela"]["id"], bundle["classroom_teacher"]["id"]
        )
        ready = validate_success(api_client.get_transition_plan(plan_id, CM_HEADERS))
        assert ready["classroom_ack_count"] == 2
        assert ready["status"] == "READY", (
            "readiness is derived from the children rather than requested"
        )

    def test_completion_is_refused_before_the_return_date_and_then_closes_the_case(self):
        """Completing a READY plan before 2026-10-05 is refused; advancing the clock
        alone lets the same request close the case and release the teacher.

        The PRD states: "Completing a plan whose `status` is not `READY` is
        `ERR_PLAN_NOT_READY`, and completing before the clock date has reached
        `target_return_date` is `ERR_RETURN_DATE_NOT_REACHED`."

        The PRD states: "Completion moves the plan `READY → COMPLETED`, stamps
        `completed_at` with the clock instant, and closes the case: the case advances
        `TRANSITION_PLANNED → CLOSED` with `close_reason` `RETURNED_TO_CAMPUS`, every
        assignment of the case whose `status` is `ACTIVE` is moved to `RELEASED` with
        `release_reason` `CASE_CLOSED` and `weekly_committed_minutes` 0,
        `committed_weekly_minutes` is recomputed for each released teacher, every
        session of the case whose `status` is `SCHEDULED` is moved to `CANCELLED_ADMIN`,
        and the case's `version` increments by one."

        Design: Difficulty/cross_entity_state_dependency/plan_ready_derived_from_all_pacing_acks_then_completion_gated_on_return_date
        """
        bundle = _coordinated_plan_awaiting_two_acknowledgements()
        plan_id = bundle["plan"]["id"]
        acknowledge_pacing_sync(
            bundle["sync_math"]["id"], bundle["classroom_teacher"]["id"]
        )
        acknowledge_pacing_sync(
            bundle["sync_ela"]["id"], bundle["classroom_teacher"]["id"]
        )

        validate_error(
            api_client.complete_transition_plan(plan_id, PA_HEADERS),
            ApiErrorId.ERR_RETURN_DATE_NOT_REACHED.value,
            409,
        )
        blocked = validate_success(api_client.get_transition_plan(plan_id, CM_HEADERS))
        assert blocked["status"] == "READY"
        assert blocked.get("completed_at") is None
        assert read_case(bundle["case"]["id"])["service_status"] == "TRANSITION_PLANNED"

        set_clock("2026-10-05T09:00:00Z")
        completed = validate_success(
            api_client.complete_transition_plan(plan_id, PA_HEADERS)
        )
        assert completed["status"] == "COMPLETED"
        assert is_iso8601_timestamp(completed["completed_at"])
        assert completed["completed_at"].startswith("2026-10-05T09:00:00"), (
            "the clock instant is stamped, not a wall-clock reading"
        )

        case = read_case(bundle["case"]["id"])
        assert case["service_status"] == "CLOSED"
        assert case["close_reason"] == "RETURNED_TO_CAMPUS"

        assignment = read_assignment(bundle["primary_assignment"]["id"])
        assert assignment["status"] == "RELEASED"
        assert assignment["release_reason"] == "CASE_CLOSED"
        assert assignment["weekly_committed_minutes"] == 0
        assert read_teacher(bundle["teacher"]["id"])["committed_weekly_minutes"] == 0
