"""Requests that break two rules at once, where only the earlier tier may answer.

Each pair below is arranged so that both rules are genuinely violated by the
same request; a control request that repairs only the winning violation proves
the losing rule really was live, which is what makes the precedence assertion
meaningful rather than accidental.
"""

from test_helpers import (
    ApiErrorId,
    CM_HEADERS,
    MIDDLE_IN_HOME_RULE,
    MIDDLE_VIRTUAL_RULE,
    accept_assignment,
    activate_case,
    api_client,
    create_extension_request_payload,
    create_session_payload,
    finalize_safety_review,
    list_data,
    open_case,
    propose_assignment,
    read_case,
    record_safety_review,
    register_student,
    review_certification,
    schedule_session,
    sessions_for_case,
    set_clock,
    setup_active_case,
    setup_case_with_primary_assignment,
    setup_eligible_case,
    submit_certification,
    validate_error,
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


def _eligible_case_with_no_safety_review() -> dict:
    """An ELIGIBLE case that was never activated and has no safety review at all,
    with an accepted primary assignment already in place."""
    bundle = setup_case_with_primary_assignment(
        rules=[MIDDLE_IN_HOME_RULE], certification=dict(CERT_WINDOW)
    )
    set_clock("2026-09-07T08:00:00Z")
    return bundle


def _virtual_case_filled_to_its_daily_limit() -> dict:
    """An ACTIVE virtual case carrying exactly 180 scheduled minutes on 2026-09-14."""
    bundle = setup_active_case(
        rules=[MIDDLE_VIRTUAL_RULE],
        case={"delivery_mode": "VIRTUAL_SYNC"},
        certification=dict(CERT_WINDOW),
        safety_review=dict(CLEARED_SAFETY_REVIEW),
    )
    slots = [
        ("2026-09-14T09:00:00Z", "2026-09-14T10:30:00Z", "MATH"),
        ("2026-09-14T11:00:00Z", "2026-09-14T12:30:00Z", "ELA"),
    ]
    bundle["sessions"] = [
        schedule_session(
            bundle["case"]["id"],
            bundle["primary_assignment"]["id"],
            scheduled_start=start,
            scheduled_end=end,
            delivery_mode="VIRTUAL_SYNC",
            subject=subject,
        )
        for start, end, subject in slots
    ]
    return bundle


def _two_active_cases_sharing_one_teacher() -> dict:
    """Two grade-7 in-home cases served by the same teacher, with one session already
    booked on case A for 2026-09-07 10:00-12:00."""
    bundle = setup_active_case(
        rules=[MIDDLE_IN_HOME_RULE],
        certification=dict(CERT_WINDOW),
        safety_review=dict(CLEARED_SAFETY_REVIEW),
    )
    teacher_id = bundle["teacher"]["id"]

    student_b = register_student(student_number="S-0002", full_name="Ben Ortiz")
    case_b = open_case(student_b["id"], delivery_mode="IN_HOME")
    certification_b = submit_certification(
        case_b["id"], physician_npi="1234567891", **CERT_WINDOW
    )
    review_certification(certification_b["id"], "ACCEPT")
    safety_b = record_safety_review(case_b["id"], **CLEARED_SAFETY_REVIEW)
    finalize_safety_review(safety_b["id"])
    assignment_b = propose_assignment(case_b["id"], "PRIMARY", teacher_id)
    assignment_b = accept_assignment(assignment_b["id"], teacher_id)
    case_b = activate_case(case_b["id"])

    bundle["case_b"] = case_b
    bundle["assignment_b"] = assignment_b
    bundle["session_a"] = schedule_session(
        bundle["case"]["id"],
        bundle["primary_assignment"]["id"],
        scheduled_start="2026-09-07T10:00:00Z",
        scheduled_end="2026-09-07T12:00:00Z",
        delivery_mode="IN_HOME",
        subject="MATH",
    )
    return bundle


def _extension_requests_for_case(case_id: str) -> list:
    rows = list_data(api_client.list_extension_requests(CM_HEADERS, params={"limit": 100}))
    return [row for row in rows if row["case_id"] == case_id]


class TestCaseStateOutranksTheMissingSafetyReview:
    """Tier 8 answers before tier 10 is consulted."""

    def test_the_lifecycle_guard_answers_and_the_safety_guard_stays_silent(self):
        """Scheduling an in-home visit on a never-activated case with no safety review
        at all is refused for the case state, not for the missing review.

        The PRD states: "Checks are grouped into fourteen tiers and evaluated
        strictly in tier order; the first tier that produces a failure determines the
        response, and no later tier is consulted."

        The PRD states: "Sessions may only be created against a case whose
        `service_status` is `ACTIVE`, `EXTENSION_PENDING` or `TRANSITION_PLANNED`;
        otherwise the request is rejected with `ERR_CASE_NOT_ACTIVE`."

        Design: Difficulty/priority_pair_validation_conflict/session_create_rejects_with_case_state_error_not_missing_safety_review_error
        """
        bundle = _eligible_case_with_no_safety_review()
        assert bundle["case"]["service_status"] == "ELIGIBLE"

        error = validate_error(
            api_client.create_session(
                create_session_payload(
                    bundle["case"]["id"],
                    bundle["primary_assignment"]["id"],
                    scheduled_start="2026-09-07T09:00:00Z",
                    scheduled_end="2026-09-07T11:00:00Z",
                    delivery_mode="IN_HOME",
                    subject="MATH",
                ),
                CM_HEADERS,
            ),
            ApiErrorId.ERR_CASE_NOT_ACTIVE.value,
            409,
        )
        assert error["error_id"] != ApiErrorId.ERR_SAFETY_REVIEW_MISSING.value, (
            "the tier-10 safety rule is never reached"
        )

    def test_the_refused_request_writes_nothing(self):
        """The rejected schedule leaves the case ELIGIBLE and creates no session row.

        The PRD states: "An in-home session requires a finalized review for the case,
        absent which the request is `ERR_SAFETY_REVIEW_MISSING`."

        Design: Difficulty/priority_pair_validation_conflict/session_create_rejects_with_case_state_error_not_missing_safety_review_error
        """
        bundle = _eligible_case_with_no_safety_review()
        case_id = bundle["case"]["id"]

        validate_error(
            api_client.create_session(
                create_session_payload(
                    case_id,
                    bundle["primary_assignment"]["id"],
                    scheduled_start="2026-09-07T09:00:00Z",
                    scheduled_end="2026-09-07T11:00:00Z",
                    delivery_mode="IN_HOME",
                    subject="MATH",
                ),
                CM_HEADERS,
            ),
            ApiErrorId.ERR_CASE_NOT_ACTIVE.value,
            409,
        )

        assert read_case(case_id)["service_status"] == "ELIGIBLE"
        assert sessions_for_case(case_id) == [], (
            "a rejected request writes nothing at all"
        )


class TestInHomePermissionOutranksTheDailyLimit:
    """Tier 10 answers before the tier-14 aggregate is consulted."""

    def test_the_mode_guard_answers_rather_than_the_daily_aggregate(self):
        """A 90-minute in-home visit added to a virtual case already holding its full
        180 daily minutes is refused for the mode, not for the daily total.

        The PRD states: "A session `delivery_mode` of `IN_HOME` is refused outright
        with `ERR_IN_HOME_NOT_PERMITTED` when the case's own `delivery_mode` is
        `VIRTUAL_SYNC` or when the governing finalized review's `clearance` is
        `VIRTUAL_ONLY` — which is also why a session's `delivery_mode` must be
        `VIRTUAL_SYNC` whenever the case's is."

        Design: Difficulty/priority_pair_validation_conflict/session_create_rejects_with_in_home_not_permitted_not_student_daily_limit
        """
        bundle = _virtual_case_filled_to_its_daily_limit()

        error = validate_error(
            api_client.create_session(
                create_session_payload(
                    bundle["case"]["id"],
                    bundle["primary_assignment"]["id"],
                    scheduled_start="2026-09-14T13:00:00Z",
                    scheduled_end="2026-09-14T14:30:00Z",
                    delivery_mode="IN_HOME",
                    subject="SCIENCE",
                ),
                CM_HEADERS,
            ),
            ApiErrorId.ERR_IN_HOME_NOT_PERMITTED.value,
            422,
        )
        assert error["error_id"] != ApiErrorId.ERR_STUDENT_DAILY_LIMIT.value, (
            "the tier-14 capacity rule is never reached"
        )

        sessions = sessions_for_case(bundle["case"]["id"])
        assert len(sessions) == 2
        assert {session["status"] for session in sessions} == {"SCHEDULED"}

    def test_the_control_request_proves_the_daily_limit_was_also_violated(self):
        """The same request in virtual mode — repairing only the mode violation — is
        refused for the daily limit, so both rules were live.

        The PRD states: "Finally, the student's day is capped: the sum of
        `scheduled_minutes` over the case's sessions with `status` `SCHEDULED` or
        `DELIVERED` on the same `service_date`, plus the new session's own
        `scheduled_minutes`, may not exceed the rule's `max_daily_minutes`; a total
        exactly equal to `max_daily_minutes` passes, and any excess is
        `ERR_STUDENT_DAILY_LIMIT`."

        Design: Difficulty/priority_pair_validation_conflict/session_create_rejects_with_in_home_not_permitted_not_student_daily_limit
        """
        bundle = _virtual_case_filled_to_its_daily_limit()

        validate_error(
            api_client.create_session(
                create_session_payload(
                    bundle["case"]["id"],
                    bundle["primary_assignment"]["id"],
                    scheduled_start="2026-09-14T13:00:00Z",
                    scheduled_end="2026-09-14T14:30:00Z",
                    delivery_mode="VIRTUAL_SYNC",
                    subject="SCIENCE",
                ),
                CM_HEADERS,
            ),
            ApiErrorId.ERR_STUDENT_DAILY_LIMIT.value,
            422,
        )
        assert len(sessions_for_case(bundle["case"]["id"])) == 2, (
            "270 requested minutes against a 180-minute ceiling books nothing"
        )


class TestAssignmentMismatchOutranksTheSlotConflict:
    """Tier 12 answers before the tier-13 overlap scan is consulted."""

    def test_the_referential_rule_answers_rather_than_the_overlap_scan(self):
        """Booking case B's session against case A's assignment, over exactly case A's
        existing interval, is refused for the mismatch rather than for the overlap.

        The PRD states: "The referenced assignment must have `status` `ACTIVE`, or the
        request fails with `ERR_ASSIGNMENT_NOT_ACTIVE`, and its own `case_id` must
        equal the `case_id` supplied for the session, or the request fails with
        `ERR_ASSIGNMENT_CASE_MISMATCH`."

        Design: Difficulty/priority_pair_validation_conflict/session_create_rejects_with_assignment_case_mismatch_not_teacher_slot_conflict
        """
        bundle = _two_active_cases_sharing_one_teacher()

        error = validate_error(
            api_client.create_session(
                create_session_payload(
                    bundle["case_b"]["id"],
                    bundle["primary_assignment"]["id"],
                    scheduled_start="2026-09-07T10:00:00Z",
                    scheduled_end="2026-09-07T12:00:00Z",
                    delivery_mode="IN_HOME",
                    subject="MATH",
                ),
                CM_HEADERS,
            ),
            ApiErrorId.ERR_ASSIGNMENT_CASE_MISMATCH.value,
            422,
        )
        assert error["error_id"] != ApiErrorId.ERR_TEACHER_SLOT_CONFLICT.value, (
            "the tier-13 temporal rule is never reached"
        )
        assert sessions_for_case(bundle["case_b"]["id"]) == []

    def test_the_control_request_proves_the_slot_conflict_was_also_violated(self):
        """The same interval booked through case B's own assignment — repairing only
        the mismatch — is refused for the teacher's double-booking.

        The PRD states: "The serving teacher may not be double-booked: the new
        session's busy interval must not overlap the busy interval of any other
        session of the same teacher whose `status` is `SCHEDULED` or `DELIVERED`."

        Design: Difficulty/priority_pair_validation_conflict/session_create_rejects_with_assignment_case_mismatch_not_teacher_slot_conflict
        """
        bundle = _two_active_cases_sharing_one_teacher()

        validate_error(
            api_client.create_session(
                create_session_payload(
                    bundle["case_b"]["id"],
                    bundle["assignment_b"]["id"],
                    scheduled_start="2026-09-07T10:00:00Z",
                    scheduled_end="2026-09-07T12:00:00Z",
                    delivery_mode="IN_HOME",
                    subject="MATH",
                ),
                CM_HEADERS,
            ),
            ApiErrorId.ERR_TEACHER_SLOT_CONFLICT.value,
            409,
        )
        assert len(sessions_for_case(bundle["case"]["id"])) == 1, (
            "only case A's original visit survives"
        )
        assert sessions_for_case(bundle["case_b"]["id"]) == []


class TestStaleVersionOutranksTheCaseState:
    """Tier 7 answers before the tier-8 lifecycle guard is consulted."""

    def test_the_concurrency_gate_answers_rather_than_the_lifecycle_gate(self):
        """An extension request against an ELIGIBLE case carrying the version the case
        held at creation is refused as stale, not as an invalid case state.

        The PRD states: "If `expected_case_version` does not equal the case's current
        `version`, the request is rejected with `ERR_STALE_CASE_VERSION` and HTTP 412,
        and nothing is written."

        Design: Difficulty/priority_pair_validation_conflict/extension_request_rejects_with_stale_case_version_not_invalid_case_state
        """
        bundle = setup_eligible_case(
            rules=[MIDDLE_IN_HOME_RULE], certification=dict(CERT_WINDOW)
        )
        case_id = bundle["case"]["id"]
        assert bundle["case"]["version"] > bundle["case_v_draft"], (
            "submission and acceptance have both moved the case past its first version"
        )

        error = validate_error(
            api_client.create_extension_request(
                create_extension_request_payload(
                    case_id,
                    bundle["certification"]["id"],
                    bundle["case_v_draft"],
                    requested_additional_days=30,
                    justification="Recovery extended by thirty days",
                ),
                CM_HEADERS,
            ),
            ApiErrorId.ERR_STALE_CASE_VERSION.value,
            412,
        )
        assert error["error_id"] != ApiErrorId.ERR_INVALID_CASE_STATE.value, (
            "the tier-8 lifecycle rule is never reached"
        )

        case = read_case(case_id)
        assert case["service_status"] == "ELIGIBLE"
        assert case["extension_count"] == 0
        assert _extension_requests_for_case(case_id) == []

    def test_the_control_request_proves_the_case_state_was_also_wrong(self):
        """The same request carrying the case's current version — repairing only the
        staleness — is refused for the case state.

        The PRD states: "Requesting an extension from any state other than `ACTIVE`
        is `ERR_INVALID_CASE_STATE`."

        Design: Difficulty/priority_pair_validation_conflict/extension_request_rejects_with_stale_case_version_not_invalid_case_state
        """
        bundle = setup_eligible_case(
            rules=[MIDDLE_IN_HOME_RULE], certification=dict(CERT_WINDOW)
        )
        case_id = bundle["case"]["id"]

        validate_error(
            api_client.create_extension_request(
                create_extension_request_payload(
                    case_id,
                    bundle["certification"]["id"],
                    bundle["case"]["version"],
                    requested_additional_days=30,
                    justification="Recovery extended by thirty days",
                ),
                CM_HEADERS,
            ),
            ApiErrorId.ERR_INVALID_CASE_STATE.value,
            409,
        )
        assert _extension_requests_for_case(case_id) == [], (
            "neither refusal leaves an extension request behind"
        )
