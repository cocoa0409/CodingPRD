"""Who may act, on which row, and whether wearing a second hat helps.

The five roles are not a hierarchy: the administrator cannot review a
certification and cannot open a case, and the two teacher roles are peers rather
than substitutes. Holding the right role is only the second of several gates —
for the two teacher roles the row itself must be theirs, and for two operations
the acting user must not be the one who authored what is being approved. Every
one of those refusals is decided before the request's state or payload is ever
consulted.
"""

from test_helpers import (
    ApiErrorId,
    CASE_MANAGER_USER_ID,
    CLASSROOM_TEACHER,
    CM2_HEADERS,
    CM_HEADERS,
    DEFAULT_TEACHER,
    MIDDLE_IN_HOME_RULE,
    NR_HEADERS,
    PA_HEADERS,
    PROGRAM_ADMINISTRATOR_USER_ID,
    SECOND_CASE_MANAGER_USER_ID,
    SECOND_TEACHER,
    SHARED_OPERATOR_USER_ID,
    accept_assignment,
    activate_case,
    api_client,
    create_assignment_payload,
    create_case_payload,
    create_certification_payload,
    create_extension_request_payload,
    create_sped_service_log_payload,
    decide_extension_payload,
    dispute_pacing_sync_payload,
    finalize_safety_review,
    is_iso8601_timestamp,
    list_data,
    log_delivered_payload,
    log_session_delivered,
    make_case_manager_headers,
    make_classroom_teacher_headers,
    make_headers,
    make_homebound_teacher_headers,
    make_program_administrator_headers,
    open_case,
    open_pacing_sync,
    publish_entitlement_rule,
    read_assignment,
    read_case,
    read_session,
    read_teacher,
    record_safety_review,
    record_sped_delivery_payload,
    register_student,
    register_teacher,
    review_certification,
    review_certification_payload,
    schedule_session,
    set_clock,
    submit_certification,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK = "2026-09-01T00:00:00Z"
ACTIVATION_CLOCK = "2026-09-07T08:00:00Z"
SERVICE_CLOCK = "2026-09-08T12:00:00Z"

CERT_WINDOW = {
    "expected_absence_days": 30,
    "certified_start_date": "2026-09-07",
    "certified_end_date": "2026-10-07",
    "signature_date": "2026-09-01",
}

CLEARED_SAFETY_REVIEW = {
    "evidence_source": "ONSITE_WALKTHROUGH",
    "review_date": "2026-09-02",
    "hazard_findings": ["UNLIT_ACCESS"],
    "escort_available": False,
}

MORNING_VISIT = {
    "scheduled_start": "2026-09-08T09:00:00Z",
    "scheduled_end": "2026-09-08T10:00:00Z",
    "delivery_mode": "IN_HOME",
    "subject": "MATH",
}

UNKNOWN_ROLE_HEADERS = make_headers("au-001", "DistrictAuditor")


def _all(list_call, headers=None) -> list:
    """Every row of one collection, unfiltered — the only declared query parameters
    are the page window, so any narrowing happens here in the test."""
    return list_data(list_call(headers or PA_HEADERS, params={"limit": 100}))


def _configured_district() -> dict:
    """The administrator's own work: clock, catalogue, student and staff roster."""
    set_clock(CLOCK)
    return {
        "rule": publish_entitlement_rule(**MIDDLE_IN_HOME_RULE),
        "student": register_student(),
        "primary_teacher": register_teacher(**DEFAULT_TEACHER),
        "classroom_teacher": register_teacher(**CLASSROOM_TEACHER),
    }


class TestEveryDeclaredRoleIsNeededToCarryOneCase:
    """Five roles, one case, and two operations that answer to either of two."""

    def test_one_case_needs_all_five_roles_and_the_two_shared_verbs_take_both(self):
        """No single role can carry a case from referral to a verified, reconcilable
        visit: the administrator configures and activates, the case manager documents and
        schedules, only the nurse reviewer can accept the certification, only the assigned
        teacher can accept and log, and only the campus teacher of record can acknowledge
        the pacing target. The two shared operations then answer to both of the roles
        declared for them.

        The PRD states: "Five roles exist and their spellings are exact:
        `ProgramAdministrator`, `CaseManager`, `NurseReviewer`, `HomeboundTeacher`, and
        `ClassroomTeacher`."

        The PRD states: "The `ProgramAdministrator` owns district configuration,
        activation, funding decisions, voiding and final decisions."

        The PRD states: "The `CaseManager` opens cases, submits documentation, staffs
        and schedules, coordinates with campuses and plans the return to the building."

        The PRD states: "The `NurseReviewer` is the only role permitted to accept or
        reject a physician certification."

        The PRD states: "The `HomeboundTeacher` accepts or declines assignments and logs
        session outcomes."

        The PRD states: "The `ClassroomTeacher` acknowledges or disputes curriculum
        pacing and assessment accommodations."

        The PRD states: "A `ClassroomTeacher` whose `X-User-ID` equals the row's
        `classroom_teacher_id` may acknowledge the pacing target and accommodation,
        moving `ack_status` to `ACKED` from either `PENDING` or `DISPUTED`, and stamping
        `acked_at` with the clock instant; that recomputes the plan counters and may
        advance a plan from `CLASSROOM_COORD_PENDING` to `READY`."

        The PRD states: "Verification is the second-person control on delivered
        instruction, and it is shared between `ProgramAdministrator` and `CaseManager`."

        The PRD states: "A successful verification stamps `verified_at` with the clock
        instant and `verified_by_user_id` with the acting `X-User-ID`."

        The PRD states: "Delivered related-service minutes are recorded by either a
        `CaseManager` or a `HomeboundTeacher`, supplying the `minutes` delivered and the
        `service_date` on which they were delivered."

        The PRD states: "Recording adds `minutes` to `delivered_cumulative_minutes` and
        sets `last_service_date` to the supplied `service_date`."

        The PRD states: "Count the weeks elapsed as the number of whole seven-day spans
        between the case's `service_start_date` and the clock date, taking the floor,
        and treating the count as 0 when `service_start_date` is null."

        The PRD states: "Multiply that count by the log's `required_weekly_minutes`,
        subtract `delivered_cumulative_minutes`, and floor the difference at 0."

        Design: Corner/rbac/all_five_roles_exercise_their_own_exclusive_and_shared_operations
        """
        district = _configured_district()
        case = open_case(district["student"]["id"])
        certification = submit_certification(case["id"], **CERT_WINDOW)

        accepted = validate_success(
            api_client.review_certification(
                certification["id"],
                review_certification_payload("ACCEPT"),
                NR_HEADERS,
            )
        )
        assert accepted["status"] == "ACCEPTED", (
            "the nurse reviewer is the only source of this transition"
        )

        review = record_safety_review(case["id"], **CLEARED_SAFETY_REVIEW)
        assert finalize_safety_review(review["id"])["status"] == "FINALIZED"
        assignment = validate_success(
            api_client.create_assignment(
                create_assignment_payload(
                    case["id"], "PRIMARY", district["primary_teacher"]["id"]
                ),
                CM_HEADERS,
            ),
            201,
        )

        accepted_assignment = validate_success(
            api_client.accept_assignment(
                assignment["id"],
                make_homebound_teacher_headers(district["primary_teacher"]["id"]),
            )
        )
        assert accepted_assignment["status"] == "ACTIVE"
        assert accepted_assignment["weekly_committed_minutes"] == 390

        set_clock(ACTIVATION_CLOCK)
        activated = validate_success(api_client.activate_case(case["id"], PA_HEADERS))
        assert activated["service_status"] == "ACTIVE"
        assert activated["funding_status"] == "ACCRUING"
        assert activated["service_start_date"] == "2026-09-07"

        sync = open_pacing_sync(
            case["id"],
            district["classroom_teacher"]["id"],
            subject="MATH",
            pacing_target_unit="Unit 3 Linear Equations",
            assessment_accommodation="EXTENDED_TIME",
        )
        acknowledged = validate_success(
            api_client.acknowledge_pacing_sync(
                sync["id"],
                make_classroom_teacher_headers(district["classroom_teacher"]["id"]),
            )
        )
        assert acknowledged["ack_status"] == "ACKED"
        assert is_iso8601_timestamp(acknowledged["acked_at"])
        assert acknowledged["acked_at"].startswith("2026-09-07T08:00:00")

        sped_log = validate_success(
            api_client.create_sped_service_log(
                create_sped_service_log_payload(
                    case["id"], service_type="SPEECH", required_weekly_minutes=60
                ),
                CM_HEADERS,
            ),
            201,
        )
        session = schedule_session(case["id"], assignment["id"], **MORNING_VISIT)

        set_clock(SERVICE_CLOCK)
        delivered = validate_success(
            api_client.log_session(
                session["id"],
                log_delivered_payload(60),
                make_homebound_teacher_headers(district["primary_teacher"]["id"]),
            )
        )
        assert delivered["status"] == "DELIVERED"
        assert delivered["credited_minutes"] == 60

        verified = validate_success(
            api_client.verify_session(session["id"], CM2_HEADERS)
        )
        assert verified["verified_by_user_id"] == SECOND_CASE_MANAGER_USER_ID, (
            "a second case manager is a different user from the case's creator"
        )

        for headers in (
            make_homebound_teacher_headers(district["primary_teacher"]["id"]),
            CM_HEADERS,
        ):
            validate_success(
                api_client.record_sped_delivery(
                    sped_log["id"],
                    record_sped_delivery_payload(30, "2026-09-08"),
                    headers,
                )
            )
        final_log = validate_success(
            api_client.get_sped_service_log(sped_log["id"], PA_HEADERS)
        )
        assert final_log["delivered_cumulative_minutes"] == 60, (
            "both allowed roles contributed thirty minutes each"
        )
        assert final_log["last_service_date"] == "2026-09-08"
        assert final_log["compensatory_minutes_owed"] == 0, (
            "one day of service is no whole seven-day span, so nothing is owed yet"
        )


class TestActingOutsideTheDeclaredRoleListIsDeniedFirst:
    """Six wrong-role writes, one wrong-role read, and one unknown role."""

    def test_authorization_answers_before_state_and_leaves_everything_untouched(self):
        """Each of six operations is attempted from a role that is not on its list, and
        every one is refused on authorization even where the request would also have
        failed on state or on a business rule — including an administrator trying to
        review a certification, which the role model never permits. A read outside a
        role's declared list is refused the same way, an undeclared role name is refused
        one tier earlier, and the role's own declared read still works afterwards.

        The PRD states: "Every request must carry two headers: `X-User-ID`, identifying
        the acting user, and `X-User-Role`, declaring the capacity in which that user
        acts."

        The PRD states: "A request that omits either header, or that supplies an
        `X-User-Role` value outside those five, is rejected with `ERR_UNAUTHENTICATED`."

        The PRD states: "A request whose role is well-formed but is not among the roles
        authorized for the called endpoint (see the table in §4) is rejected with
        `ERR_UNAUTHORIZED`."

        The PRD states: "The `NurseReviewer` is the only role permitted to accept or
        reject a physician certification."

        The PRD states: "Checks are grouped into fourteen tiers and evaluated strictly
        in tier order; the first tier that produces a failure determines the response,
        and no later tier is consulted."

        The PRD states: "**Authorization.** The acting role appears in the called
        endpoint's authorized-role list — otherwise `ERR_UNAUTHORIZED` (403)."

        Design: Corner/rbac/acting_outside_the_declared_role_list_is_denied_before_anything_else
        """
        district = _configured_district()
        support_teacher = register_teacher(**SECOND_TEACHER)
        student_id = district["student"]["id"]
        case = open_case(student_id)
        case_id = case["id"]
        certification = submit_certification(case_id, **CERT_WINDOW)
        review_certification(certification["id"], "ACCEPT")
        finalize_safety_review(
            record_safety_review(case_id, **CLEARED_SAFETY_REVIEW)["id"]
        )
        primary_assignment = validate_success(
            api_client.create_assignment(
                create_assignment_payload(
                    case_id, "PRIMARY", district["primary_teacher"]["id"]
                ),
                CM_HEADERS,
            ),
            201,
        )
        accept_assignment(primary_assignment["id"], district["primary_teacher"]["id"])

        # A coordination row may only be opened against a case in service, so the
        # case is activated first; the assignment left at PROPOSED for the
        # wrong-role acceptance attempt is a second, support row.
        set_clock(ACTIVATION_CLOCK)
        activate_case(case_id)
        assignment = validate_success(
            api_client.create_assignment(
                create_assignment_payload(case_id, "SUPPORT", support_teacher["id"]),
                CM_HEADERS,
            ),
            201,
        )
        sync = open_pacing_sync(
            case_id,
            district["classroom_teacher"]["id"],
            subject="MATH",
            assessment_accommodation="NONE",
        )
        version_before = read_case(case_id)["version"]

        validate_error(
            api_client.activate_case(case_id, CM_HEADERS),
            ApiErrorId.ERR_UNAUTHORIZED.value,
            403,
        )
        validate_error(
            api_client.create_case(
                create_case_payload(student_id, referral_date="2026-09-02"), PA_HEADERS
            ),
            ApiErrorId.ERR_UNAUTHORIZED.value,
            403,
        )
        validate_error(
            api_client.review_certification(
                certification["id"],
                review_certification_payload(
                    "REJECT", review_note="Administrator override attempt"
                ),
                PA_HEADERS,
            ),
            ApiErrorId.ERR_UNAUTHORIZED.value,
            403,
        )
        validate_error(
            api_client.create_certification(
                create_certification_payload(case_id, version_before, **CERT_WINDOW),
                NR_HEADERS,
            ),
            ApiErrorId.ERR_UNAUTHORIZED.value,
            403,
        )
        validate_error(
            api_client.acknowledge_pacing_sync(
                sync["id"],
                make_homebound_teacher_headers(district["classroom_teacher"]["id"]),
            ),
            ApiErrorId.ERR_UNAUTHORIZED.value,
            403,
        )
        validate_error(
            api_client.accept_assignment(
                assignment["id"],
                make_classroom_teacher_headers(support_teacher["id"]),
            ),
            ApiErrorId.ERR_UNAUTHORIZED.value,
            403,
        )
        validate_error(
            api_client.list_pacing_syncs(NR_HEADERS, params={"limit": 100}),
            ApiErrorId.ERR_UNAUTHORIZED.value,
            403,
        )

        validate_error(
            api_client.get_case(case_id, UNKNOWN_ROLE_HEADERS),
            ApiErrorId.ERR_UNAUTHENTICATED.value,
            401,
        )
        validate_error(
            api_client.get_case(case_id, {"X-User-Role": "CaseManager"}),
            ApiErrorId.ERR_UNAUTHENTICATED.value,
            401,
        )
        validate_error(
            api_client.get_case(case_id, {"X-User-ID": CASE_MANAGER_USER_ID}),
            ApiErrorId.ERR_UNAUTHENTICATED.value,
            401,
        )

        certifications, meta = validate_paginated(
            api_client.list_certifications(NR_HEADERS, params={"limit": 100})
        )
        assert meta["total_count"] == 1, (
            "the denials are per endpoint, not a blanket lockout of the role"
        )
        assert certifications[0]["id"] == certification["id"]

        after = read_case(case_id)
        assert after["service_status"] == "ACTIVE"
        assert after["version"] == version_before, "no refused request mutated the case"
        assert read_assignment(assignment["id"])["status"] == "PROPOSED"
        remaining = [
            row for row in _all(api_client.list_pacing_syncs) if row["id"] == sync["id"]
        ]
        assert [row["ack_status"] for row in remaining] == ["PENDING"]


class TestTheTwoTeacherRolesMayOnlyTouchTheirOwnRows:
    """The right role on the wrong row is still refused, and refused early."""

    def test_ownership_is_checked_before_state_for_both_entity_backed_roles(self):
        """A homebound teacher is refused on another teacher's assignment and on a session
        belonging to another teacher's assignment — and the ownership refusal wins even
        after that session has already been logged, where a state refusal would otherwise
        apply. A classroom teacher who is not the teacher of record is refused on both
        answers a pacing row accepts, leaving the row untouched for its real owner.

        The PRD states: "When `X-User-Role` is `HomeboundTeacher`, `X-User-ID` is the
        `id` of the acting `Teacher`; ownership checks on any resource that references a
        `Teacher` compare the resource's foreign-key field to `X-User-ID`, so accepting
        or declining an assignment requires `X-User-ID` to equal that assignment's
        `teacher_id`, and logging a session outcome requires `X-User-ID` to equal the
        `teacher_id` of the assignment the session references."

        The PRD states: "A mismatch is rejected with `ERR_NOT_ASSIGNED_TEACHER`."

        The PRD states: "When `X-User-Role` is `ClassroomTeacher`, `X-User-ID` is
        likewise the `id` of the acting `Teacher`; acknowledging or disputing a pacing
        coordination row requires `X-User-ID` to equal that row's
        `classroom_teacher_id`, and a mismatch is rejected with
        `ERR_NOT_CLASSROOM_TEACHER_OF_RECORD`."

        The PRD states: "**Resource ownership for entity-backed roles.** The
        `HomeboundTeacher` and `ClassroomTeacher` ownership checks described in §2.1,
        rejecting with `ERR_NOT_ASSIGNED_TEACHER` or
        `ERR_NOT_CLASSROOM_TEACHER_OF_RECORD` (403)."

        The PRD states: "**State preconditions.** The from-state of every requested
        transition, rejecting with the state-specific 409 codes described alongside each
        workflow in §3."

        The PRD states: "Logging is permitted only from `SCHEDULED`, and logging against
        a session in any other status is `ERR_SESSION_ALREADY_LOGGED`."

        The PRD states: "The same teacher may instead dispute, but only from `PENDING`,
        recording a required `dispute_note` and moving `ack_status` `PENDING →
        DISPUTED`; that too recomputes the counters and may pull a `READY` plan back to
        `CLASSROOM_COORD_PENDING`."

        Design: Corner/rbac/entity_backed_roles_may_only_touch_their_own_rows
        """
        district = _configured_district()
        support_teacher = register_teacher(**SECOND_TEACHER)
        other_classroom_teacher = register_teacher(
            full_name="Omar Kite",
            employee_number="E-1008",
            credential_areas=["ELA"],
            grade_bands=["MIDDLE"],
            max_weekly_caseload_minutes=600,
            home_visit_eligible=False,
        )
        primary_teacher_id = district["primary_teacher"]["id"]

        case = open_case(district["student"]["id"])
        case_id = case["id"]
        certification = submit_certification(case_id, **CERT_WINDOW)
        review_certification(certification["id"], "ACCEPT")
        finalize_safety_review(
            record_safety_review(case_id, **CLEARED_SAFETY_REVIEW)["id"]
        )
        primary_assignment = validate_success(
            api_client.create_assignment(
                create_assignment_payload(case_id, "PRIMARY", primary_teacher_id),
                CM_HEADERS,
            ),
            201,
        )
        accept_assignment(primary_assignment["id"], primary_teacher_id)

        set_clock(ACTIVATION_CLOCK)
        activate_case(case_id)
        support_assignment = validate_success(
            api_client.create_assignment(
                create_assignment_payload(case_id, "SUPPORT", support_teacher["id"]),
                CM_HEADERS,
            ),
            201,
        )
        sync = open_pacing_sync(
            case_id,
            district["classroom_teacher"]["id"],
            subject="MATH",
            assessment_accommodation="NONE",
        )
        session = schedule_session(case_id, primary_assignment["id"], **MORNING_VISIT)

        validate_error(
            api_client.accept_assignment(
                support_assignment["id"],
                make_homebound_teacher_headers(primary_teacher_id),
            ),
            ApiErrorId.ERR_NOT_ASSIGNED_TEACHER.value,
            403,
        )
        assert read_assignment(support_assignment["id"])["status"] == "PROPOSED"
        assert read_teacher(primary_teacher_id)["committed_weekly_minutes"] == 390, (
            "the refused acceptance changed nobody's load"
        )

        validate_error(
            api_client.log_session(
                session["id"],
                log_delivered_payload(60),
                make_homebound_teacher_headers(support_teacher["id"]),
            ),
            ApiErrorId.ERR_NOT_ASSIGNED_TEACHER.value,
            403,
        )

        set_clock(SERVICE_CLOCK)
        delivered = log_session_delivered(session["id"], primary_teacher_id, 60)
        assert delivered["status"] == "DELIVERED"
        assert delivered["credited_minutes"] == 60

        refusal = validate_error(
            api_client.log_session(
                session["id"],
                log_delivered_payload(45),
                make_homebound_teacher_headers(support_teacher["id"]),
            ),
            ApiErrorId.ERR_NOT_ASSIGNED_TEACHER.value,
            403,
        )
        assert refusal["error_id"] != ApiErrorId.ERR_SESSION_ALREADY_LOGGED.value, (
            "ownership is settled before the session's own state is examined"
        )

        intruder_headers = make_classroom_teacher_headers(other_classroom_teacher["id"])
        validate_error(
            api_client.acknowledge_pacing_sync(sync["id"], intruder_headers),
            ApiErrorId.ERR_NOT_CLASSROOM_TEACHER_OF_RECORD.value,
            403,
        )
        validate_error(
            api_client.dispute_pacing_sync(
                sync["id"],
                dispute_pacing_sync_payload(dispute_note="Not my roster"),
                intruder_headers,
            ),
            ApiErrorId.ERR_NOT_CLASSROOM_TEACHER_OF_RECORD.value,
            403,
        )
        still_pending = [
            row for row in _all(api_client.list_pacing_syncs) if row["id"] == sync["id"]
        ][0]
        assert still_pending["ack_status"] == "PENDING", (
            "neither refused answer moved the row for its real owner"
        )
        assert still_pending["acked_at"] is None

        acknowledged = validate_success(
            api_client.acknowledge_pacing_sync(
                sync["id"],
                make_classroom_teacher_headers(district["classroom_teacher"]["id"]),
            )
        )
        assert acknowledged["ack_status"] == "ACKED"
        assert acknowledged["acked_at"].startswith("2026-09-08T12:00:00")


class TestOneUserIdCannotBothAuthorAndApprove:
    """Two operations refuse the author, whichever hat the author puts on."""

    def test_the_same_user_id_is_refused_on_both_second_person_controls(self):
        """The user who created the case cannot verify that case's delivered session, and
        switching from the case-manager role to the administrator role does not launder
        the identity, because operator identities are opaque header values rather than
        entity references. The user who submitted an extension request likewise cannot
        decide it. A different user id in the same role succeeds on both.

        The PRD states: "When `X-User-Role` is `ProgramAdministrator`, `CaseManager`, or
        `NurseReviewer`, `X-User-ID` is an opaque operator identifier that is not tied
        to any persisted entity."

        The PRD states: "Two operations additionally enforce segregation of duties on
        top of role membership."

        The PRD states: "**Segregation of duties.** The two
        acting-user-versus-recorded-user checks, rejecting with
        `ERR_SEGREGATION_OF_DUTIES` (403)."

        The PRD states: "Here segregation of duties bites: the verifying `X-User-ID`
        must differ from the `created_by_user_id` of the session's case, and a
        self-verification is rejected with `ERR_SEGREGATION_OF_DUTIES`."

        The PRD states: "A successful verification stamps `verified_at` with the clock
        instant and `verified_by_user_id` with the acting `X-User-ID`."

        The PRD states: "Segregation of duties applies: the deciding `X-User-ID` must
        differ from the request's `submitted_by_user_id`, and a self-decision is
        rejected with `ERR_SEGREGATION_OF_DUTIES`."

        The PRD states: "Either decision stamps `decided_by_user_id` with the acting
        `X-User-ID`, moves the case `EXTENSION_PENDING → ACTIVE`, and increments the
        case's `version` by one — the loop `ACTIVE → EXTENSION_PENDING → ACTIVE` is
        deliberately cyclic, and `extension_count` reaching 2 is what terminates it."

        The PRD states: "An `APPROVED` decision moves the request `UNDER_REVIEW →
        APPROVED` and cascades into the case: `certified_end_date` is advanced by
        `requested_additional_days` calendar days from its current value,
        `extension_count` increments by one, `weekly_entitled_minutes` is recomputed per
        §3.3 — where the newly approved days now feed the effective absence duration and
        may cross a duration-bonus threshold — the weekly allocation is recomputed
        across the case's active assignments, and `committed_weekly_minutes` is
        recomputed for every affected teacher."

        Design: Corner/rbac/the_same_user_id_cannot_both_author_and_approve
        """
        author_cm_headers = make_case_manager_headers(SHARED_OPERATOR_USER_ID)
        author_pa_headers = make_program_administrator_headers(SHARED_OPERATOR_USER_ID)
        district = _configured_district()
        primary_teacher_id = district["primary_teacher"]["id"]

        case = open_case(district["student"]["id"], headers=author_cm_headers)
        case_id = case["id"]
        assert case["created_by_user_id"] == SHARED_OPERATOR_USER_ID
        certification = submit_certification(
            case_id, headers=author_cm_headers, **CERT_WINDOW
        )
        review_certification(certification["id"], "ACCEPT")
        finalize_safety_review(
            record_safety_review(
                case_id, headers=author_cm_headers, **CLEARED_SAFETY_REVIEW
            )["id"],
            headers=author_cm_headers,
        )
        assignment = validate_success(
            api_client.create_assignment(
                create_assignment_payload(case_id, "PRIMARY", primary_teacher_id),
                author_cm_headers,
            ),
            201,
        )
        accept_assignment(assignment["id"], primary_teacher_id)

        set_clock(ACTIVATION_CLOCK)
        activate_case(case_id)
        session = schedule_session(
            case_id, assignment["id"], headers=author_cm_headers, **MORNING_VISIT
        )

        set_clock(SERVICE_CLOCK)
        log_session_delivered(session["id"], primary_teacher_id, 60)

        for headers, hat in (
            (author_cm_headers, "as a case manager"),
            (author_pa_headers, "as an administrator"),
        ):
            validate_error(
                api_client.verify_session(session["id"], headers),
                ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
                403,
            )
            assert read_session(session["id"])["verified_at"] is None, (
                f"the author was refused {hat} and stamped nothing"
            )

        verified = validate_success(
            api_client.verify_session(session["id"], CM2_HEADERS)
        )
        assert verified["verified_by_user_id"] == SECOND_CASE_MANAGER_USER_ID
        assert verified["verified_at"].startswith("2026-09-08T12:00:00")

        request = validate_success(
            api_client.create_extension_request(
                create_extension_request_payload(
                    case_id,
                    certification["id"],
                    read_case(case_id)["version"],
                    requested_additional_days=15,
                    justification="Recovery slower than certified",
                ),
                author_cm_headers,
            ),
            201,
        )
        assert request["submitted_by_user_id"] == SHARED_OPERATOR_USER_ID
        validate_success(
            api_client.start_extension_review(request["id"], PA_HEADERS)
        )

        validate_error(
            api_client.decide_extension_request(
                request["id"], decide_extension_payload("APPROVED"), author_pa_headers
            ),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
            403,
        )
        held = validate_success(
            api_client.get_extension_request(request["id"], PA_HEADERS)
        )
        assert held["status"] == "UNDER_REVIEW"
        assert held["decided_by_user_id"] is None
        assert read_case(case_id)["service_status"] == "EXTENSION_PENDING"

        decided = validate_success(
            api_client.decide_extension_request(
                request["id"],
                decide_extension_payload(
                    "APPROVED", decision_note="Independent approver"
                ),
                PA_HEADERS,
            )
        )
        assert decided["status"] == "APPROVED"
        assert decided["decided_by_user_id"] == PROGRAM_ADMINISTRATOR_USER_ID

        final_case = read_case(case_id)
        assert final_case["service_status"] == "ACTIVE"
        assert final_case["extension_count"] == 1
        assert final_case["certified_end_date"] == "2026-10-22"
