"""Which rule a request breaks, and which of several broken rules gets to answer.

Every uniqueness constraint here is scoped rather than absolute, so retiring a
rule or denying a case frees the key it was holding. Every date rule fires on a
different comparison. And where one request breaks two rules at once, the tier
order — not the order the fields appear in the payload — decides the code.
"""

from test_helpers import (
    ApiErrorId,
    CLASSROOM_TEACHER,
    CM_HEADERS,
    MIDDLE_IN_HOME_RULE,
    NR_HEADERS,
    PA_HEADERS,
    accept_assignment,
    activate_case,
    api_client,
    assignments_for_case,
    create_assignment_payload,
    create_case_payload,
    create_certification_payload,
    create_entitlement_rule_payload,
    create_extension_request_payload,
    create_pacing_sync_payload,
    create_session_payload,
    create_sped_service_log_payload,
    create_student_payload,
    create_transition_plan_payload,
    deny_case_payload,
    finalize_safety_review,
    list_data,
    make_homebound_teacher_headers,
    open_case,
    open_pacing_sync,
    open_sped_service_log,
    propose_assignment,
    read_assignment,
    read_case,
    read_teacher,
    record_safety_review,
    register_student,
    register_teacher,
    review_certification,
    sessions_for_case,
    set_clock,
    setup_active_case,
    setup_case_with_primary_assignment,
    setup_catalogue,
    student_enrollment_payload,
    submit_certification,
    teacher_clearance_payload,
    validate_error,
    validate_success,
)

CLOCK = "2026-09-01T00:00:00Z"
ACTIVATION_CLOCK = "2026-09-07T08:00:00Z"

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

PRIMARY_BAND_RULE = {
    "grade_band": "PRIMARY",
    "delivery_mode": "IN_HOME",
    "base_weekly_minutes": 300,
    "cap_weekly_minutes": 400,
    "min_session_minutes": 30,
    "max_session_minutes": 90,
    "max_daily_minutes": 180,
    "min_gap_minutes": 15,
    "travel_buffer_minutes": 30,
}

MORNING_VISIT = {
    "scheduled_start": "2026-09-08T09:00:00Z",
    "scheduled_end": "2026-09-08T10:00:00Z",
    "delivery_mode": "IN_HOME",
    "subject": "MATH",
}


def _all(list_call) -> list:
    """Every row of one collection, unfiltered — the only declared query parameters
    are the page window, so any narrowing happens here in the test."""
    return list_data(list_call(PA_HEADERS, params={"limit": 100}))


def _book(case_id: str, assignment_id: str, **overrides):
    return api_client.create_session(
        create_session_payload(case_id, assignment_id, **overrides), CM_HEADERS
    )


def _propose(case_id: str, role: str, teacher_id: str):
    return api_client.create_assignment(
        create_assignment_payload(case_id, role, teacher_id), CM_HEADERS
    )


def _accept(assignment_id: str, teacher_id: str):
    return api_client.accept_assignment(
        assignment_id, make_homebound_teacher_headers(teacher_id)
    )


def _case_with_one_of_everything() -> dict:
    """An ACTIVE case that already holds a primary assignment, one MATH coordination
    row and one SPEECH continuation log, so every uniqueness key is occupied."""
    bundle = setup_active_case(
        clock=CLOCK,
        rules=[MIDDLE_IN_HOME_RULE],
        certification=dict(CERT_WINDOW),
        safety_review=dict(CLEARED_SAFETY_REVIEW),
    )
    case_id = bundle["case"]["id"]
    bundle["classroom_teacher"] = register_teacher(**CLASSROOM_TEACHER)
    bundle["pacing_sync"] = open_pacing_sync(
        case_id, bundle["classroom_teacher"]["id"], subject="MATH"
    )
    bundle["sped_log"] = open_sped_service_log(
        case_id, service_type="SPEECH", required_weekly_minutes=60
    )
    bundle["case"] = read_case(case_id)
    return bundle


def _denied_case_and_a_published_rule() -> dict:
    """One PUBLISHED MIDDLE / IN_HOME rule, and one student whose only case has been
    denied before it ever reached eligibility."""
    rules = setup_catalogue(clock=CLOCK, rules=[MIDDLE_IN_HOME_RULE])
    student = register_student()
    first_case = open_case(student["id"])
    denied = validate_success(
        api_client.deny_case(
            first_case["id"],
            deny_case_payload(deny_note="Family declined homebound services"),
            PA_HEADERS,
        )
    )
    return {"rule": rules[0], "student": student, "denied_case": denied}


def _draft_case_awaiting_certification() -> dict:
    """A DRAFT case with a registered teacher standing by, at clock 2026-09-01."""
    rules = setup_catalogue(clock=CLOCK, rules=[MIDDLE_IN_HOME_RULE])
    student = register_student()
    teacher = register_teacher()
    case = open_case(student["id"])
    return {
        "rule": rules[0],
        "student": student,
        "teacher": teacher,
        "case": case,
    }


def _case_with_two_narrow_support_candidates() -> dict:
    """An ELIGIBLE 390-minute case with an accepted primary row and two PROPOSED support
    rows, one teacher capped at 100 weekly minutes and one capped at exactly 115."""
    bundle = setup_case_with_primary_assignment(
        clock=CLOCK, rules=[MIDDLE_IN_HOME_RULE], certification=dict(CERT_WINDOW)
    )
    case_id = bundle["case"]["id"]
    bundle["tiny_teacher"] = register_teacher(
        full_name="Ivo Renn",
        employee_number="E-1005",
        credential_areas=["SCIENCE"],
        grade_bands=["MIDDLE"],
        max_weekly_caseload_minutes=100,
    )
    bundle["exact_teacher"] = register_teacher(
        full_name="Ora Blay",
        employee_number="E-1006",
        credential_areas=["SOCIAL_STUDIES"],
        grade_bands=["MIDDLE"],
        max_weekly_caseload_minutes=115,
    )
    bundle["tiny_assignment"] = propose_assignment(
        case_id, "SUPPORT", bundle["tiny_teacher"]["id"]
    )
    bundle["exact_assignment"] = propose_assignment(
        case_id, "SUPPORT", bundle["exact_teacher"]["id"]
    )
    return bundle


def _two_cases_and_a_spare_student() -> dict:
    """Case A is ACTIVE and carries a REJECTED certification alongside its ACCEPTED one;
    case B is ELIGIBLE and fully staffed; a third student holds no case at all."""
    rules = setup_catalogue(clock=CLOCK, rules=[MIDDLE_IN_HOME_RULE])
    teacher = register_teacher()
    students = {
        "a": register_student(),
        "b": register_student(
            student_number="S-0002", full_name="Ben Oyo", grade_level=8
        ),
        "c": register_student(
            student_number="S-0003", full_name="Cara Voss", grade_level=7
        ),
    }
    bundle = {"rule": rules[0], "teacher": teacher, "students": students}

    case_a = open_case(students["a"]["id"])
    rejected = submit_certification(case_a["id"], **CERT_WINDOW)
    review_certification(
        rejected["id"], "REJECT", review_note="Missing physician signature block"
    )
    bundle["rejected_certification"] = rejected
    accepted = submit_certification(case_a["id"], **CERT_WINDOW)
    review_certification(accepted["id"], "ACCEPT")
    bundle["accepted_certification_a"] = accepted
    finalize_safety_review(
        record_safety_review(case_a["id"], **CLEARED_SAFETY_REVIEW)["id"]
    )
    assignment_a = propose_assignment(case_a["id"], "PRIMARY", teacher["id"])
    accept_assignment(assignment_a["id"], teacher["id"])

    case_b = open_case(students["b"]["id"])
    certification_b = submit_certification(
        case_b["id"], physician_npi="1234567891", **CERT_WINDOW
    )
    review_certification(certification_b["id"], "ACCEPT")
    bundle["certification_b"] = certification_b
    finalize_safety_review(
        record_safety_review(case_b["id"], **CLEARED_SAFETY_REVIEW)["id"]
    )
    assignment_b = propose_assignment(case_b["id"], "PRIMARY", teacher["id"])
    accept_assignment(assignment_b["id"], teacher["id"])

    set_clock(ACTIVATION_CLOCK)
    bundle["case_a"] = activate_case(case_a["id"])
    bundle["case_b"] = read_case(case_b["id"])
    return bundle


def _case_with_no_resolvable_rule() -> dict:
    """A grade-7 IN_HOME case whose only published rule is keyed to the PRIMARY band,
    sitting in PENDING_CERT_REVIEW with one SUBMITTED certification."""
    rules = setup_catalogue(clock=CLOCK, rules=[PRIMARY_BAND_RULE])
    student = register_student()
    case = open_case(student["id"])
    certification = submit_certification(case["id"], **CERT_WINDOW)
    return {
        "primary_band_rule": rules[0],
        "student": student,
        "case": case,
        "certification": certification,
    }


def _staffed_case_and_a_high_band_teacher() -> dict:
    """An ELIGIBLE case with an ACTIVE primary row, plus a teacher who serves the HIGH
    band only and so cannot serve this grade-7 student."""
    bundle = setup_case_with_primary_assignment(
        clock=CLOCK, rules=[MIDDLE_IN_HOME_RULE], certification=dict(CERT_WINDOW)
    )
    bundle["high_band_teacher"] = register_teacher(
        full_name="Pia Cole",
        employee_number="E-1007",
        credential_areas=["MATH"],
        grade_bands=["HIGH"],
        max_weekly_caseload_minutes=900,
    )
    return bundle


def _case_in_service_with_a_pending_support_row() -> dict:
    """An ACTIVE case with an ACTIVE primary row for one teacher and a PROPOSED support
    row for another."""
    bundle = setup_active_case(
        clock=CLOCK,
        rules=[MIDDLE_IN_HOME_RULE],
        certification=dict(CERT_WINDOW),
        safety_review=dict(CLEARED_SAFETY_REVIEW),
    )
    bundle["support_teacher"] = register_teacher(
        full_name="Sam Duro",
        employee_number="E-1002",
        credential_areas=["SCIENCE"],
        grade_bands=["MIDDLE"],
        max_weekly_caseload_minutes=600,
    )
    bundle["support_assignment"] = propose_assignment(
        bundle["case"]["id"], "SUPPORT", bundle["support_teacher"]["id"]
    )
    return bundle


class TestEveryOccupiedKeyRefusesASecondClaimant:
    """Six duplicate keys, six different codes, and a duration band that is its own rule."""

    def test_each_uniqueness_rule_answers_on_its_own_endpoint_with_its_own_code(self):
        """A repeated student number, a second published rule for one pair, a second live
        case for one student, a second primary row, a repeated coordination subject and a
        repeated service type each produce their own conflict, and a session of 20 or 150
        minutes fails the rule's inclusive band — with nothing persisted by any of them.

        The PRD states: "Registration supplies a `student_number`, which must be unique
        across all students and between one and thirty-two characters long — a collision
        is rejected with `ERR_DUPLICATE_STUDENT_NUMBER` — together with the student's
        legal `full_name`, a `grade_level` from 0 through 12 inclusive where 0 denotes
        kindergarten, and a `campus_code` naming the home campus used for classroom
        coordination."

        The PRD states: "Only a `PUBLISHED` rule is ever selectable for an entitlement
        computation, and at most one `PUBLISHED` rule may exist for any given
        grade-band-and-delivery-mode pair; publishing a second one for the same pair is
        rejected with `ERR_DUPLICATE_ENTITLEMENT_RULE`."

        The PRD states: "A student may hold only one live case at a time: if the student
        already has a case whose `service_status` is anything other than `CLOSED` or
        `DENIED`, the request is rejected with `ERR_OPEN_CASE_EXISTS`."

        The PRD states: "A case may hold only one primary staffing commitment: if
        another assignment of the same case has `role` `PRIMARY` and `status` either
        `PROPOSED` or `ACTIVE`, the request is rejected with
        `ERR_DUPLICATE_PRIMARY_ASSIGNMENT`."

        The PRD states: "Each subject is coordinated once per case: a second row for the
        same subject is rejected with `ERR_DUPLICATE_PACING_SUBJECT`."

        The PRD states: "Logs may only be opened against a case in service, otherwise
        `ERR_CASE_NOT_ACTIVE`, and each service type is tracked once per case — a
        duplicate is `ERR_DUPLICATE_SPED_SERVICE_TYPE`."

        The PRD states: "The session's `scheduled_minutes` must lie between the rule's
        `min_session_minutes` and `max_session_minutes`, inclusive on both ends; outside
        that range the request is `ERR_SESSION_DURATION_INVALID`."

        Design: Corner/validations/every_uniqueness_rule_and_the_session_duration_band_reject_their_violation
        """
        bundle = _case_with_one_of_everything()
        case_id = bundle["case"]["id"]
        assignment_id = bundle["primary_assignment"]["id"]
        version_before = bundle["case"]["version"]

        validate_error(
            api_client.create_student(
                create_student_payload(
                    student_number="S-0001",
                    full_name="Ada Lin Duplicate",
                    grade_level=9,
                    campus_code="HS-01",
                ),
                PA_HEADERS,
            ),
            ApiErrorId.ERR_DUPLICATE_STUDENT_NUMBER.value,
            409,
        )
        validate_error(
            api_client.create_entitlement_rule(
                create_entitlement_rule_payload(
                    base_weekly_minutes=420, cap_weekly_minutes=500
                ),
                PA_HEADERS,
            ),
            ApiErrorId.ERR_DUPLICATE_ENTITLEMENT_RULE.value,
            409,
        )
        validate_error(
            api_client.create_case(
                create_case_payload(
                    bundle["student"]["id"],
                    referral_date="2026-09-07",
                    delivery_mode="VIRTUAL_SYNC",
                ),
                CM_HEADERS,
            ),
            ApiErrorId.ERR_OPEN_CASE_EXISTS.value,
            409,
        )
        validate_error(
            _propose(case_id, "PRIMARY", bundle["classroom_teacher"]["id"]),
            ApiErrorId.ERR_DUPLICATE_PRIMARY_ASSIGNMENT.value,
            409,
        )
        validate_error(
            api_client.create_pacing_sync(
                create_pacing_sync_payload(
                    case_id,
                    bundle["classroom_teacher"]["id"],
                    subject="MATH",
                    pacing_target_unit="Unit 4 Systems",
                    assessment_accommodation="NONE",
                ),
                CM_HEADERS,
            ),
            ApiErrorId.ERR_DUPLICATE_PACING_SUBJECT.value,
            409,
        )
        validate_error(
            api_client.create_sped_service_log(
                create_sped_service_log_payload(
                    case_id, service_type="SPEECH", required_weekly_minutes=30
                ),
                CM_HEADERS,
            ),
            ApiErrorId.ERR_DUPLICATE_SPED_SERVICE_TYPE.value,
            409,
        )
        validate_error(
            _book(
                case_id,
                assignment_id,
                scheduled_start="2026-09-08T09:00:00Z",
                scheduled_end="2026-09-08T09:20:00Z",
            ),
            ApiErrorId.ERR_SESSION_DURATION_INVALID.value,
            422,
        )
        validate_error(
            _book(
                case_id,
                assignment_id,
                scheduled_start="2026-09-08T09:00:00Z",
                scheduled_end="2026-09-08T11:30:00Z",
            ),
            ApiErrorId.ERR_SESSION_DURATION_INVALID.value,
            422,
        )

        students = [
            row
            for row in _all(api_client.list_students)
            if row["student_number"] == "S-0001"
        ]
        assert len(students) == 1
        published = [
            row
            for row in _all(api_client.list_entitlement_rules)
            if row["grade_band"] == "MIDDLE"
            and row["delivery_mode"] == "IN_HOME"
            and row["status"] == "PUBLISHED"
        ]
        assert len(published) == 1
        cases = [
            row
            for row in _all(api_client.list_cases)
            if row["student_id"] == bundle["student"]["id"]
        ]
        assert len(cases) == 1
        syncs = [
            row for row in _all(api_client.list_pacing_syncs) if row["case_id"] == case_id
        ]
        assert len(syncs) == 1
        logs = [
            row
            for row in _all(api_client.list_sped_service_logs)
            if row["case_id"] == case_id
        ]
        assert len(logs) == 1
        assert len(assignments_for_case(case_id)) == 1
        assert sessions_for_case(case_id) == [], (
            "no rejected call put a visit on the calendar"
        )
        assert read_case(case_id)["version"] == version_before, (
            "eight refusals in a row left the case exactly where it was"
        )


class TestBothUniquenessRulesAreScopedRatherThanAbsolute:
    """Retiring the rule frees the pair; denying the case frees the student."""

    def test_a_retired_rule_and_a_denied_case_both_release_the_key_they_held(self):
        """Once the first rule is RETIRED a second PUBLISHED rule for the same pair is
        accepted, and once the student's only case is DENIED a second case is accepted —
        while retiring the same rule twice is refused.

        The PRD states: "A rule's `status` is either `PUBLISHED` or `RETIRED` and
        defaults to `PUBLISHED`."

        The PRD states: "Only a `PUBLISHED` rule is ever selectable for an entitlement
        computation, and at most one `PUBLISHED` rule may exist for any given
        grade-band-and-delivery-mode pair; publishing a second one for the same pair is
        rejected with `ERR_DUPLICATE_ENTITLEMENT_RULE`."

        The PRD states: "A `ProgramAdministrator` retires a rule to withdraw it from
        future resolution; retiring a rule whose `status` is already `RETIRED` is
        rejected with `ERR_RULE_ALREADY_RETIRED`."

        The PRD states: "Denial is permitted only while the case's `service_status` is
        `DRAFT` or `PENDING_CERT_REVIEW`; from either of those the case moves to
        `DENIED`, and from any other state the request is rejected with
        `ERR_INVALID_CASE_STATE`."

        The PRD states: "A student may hold only one live case at a time: if the student
        already has a case whose `service_status` is anything other than `CLOSED` or
        `DENIED`, the request is rejected with `ERR_OPEN_CASE_EXISTS`."

        The PRD states: "The new case starts with `service_status` `DRAFT` and
        `funding_status` `NOT_REPORTED`, and the server stamps `created_by_user_id` with
        the acting `X-User-ID` — a value that later governs who may verify this case's
        sessions."

        Design: Corner/validations/retiring_a_rule_frees_its_pair_and_a_closed_case_frees_the_student
        """
        bundle = _denied_case_and_a_published_rule()
        first_rule_id = bundle["rule"]["id"]
        assert bundle["denied_case"]["service_status"] == "DENIED"

        retired = validate_success(
            api_client.retire_entitlement_rule(first_rule_id, PA_HEADERS)
        )
        assert retired["status"] == "RETIRED"

        second_rule = validate_success(
            api_client.create_entitlement_rule(
                create_entitlement_rule_payload(
                    base_weekly_minutes=420, cap_weekly_minutes=500
                ),
                PA_HEADERS,
            ),
            201,
        )
        assert second_rule["status"] == "PUBLISHED"
        assert second_rule["base_weekly_minutes"] == 420, (
            "the retired row no longer occupies the pair"
        )

        validate_error(
            api_client.retire_entitlement_rule(first_rule_id, PA_HEADERS),
            ApiErrorId.ERR_RULE_ALREADY_RETIRED.value,
            409,
        )

        second_case = validate_success(
            api_client.create_case(
                create_case_payload(
                    bundle["student"]["id"], referral_date="2026-09-08"
                ),
                CM_HEADERS,
            ),
            201,
        )
        assert second_case["service_status"] == "DRAFT", (
            "a denied case does not count as a live one"
        )
        assert second_case["funding_status"] == "NOT_REPORTED"
        assert second_case["student_id"] == bundle["student"]["id"]

        pair = [
            row
            for row in _all(api_client.list_entitlement_rules)
            if row["grade_band"] == "MIDDLE" and row["delivery_mode"] == "IN_HOME"
        ]
        assert len(pair) == 2
        assert {row["id"]: row["status"] for row in pair} == {
            first_rule_id: "RETIRED",
            second_rule["id"]: "PUBLISHED",
        }


class TestEachDateRuleFiresOnItsOwnComparison:
    """An inverted window, a future signature, a stale signature, and an expired review."""

    def test_three_window_failures_share_a_code_while_the_boundary_and_the_expiry_do_not(
        self,
    ):
        """An end date before the start, a signature after the clock and a signature more
        than thirty days early all answer with the same window code, a signature exactly
        thirty days early passes, and a session outside the certified window is a
        different refusal from one guarded by a review that has aged out.

        The PRD states: "The window itself is checked too: `certified_end_date` may not
        precede `certified_start_date`, `signature_date` may not fall later than the
        clock date, and `signature_date` may not fall earlier than thirty days before
        `certified_start_date`. Any of those three failures is
        `ERR_CERT_WINDOW_INVALID`."

        The PRD states: "The `service_date` must fall inside the case's certified
        window, on or after `certified_start_date` and on or before
        `certified_end_date`; outside that window the request is rejected with
        `ERR_SESSION_OUTSIDE_CERT_WINDOW`."

        The PRD states: "The server also derives `expires_on` as the `review_date`
        advanced by sixty days, and computes an initial `risk_score`."

        The PRD states: "A superseded review no longer governs scheduling; the newer
        finalized review does."

        The PRD states: "That finalized review's `expires_on` must be on or after the
        session's `service_date`; an in-home session scheduled beyond the sixty-day
        validity of the review is rejected with `ERR_SAFETY_REVIEW_EXPIRED`."

        Design: Corner/validations/certification_window_session_window_and_review_expiry_all_reject_on_dates
        """
        bundle = _draft_case_awaiting_certification()
        case_id = bundle["case"]["id"]
        draft_version = bundle["case"]["version"]

        broken_windows = (
            (
                "an inverted window",
                {
                    "certified_start_date": "2026-09-20",
                    "certified_end_date": "2026-09-10",
                },
            ),
            ("a signature later than the clock date", {"signature_date": "2026-09-05"}),
            (
                "a signature more than thirty days before the start",
                {"signature_date": "2026-08-01"},
            ),
        )
        for why, overrides in broken_windows:
            validate_error(
                api_client.create_certification(
                    create_certification_payload(
                        case_id, draft_version, **{**CERT_WINDOW, **overrides}
                    ),
                    CM_HEADERS,
                ),
                ApiErrorId.ERR_CERT_WINDOW_INVALID.value,
                422,
            )
            assert _all(api_client.list_certifications) == [], (
                f"{why} left no document behind"
            )

        accepted_boundary = validate_success(
            api_client.create_certification(
                create_certification_payload(
                    case_id,
                    draft_version,
                    **{**CERT_WINDOW, "signature_date": "2026-08-08"},
                ),
                CM_HEADERS,
            ),
            201,
        )
        assert accepted_boundary["signature_date"] == "2026-08-08", (
            "thirty days before the start date is the inclusive edge of the rule"
        )
        review_certification(accepted_boundary["id"], "ACCEPT")

        fresh_review = record_safety_review(case_id, **CLEARED_SAFETY_REVIEW)
        assert fresh_review["expires_on"] == "2026-11-01"
        finalize_safety_review(fresh_review["id"])
        assignment = propose_assignment(case_id, "PRIMARY", bundle["teacher"]["id"])
        accept_assignment(assignment["id"], bundle["teacher"]["id"])
        set_clock(ACTIVATION_CLOCK)
        activate_case(case_id)

        validate_error(
            _book(
                case_id,
                assignment["id"],
                scheduled_start="2026-10-09T09:00:00Z",
                scheduled_end="2026-10-09T10:00:00Z",
                delivery_mode="IN_HOME",
                subject="MATH",
            ),
            ApiErrorId.ERR_SESSION_OUTSIDE_CERT_WINDOW.value,
            422,
        )

        stale_review = record_safety_review(
            case_id, review_date="2026-07-05", **CLEARED_SAFETY_REVIEW
        )
        assert stale_review["expires_on"] == "2026-09-03", "sixty days past 2026-07-05"
        assert stale_review["risk_score"] == 5
        finalize_safety_review(stale_review["id"])

        validate_error(
            _book(case_id, assignment["id"], **MORNING_VISIT),
            ApiErrorId.ERR_SAFETY_REVIEW_EXPIRED.value,
            422,
        )
        assert sessions_for_case(case_id) == [], (
            "a date inside the certified window is not enough on its own"
        )


class TestTheCaseloadCeilingIsCheckedAgainstTheAllocationItWouldGrant:
    """One minute of headroom is the whole difference between the two acceptances."""

    def test_a_support_row_worth_one_fifteen_fails_a_hundred_cap_and_passes_an_exact_one(
        self,
    ):
        """The support share this row would receive is 115, so a teacher capped at 100 is
        refused while a teacher capped at exactly 115 is admitted, and the refused row
        leaves both its own minutes and the primary allocation untouched.

        The PRD states: "The caseload ceiling is enforced at acceptance: if the
        teacher's `committed_weekly_minutes` plus the allocation this assignment would
        receive would exceed `max_weekly_caseload_minutes`, the acceptance is rejected
        with `ERR_TEACHER_CASELOAD_EXCEEDED`."

        The PRD states: "Support staff share thirty percent of the entitlement: when the
        case has at least one active support assignment, multiply
        `weekly_entitled_minutes` by 0.30, divide by the number of active support
        assignments, divide by five, round half up to a whole number, and multiply back
        by five; every active support assignment receives that same per-support figure,
        and the support total is that figure multiplied by the number of support
        assignments."

        The PRD states: "The primary assignment nominally carries the remaining seventy
        percent, and concretely it receives the case's `weekly_entitled_minutes` minus
        the support total — so the primary row absorbs the entire rounding residual and
        the sum of `weekly_committed_minutes` across active assignments equals
        `weekly_entitled_minutes` exactly."

        The PRD states: "Only assignments whose `status` is `ACTIVE` participate;
        `PROPOSED`, `DECLINED` and `RELEASED` assignments are excluded and always hold
        `weekly_committed_minutes` 0."

        The PRD states: "The derived flag `over_cap` is true when
        `committed_weekly_minutes` is strictly greater than that teacher's
        `max_weekly_caseload_minutes`, and false when the two are equal."

        Design: Corner/validations/caseload_aggregate_blocks_one_acceptance_and_admits_the_exact_boundary
        """
        bundle = _case_with_two_narrow_support_candidates()
        assert bundle["case"]["weekly_entitled_minutes"] == 390

        validate_error(
            _accept(bundle["tiny_assignment"]["id"], bundle["tiny_teacher"]["id"]),
            ApiErrorId.ERR_TEACHER_CASELOAD_EXCEEDED.value,
            422,
        )

        admitted = validate_success(
            _accept(bundle["exact_assignment"]["id"], bundle["exact_teacher"]["id"])
        )
        assert admitted["status"] == "ACTIVE"
        assert admitted["weekly_committed_minutes"] == 115, (
            "nothing plus 115 is not greater than 115, so the boundary is admitted"
        )

        refused_teacher = read_teacher(bundle["tiny_teacher"]["id"])
        assert refused_teacher["committed_weekly_minutes"] == 0
        assert refused_teacher["over_cap"] is False
        refused_row = read_assignment(bundle["tiny_assignment"]["id"])
        assert refused_row["status"] == "PROPOSED"
        assert refused_row["weekly_committed_minutes"] == 0

        primary = read_assignment(bundle["primary_assignment"]["id"])
        assert primary["weekly_committed_minutes"] == 275, (
            "only the accepted support row entered the allocation"
        )


class TestRampWeeksIsLegalOnlyRelativeToTheReintegrationShape:
    """The same integer is required in one mode and forbidden in another."""

    def test_two_inconsistent_pairings_are_refused_before_the_third_one_opens_the_plan(
        self,
    ):
        """A full-day return with two ramp weeks and a partial-day ramp with the default
        zero are both inconsistent pairings, while a virtual bridge of three ramp weeks
        opens the plan and moves the case out of ACTIVE without disturbing its funding.

        The PRD states: "The payload names the `case_id`, a `target_return_date` on
        which the student re-enters the building, a `reintegration_mode` of `FULL_DAY`,
        `PARTIAL_DAY_RAMP`, or `VIRTUAL_BRIDGE`, the `expected_case_version` guard of
        §2.7, and optionally `ramp_weeks` between 0 and 8 inclusive, defaulting to 0."

        The PRD states: "Ramp weeks must be consistent with the reintegration shape:
        exactly 0 when `reintegration_mode` is `FULL_DAY`, and at least 1 when it is
        `PARTIAL_DAY_RAMP` or `VIRTUAL_BRIDGE`."

        The PRD states: "An inconsistent pairing is rejected with
        `ERR_RAMP_WEEKS_INVALID`."

        The PRD states: "A `CaseManager` opens a plan against an `ACTIVE` case, which
        advances the case `ACTIVE → TRANSITION_PLANNED` and increments its `version` by
        one."

        The PRD states: "A new plan starts with `status` `DRAFT`, and its
        `required_ack_count` and `classroom_ack_count` are computed on creation."

        The PRD states: "`required_ack_count` is the number of coordination rows for the
        plan's case whose `ack_status` is `PENDING`, `ACKED` or `DISPUTED`;
        `classroom_ack_count` is the number of those rows whose `ack_status` is
        `ACKED`."

        The PRD states: "Completion moves the plan `READY → COMPLETED`, stamps
        `completed_at` with the clock instant, and closes the case: the case advances
        `TRANSITION_PLANNED → CLOSED` with `close_reason` `RETURNED_TO_CAMPUS`, every
        assignment of the case whose `status` is `ACTIVE` is moved to `RELEASED` with
        `release_reason` `CASE_CLOSED` and `weekly_committed_minutes` 0,
        `committed_weekly_minutes` is recomputed for each released teacher, every
        session of the case whose `status` is `SCHEDULED` is moved to `CANCELLED_ADMIN`,
        and the case's `version` increments by one."

        The PRD states: "A `HomeboundCase` carries two independent status dimensions
        that advance separately and must never be conflated."

        Design: Corner/validations/ramp_weeks_requirement_flips_with_the_reintegration_mode
        """
        bundle = setup_active_case(
            clock=CLOCK,
            rules=[MIDDLE_IN_HOME_RULE],
            certification=dict(CERT_WINDOW),
            safety_review=dict(CLEARED_SAFETY_REVIEW),
        )
        case_id = bundle["case"]["id"]
        version_before = bundle["case"]["version"]

        validate_error(
            api_client.create_transition_plan(
                create_transition_plan_payload(
                    case_id,
                    version_before,
                    target_return_date="2026-10-05",
                    reintegration_mode="FULL_DAY",
                    ramp_weeks=2,
                ),
                CM_HEADERS,
            ),
            ApiErrorId.ERR_RAMP_WEEKS_INVALID.value,
            422,
        )
        validate_error(
            api_client.create_transition_plan(
                create_transition_plan_payload(
                    case_id,
                    version_before,
                    target_return_date="2026-10-05",
                    reintegration_mode="PARTIAL_DAY_RAMP",
                ),
                CM_HEADERS,
            ),
            ApiErrorId.ERR_RAMP_WEEKS_INVALID.value,
            422,
        )

        plan = validate_success(
            api_client.create_transition_plan(
                create_transition_plan_payload(
                    case_id,
                    version_before,
                    target_return_date="2026-10-05",
                    reintegration_mode="VIRTUAL_BRIDGE",
                    ramp_weeks=3,
                ),
                CM_HEADERS,
            ),
            201,
        )
        assert plan["status"] == "DRAFT"
        assert plan["ramp_weeks"] == 3
        assert plan["required_ack_count"] == 0, "the case has no coordination rows yet"
        assert plan["classroom_ack_count"] == 0
        assert plan["completed_at"] is None

        case = read_case(case_id)
        assert case["service_status"] == "TRANSITION_PLANNED"
        assert case["funding_status"] == "ACCRUING", (
            "planning a return moves the service dimension only"
        )
        assert case["version"] == version_before + 1, (
            "the two refused pairings never touched the case"
        )
        plans = [
            row
            for row in _all(api_client.list_transition_plans)
            if row["case_id"] == case_id
        ]
        assert [row["id"] for row in plans] == [plan["id"]]


class TestEachCrossEntityCheckReadsADifferentSiblingRow:
    """A certification's parent, a certification's status, and a student's enrollment."""

    def test_the_wrong_certification_the_rejected_one_and_a_withdrawn_student_each_answer(
        self,
    ):
        """An extension request naming another case's accepted certification is a mismatch,
        one naming its own case's rejected certification is a status failure, and
        withdrawing a student retroactively blocks both a new case and the activation of
        one that was already eligible.

        The PRD states: "The referenced certification must belong to the same case, or
        the request fails with `ERR_CERT_CASE_MISMATCH`, and its `status` must be
        `ACCEPTED`, or the request fails with `ERR_CERT_NOT_ACCEPTED`."

        The PRD states: "Enrollment posture is maintained separately after registration;
        a `ProgramAdministrator` may withdraw or re-enroll a student by supplying a new
        `enrollment_status`, and that change increments the student's `version` by one."

        The PRD states: "A case may only be opened for an enrolled student; a
        `WITHDRAWN` student is rejected with `ERR_STUDENT_NOT_ENROLLED`."

        The PRD states: "The student's `enrollment_status` must still be `ENROLLED`, or
        the activation fails with `ERR_STUDENT_NOT_ENROLLED`."

        The PRD states: "Activation advances `service_status` `ELIGIBLE → ACTIVE`, sets
        `service_start_date` to the clock date, refreshes `escort_required` from the
        governing finalized review, moves `funding_status` `NOT_REPORTED → ACCRUING` in
        the same request with `service_gap_minutes` initialized to 0, and increments the
        case's `version` by one."

        The PRD states: "The case's `extension_count` — the number of that case's
        extension requests whose `status` is `APPROVED` — must be less than 2, and a
        third attempt is rejected with `ERR_EXTENSION_LIMIT_REACHED`."

        Design: Corner/validations/extension_and_activation_checks_reach_across_to_certification_and_student_rows
        """
        bundle = _two_cases_and_a_spare_student()
        case_a_id = bundle["case_a"]["id"]
        case_b_id = bundle["case_b"]["id"]
        case_a_version = bundle["case_a"]["version"]

        validate_error(
            api_client.create_extension_request(
                create_extension_request_payload(
                    case_a_id,
                    bundle["certification_b"]["id"],
                    case_a_version,
                    requested_additional_days=15,
                    justification="Wrong certification attached",
                ),
                CM_HEADERS,
            ),
            ApiErrorId.ERR_CERT_CASE_MISMATCH.value,
            422,
        )
        validate_error(
            api_client.create_extension_request(
                create_extension_request_payload(
                    case_a_id,
                    bundle["rejected_certification"]["id"],
                    case_a_version,
                    requested_additional_days=15,
                    justification="Rejected certification attached",
                ),
                CM_HEADERS,
            ),
            ApiErrorId.ERR_CERT_NOT_ACCEPTED.value,
            422,
        )

        withdrawn_spare = validate_success(
            api_client.set_student_enrollment(
                bundle["students"]["c"]["id"],
                student_enrollment_payload("WITHDRAWN"),
                PA_HEADERS,
            )
        )
        assert withdrawn_spare["enrollment_status"] == "WITHDRAWN"

        validate_error(
            api_client.create_case(
                create_case_payload(
                    bundle["students"]["c"]["id"], referral_date="2026-09-07"
                ),
                CM_HEADERS,
            ),
            ApiErrorId.ERR_STUDENT_NOT_ENROLLED.value,
            422,
        )
        assert [
            row
            for row in _all(api_client.list_cases)
            if row["student_id"] == bundle["students"]["c"]["id"]
        ] == []

        validate_success(
            api_client.set_student_enrollment(
                bundle["students"]["b"]["id"],
                student_enrollment_payload("WITHDRAWN"),
                PA_HEADERS,
            )
        )
        validate_error(
            api_client.activate_case(case_b_id, PA_HEADERS),
            ApiErrorId.ERR_STUDENT_NOT_ENROLLED.value,
            422,
        )
        case_b = read_case(case_b_id)
        assert case_b["service_status"] == "ELIGIBLE"
        assert case_b["funding_status"] == "NOT_REPORTED"
        assert case_b["service_start_date"] is None

        requests = [
            row
            for row in _all(api_client.list_extension_requests)
            if row["case_id"] == case_a_id
        ]
        assert requests == []
        assert read_case(case_a_id)["extension_count"] == 0


class TestAStatePreconditionOutranksAMissingRule:
    """The same call reports the catalogue gap only while no earlier tier objects."""

    def test_the_rule_gap_is_reported_until_acceptance_makes_the_document_unreviewable(
        self,
    ):
        """With no rule for the student's band the acceptance fails on the catalogue;
        publishing the rule lets the same call through; and retiring the rule afterwards
        does not bring the catalogue code back, because the document is no longer
        reviewable at all.

        The PRD states: "Because a single request can violate several rules at once, the
        order in which checks run is part of the contract."

        The PRD states: "Checks are grouped into fourteen tiers and evaluated strictly
        in tier order; the first tier that produces a failure determines the response,
        and no later tier is consulted."

        The PRD states: "From `grade_level` the server derives `grade_band`, which is
        the key the entitlement catalogue is looked up by: `PRIMARY` when `grade_level`
        is 5 or below, `MIDDLE` when `grade_level` is 6, 7 or 8, and `HIGH` when
        `grade_level` is 9 or above."

        The PRD states: "Next the case's `entitlement_rule_id` is resolved by matching
        the student's `grade_band` and the case's `delivery_mode` against the
        `PUBLISHED` entitlement catalogue, failing with
        `ERR_NO_PUBLISHED_ENTITLEMENT_RULE` if no such rule exists."

        The PRD states: "Only a `NurseReviewer` may review a certification, and only one
        whose `status` is `SUBMITTED` — reviewing anything else is
        `ERR_CERT_NOT_REVIEWABLE`."

        The PRD states: "On acceptance the certification's `status` becomes `ACCEPTED`
        and its `is_current` becomes true, and any certification of the same case that
        previously held `is_current` true is moved to `SUPERSEDED` with its `is_current`
        set false; exactly one accepted certification per case is current at any
        moment."

        The PRD states: "Retirement does not disturb the `entitlement_rule_id` already
        recorded on existing cases — those cases continue to read the rule they resolved
        to — but no future resolution will select it."

        Design: Corner/validations/missing_published_rule_is_reported_until_a_higher_priority_state_rule_takes_over
        """
        bundle = _case_with_no_resolvable_rule()
        case_id = bundle["case"]["id"]
        certification_id = bundle["certification"]["id"]

        validate_error(
            api_client.review_certification(
                certification_id, {"decision": "ACCEPT"}, NR_HEADERS
            ),
            ApiErrorId.ERR_NO_PUBLISHED_ENTITLEMENT_RULE.value,
            422,
        )
        pending = [
            row
            for row in _all(api_client.list_certifications)
            if row["id"] == certification_id
        ]
        assert pending[0]["status"] == "SUBMITTED"
        assert read_case(case_id)["service_status"] == "PENDING_CERT_REVIEW"

        middle_rule = validate_success(
            api_client.create_entitlement_rule(
                create_entitlement_rule_payload(), PA_HEADERS
            ),
            201,
        )
        accepted = validate_success(
            api_client.review_certification(
                certification_id, {"decision": "ACCEPT"}, NR_HEADERS
            )
        )
        assert accepted["status"] == "ACCEPTED"
        assert accepted["is_current"] is True

        validate_success(
            api_client.retire_entitlement_rule(middle_rule["id"], PA_HEADERS)
        )
        superseding = validate_error(
            api_client.review_certification(
                certification_id, {"decision": "ACCEPT"}, NR_HEADERS
            ),
            ApiErrorId.ERR_CERT_NOT_REVIEWABLE.value,
            409,
        )
        assert (
            superseding["error_id"] != ApiErrorId.ERR_NO_PUBLISHED_ENTITLEMENT_RULE.value
        ), "the earlier tier answers and the catalogue tier is never consulted"

        case = read_case(case_id)
        assert case["service_status"] == "ELIGIBLE"
        assert case["weekly_entitled_minutes"] == 390
        assert case["entitlement_rule_id"] == middle_rule["id"], (
            "the resolved rule stays recorded even after it is retired"
        )


class TestTheUniquenessTierAnswersBeforeTheConsistencyTier:
    """One request breaks two rules; changing the role reveals the second."""

    def test_the_duplicate_primary_code_wins_until_the_role_makes_it_inapplicable(self):
        """A second primary row naming a teacher outside the student's band reports the
        duplicate rather than the mismatch, and only once the role is changed to support
        does the same teacher produce the band failure.

        The PRD states: "Checks are grouped into fourteen tiers and evaluated strictly
        in tier order; the first tier that produces a failure determines the response,
        and no later tier is consulted."

        The PRD states: "A case may hold only one primary staffing commitment: if
        another assignment of the same case has `role` `PRIMARY` and `status` either
        `PROPOSED` or `ACTIVE`, the request is rejected with
        `ERR_DUPLICATE_PRIMARY_ASSIGNMENT`."

        The PRD states: "When the caller names a `teacher_id` explicitly, the only
        cross-record check applied is that the named teacher's `grade_bands` array
        contains the student's `grade_band`; a mismatch is `ERR_TEACHER_BAND_MISMATCH`."

        The PRD states: "A new assignment starts with `status` `PROPOSED` and
        `weekly_committed_minutes` 0."

        The PRD states: "A teacher's own `committed_weekly_minutes` is the sum of
        `weekly_committed_minutes` across every assignment of that teacher whose
        `status` is `ACTIVE`, across every case, with no time window."

        Design: Corner/validations/duplicate_primary_rule_preempts_the_band_rule_on_the_same_request
        """
        bundle = _staffed_case_and_a_high_band_teacher()
        case_id = bundle["case"]["id"]
        high_band_teacher_id = bundle["high_band_teacher"]["id"]

        duplicate = validate_error(
            _propose(case_id, "PRIMARY", high_band_teacher_id),
            ApiErrorId.ERR_DUPLICATE_PRIMARY_ASSIGNMENT.value,
            409,
        )
        assert duplicate["error_id"] != ApiErrorId.ERR_TEACHER_BAND_MISMATCH.value, (
            "both rules are broken, and the earlier tier is the one that answers"
        )

        validate_error(
            _propose(case_id, "SUPPORT", high_band_teacher_id),
            ApiErrorId.ERR_TEACHER_BAND_MISMATCH.value,
            422,
        )

        rows = assignments_for_case(case_id)
        assert [row["id"] for row in rows] == [bundle["primary_assignment"]["id"]]
        assert rows[0]["status"] == "ACTIVE", "neither refused proposal persisted a row"
        assert read_teacher(high_band_teacher_id)["committed_weekly_minutes"] == 0


class TestOneClearanceEditReachesTwoUnrelatedOperations:
    """No assignment row changes, yet two downstream calls stop working."""

    def test_an_expired_clearance_blocks_acceptance_and_so_does_home_visit_ineligibility(
        self,
    ):
        """Expiring the support teacher's clearance blocks her acceptance, expiring the
        primary teacher's blocks scheduling against a row that is already active, and
        restoring the clearance while leaving in-home eligibility false still blocks the
        same visit under the same code.

        The PRD states: "A `ProgramAdministrator` may later revise a teacher's
        `safety_clearance_status`, `clearance_expires_on` and `home_visit_eligible`,
        which increments that teacher's `version` by one."

        The PRD states: "A teacher whose `safety_clearance_status` is `EXPIRED` may not
        accept at all, and that rejection carries `ERR_TEACHER_CLEARANCE_EXPIRED`."

        The PRD states: "The serving teacher must not have `safety_clearance_status`
        `EXPIRED`, and must have `home_visit_eligible` true whenever the session's
        `delivery_mode` is `IN_HOME`; either failure is
        `ERR_TEACHER_CLEARANCE_EXPIRED`."

        The PRD states: "Only assignments whose `status` is `ACTIVE` participate;
        `PROPOSED`, `DECLINED` and `RELEASED` assignments are excluded and always hold
        `weekly_committed_minutes` 0."

        The PRD states: "A teacher's own `committed_weekly_minutes` is the sum of
        `weekly_committed_minutes` across every assignment of that teacher whose
        `status` is `ACTIVE`, across every case, with no time window."

        Design: Corner/validations/expiring_a_teacher_clearance_invalidates_acceptance_and_scheduling_downstream
        """
        bundle = _case_in_service_with_a_pending_support_row()
        case_id = bundle["case"]["id"]
        primary_teacher_id = bundle["teacher"]["id"]
        support_teacher_id = bundle["support_teacher"]["id"]

        expired_support = validate_success(
            api_client.update_teacher_clearance(
                support_teacher_id,
                teacher_clearance_payload(
                    safety_clearance_status="EXPIRED",
                    clearance_expires_on="2026-08-31",
                ),
                PA_HEADERS,
            )
        )
        assert expired_support["safety_clearance_status"] == "EXPIRED"
        assert expired_support["committed_weekly_minutes"] == 0, (
            "the proposed row never contributed a minute to begin with"
        )

        validate_error(
            _accept(bundle["support_assignment"]["id"], support_teacher_id),
            ApiErrorId.ERR_TEACHER_CLEARANCE_EXPIRED.value,
            422,
        )
        assert read_assignment(bundle["support_assignment"]["id"])["status"] == "PROPOSED"

        validate_success(
            api_client.update_teacher_clearance(
                primary_teacher_id,
                teacher_clearance_payload(
                    safety_clearance_status="EXPIRED",
                    clearance_expires_on="2026-08-31",
                ),
                PA_HEADERS,
            )
        )
        validate_error(
            _book(case_id, bundle["primary_assignment"]["id"], **MORNING_VISIT),
            ApiErrorId.ERR_TEACHER_CLEARANCE_EXPIRED.value,
            422,
        )

        restored = validate_success(
            api_client.update_teacher_clearance(
                primary_teacher_id,
                teacher_clearance_payload(home_visit_eligible=False),
                PA_HEADERS,
            )
        )
        assert restored["safety_clearance_status"] == "CLEARED"
        assert restored["home_visit_eligible"] is False
        validate_error(
            _book(case_id, bundle["primary_assignment"]["id"], **MORNING_VISIT),
            ApiErrorId.ERR_TEACHER_CLEARANCE_EXPIRED.value,
            422,
        )

        assert sessions_for_case(case_id) == []
        assert read_teacher(primary_teacher_id)["committed_weekly_minutes"] == 390, (
            "not one assignment row moved through any of this"
        )
