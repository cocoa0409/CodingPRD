"""Where each lifecycle starts, which moves it accepts, and which it refuses.

Every record in this program is born in a declared posture and leaves it only
through a named transition. The refusals are as much of the contract as the
advances: repeating a move that has already happened, or skipping a step the
sequence requires, each answers with its own code, and the records around the
refusal are left exactly where they were.
"""

from test_helpers import (
    ApiErrorId,
    CASE_MANAGER_USER_ID,
    CLASSROOM_TEACHER,
    CM_HEADERS,
    MIDDLE_IN_HOME_RULE,
    NR_HEADERS,
    NURSE_REVIEWER_USER_ID,
    PA_HEADERS,
    PROGRAM_ADMINISTRATOR_USER_ID,
    SECOND_TEACHER,
    acknowledge_pacing_sync,
    add_support_assignment,
    api_client,
    assignments_for_case,
    close_case_payload,
    create_assignment_payload,
    create_case_payload,
    create_certification_payload,
    create_safety_review_payload,
    decide_extension_payload,
    decline_assignment_payload,
    deny_case_payload,
    dispute_pacing_sync_payload,
    ledger_entries_for_case,
    list_data,
    log_delivered_payload,
    log_safety_aborted_payload,
    log_session,
    log_session_delivered,
    log_student_unavailable_payload,
    log_teacher_cancelled_payload,
    make_classroom_teacher_headers,
    make_homebound_teacher_headers,
    open_case,
    open_extension_request,
    open_pacing_sync,
    open_sped_service_log,
    propose_assignment,
    publish_entitlement_rule,
    read_assignment,
    read_case,
    read_session,
    read_teacher,
    record_sped_delivery_payload,
    register_student,
    register_teacher,
    release_assignment_payload,
    request_extension_info_payload,
    resubmit_extension_payload,
    review_certification_payload,
    schedule_session,
    sessions_for_case,
    set_clock,
    setup_active_case,
    setup_case_with_primary_assignment,
    setup_catalogue,
    setup_eligible_case,
    sped_continuation_payload,
    submit_certification,
    validate_error,
    validate_success,
    verify_session,
)

CLOCK = "2026-09-01T00:00:00Z"

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
    "grade_level": 7,
    "special_ed_status": "IEP",
    "iep_service_minutes_weekly": 300,
}

REJECT_NOTE = "Diagnosis category unsupported by the attached note"
DECLINE_REASON = "Caseload already committed to another campus"
DISPUTE_NOTE = "Unit 3 was already assessed in class last week"


def _certifications_for_case(case_id: str) -> list:
    """Every certification of one case, selected client-side from the unfiltered
    list, because `limit` and `offset` are the only declared query parameters."""
    rows = list_data(api_client.list_certifications(PA_HEADERS, params={"limit": 100}))
    return [row for row in rows if row["case_id"] == case_id]


def _pacing_syncs_for_case(case_id: str) -> list:
    rows = list_data(api_client.list_pacing_syncs(PA_HEADERS, params={"limit": 100}))
    return [row for row in rows if row["case_id"] == case_id]


def _case_awaiting_nurse_review() -> dict:
    """A case in PENDING_CERT_REVIEW holding exactly one SUBMITTED certification,
    with the MIDDLE / IN_HOME rule published and the clock at 2026-09-01."""
    setup_catalogue(clock=CLOCK, rules=[MIDDLE_IN_HOME_RULE])
    student = register_student()
    case = open_case(student["id"], delivery_mode="IN_HOME")
    certification = submit_certification(case["id"], **CERT_WINDOW)
    return {
        "student": student,
        "case": read_case(case["id"]),
        "certification": certification,
    }


def _denied_case() -> dict:
    """A case denied straight out of PENDING_CERT_REVIEW, with no entitlement
    catalogue published at all."""
    set_clock(CLOCK)
    student = register_student()
    case = open_case(student["id"], delivery_mode="IN_HOME")
    certification = submit_certification(case["id"], **CERT_WINDOW)
    denied = api_client.deny_case(
        case["id"],
        deny_case_payload(deny_note="Physician certification withdrawn by the family"),
        PA_HEADERS,
    )
    return {
        "certification": certification,
        "case": validate_success(denied),
    }


def _active_case_with_two_scheduled_visits() -> dict:
    """An ACTIVE / ACCRUING case at 390 weekly minutes holding two 120-minute
    in-home visits on 2026-09-07, at 09:00-11:00 and 13:00-15:00, with the clock
    advanced to 2026-09-07T16:00:00Z so both may be logged."""
    bundle = setup_active_case(
        rules=[MIDDLE_IN_HOME_RULE],
        certification=dict(CERT_WINDOW),
        safety_review=dict(CLEARED_SAFETY_REVIEW),
    )
    bundle["session_a"] = schedule_session(
        bundle["case"]["id"],
        bundle["primary_assignment"]["id"],
        scheduled_start="2026-09-07T09:00:00Z",
        scheduled_end="2026-09-07T11:00:00Z",
        delivery_mode="IN_HOME",
        subject="MATH",
    )
    bundle["session_b"] = schedule_session(
        bundle["case"]["id"],
        bundle["primary_assignment"]["id"],
        scheduled_start="2026-09-07T13:00:00Z",
        scheduled_end="2026-09-07T15:00:00Z",
        delivery_mode="IN_HOME",
        subject="ELA",
    )
    set_clock("2026-09-07T16:00:00Z")
    return bundle


class TestEveryLifecycleStartsWhereItIsDeclaredTo:
    """Four records created back to back, four different opening postures."""

    def test_the_four_creation_paths_each_land_in_their_declared_initial_state(self):
        """A case opens on the DRAFT and NOT_REPORTED product of its two dimensions, a
        certification on SUBMITTED and not current, an assignment on PROPOSED with no
        minutes, and a safety review on DRAFT reading PENDING even though its score is
        already 25.

        The PRD states: "The new case starts with `service_status` `DRAFT` and
        `funding_status` `NOT_REPORTED`, and the server stamps `created_by_user_id` with
        the acting `X-User-ID` — a value that later governs who may verify this case's
        sessions."

        The PRD states: "A case that has never been activated — one whose
        `service_status` is `DRAFT`, `PENDING_CERT_REVIEW`, `ELIGIBLE` or `DENIED`, and
        whose `service_start_date` is therefore null — always holds
        `service_gap_minutes` 0."

        The PRD states: "Before any certification has been accepted the case's
        `diagnosis_category` is null."

        The PRD states: "A newly submitted certification starts with `status`
        `SUBMITTED`, `is_current` false, and `submitted_by_user_id` set to the acting
        `X-User-ID`."

        The PRD states: "A new assignment starts with `status` `PROPOSED` and
        `weekly_committed_minutes` 0."

        The PRD states: "The new review starts with `status` `DRAFT` and `clearance`
        `PENDING`."

        The PRD states: "While a review's `status` is `DRAFT` its `clearance` reads
        `PENDING` regardless of the computed score."

        The PRD states: "A teacher's own `committed_weekly_minutes` is the sum of
        `weekly_committed_minutes` across every assignment of that teacher whose
        `status` is `ACTIVE`, across every case, with no time window."

        Design: Corner/state_machines/newly_created_records_start_in_their_declared_initial_states
        """
        set_clock(CLOCK)
        publish_entitlement_rule(**MIDDLE_IN_HOME_RULE)
        student = register_student()
        teacher = register_teacher()

        case = validate_success(
            api_client.create_case(create_case_payload(student["id"]), CM_HEADERS), 201
        )
        assert case["service_status"] == "DRAFT"
        assert case["funding_status"] == "NOT_REPORTED", (
            "the two dimensions open independently of one another"
        )
        assert case["certification_count"] == 0
        assert case["extension_count"] == 0
        assert case["diagnosis_category"] is None
        assert case["service_gap_minutes"] == 0
        assert case.get("service_start_date") is None

        certification = validate_success(
            api_client.create_certification(
                create_certification_payload(case["id"], case["version"], **CERT_WINDOW),
                CM_HEADERS,
            ),
            201,
        )
        assert certification["status"] == "SUBMITTED"
        assert certification["is_current"] is False, (
            "a document only becomes current once a nurse accepts it"
        )
        assert certification["submitted_by_user_id"] == CASE_MANAGER_USER_ID

        assignment = validate_success(
            api_client.create_assignment(
                create_assignment_payload(case["id"], "PRIMARY", teacher["id"]),
                CM_HEADERS,
            ),
            201,
        )
        assert assignment["status"] == "PROPOSED"
        assert assignment["weekly_committed_minutes"] == 0
        assert assignment.get("accepted_at") is None
        assert assignment.get("released_at") is None

        review = validate_success(
            api_client.create_safety_review(
                create_safety_review_payload(
                    case["id"],
                    hazard_findings=["AGGRESSIVE_ANIMAL"],
                    escort_available=False,
                ),
                CM_HEADERS,
            ),
            201,
        )
        assert review["status"] == "DRAFT"
        assert review["clearance"] == "PENDING", (
            "the band is withheld until the review is finalized"
        )
        assert review["scoring_variant"] == "ONSITE_VERIFIED"
        assert review["risk_score"] == 25, "one aggressive-animal finding, undiscounted"

        assert read_teacher(teacher["id"])["committed_weekly_minutes"] == 0, (
            "a proposed assignment commits nothing"
        )


class TestTheCertificationReviewIsATakenOnceDecision:
    """One review per document, and one pending document per case."""

    def test_a_rejection_returns_the_case_to_draft_and_leaves_no_eligibility(self):
        """The certification reaches REJECTED and the case falls back to DRAFT with no
        accepted count, no absorbed diagnosis and no current document.

        The PRD states: "The certification moves from `SUBMITTED` to `REJECTED`, its
        `is_current` stays false, and the case's `service_status` returns from
        `PENDING_CERT_REVIEW` back to `DRAFT` so that a corrected certification can be
        submitted."

        The PRD states: "The review supplies a `decision` of either `ACCEPT` or `REJECT`
        and optionally a `review_note`, and in both cases the reviewer's `X-User-ID` is
        stamped as `reviewed_by_user_id`."

        The PRD states: "The case then advances from `PENDING_CERT_REVIEW` to `ELIGIBLE`
        and absorbs the accepted document: the case's `diagnosis_category`,
        `certified_start_date` and `certified_end_date` are copied from the accepted
        certification, and `certification_count` is recomputed as the number of that
        case's certifications whose `status` is `ACCEPTED`."

        The PRD states: "Before any certification has been accepted the case's
        `diagnosis_category` is null."

        Design: Corner/state_machines/rejecting_a_certification_returns_the_case_to_draft_and_locks_the_certification
        """
        bundle = _case_awaiting_nurse_review()
        case_id = bundle["case"]["id"]
        assert bundle["case"]["service_status"] == "PENDING_CERT_REVIEW"

        rejected = validate_success(
            api_client.review_certification(
                bundle["certification"]["id"],
                review_certification_payload("REJECT", review_note=REJECT_NOTE),
                NR_HEADERS,
            )
        )
        assert rejected["status"] == "REJECTED"
        assert rejected["reviewed_by_user_id"] == NURSE_REVIEWER_USER_ID
        assert rejected["review_note"] == REJECT_NOTE
        assert rejected["is_current"] is False

        case = read_case(case_id)
        assert case["service_status"] == "DRAFT", (
            "rejection is a revision cycle, not a terminal denial"
        )
        assert case["funding_status"] == "NOT_REPORTED", (
            "the funding dimension never moved in the first place"
        )
        assert case["certification_count"] == 0, "no certification reached ACCEPTED"
        assert case["diagnosis_category"] is None

        current = [row for row in _certifications_for_case(case_id) if row["is_current"]]
        assert current == [], "the rejection leaves no current document behind"

    def test_a_second_review_of_the_same_document_is_refused_either_way(self):
        """Both a repeat ACCEPT and a late REJECT answer ERR_CERT_NOT_REVIEWABLE, and the
        eligibility the first acceptance earned is untouched.

        The PRD states: "Only a `NurseReviewer` may review a certification, and only one
        whose `status` is `SUBMITTED` — reviewing anything else is
        `ERR_CERT_NOT_REVIEWABLE`."

        The PRD states: "On acceptance the certification's `status` becomes `ACCEPTED`
        and its `is_current` becomes true, and any certification of the same case that
        previously held `is_current` true is moved to `SUPERSEDED` with its `is_current`
        set false; exactly one accepted certification per case is current at any
        moment."

        Design: Corner/state_machines/reviewing_a_certification_a_second_time_is_rejected_as_not_reviewable
        """
        bundle = setup_eligible_case(
            clock=CLOCK, rules=[MIDDLE_IN_HOME_RULE], certification=dict(CERT_WINDOW)
        )
        case_id = bundle["case"]["id"]
        certification_id = bundle["certification"]["id"]
        assert bundle["case"]["service_status"] == "ELIGIBLE"
        assert bundle["case"]["weekly_entitled_minutes"] == 390
        version_before = bundle["case"]["version"]

        validate_error(
            api_client.review_certification(
                certification_id,
                review_certification_payload(
                    "ACCEPT", review_note="Duplicate acceptance attempt"
                ),
                NR_HEADERS,
            ),
            ApiErrorId.ERR_CERT_NOT_REVIEWABLE.value,
            409,
        )
        validate_error(
            api_client.review_certification(
                certification_id,
                review_certification_payload(
                    "REJECT", review_note="Late reversal attempt"
                ),
                NR_HEADERS,
            ),
            ApiErrorId.ERR_CERT_NOT_REVIEWABLE.value,
            409,
        )

        case = read_case(case_id)
        assert case["service_status"] == "ELIGIBLE"
        assert case["weekly_entitled_minutes"] == 390, (
            "no second acceptance re-resolved the entitlement"
        )
        assert case["certification_count"] == 1
        assert case["version"] == version_before, "two refusals mutate nothing"

        stored = validate_success(
            api_client.get_certification(certification_id, NR_HEADERS)
        )
        assert stored["status"] == "ACCEPTED"
        assert stored["is_current"] is True

    def test_a_second_submission_names_the_pending_document_not_the_case_state(self):
        """Two guards fail at once and the more specific one answers: the already-pending
        check runs first, so neither the case-state code nor the version code appears.

        The PRD states: "When a certification is submitted against a case, the check for
        an already-pending certification runs before the case from-state check, so a
        second submission while the case sits in `PENDING_CERT_REVIEW` surfaces as
        `ERR_CERT_ALREADY_PENDING` rather than as `ERR_INVALID_CASE_STATE`."

        The PRD states: "If `expected_case_version` does not equal the case's current
        `version`, the request is rejected with `ERR_STALE_CASE_VERSION` and HTTP 412,
        and nothing is written."

        Design: Corner/state_machines/submitting_a_second_certification_while_one_is_still_submitted_is_rejected
        """
        bundle = _case_awaiting_nurse_review()
        case = bundle["case"]

        error = validate_error(
            api_client.create_certification(
                create_certification_payload(
                    case["id"],
                    case["version"],
                    physician_npi="1234567899",
                    diagnosis_category="MEDICAL_CHRONIC",
                    certified_start_date="2026-09-07",
                    certified_end_date="2026-11-07",
                    expected_absence_days=45,
                    signature_date="2026-09-01",
                ),
                CM_HEADERS,
            ),
            ApiErrorId.ERR_CERT_ALREADY_PENDING.value,
            409,
        )
        assert error["error_id"] != ApiErrorId.ERR_INVALID_CASE_STATE.value, (
            "the from-state guard is also violated but loses the tie-break"
        )
        assert error["error_id"] != ApiErrorId.ERR_STALE_CASE_VERSION.value, (
            "the supplied version is the current one"
        )

        assert len(_certifications_for_case(case["id"])) == 1, (
            "the second document was never persisted"
        )
        after = read_case(case["id"])
        assert after["service_status"] == "PENDING_CERT_REVIEW"
        assert after["version"] == case["version"]


class TestADeniedCaseAcceptsNothingFurther:
    """One terminal state on the service dimension, four refused approaches."""

    def test_activate_close_deny_and_certify_all_answer_the_case_state_guard(self):
        """Every onward move against a DENIED case answers ERR_INVALID_CASE_STATE, and
        the funding dimension is frozen where it started.

        The PRD states: "`service_status` is the instructional lifecycle: `DRAFT`,
        `PENDING_CERT_REVIEW`, `ELIGIBLE`, `ACTIVE`, `EXTENSION_PENDING`,
        `TRANSITION_PLANNED`, `CLOSED`, or `DENIED`, beginning at `DRAFT` and
        terminating at `CLOSED` or `DENIED`."

        The PRD states: "Denial is permitted only while the case's `service_status` is
        `DRAFT` or `PENDING_CERT_REVIEW`; from either of those the case moves to
        `DENIED`, and from any other state the request is rejected with
        `ERR_INVALID_CASE_STATE`."

        The PRD states: "Denial sets `close_reason` to `DENIED_ELIGIBILITY` and, as a
        cascade, marks every certification of that case whose `status` is `SUBMITTED` as
        `REJECTED`."

        The PRD states: "Attempting to activate from any state other than `ELIGIBLE` is
        `ERR_INVALID_CASE_STATE`."

        The PRD states: "A `ProgramAdministrator` closes a case whose `service_status`
        is `ELIGIBLE`, `ACTIVE` or `EXTENSION_PENDING`, supplying a `close_reason` from
        `WITHDRAWN`, `CERT_EXPIRED`, `DENIED_ELIGIBILITY`, and `ADMIN_CLOSURE`;
        `RETURNED_TO_CAMPUS` is reserved for a completed transition plan and is not
        accepted here, and closing from any other service state is
        `ERR_INVALID_CASE_STATE`."

        The PRD states: "When a certification is submitted against a case, the check for
        an already-pending certification runs before the case from-state check, so a
        second submission while the case sits in `PENDING_CERT_REVIEW` surfaces as
        `ERR_CERT_ALREADY_PENDING` rather than as `ERR_INVALID_CASE_STATE`."

        Design: Corner/state_machines/a_denied_case_is_terminal_and_accepts_no_further_transitions
        """
        bundle = _denied_case()
        case = bundle["case"]
        case_id = case["id"]
        assert case["service_status"] == "DENIED"
        assert case["close_reason"] == "DENIED_ELIGIBILITY"
        denied_version = case["version"]

        cascaded = validate_success(
            api_client.get_certification(bundle["certification"]["id"], PA_HEADERS)
        )
        assert cascaded["status"] == "REJECTED", (
            "the denial swept the pending document with it"
        )

        validate_error(
            api_client.activate_case(case_id, PA_HEADERS),
            ApiErrorId.ERR_INVALID_CASE_STATE.value,
            409,
        )
        validate_error(
            api_client.close_case(
                case_id, close_case_payload(close_reason="ADMIN_CLOSURE"), PA_HEADERS
            ),
            ApiErrorId.ERR_INVALID_CASE_STATE.value,
            409,
        )
        validate_error(
            api_client.deny_case(
                case_id,
                deny_case_payload(deny_note="Second denial attempt"),
                PA_HEADERS,
            ),
            ApiErrorId.ERR_INVALID_CASE_STATE.value,
            409,
        )
        error = validate_error(
            api_client.create_certification(
                create_certification_payload(
                    case_id,
                    denied_version,
                    physician_npi="1234567891",
                    diagnosis_category="MEDICAL_CHRONIC",
                    certified_start_date="2026-09-07",
                    certified_end_date="2026-11-07",
                    expected_absence_days=45,
                    signature_date="2026-09-01",
                ),
                CM_HEADERS,
            ),
            ApiErrorId.ERR_INVALID_CASE_STATE.value,
            409,
        )
        assert error["error_id"] != ApiErrorId.ERR_CERT_ALREADY_PENDING.value, (
            "the cascade left nothing at SUBMITTED, so the from-state guard answers"
        )

        after = read_case(case_id)
        assert after["service_status"] == "DENIED"
        assert after["funding_status"] == "NOT_REPORTED", (
            "a denied case never begins accruing"
        )
        assert after.get("service_start_date") is None
        assert after["version"] == denied_version, "four refusals mutate nothing"


class TestTheAssignmentGuardsNameDifferentCodes:
    """Accept, decline and release each read a different from-state."""

    def test_a_declined_row_refuses_both_teacher_actions_while_release_names_its_own_code(
        self,
    ):
        """DECLINED refuses accept and decline alike, while releasing a still-PROPOSED row
        answers the not-active code instead — and the declining teacher accrued nothing.

        The PRD states: "Accepting anything not in `PROPOSED` is
        `ERR_ASSIGNMENT_NOT_PROPOSED`."

        The PRD states: "Declining is the mirror action, also restricted to the assigned
        teacher and also only from `PROPOSED`."

        The PRD states: "A decline supplies a free-text `decline_reason`, moves the
        assignment `PROPOSED → DECLINED`, and sets `weekly_committed_minutes` to 0."

        The PRD states: "Release is a `ProgramAdministrator` action against an `ACTIVE`
        assignment; releasing anything else is `ERR_ASSIGNMENT_NOT_ACTIVE`."

        The PRD states: "A teacher's own `committed_weekly_minutes` is the sum of
        `weekly_committed_minutes` across every assignment of that teacher whose
        `status` is `ACTIVE`, across every case, with no time window."

        Design: Corner/state_machines/accepting_a_declined_assignment_and_releasing_a_proposed_one_are_both_rejected
        """
        bundle = setup_case_with_primary_assignment(
            clock=CLOCK,
            rules=[MIDDLE_IN_HOME_RULE],
            certification=dict(CERT_WINDOW),
            accept=False,
        )
        case_id = bundle["case"]["id"]
        primary_id = bundle["primary_assignment"]["id"]
        support_teacher = register_teacher(
            **{**SECOND_TEACHER, "max_weekly_caseload_minutes": 600}
        )
        support_headers = make_homebound_teacher_headers(support_teacher["id"])
        support = propose_assignment(case_id, "SUPPORT", support_teacher["id"])

        declined = validate_success(
            api_client.decline_assignment(
                support["id"],
                decline_assignment_payload(decline_reason=DECLINE_REASON),
                support_headers,
            )
        )
        assert declined["status"] == "DECLINED"

        validate_error(
            api_client.accept_assignment(support["id"], support_headers),
            ApiErrorId.ERR_ASSIGNMENT_NOT_PROPOSED.value,
            409,
        )
        validate_error(
            api_client.decline_assignment(
                support["id"],
                decline_assignment_payload(decline_reason="Second decline attempt"),
                support_headers,
            ),
            ApiErrorId.ERR_ASSIGNMENT_NOT_PROPOSED.value,
            409,
        )
        error = validate_error(
            api_client.release_assignment(
                primary_id,
                release_assignment_payload(release_reason="CASELOAD_REBALANCE"),
                PA_HEADERS,
            ),
            ApiErrorId.ERR_ASSIGNMENT_NOT_ACTIVE.value,
            409,
        )
        assert error["error_id"] != ApiErrorId.ERR_ASSIGNMENT_NOT_PROPOSED.value, (
            "release reads a different from-state than accept and decline do"
        )

        stored_support = read_assignment(support["id"])
        assert stored_support["status"] == "DECLINED"
        assert stored_support["decline_reason"] == DECLINE_REASON
        assert stored_support["weekly_committed_minutes"] == 0
        assert stored_support.get("accepted_at") is None

        stored_primary = read_assignment(primary_id)
        assert stored_primary["status"] == "PROPOSED"
        assert stored_primary.get("released_at") is None

        teacher = read_teacher(support_teacher["id"])
        assert teacher["committed_weekly_minutes"] == 0
        assert teacher["over_cap"] is False

    def test_release_is_blocked_by_a_live_session_and_succeeds_once_it_is_cancelled(self):
        """The same release call fails while one visit is still on the books and succeeds
        the moment it is cancelled, moving the support teacher from 115 minutes to 0.

        The PRD states: "An assignment may not be released while it still has
        instructional work on the books: if any session referencing it has `status`
        `SCHEDULED`, the release is rejected with
        `ERR_ASSIGNMENT_HAS_SCHEDULED_SESSIONS`."

        The PRD states: "A `ProgramAdministrator` may cancel a `SCHEDULED` session,
        moving it `SCHEDULED → CANCELLED_ADMIN`; no ledger row is written and the case's
        `makeup_obligation_minutes` is unchanged."

        The PRD states: "A release records a `release_reason` from `CASE_CLOSED`,
        `MODE_CHANGE`, `CASELOAD_REBALANCE`, `CLEARANCE_LAPSED`, and `STAFF_LEAVE`,
        moves the assignment `ACTIVE → RELEASED`, stamps `released_at` with the clock
        instant, sets its `weekly_committed_minutes` to 0, recomputes the allocation
        across the case's remaining active assignments, and recomputes
        `committed_weekly_minutes` and `over_cap` for every teacher whose allocation
        changed."

        Design: Corner/state_machines/releasing_an_active_assignment_with_a_scheduled_session_is_blocked_until_it_is_cancelled
        """
        bundle = setup_active_case(
            clock=CLOCK,
            rules=[MIDDLE_IN_HOME_RULE],
            certification=dict(CERT_WINDOW),
            safety_review=dict(CLEARED_SAFETY_REVIEW),
        )
        add_support_assignment(bundle, teacher={"max_weekly_caseload_minutes": 600})
        support_id = bundle["support_assignment"]["id"]
        assert bundle["support_assignment"]["weekly_committed_minutes"] == 115
        assert read_teacher(bundle["support_teacher"]["id"])["committed_weekly_minutes"] == 115

        session = schedule_session(
            bundle["case"]["id"],
            support_id,
            scheduled_start="2026-09-08T09:00:00Z",
            scheduled_end="2026-09-08T10:00:00Z",
            delivery_mode="IN_HOME",
            subject="SCIENCE",
        )

        validate_error(
            api_client.release_assignment(
                support_id,
                release_assignment_payload(release_reason="STAFF_LEAVE"),
                PA_HEADERS,
            ),
            ApiErrorId.ERR_ASSIGNMENT_HAS_SCHEDULED_SESSIONS.value,
            409,
        )
        assert read_assignment(support_id)["status"] == "ACTIVE", (
            "the precondition is a live-child check, so the row keeps its state"
        )

        cancelled = validate_success(
            api_client.cancel_session(session["id"], PA_HEADERS)
        )
        assert cancelled["status"] == "CANCELLED_ADMIN"

        released = validate_success(
            api_client.release_assignment(
                support_id,
                release_assignment_payload(release_reason="STAFF_LEAVE"),
                PA_HEADERS,
            )
        )
        assert released["status"] == "RELEASED"
        assert released["release_reason"] == "STAFF_LEAVE"
        assert released.get("released_at") is not None
        assert released["weekly_committed_minutes"] == 0

        assert read_teacher(bundle["support_teacher"]["id"])["committed_weekly_minutes"] == 0
        assert (
            read_assignment(bundle["primary_assignment"]["id"])[
                "weekly_committed_minutes"
            ]
            == 390
        ), "the released support share returned to the primary row"


class TestTheSessionLifecycleWritesOnceAndRefusesTheRest:
    """Each outcome writes exactly one row; each repeat names its own code."""

    def test_both_non_delivery_outcomes_write_not_served_and_owe_the_whole_visit_back(
        self,
    ):
        """A teacher cancellation and a safety abort each append a HB_NOT_SERVED row worth
        nothing and each add their full scheduled span to the make-up obligation.

        The PRD states: "A `TEACHER_CANCELLED` outcome advances the session `SCHEDULED →
        TEACHER_CANCELLED`, sets `credited_minutes` to 0, and appends a ledger row with
        `attendance_code` `HB_NOT_SERVED` and `apportionment_minutes` 0."

        The PRD states: "A `SAFETY_ABORTED` outcome advances the session `SCHEDULED →
        SAFETY_ABORTED`, sets `credited_minutes` to 0, and likewise appends a
        `HB_NOT_SERVED` row with `apportionment_minutes` 0."

        The PRD states: "All three of these non-delivery outcomes add the session's
        `scheduled_minutes` to the case's `makeup_obligation_minutes`."

        The PRD states: "Every ledger row also records `recorded_by_user_id` as the
        `X-User-ID` of the actor whose action produced it, along with a `service_date`
        and `delivery_mode` copied from the session that produced it and the
        `session_id` and `case_id` identifying it."

        The PRD states: "A case that has never been activated — one whose
        `service_status` is `DRAFT`, `PENDING_CERT_REVIEW`, `ELIGIBLE` or `DENIED`, and
        whose `service_start_date` is therefore null — always holds
        `service_gap_minutes` 0."

        Design: Corner/state_machines/session_outcome_branches_write_the_declared_attendance_codes_and_makeup_obligation
        """
        bundle = _active_case_with_two_scheduled_visits()
        case_id = bundle["case"]["id"]
        teacher_id = bundle["teacher"]["id"]

        first = log_session(
            bundle["session_a"]["id"],
            teacher_id,
            log_teacher_cancelled_payload(outcome_reason="Teacher illness"),
        )
        assert first["status"] == "TEACHER_CANCELLED"
        assert first["credited_minutes"] == 0
        assert first["logged_by_user_id"] == teacher_id

        second = log_session(
            bundle["session_b"]["id"], teacher_id, log_safety_aborted_payload()
        )
        assert second["status"] == "SAFETY_ABORTED"
        assert second["credited_minutes"] == 0
        assert second["outcome_reason"] == "Unsecured dog in the entry hallway"

        entries = ledger_entries_for_case(case_id)
        assert len(entries) == 2, "one row per outcome, never a second and never none"
        for entry in entries:
            assert entry["attendance_code"] == "HB_NOT_SERVED"
            assert entry["apportionment_minutes"] == 0, (
                "a non-delivery row is zero, not negative and not absent"
            )
            assert entry["service_date"] == "2026-09-07"
            assert entry["delivery_mode"] == "IN_HOME"
            assert entry.get("reversal_of_entry_id") is None
            assert entry["recorded_by_user_id"] == teacher_id

        case = read_case(case_id)
        assert case["reported_apportionment_minutes"] == 0
        assert case["makeup_obligation_minutes"] == 240, "120 plus 120, both owed back"
        assert case["funding_status"] == "ACCRUING"
        assert case["service_gap_minutes"] == 0, (
            "no whole seven-day span has elapsed since the service start date"
        )

    def test_relogging_recancelling_and_reverifying_each_answer_their_own_code(self):
        """Three refusals with three different codes guard one delivered visit, and a
        fourth distinguishes an absent visit from an already-verified one.

        The PRD states: "Logging is permitted only from `SCHEDULED`, and logging against
        a session in any other status is `ERR_SESSION_ALREADY_LOGGED`."

        The PRD states: "Cancelling a session that is not `SCHEDULED` is
        `ERR_SESSION_ALREADY_LOGGED`."

        The PRD states: "Verification is permitted only against a session whose `status`
        is `DELIVERED` — anything else is `ERR_SESSION_NOT_DELIVERED` — and only once: a
        session that already carries `verified_at` is rejected with
        `ERR_SESSION_ALREADY_VERIFIED`."

        The PRD states: "A successful verification stamps `verified_at` with the clock
        instant and `verified_by_user_id` with the acting `X-User-ID`."

        Design: Corner/state_machines/relogging_recancelling_and_reverifying_a_session_are_all_rejected
        """
        bundle = _active_case_with_two_scheduled_visits()
        case_id = bundle["case"]["id"]
        teacher_id = bundle["teacher"]["id"]
        session_a_id = bundle["session_a"]["id"]
        session_b_id = bundle["session_b"]["id"]

        log_session_delivered(session_a_id, teacher_id, 120)
        log_session(
            session_b_id,
            teacher_id,
            log_student_unavailable_payload("MEDICAL", outcome_reason="Fever"),
        )
        verified = verify_session(session_a_id)
        verified_at = verified["verified_at"]

        validate_error(
            api_client.log_session(
                session_a_id,
                log_delivered_payload(90),
                make_homebound_teacher_headers(teacher_id),
            ),
            ApiErrorId.ERR_SESSION_ALREADY_LOGGED.value,
            409,
        )
        validate_error(
            api_client.cancel_session(session_a_id, PA_HEADERS),
            ApiErrorId.ERR_SESSION_ALREADY_LOGGED.value,
            409,
        )
        error = validate_error(
            api_client.verify_session(session_a_id, PA_HEADERS),
            ApiErrorId.ERR_SESSION_ALREADY_VERIFIED.value,
            409,
        )
        assert error["error_id"] != ApiErrorId.ERR_SESSION_NOT_DELIVERED.value, (
            "the status is still DELIVERED, so only the once-only rule can bite"
        )
        validate_error(
            api_client.verify_session(session_b_id, PA_HEADERS),
            ApiErrorId.ERR_SESSION_NOT_DELIVERED.value,
            409,
        )

        after = read_session(session_a_id)
        assert after["status"] == "DELIVERED"
        assert after["actual_minutes"] == 120, "the refused re-log wrote no new figure"
        assert after["credited_minutes"] == 120
        assert after["verified_by_user_id"] == PROGRAM_ADMINISTRATOR_USER_ID
        assert after["verified_at"] == verified_at

        assert len(ledger_entries_for_case(case_id)) == 2, (
            "no refusal appended a duplicate row"
        )


class TestTheCoordinationAndContinuationLoopsAreDirected:
    """Both machines allow a return path and forbid standing still."""

    def test_a_disputed_row_can_still_be_acknowledged_but_not_twice(self):
        """DISPUTED is not terminal — the teacher of record may still acknowledge, keeping
        the dispute note — after which neither a second acknowledge nor a dispute is
        accepted.

        The PRD states: "A new row starts with `ack_status` `PENDING`, and its creation
        recomputes the acknowledgement counters of any open transition plan on the case,
        which may pull a `READY` plan back to `CLASSROOM_COORD_PENDING`."

        The PRD states: "The same teacher may instead dispute, but only from `PENDING`,
        recording a required `dispute_note` and moving `ack_status` `PENDING →
        DISPUTED`; that too recomputes the counters and may pull a `READY` plan back to
        `CLASSROOM_COORD_PENDING`."

        The PRD states: "A `ClassroomTeacher` whose `X-User-ID` equals the row's
        `classroom_teacher_id` may acknowledge the pacing target and accommodation,
        moving `ack_status` to `ACKED` from either `PENDING` or `DISPUTED`, and stamping
        `acked_at` with the clock instant; that recomputes the plan counters and may
        advance a plan from `CLASSROOM_COORD_PENDING` to `READY`."

        The PRD states: "Acknowledging a row that is already `ACKED`, or disputing a row
        that is not `PENDING`, is rejected with `ERR_PACING_ALREADY_ACKED`."

        Design: Corner/state_machines/pacing_sync_cycles_from_disputed_back_to_acked_and_refuses_a_second_acknowledge
        """
        bundle = setup_active_case(
            clock=CLOCK,
            rules=[MIDDLE_IN_HOME_RULE],
            certification=dict(CERT_WINDOW),
            safety_review=dict(CLEARED_SAFETY_REVIEW),
        )
        case_id = bundle["case"]["id"]
        classroom_teacher = register_teacher(**CLASSROOM_TEACHER)
        classroom_headers = make_classroom_teacher_headers(classroom_teacher["id"])
        sync = open_pacing_sync(
            case_id,
            classroom_teacher["id"],
            subject="MATH",
            pacing_target_unit="Unit 3 Linear Equations",
            assessment_accommodation="EXTENDED_TIME",
        )
        assert sync["ack_status"] == "PENDING"

        disputed = validate_success(
            api_client.dispute_pacing_sync(
                sync["id"],
                dispute_pacing_sync_payload(dispute_note=DISPUTE_NOTE),
                classroom_headers,
            )
        )
        assert disputed["ack_status"] == "DISPUTED"
        assert disputed["dispute_note"] == DISPUTE_NOTE
        assert disputed.get("acked_at") is None

        acked = acknowledge_pacing_sync(sync["id"], classroom_teacher["id"])
        assert acked["ack_status"] == "ACKED", "DISPUTED is a way station, not an end"
        assert acked.get("acked_at") is not None
        assert acked["dispute_note"] == DISPUTE_NOTE, (
            "the acknowledgement does not erase what was disputed"
        )

        validate_error(
            api_client.acknowledge_pacing_sync(sync["id"], classroom_headers),
            ApiErrorId.ERR_PACING_ALREADY_ACKED.value,
            409,
        )
        validate_error(
            api_client.dispute_pacing_sync(
                sync["id"],
                dispute_pacing_sync_payload(dispute_note="Second dispute attempt"),
                classroom_headers,
            ),
            ApiErrorId.ERR_PACING_ALREADY_ACKED.value,
            409,
        )

        acked_rows = [
            row for row in _pacing_syncs_for_case(case_id) if row["ack_status"] == "ACKED"
        ]
        assert [row["id"] for row in acked_rows] == [sync["id"]]

    def test_the_continuation_walk_succeeds_while_every_self_transition_is_refused(self):
        """CONTINUED to CONTINUED and MODIFIED_VIRTUAL to itself are both refused, the
        declared three-hop walk succeeds, and a suspended log accepts no delivery.

        The PRD states: "A new log starts with `continuation_status` `CONTINUED` and
        `delivered_cumulative_minutes` 0."

        The PRD states: "The continuation posture itself is a `CaseManager` decision,
        supplied as a `to_status` together with a free-text `continuation_reason`
        recorded on the change."

        The PRD states: "Four transitions are declared and no self-transition is
        permitted; a requested transition that is not declared for the log's current
        `continuation_status` is rejected with `ERR_SPED_CONTINUATION_INVALID`."

        The PRD states: "From `CONTINUED` the log may move to `MODIFIED_VIRTUAL`, which
        records the reason and recomputes `compensatory_minutes_owed`."

        The PRD states: "From either `CONTINUED` or `MODIFIED_VIRTUAL` the log may move
        to `SUSPENDED_PENDING_IEP`, which freezes `delivered_cumulative_minutes` — while
        a log is suspended, any attempt to record delivered minutes against it is
        rejected with `ERR_SPED_SERVICE_SUSPENDED` — while `compensatory_minutes_owed`
        keeps accruing with each elapsed week, so the suspension window accumulates as a
        debt."

        The PRD states: "From either `MODIFIED_VIRTUAL` or `SUSPENDED_PENDING_IEP` the
        log may return to `CONTINUED`, which recomputes `compensatory_minutes_owed`
        against the elapsed service weeks so that the suspension window is owed back in
        full."

        The PRD states: "Recording adds `minutes` to `delivered_cumulative_minutes` and
        sets `last_service_date` to the supplied `service_date`."

        Design: Corner/state_machines/sped_continuation_self_transitions_are_rejected_while_declared_moves_succeed
        """
        bundle = setup_active_case(
            clock=CLOCK,
            rules=[MIDDLE_IN_HOME_RULE],
            student=dict(IEP_STUDENT),
            certification=dict(CERT_WINDOW),
            safety_review=dict(CLEARED_SAFETY_REVIEW),
        )
        log = open_sped_service_log(
            bundle["case"]["id"], service_type="SPEECH", required_weekly_minutes=60
        )
        log_id = log["id"]
        assert log["continuation_status"] == "CONTINUED"
        assert log["delivered_cumulative_minutes"] == 0

        def change(to_status: str, reason: str):
            return api_client.change_sped_continuation(
                log_id,
                sped_continuation_payload(to_status, continuation_reason=reason),
                CM_HEADERS,
            )

        validate_error(
            change("CONTINUED", "No change"),
            ApiErrorId.ERR_SPED_CONTINUATION_INVALID.value,
            409,
        )

        virtual = validate_success(
            change("MODIFIED_VIRTUAL", "Therapist delivering via teletherapy")
        )
        assert virtual["continuation_status"] == "MODIFIED_VIRTUAL"
        assert virtual["continuation_reason"] == "Therapist delivering via teletherapy"

        validate_error(
            change("MODIFIED_VIRTUAL", "Repeat of the same status"),
            ApiErrorId.ERR_SPED_CONTINUATION_INVALID.value,
            409,
        )

        suspended = validate_success(
            change("SUSPENDED_PENDING_IEP", "Awaiting IEP amendment meeting")
        )
        assert suspended["continuation_status"] == "SUSPENDED_PENDING_IEP"

        validate_error(
            api_client.record_sped_delivery(
                log_id,
                record_sped_delivery_payload(minutes=30, service_date="2026-09-09"),
                make_homebound_teacher_headers(bundle["teacher"]["id"]),
            ),
            ApiErrorId.ERR_SPED_SERVICE_SUSPENDED.value,
            422,
        )

        resumed = validate_success(change("CONTINUED", "IEP amendment signed"))
        assert resumed["continuation_status"] == "CONTINUED"
        assert resumed["continuation_reason"] == "IEP amendment signed"
        assert resumed["delivered_cumulative_minutes"] == 0, (
            "the refused delivery added nothing"
        )
        assert resumed.get("last_service_date") is None


class TestTheExtensionReviewSequenceCannotBeSkipped:
    """Three later actions all wait on a review that has not begun."""

    def test_decide_request_info_and_resubmit_are_all_refused_from_submitted(self):
        """Each of the three onward actions needs a different from-state, so all three
        answer ERR_EXTENSION_STATE_INVALID while the request is still SUBMITTED.

        The PRD states: "A new request starts with `status` `SUBMITTED`,
        `resubmit_count` 0, and `submitted_by_user_id` set to the acting `X-User-ID`."

        The PRD states: "A `CaseManager` requests one against an `ACTIVE` case, which
        advances `service_status` `ACTIVE → EXTENSION_PENDING` and increments the case's
        `version` by one."

        The PRD states: "Any of these four actions attempted from the wrong posture —
        start-review from anything but `SUBMITTED`, request-info or decide from anything
        but `UNDER_REVIEW`, resubmit from anything but `INFO_REQUESTED` — is rejected
        with `ERR_EXTENSION_STATE_INVALID`."

        The PRD states: "The case's `extension_count` — the number of that case's
        extension requests whose `status` is `APPROVED` — must be less than 2, and a
        third attempt is rejected with `ERR_EXTENSION_LIMIT_REACHED`."

        Design: Corner/state_machines/deciding_an_extension_request_before_review_starts_is_rejected
        """
        bundle = setup_active_case(
            clock=CLOCK,
            rules=[MIDDLE_IN_HOME_RULE],
            certification=dict(CERT_WINDOW),
            safety_review=dict(CLEARED_SAFETY_REVIEW),
        )
        case_id = bundle["case"]["id"]
        request = open_extension_request(
            case_id,
            bundle["certification"]["id"],
            requested_additional_days=15,
            justification="Recovery slower than projected",
        )
        request_id = request["id"]
        assert request["status"] == "SUBMITTED"
        assert request["resubmit_count"] == 0
        assert read_case(case_id)["service_status"] == "EXTENSION_PENDING"

        validate_error(
            api_client.decide_extension_request(
                request_id,
                decide_extension_payload("APPROVED", decision_note="Skipping review"),
                PA_HEADERS,
            ),
            ApiErrorId.ERR_EXTENSION_STATE_INVALID.value,
            409,
        )
        validate_error(
            api_client.request_extension_info(
                request_id,
                request_extension_info_payload(
                    info_note="Need an updated physician note"
                ),
                PA_HEADERS,
            ),
            ApiErrorId.ERR_EXTENSION_STATE_INVALID.value,
            409,
        )
        validate_error(
            api_client.resubmit_extension_request(
                request_id,
                resubmit_extension_payload(bundle["certification"]["id"]),
                CM_HEADERS,
            ),
            ApiErrorId.ERR_EXTENSION_STATE_INVALID.value,
            409,
        )

        after = validate_success(
            api_client.get_extension_request(request_id, PA_HEADERS)
        )
        assert after["status"] == "SUBMITTED"
        assert after["resubmit_count"] == 0
        assert after.get("decided_by_user_id") is None
        assert after.get("info_note") is None

        case = read_case(case_id)
        assert case["service_status"] == "EXTENSION_PENDING"
        assert case["extension_count"] == 0, "nothing reached APPROVED"
        assert case["certified_end_date"] == "2026-10-07", (
            "the refused decision advanced no window"
        )
        assert case["weekly_entitled_minutes"] == 390


class TestClosureReachesEveryOpenChild:
    """One close call settles four child machines and leaves history alone."""

    def test_closing_the_case_cancels_releases_and_denies_without_rewriting_history(self):
        """The scheduled visit is cancelled, the active assignment released to zero, the
        open extension request denied by the cascade rather than by an operator, and the
        delivered visit and its ledger row are left exactly as they were.

        The PRD states: "A `ProgramAdministrator` closes a case whose `service_status`
        is `ELIGIBLE`, `ACTIVE` or `EXTENSION_PENDING`, supplying a `close_reason` from
        `WITHDRAWN`, `CERT_EXPIRED`, `DENIED_ELIGIBILITY`, and `ADMIN_CLOSURE`;
        `RETURNED_TO_CAMPUS` is reserved for a completed transition plan and is not
        accepted here, and closing from any other service state is
        `ERR_INVALID_CASE_STATE`."

        The PRD states: "Closure moves the case to `CLOSED` and cascades: every
        assignment of the case whose `status` is `ACTIVE` is `RELEASED` with
        `release_reason` `CASE_CLOSED` and `weekly_committed_minutes` 0, with
        `committed_weekly_minutes` recomputed for each released teacher; every session
        of the case whose `status` is `SCHEDULED` becomes `CANCELLED_ADMIN`; every plan
        of the case whose `status` is `DRAFT`, `CLASSROOM_COORD_PENDING` or `READY`
        becomes `SUPERSEDED`, after which it neither blocks nor enables any case
        transition; and every extension request of the case whose `status` is
        `SUBMITTED`, `UNDER_REVIEW` or `INFO_REQUESTED` becomes `DENIED` with its
        `decision_note` recorded as "case closed"."

        The PRD states: "Attendance ledger rows are append-only: once written they are
        never updated, corrected in place, or deleted."

        The PRD states: "A `CaseManager` requests one against an `ACTIVE` case, which
        advances `service_status` `ACTIVE → EXTENSION_PENDING` and increments the case's
        `version` by one."

        Design: Corner/state_machines/closing_a_case_cascades_down_to_sessions_assignments_and_extension_requests
        """
        bundle = setup_active_case(
            clock=CLOCK,
            rules=[MIDDLE_IN_HOME_RULE],
            certification=dict(CERT_WINDOW),
            safety_review=dict(CLEARED_SAFETY_REVIEW),
        )
        case_id = bundle["case"]["id"]
        teacher_id = bundle["teacher"]["id"]
        delivered = schedule_session(
            case_id,
            bundle["primary_assignment"]["id"],
            scheduled_start="2026-09-07T09:00:00Z",
            scheduled_end="2026-09-07T11:00:00Z",
            delivery_mode="IN_HOME",
            subject="MATH",
        )
        future = schedule_session(
            case_id,
            bundle["primary_assignment"]["id"],
            scheduled_start="2026-09-09T09:00:00Z",
            scheduled_end="2026-09-09T11:00:00Z",
            delivery_mode="IN_HOME",
            subject="ELA",
        )
        set_clock("2026-09-07T16:00:00Z")
        log_session_delivered(delivered["id"], teacher_id, 120)

        version_before_extension = read_case(case_id)["version"]
        request = open_extension_request(
            case_id,
            bundle["certification"]["id"],
            requested_additional_days=15,
            justification="Recovery slower than projected",
        )

        closed = validate_success(
            api_client.close_case(
                case_id, close_case_payload(close_reason="WITHDRAWN"), PA_HEADERS
            )
        )
        assert closed["service_status"] == "CLOSED"
        assert closed["close_reason"] == "WITHDRAWN"
        assert closed["version"] == version_before_extension + 2, (
            "the extension request moved the case once and the closure once"
        )

        cancelled = [
            row
            for row in sessions_for_case(case_id)
            if row["status"] == "CANCELLED_ADMIN"
        ]
        assert [row["id"] for row in cancelled] == [future["id"]]

        rows = assignments_for_case(case_id)
        assert len(rows) == 1
        assert rows[0]["status"] == "RELEASED"
        assert rows[0]["release_reason"] == "CASE_CLOSED"
        assert rows[0]["weekly_committed_minutes"] == 0
        assert rows[0].get("released_at") is not None

        teacher = read_teacher(teacher_id)
        assert teacher["committed_weekly_minutes"] == 0
        assert teacher["over_cap"] is False

        extension = validate_success(
            api_client.get_extension_request(request["id"], PA_HEADERS)
        )
        assert extension["status"] == "DENIED"
        assert extension.get("decided_by_user_id") is None, (
            "the cascade denied it, so no operator is recorded"
        )

        entries = ledger_entries_for_case(case_id)
        assert len(entries) == 1
        assert entries[0]["attendance_code"] == "HB_PRESENT"
        assert entries[0]["apportionment_minutes"] == 120, (
            "closing the case never rewrites delivered history"
        )

        still_delivered = read_session(delivered["id"])
        assert still_delivered["status"] == "DELIVERED"
        assert still_delivered["credited_minutes"] == 120
