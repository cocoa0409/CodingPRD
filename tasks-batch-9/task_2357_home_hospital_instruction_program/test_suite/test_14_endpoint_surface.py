"""What each endpoint actually hands back, and what it quietly leaves alone.

The catalogue has no update verb at all — a rule is created, read, listed and
retired, and retirement rewrites one field of nine. The three action verbs on a
served case have three different footprints. The funding summary recomputes on
every call and writes nothing. And one endpoint has two modes, depending on
whether the caller names the teacher or lets the server pick one.
"""

from test_helpers import (
    ApiErrorId,
    CM_HEADERS,
    MIDDLE_IN_HOME_RULE,
    PA_HEADERS,
    PROGRAM_ADMINISTRATOR_USER_ID,
    accept_assignment,
    activate_case,
    api_client,
    assert_append_only_resource,
    assert_entitlement_rule,
    create_assignment_payload,
    create_entitlement_rule_payload,
    finalize_safety_review,
    is_iso8601_timestamp,
    ledger_entries_for_case,
    list_data,
    log_session_delivered,
    open_case,
    open_pacing_sync,
    propose_assignment,
    read_case,
    read_teacher,
    record_safety_review,
    register_student,
    register_teacher,
    review_certification,
    schedule_session,
    set_clock,
    setup_active_case,
    setup_catalogue,
    submit_certification,
    validate_error,
    validate_paginated,
    validate_success,
    verify_session,
)

CLOCK = "2026-09-01T00:00:00Z"
LATER_CLOCK = "2026-09-01T01:00:00Z"
ACTIVATION_CLOCK = "2026-09-07T08:00:00Z"
FIRST_LOG_CLOCK = "2026-09-08T12:00:00Z"
SECOND_LOG_CLOCK = "2026-09-09T15:00:00Z"

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

# A HIGH / VIRTUAL_SYNC rule that leans on the two floors of zero.
VIRTUAL_RULE = {
    "grade_band": "HIGH",
    "delivery_mode": "VIRTUAL_SYNC",
    "base_weekly_minutes": 300,
    "cap_weekly_minutes": 420,
    "min_session_minutes": 20,
    "max_session_minutes": 90,
    "max_daily_minutes": 180,
    "min_gap_minutes": 0,
    "travel_buffer_minutes": 0,
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

CATALOGUE_NUMERICS = (
    "base_weekly_minutes",
    "cap_weekly_minutes",
    "min_session_minutes",
    "max_session_minutes",
    "max_daily_minutes",
    "min_gap_minutes",
    "travel_buffer_minutes",
)

LONG_SESSION = {
    "scheduled_start": "2026-09-08T09:00:00Z",
    "scheduled_end": "2026-09-08T10:58:00Z",
    "delivery_mode": "IN_HOME",
    "subject": "MATH",
}


def _envelope(response) -> dict:
    return response.json()


def _rule(**overrides):
    return api_client.create_entitlement_rule(
        create_entitlement_rule_payload(**overrides), PA_HEADERS
    )


def _propose_without_naming_anyone(case_id: str, role: str):
    return api_client.create_assignment(
        create_assignment_payload(case_id, role), CM_HEADERS
    )


def _case_ready_for_a_long_visit() -> dict:
    """An ACTIVE case with one SCHEDULED 118-minute in-home visit on 2026-09-08."""
    bundle = setup_active_case(
        clock=CLOCK,
        rules=[MIDDLE_IN_HOME_RULE],
        certification=dict(CERT_WINDOW),
        safety_review=dict(CLEARED_SAFETY_REVIEW),
    )
    bundle["session"] = schedule_session(
        bundle["case"]["id"], bundle["primary_assignment"]["id"], **LONG_SESSION
    )
    bundle["case"] = read_case(bundle["case"]["id"])
    return bundle


def _one_teacher_serving_two_cases() -> dict:
    """Two ACTIVE cases, both served in-home by the same teacher row."""
    rules = setup_catalogue(clock=CLOCK, rules=[MIDDLE_IN_HOME_RULE])
    teacher = register_teacher()
    bundle = {"rule": rules[0], "teacher": teacher}
    students = (
        ("a", {}, "1234567890"),
        ("b", {"student_number": "S-0002", "full_name": "Ben Oyo", "grade_level": 8},
         "1234567891"),
    )
    for key, student_overrides, npi in students:
        student = register_student(**student_overrides)
        case = open_case(student["id"])
        certification = submit_certification(
            case["id"], physician_npi=npi, **CERT_WINDOW
        )
        review_certification(certification["id"], "ACCEPT")
        finalize_safety_review(
            record_safety_review(case["id"], **CLEARED_SAFETY_REVIEW)["id"]
        )
        assignment = propose_assignment(case["id"], "PRIMARY", teacher["id"])
        accept_assignment(assignment["id"], teacher["id"])
        bundle[f"student_{key}"] = student
        bundle[f"case_{key}"] = case
        bundle[f"assignment_{key}"] = assignment

    set_clock(ACTIVATION_CLOCK)
    for key in ("a", "b"):
        bundle[f"case_{key}"] = activate_case(bundle[f"case_{key}"]["id"])
    return bundle


def _case_with_one_verified_and_two_planned_visits() -> dict:
    """An ACTIVE case carrying one verified 118-minute visit and two still-scheduled
    two-hour visits that exactly fill the next day's cap."""
    bundle = setup_active_case(
        clock=CLOCK,
        rules=[MIDDLE_IN_HOME_RULE],
        certification=dict(CERT_WINDOW),
        safety_review=dict(CLEARED_SAFETY_REVIEW),
    )
    case_id = bundle["case"]["id"]
    assignment_id = bundle["primary_assignment"]["id"]
    plan = (
        ("first", LONG_SESSION),
        (
            "second",
            {
                "scheduled_start": "2026-09-09T09:00:00Z",
                "scheduled_end": "2026-09-09T11:00:00Z",
                "delivery_mode": "IN_HOME",
                "subject": "MATH",
            },
        ),
        (
            "third",
            {
                "scheduled_start": "2026-09-09T12:00:00Z",
                "scheduled_end": "2026-09-09T14:00:00Z",
                "delivery_mode": "IN_HOME",
                "subject": "ELA",
            },
        ),
    )
    for key, overrides in plan:
        bundle[key] = schedule_session(case_id, assignment_id, **overrides)

    set_clock(FIRST_LOG_CLOCK)
    bundle["first"] = log_session_delivered(
        bundle["first"]["id"], bundle["teacher"]["id"], 118
    )
    bundle["first"] = verify_session(bundle["first"]["id"])
    bundle["case"] = read_case(case_id)
    return bundle


def _two_cases_and_five_teachers() -> dict:
    """A grade-7 in-home case and a grade-3 in-home case, both ELIGIBLE, against a
    staff roster where only two teachers clear every eligibility condition."""
    rules = setup_catalogue(clock=CLOCK, rules=[MIDDLE_IN_HOME_RULE, PRIMARY_BAND_RULE])
    bundle = {"middle_rule": rules[0], "primary_rule": rules[1]}

    roster = (
        ("first", "Zoe Alt", "E-1010", {}, "2026-09-01T00:10:00Z"),
        ("second", "Yan Bex", "E-1011", {"credential_areas": ["SCIENCE"]},
         "2026-09-01T00:20:00Z"),
        ("wrong_band", "Xia Corr", "E-1012", {"grade_bands": ["HIGH"]},
         "2026-09-01T00:30:00Z"),
        ("no_home_visit", "Wes Dunn", "E-1013", {"home_visit_eligible": False},
         "2026-09-01T00:40:00Z"),
        ("restricted", "Vic Eng", "E-1014", {"safety_clearance_status": "RESTRICTED"},
         "2026-09-01T00:50:00Z"),
    )
    for key, full_name, employee_number, overrides, created_at_clock in roster:
        set_clock(created_at_clock)
        attributes = {
            "full_name": full_name,
            "employee_number": employee_number,
            "credential_areas": ["MATH", "ELA"],
            "grade_bands": ["MIDDLE"],
            "max_weekly_caseload_minutes": 1200,
        }
        attributes.update(overrides)
        bundle[f"teacher_{key}"] = register_teacher(**attributes)

    set_clock(LATER_CLOCK)
    plan = (
        ("middle", {}, "1234567890"),
        (
            "primary",
            {
                "student_number": "S-0009",
                "full_name": "Rex Pham",
                "grade_level": 3,
                "campus_code": "ES-02",
            },
            "1234567892",
        ),
    )
    for key, student_overrides, npi in plan:
        student = register_student(**student_overrides)
        case = open_case(student["id"])
        certification = submit_certification(
            case["id"], physician_npi=npi, **CERT_WINDOW
        )
        review_certification(certification["id"], "ACCEPT")
        bundle[f"student_{key}"] = student
        bundle[f"case_{key}"] = read_case(case["id"])
    return bundle


class TestTheCatalogueIsWrittenOnceAndWithdrawnRatherThanEdited:
    """No update verb exists, so retirement is the only way a rule ever changes."""

    def test_two_creates_a_read_a_page_and_a_retire_are_the_whole_rule_surface(self):
        """A rule accepts zero for both of its non-negative floors, reads back by id
        exactly as it was created, appears in a page window whose counts describe the
        whole table rather than the page, and after retirement differs from its created
        form in `status` alone while remaining readable.

        The PRD states: "Each rule declares `base_weekly_minutes`, the weekly
        instructional minutes before any diagnosis or duration adjustment, which must be
        greater than zero; `cap_weekly_minutes`, the hard weekly ceiling applied after
        every adjustment, which must be at least `base_weekly_minutes`;
        `min_session_minutes`, the shortest permitted single session, greater than zero;
        `max_session_minutes`, the longest permitted single session and simultaneously
        the per-session credit ceiling, at least `min_session_minutes`;
        `max_daily_minutes`, the largest aggregate scheduled minutes permitted for one
        student on one service date, at least `max_session_minutes`; `min_gap_minutes`,
        the minimum required separation between two sessions of the same case on one
        service date, not negative; and `travel_buffer_minutes`, the buffer extended on
        both ends of an in-home session when checking a teacher's slot conflicts, not
        negative."

        The PRD states: "A rule's `status` is either `PUBLISHED` or `RETIRED` and
        defaults to `PUBLISHED`."

        The PRD states: "A `ProgramAdministrator` retires a rule to withdraw it from
        future resolution; retiring a rule whose `status` is already `RETIRED` is
        rejected with `ERR_RULE_ALREADY_RETIRED`."

        The PRD states: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data field."

        The PRD states: "`limit` sets the maximum number of rows returned; it defaults
        to 10, has a minimum of 1, and has a maximum of 100."

        The PRD states: "`offset` sets how many rows are skipped before the page begins;
        it defaults to 0 and may not be negative."

        The PRD states: "Unless a specific endpoint says otherwise, list results are
        ordered by `created_at` ascending."

        The PRD states: "Every list response carries `limit`, `offset`, `total_count`,
        and `has_more` inside the envelope's `meta` object."

        The PRD states: "`total_count` reflects the number of rows matching the supplied
        filters before the page window is applied, and `has_more` is true exactly when
        rows matching those filters remain beyond the current window."

        Design: Corner/endpoints/entitlement_rule_surface_is_create_read_list_and_retire_only
        """
        set_clock(CLOCK)
        home_response = _rule()
        home_rule = validate_success(home_response, 201)
        assert_entitlement_rule(home_rule)
        assert _envelope(home_response)["response_type"] == "object"
        assert home_rule["status"] == "PUBLISHED", "the catalogue publishes by default"
        for field in CATALOGUE_NUMERICS:
            assert home_rule[field] == MIDDLE_IN_HOME_RULE[field], (
                f"{field} came back exactly as submitted"
            )

        set_clock(LATER_CLOCK)
        virtual_rule = validate_success(_rule(**VIRTUAL_RULE), 201)
        assert virtual_rule["min_gap_minutes"] == 0
        assert virtual_rule["travel_buffer_minutes"] == 0, (
            "both buffers are floored at zero rather than required to be positive"
        )

        read_back = validate_success(
            api_client.get_entitlement_rule(home_rule["id"], CM_HEADERS)
        )
        assert read_back == home_rule, "the read is the same row, field for field"

        rows, meta = validate_paginated(
            api_client.list_entitlement_rules(CM_HEADERS)
        )
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert meta["total_count"] == 2
        assert meta["has_more"] is False
        assert [row["id"] for row in rows] == [home_rule["id"], virtual_rule["id"]], (
            "oldest first"
        )

        first_page, first_meta = validate_paginated(
            api_client.list_entitlement_rules(PA_HEADERS, params={"limit": 1})
        )
        assert [row["id"] for row in first_page] == [home_rule["id"]]
        assert first_meta["total_count"] == 2
        assert first_meta["has_more"] is True, "one row still waits beyond the window"

        second_page, second_meta = validate_paginated(
            api_client.list_entitlement_rules(
                PA_HEADERS, params={"limit": 1, "offset": 1}
            )
        )
        assert [row["id"] for row in second_page] == [virtual_rule["id"]]
        assert second_meta["total_count"] == 2, (
            "the count describes the table, not the page"
        )
        assert second_meta["has_more"] is False

        retired = validate_success(
            api_client.retire_entitlement_rule(home_rule["id"], PA_HEADERS)
        )
        assert retired["status"] == "RETIRED"
        for field in CATALOGUE_NUMERICS:
            assert retired[field] == home_rule[field], (
                f"retirement left {field} alone"
            )
        assert retired["grade_band"] == home_rule["grade_band"]
        assert retired["delivery_mode"] == home_rule["delivery_mode"]

        still_readable = validate_success(
            api_client.get_entitlement_rule(home_rule["id"], CM_HEADERS)
        )
        assert still_readable["id"] == home_rule["id"]
        assert still_readable["status"] == "RETIRED"

        validate_error(
            api_client.retire_entitlement_rule(home_rule["id"], PA_HEADERS),
            ApiErrorId.ERR_RULE_ALREADY_RETIRED.value,
            409,
        )
        final_rows, final_meta = validate_paginated(
            api_client.list_entitlement_rules(PA_HEADERS, params={"limit": 100})
        )
        assert final_meta["total_count"] == 2, "retirement withdraws, it does not delete"
        assert {row["id"]: row["status"] for row in final_rows} == {
            home_rule["id"]: "RETIRED",
            virtual_rule["id"]: "PUBLISHED",
        }


class TestThreeVerbsOnOneCaseHaveThreeDifferentFootprints:
    """One appends a ledger row, one stamps two fields, one answers with the parent."""

    def test_logging_writes_a_row_verifying_writes_none_and_reporting_answers_with_the_case(
        self,
    ):
        """Logging 118 delivered minutes credits 120 and appends one ledger row; verifying
        stamps the reviewer and the instant without touching the ledger or the case; and
        reporting hands back the case rather than the session — so the case's version has
        moved exactly twice across the three calls.

        The PRD states: "A `DELIVERED` outcome requires `actual_minutes` of at least 1
        and advances the session `SCHEDULED → DELIVERED`."

        The PRD states: "`credited_minutes` is computed from the rule the case's
        `entitlement_rule_id` names: take the lesser of the reported `actual_minutes`
        and the rule's `max_session_minutes`; multiply that capped figure by 0.90 when
        the session's `delivery_mode` is `VIRTUAL_SYNC` and leave it unchanged when the
        mode is `IN_HOME`; then divide by five, round half up to a whole number, and
        multiply back by five."

        The PRD states: "A ledger row is appended carrying `attendance_code`
        `HB_PRESENT` when the session's `delivery_mode` is `IN_HOME` and
        `HB_VIRTUAL_PRESENT` when it is `VIRTUAL_SYNC`, with `apportionment_minutes`
        equal to the session's `credited_minutes`."

        The PRD states: "From those two instants the server derives `scheduled_minutes`
        as the whole-minute span between them and `service_date` as the UTC calendar
        date of `scheduled_start`."

        The PRD states: "A successful verification stamps `verified_at` with the clock
        instant and `verified_by_user_id` with the acting `X-User-ID`."

        The PRD states: "Attendance ledger rows are append-only: once written they are
        never updated, corrected in place, or deleted."

        The PRD states: "The result is written to `provisional_apportionment_minutes`."

        The PRD states: "Reporting also recomputes `service_gap_minutes`, which may fire
        a hold or release one, and increments the case's `version` by one."

        The PRD states: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data field."

        The PRD states: "`version` (integer): an integer that increments by one on every
        mutation of the row."

        Design: Corner/endpoints/log_verify_and_report_are_verbs_that_return_the_updated_resource
        """
        bundle = _case_ready_for_a_long_visit()
        case_id = bundle["case"]["id"]
        session_id = bundle["session"]["id"]
        version_before = bundle["case"]["version"]

        set_clock(FIRST_LOG_CLOCK)
        logged = log_session_delivered(session_id, bundle["teacher"]["id"], 118)
        assert logged["status"] == "DELIVERED"
        assert logged["actual_minutes"] == 118
        assert logged["scheduled_minutes"] == 118
        assert logged["service_date"] == "2026-09-08"
        assert logged["credited_minutes"] == 120, (
            "118 rounds half up to the nearest five"
        )

        after_log = ledger_entries_for_case(case_id)
        assert len(after_log) == 1
        row = after_log[0]
        assert_append_only_resource(row)
        assert row["attendance_code"] == "HB_PRESENT"
        assert row["apportionment_minutes"] == 120
        assert row["session_id"] == session_id

        verify_response = api_client.verify_session(session_id, PA_HEADERS)
        verified = validate_success(verify_response)
        assert _envelope(verify_response)["response_type"] == "object"
        assert is_iso8601_timestamp(verified["verified_at"])
        assert verified["verified_at"].startswith("2026-09-08T12:00:00")
        assert verified["verified_by_user_id"] == PROGRAM_ADMINISTRATOR_USER_ID
        assert verified["status"] == "DELIVERED", "verification is not a state change"
        assert verified["credited_minutes"] == 120
        assert ledger_entries_for_case(case_id) == after_log, (
            "verification appends nothing"
        )

        report_response = api_client.report_case_funding(case_id, PA_HEADERS)
        reported = validate_success(report_response)
        assert _envelope(report_response)["response_type"] == "object"
        assert reported["id"] == case_id, (
            "the verb answers with the case it summarises, not the session"
        )
        assert reported["provisional_apportionment_minutes"] == 120
        assert reported["reported_apportionment_minutes"] == 120
        assert reported["service_gap_minutes"] == 0
        assert reported["funding_status"] == "ACCRUING"

        assert reported["version"] == version_before + 2, (
            "logging and reporting each moved the case; verifying did not"
        )

        row_by_id = validate_success(
            api_client.get_attendance_entry(row["id"], CM_HEADERS)
        )
        assert row_by_id == row, "the ledger row was never rewritten"


class TestOneTeacherRowIsReachableThroughThreeDifferentForeignKeys:
    """Two cases, three links, one staff record — and each link carries its own case."""

    def test_the_same_teacher_serves_two_cases_and_coordinates_one_of_them(self):
        """The same teacher row is legal as the assignee on two cases and as the classroom
        teacher of record on one of them; each assignment carries the full 390-minute
        allocation of its own case, the coordination row belongs to only the first case,
        and the teacher's own committed total is the sum across both.

        The PRD states: "A `CaseManager` proposes a teacher for a case by naming the
        `case_id` and a `role` of `PRIMARY`, `SUPPORT`, or `SPED_SERVICE`."

        The PRD states: "A `CaseManager` opens a coordination row per subject, naming
        the `case_id`, the `classroom_teacher_id` of the campus classroom teacher of
        record for that subject, the `subject`, a `pacing_target_unit` naming the unit
        or chapter the homebound teacher must reach to stay aligned with the classroom,
        and an `assessment_accommodation` of `NONE`, `EXTENDED_TIME`,
        `ORAL_ADMINISTRATION`, or `ALTERNATE_SETTING_PROCTOR` agreed for the homebound
        period."

        The PRD states: "The primary assignment nominally carries the remaining seventy
        percent, and concretely it receives the case's `weekly_entitled_minutes` minus
        the support total — so the primary row absorbs the entire rounding residual and
        the sum of `weekly_committed_minutes` across active assignments equals
        `weekly_entitled_minutes` exactly."

        The PRD states: "A teacher's own `committed_weekly_minutes` is the sum of
        `weekly_committed_minutes` across every assignment of that teacher whose
        `status` is `ACTIVE`, across every case, with no time window."

        The PRD states: "The derived flag `over_cap` is true when
        `committed_weekly_minutes` is strictly greater than that teacher's
        `max_weekly_caseload_minutes`, and false when the two are equal."

        The PRD states: "Scheduling a session is a `CaseManager` action naming the
        `case_id`, the `assignment_id` of the active assignment that will serve it, the
        `scheduled_start` and `scheduled_end` instants, the session's own
        `delivery_mode` of either `IN_HOME` or `VIRTUAL_SYNC`, the `subject` from
        `MATH`, `ELA`, `SCIENCE`, `SOCIAL_STUDIES`, and `GENERAL_ELEMENTARY`, and
        optionally `escort_confirmed`."

        Design: Corner/endpoints/one_teacher_row_is_reachable_from_two_cases_through_three_different_links
        """
        bundle = _one_teacher_serving_two_cases()
        teacher_id = bundle["teacher"]["id"]
        case_a_id = bundle["case_a"]["id"]
        case_b_id = bundle["case_b"]["id"]

        sync = open_pacing_sync(case_a_id, teacher_id, subject="MATH")
        assert sync["case_id"] == case_a_id
        assert sync["classroom_teacher_id"] == teacher_id, (
            "one staff record may stand on both sides of the coordination link"
        )

        session_a = schedule_session(
            case_a_id,
            bundle["assignment_a"]["id"],
            scheduled_start="2026-09-08T09:00:00Z",
            scheduled_end="2026-09-08T10:00:00Z",
            delivery_mode="IN_HOME",
            subject="MATH",
        )
        session_b = schedule_session(
            case_b_id,
            bundle["assignment_b"]["id"],
            scheduled_start="2026-09-08T13:00:00Z",
            scheduled_end="2026-09-08T14:00:00Z",
            delivery_mode="IN_HOME",
            subject="ELA",
        )

        all_assignments = list_data(
            api_client.list_assignments(PA_HEADERS, params={"limit": 100})
        )
        teacher_rows = [
            row for row in all_assignments if row["teacher_id"] == teacher_id
        ]
        assert {row["id"] for row in teacher_rows} == {
            bundle["assignment_a"]["id"],
            bundle["assignment_b"]["id"],
        }
        for row in teacher_rows:
            assert row["status"] == "ACTIVE"
            assert row["weekly_committed_minutes"] == 390, (
                "with no support row the primary carries the whole entitlement"
            )
        case_b_rows = [row for row in all_assignments if row["case_id"] == case_b_id]
        assert [row["id"] for row in case_b_rows] == [bundle["assignment_b"]["id"]]

        syncs = [
            row
            for row in list_data(
                api_client.list_pacing_syncs(CM_HEADERS, params={"limit": 100})
            )
            if row["classroom_teacher_id"] == teacher_id
        ]
        assert [row["id"] for row in syncs] == [sync["id"]]
        assert syncs[0]["case_id"] == case_a_id

        sessions = list_data(
            api_client.list_sessions(CM_HEADERS, params={"limit": 100})
        )
        for_assignment_a = [
            row
            for row in sessions
            if row["assignment_id"] == bundle["assignment_a"]["id"]
        ]
        assert [row["id"] for row in for_assignment_a] == [session_a["id"]]
        assert session_b["id"] not in {row["id"] for row in for_assignment_a}, (
            "the two visits share a teacher and a date but not an assignment"
        )

        teacher = read_teacher(teacher_id)
        assert teacher["committed_weekly_minutes"] == 780, "390 on each case"
        assert teacher["over_cap"] is False


class TestTheFundingSummaryIsRecomputedAndNeverPersisted:
    """The same URL, read twice by two roles, moves nothing at all."""

    def test_the_summary_shows_both_variants_diverging_and_then_converging(self):
        """With one visit verified and two still planned, the forward-looking figure is 360
        against a verified 120; two roles reading the same URL see the identical payload
        and the case is untouched by the reads; once all three are delivered and verified
        the two variants meet at 360, and the diagnostic total is the one figure rounded
        at the end rather than per session.

        The PRD states: "Its input set is that case's sessions whose `status` is
        `SCHEDULED` or `DELIVERED` and whose `service_date` falls between
        `service_start_date` and `certified_end_date` inclusive on both ends; sessions
        that are `VOIDED`, `CANCELLED_ADMIN`, `STUDENT_UNAVAILABLE`, `TEACHER_CANCELLED`
        or `SAFETY_ABORTED` never participate, and verification is ignored entirely."

        The PRD states: "Each `DELIVERED` session contributes its `credited_minutes`."

        The PRD states: "Each still-`SCHEDULED` session contributes a projected credit
        computed the same way delivered credit is computed but from the plan rather than
        from the report: take the lesser of that session's `scheduled_minutes` and the
        rule's `max_session_minutes`, multiply by 0.90 when the session's
        `delivery_mode` is `VIRTUAL_SYNC` and by 1.00 when it is `IN_HOME`, divide by
        five, round half up, and multiply back by five."

        The PRD states: "The final input set is that case's sessions whose `status` is
        `DELIVERED` *and* which carry a non-null `verified_at`, whose `service_date`
        falls between `service_start_date` and `certified_end_date` inclusive on both
        ends."

        The PRD states: "For each session in turn, compute the room remaining in its
        week as the case's `weekly_entitled_minutes` minus the minutes already accepted
        into that week's bucket, floor that room at 0, take the lesser of the session's
        `credited_minutes` and that floored room, add the taken amount to the week's
        bucket, and add it to the running accepted total."

        The PRD states: "Count elapsed weeks as the number of days separating
        `service_start_date` from the clock date, plus one, divided by seven and rounded
        up to a whole week; count window weeks the same way, from `service_start_date`
        to `certified_end_date`; and take service weeks as the lesser of the two, so a
        case reconciled early is measured against elapsed time and a case reconciled
        late is measured against its window."

        The PRD states: "The entitled total is the case's `weekly_entitled_minutes`
        multiplied by service weeks."

        The PRD states: "A read-only funding summary is available to
        `ProgramAdministrator` and `CaseManager` for any one case, and it exists to let
        a reviewer see the two apportionment variants side by side before deciding."

        The PRD states: "The `projected_unrounded_minutes` field is the one place in the
        system where per-session rounding is *not* applied first: it sums the un-rounded
        intermediate credit values across all of the case's delivered sessions and
        applies the round-half-up-to-the-nearest-five step exactly once at the end."

        Design: Corner/endpoints/funding_summary_projects_both_variants_without_persisting_anything
        """
        bundle = _case_with_one_verified_and_two_planned_visits()
        case_id = bundle["case"]["id"]
        version_before_reads = bundle["case"]["version"]

        first = validate_success(api_client.get_funding_summary(case_id, CM_HEADERS))
        assert first["case_id"] == case_id
        assert first["weekly_entitled_minutes"] == 390
        assert first["window_weeks"] == 5, "2026-09-07 to 2026-10-07 spans five weeks"
        assert first["service_weeks"] == 1, "only one week has been entered so far"
        assert first["entitled_total_minutes"] == 390
        assert first["provisional_minutes"] == 360, (
            "120 delivered plus two planned visits projected at 120 each"
        )
        assert first["final_verified_minutes"] == 120, (
            "only the verified visit reaches the narrower figure"
        )
        assert first["projected_unrounded_minutes"] == 120
        assert first["reported_apportionment_minutes"] == 120
        assert first["service_gap_minutes"] == 0
        assert first["funding_status"] == "ACCRUING"

        second = validate_success(api_client.get_funding_summary(case_id, PA_HEADERS))
        assert second == first, "the read is pure, and the same for both roles"

        between = read_case(case_id)
        assert between["version"] == version_before_reads, (
            "two reads moved nothing on the case"
        )
        assert between["provisional_apportionment_minutes"] == 0, (
            "the summary projects; only reporting writes"
        )

        set_clock(SECOND_LOG_CLOCK)
        for key in ("second", "third"):
            logged = log_session_delivered(
                bundle[key]["id"], bundle["teacher"]["id"], 120
            )
            assert logged["credited_minutes"] == 120
            verify_session(logged["id"])

        third = validate_success(api_client.get_funding_summary(case_id, CM_HEADERS))
        assert third["provisional_minutes"] == 360
        assert third["final_verified_minutes"] == 360, (
            "all three sit inside one ISO week and 360 fits under its 390 ceiling"
        )
        assert third["projected_unrounded_minutes"] == 360, (
            "118 + 120 + 120 rounded once at the end is 360"
        )
        assert third["reported_apportionment_minutes"] == 360
        assert third["service_weeks"] == 1
        assert third["entitled_total_minutes"] == 390
        assert third["funding_status"] == "ACCRUING", (
            "no reconciliation has run, so the persisted posture is unchanged"
        )


class TestTheAssignmentEndpointHasTwoModes:
    """Naming a teacher validates that one; omitting the field runs a policy."""

    def test_the_selector_picks_the_least_loaded_eligible_teacher_or_refuses_outright(
        self,
    ):
        """With the field omitted the server filters out the wrong band, the teacher who
        cannot enter a home and the one whose clearance is restricted, then breaks the tie
        between the two survivors on age; the second call prefers the other survivor
        because the first is now loaded; a case in a band nobody serves has an empty
        candidate set; and naming that same unsuitable teacher explicitly answers with the
        band code instead.

        The PRD states: "The `teacher_id` field is optional, and omitting it is
        meaningful."

        The PRD states: "When the caller names a `teacher_id` explicitly, the only
        cross-record check applied is that the named teacher's `grade_bands` array
        contains the student's `grade_band`; a mismatch is `ERR_TEACHER_BAND_MISMATCH`."

        The PRD states: "When the caller omits `teacher_id`, the server runs a selector
        policy and writes the winner into `teacher_id`."

        The PRD states: "The candidate set is every teacher who satisfies all four
        eligibility conditions: the teacher's `safety_clearance_status` is `CLEARED`,
        except that when the case's `delivery_mode` is `VIRTUAL_SYNC` either `CLEARED`
        or `RESTRICTED` is acceptable; the teacher's `grade_bands` contains the
        student's `grade_band`; the teacher's `home_visit_eligible` is true whenever the
        case's `delivery_mode` is `IN_HOME` or `HYBRID`; and the teacher's current
        `committed_weekly_minutes` plus the allocation this role would receive on this
        case does not exceed that teacher's `max_weekly_caseload_minutes`."

        The PRD states: "Candidates are ranked by `committed_weekly_minutes` ascending,
        so the least-loaded eligible teacher wins, with ties broken by `created_at`
        ascending."

        The PRD states: "When the candidate set is empty the request is rejected with
        `ERR_NO_ELIGIBLE_TEACHER`."

        The PRD states: "A new assignment starts with `status` `PROPOSED` and
        `weekly_committed_minutes` 0."

        Design: Corner/endpoints/omitting_teacher_id_hands_the_choice_to_the_selector_policy
        """
        bundle = _two_cases_and_five_teachers()
        case_middle_id = bundle["case_middle"]["id"]
        case_primary_id = bundle["case_primary"]["id"]
        assert bundle["case_middle"]["weekly_entitled_minutes"] == 390
        assert bundle["case_primary"]["weekly_entitled_minutes"] == 330

        auto_primary = validate_success(
            _propose_without_naming_anyone(case_middle_id, "PRIMARY"), 201
        )
        assert auto_primary["status"] == "PROPOSED"
        assert auto_primary["weekly_committed_minutes"] == 0
        assert auto_primary["teacher_id"] == bundle["teacher_first"]["id"], (
            "two teachers survive the four filters, and the older one wins the tie"
        )

        accept_assignment(auto_primary["id"], bundle["teacher_first"]["id"])

        auto_support = validate_success(
            _propose_without_naming_anyone(case_middle_id, "SUPPORT"), 201
        )
        assert auto_support["teacher_id"] == bundle["teacher_second"]["id"], (
            "the first teacher now carries 390 minutes, so the ranking prefers the other"
        )

        validate_error(
            _propose_without_naming_anyone(case_primary_id, "PRIMARY"),
            ApiErrorId.ERR_NO_ELIGIBLE_TEACHER.value,
            422,
        )
        validate_error(
            api_client.create_assignment(
                create_assignment_payload(
                    case_primary_id, "PRIMARY", bundle["teacher_first"]["id"]
                ),
                CM_HEADERS,
            ),
            ApiErrorId.ERR_TEACHER_BAND_MISMATCH.value,
            422,
        )

        all_assignments = list_data(
            api_client.list_assignments(CM_HEADERS, params={"limit": 100})
        )
        assert [
            row for row in all_assignments if row["case_id"] == case_primary_id
        ] == [], "neither refusal staffed the grade-three case"
        middle_rows = [
            row for row in all_assignments if row["case_id"] == case_middle_id
        ]
        assert {row["role"]: row["status"] for row in middle_rows} == {
            "PRIMARY": "ACTIVE",
            "SUPPORT": "PROPOSED",
        }
