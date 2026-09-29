"""Inclusive thresholds probed one unit either side of the line.

Thirty expected absence days against twenty-nine; a delivery ratio of exactly
0.50 against 0.46; a daily total of exactly 240 minutes and a gap of exactly 15
against the next thirty minutes; and an expected absence of exactly ten days
against nine.
"""

from test_helpers import (
    ApiErrorId,
    CM_HEADERS,
    MIDDLE_IN_HOME_RULE,
    NR_HEADERS,
    PA_HEADERS,
    accept_assignment,
    activate_case,
    api_client,
    create_session_payload,
    finalize_safety_review,
    log_session_delivered,
    open_case,
    propose_assignment,
    read_case,
    record_safety_review,
    register_student,
    register_teacher,
    review_certification,
    review_certification_payload,
    schedule_session,
    sessions_for_case,
    set_clock,
    setup_active_case,
    setup_catalogue,
    submit_certification,
    validate_error,
    validate_success,
    verify_session,
)

FULL_CERT_WINDOW = {
    "expected_absence_days": 30,
    "certified_start_date": "2026-09-07",
    "certified_end_date": "2026-10-07",
    "signature_date": "2026-09-01",
}

CLEARED_SAFETY_REVIEW = {
    "hazard_findings": ["UNLIT_ACCESS"],
    "escort_available": False,
}

SECOND_TEACHER_ROW = {
    "full_name": "Sam Duro",
    "employee_number": "E-1002",
    "credential_areas": ["MATH", "ELA"],
    "grade_bands": ["MIDDLE"],
    "max_weekly_caseload_minutes": 1200,
}


def _two_cases_awaiting_review_at_twenty_nine_and_thirty_days() -> dict:
    """Two otherwise identical grade-7 in-home cases whose submitted certifications
    differ only in expected absence duration: 29 days against 30."""
    rules = setup_catalogue(rules=[MIDDLE_IN_HOME_RULE])
    student_a = register_student(student_number="S-0001", full_name="Ada Lin")
    student_b = register_student(student_number="S-0002", full_name="Ben Ortiz")
    case_a = open_case(student_a["id"], delivery_mode="IN_HOME")
    case_b = open_case(student_b["id"], delivery_mode="IN_HOME")
    certification_a = submit_certification(
        case_a["id"],
        physician_npi="1234567890",
        diagnosis_category="MEDICAL_ACUTE",
        certified_start_date="2026-09-07",
        certified_end_date="2026-10-05",
        expected_absence_days=29,
        signature_date="2026-09-01",
    )
    certification_b = submit_certification(
        case_b["id"],
        physician_npi="1234567890",
        diagnosis_category="MEDICAL_ACUTE",
        certified_start_date="2026-09-07",
        certified_end_date="2026-10-06",
        expected_absence_days=30,
        signature_date="2026-09-01",
    )
    return {
        "rule": rules[0],
        "case_a": case_a,
        "case_b": case_b,
        "certification_a": certification_a,
        "certification_b": certification_b,
    }


def _build_active_case(*, student_number, full_name, physician_npi, teacher) -> dict:
    """One further ACTIVE in-home case on an already-published catalogue."""
    student = register_student(student_number=student_number, full_name=full_name)
    case = open_case(student["id"], delivery_mode="IN_HOME")
    certification = submit_certification(
        case["id"], physician_npi=physician_npi, **FULL_CERT_WINDOW
    )
    review_certification(certification["id"], "ACCEPT")
    review = record_safety_review(case["id"], **CLEARED_SAFETY_REVIEW)
    finalize_safety_review(review["id"])
    teacher_row = register_teacher(**teacher)
    assignment = propose_assignment(case["id"], "PRIMARY", teacher_row["id"])
    assignment = accept_assignment(assignment["id"], teacher_row["id"])
    return {
        "case": activate_case(case["id"]),
        "teacher": teacher_row,
        "primary_assignment": assignment,
    }


def _two_cases_astride_the_forfeit_boundary() -> dict:
    """Two ACTIVE cases at 390 weekly minutes, one holding 390 verified minutes and
    the other 360, with the clock parked at 2026-09-20T00:00:00Z."""
    case_a = setup_active_case(
        rules=[MIDDLE_IN_HOME_RULE],
        certification=dict(FULL_CERT_WINDOW),
        safety_review=dict(CLEARED_SAFETY_REVIEW),
    )
    case_b = _build_active_case(
        student_number="S-0002",
        full_name="Ben Ortiz",
        physician_npi="1234567890",
        teacher=SECOND_TEACHER_ROW,
    )

    def book(bundle, start, end, subject):
        return schedule_session(
            bundle["case"]["id"],
            bundle["primary_assignment"]["id"],
            scheduled_start=start,
            scheduled_end=end,
            delivery_mode="IN_HOME",
            subject=subject,
        )

    a_week_37 = [
        book(case_a, "2026-09-07T09:00:00Z", "2026-09-07T11:00:00Z", "MATH"),
        book(case_a, "2026-09-08T09:00:00Z", "2026-09-08T11:00:00Z", "ELA"),
    ]
    a_week_38 = [
        book(case_a, "2026-09-14T09:00:00Z", "2026-09-14T11:00:00Z", "MATH"),
        book(case_a, "2026-09-15T09:00:00Z", "2026-09-15T09:30:00Z", "ELA"),
    ]
    b_week_37 = [
        book(case_b, "2026-09-07T09:00:00Z", "2026-09-07T11:00:00Z", "MATH"),
        book(case_b, "2026-09-08T09:00:00Z", "2026-09-08T11:00:00Z", "ELA"),
    ]
    b_week_38 = [book(case_b, "2026-09-14T09:00:00Z", "2026-09-14T11:00:00Z", "MATH")]

    set_clock("2026-09-08T18:00:00Z")
    for session in a_week_37:
        log_session_delivered(session["id"], case_a["teacher"]["id"], 120)
    for session in b_week_37:
        log_session_delivered(session["id"], case_b["teacher"]["id"], 120)

    set_clock("2026-09-15T18:00:00Z")
    log_session_delivered(a_week_38[0]["id"], case_a["teacher"]["id"], 120)
    log_session_delivered(a_week_38[1]["id"], case_a["teacher"]["id"], 30)
    log_session_delivered(b_week_38[0]["id"], case_b["teacher"]["id"], 120)

    for session in a_week_37 + a_week_38 + b_week_37 + b_week_38:
        verify_session(session["id"])

    set_clock("2026-09-20T00:00:00Z")
    case_a["case"] = read_case(case_a["case"]["id"])
    case_b["case"] = read_case(case_b["case"]["id"])
    return {"a": case_a, "b": case_b}


def _case_holding_two_hundred_forty_minutes_on_one_day() -> dict:
    """An ACTIVE case whose 2026-09-09 already carries one 120-minute primary visit,
    with a support assignment ready to carry the second."""
    bundle = setup_active_case(
        rules=[MIDDLE_IN_HOME_RULE],
        certification=dict(FULL_CERT_WINDOW),
        safety_review=dict(CLEARED_SAFETY_REVIEW),
    )
    support_teacher = register_teacher(
        full_name="Sam Duro",
        employee_number="E-1002",
        credential_areas=["SCIENCE"],
        grade_bands=["MIDDLE"],
        max_weekly_caseload_minutes=600,
    )
    support_assignment = propose_assignment(
        bundle["case"]["id"], "SUPPORT", support_teacher["id"]
    )
    bundle["support_assignment"] = accept_assignment(
        support_assignment["id"], support_teacher["id"]
    )
    bundle["support_teacher"] = support_teacher
    bundle["first_session"] = schedule_session(
        bundle["case"]["id"],
        bundle["primary_assignment"]["id"],
        scheduled_start="2026-09-09T09:00:00Z",
        scheduled_end="2026-09-09T11:00:00Z",
        delivery_mode="IN_HOME",
        subject="MATH",
    )
    return bundle


def _book_the_second_session_at_the_exact_gap(bundle: dict) -> dict:
    """The support teacher's 120-minute visit, starting exactly `min_gap_minutes`
    after the first one ends and bringing the day to exactly `max_daily_minutes`."""
    return validate_success(
        api_client.create_session(
            create_session_payload(
                bundle["case"]["id"],
                bundle["support_assignment"]["id"],
                scheduled_start="2026-09-09T11:15:00Z",
                scheduled_end="2026-09-09T13:15:00Z",
                delivery_mode="IN_HOME",
                subject="SCIENCE",
            ),
            CM_HEADERS,
        ),
        201,
    )


def _two_cases_awaiting_review_at_ten_and_nine_days() -> dict:
    """Two grade-7 in-home cases whose submitted certifications claim expected
    absences of exactly ten days and of nine days."""
    rules = setup_catalogue(rules=[MIDDLE_IN_HOME_RULE])
    student_a = register_student(student_number="S-0001", full_name="Ada Lin")
    student_b = register_student(student_number="S-0002", full_name="Ben Ortiz")
    case_a = open_case(student_a["id"], delivery_mode="IN_HOME")
    case_b = open_case(student_b["id"], delivery_mode="IN_HOME")
    certification_a = submit_certification(
        case_a["id"],
        physician_npi="1234567890",
        certified_start_date="2026-09-07",
        certified_end_date="2026-09-16",
        expected_absence_days=10,
        signature_date="2026-09-01",
    )
    certification_b = submit_certification(
        case_b["id"],
        physician_npi="1234567890",
        certified_start_date="2026-09-07",
        certified_end_date="2026-09-15",
        expected_absence_days=9,
        signature_date="2026-09-01",
    )
    return {
        "rule": rules[0],
        "case_a": case_a,
        "case_b": case_b,
        "certification_a": certification_a,
        "certification_b": certification_b,
    }


class TestMidDurationBonusThreshold:
    """Thirty days earns the bonus; twenty-nine does not."""

    def test_thirty_days_earns_the_bonus_and_twenty_nine_does_not(self):
        """Two otherwise identical cases settle at 390 and 360 weekly minutes, a delta
        of exactly the thirty-minute mid-duration bonus.

        The PRD states: "An effective duration of at least 60 calendar days earns a
        bonus of 60 minutes; failing that, an effective duration of at least 30
        calendar days earns a bonus of 30 minutes; a shorter effective duration earns
        no bonus."

        Design: Difficulty/boundary_precision_check/mid_duration_bonus_applies_at_exactly_thirty_expected_absence_days_not_at_twenty_nine
        """
        bundle = _two_cases_awaiting_review_at_twenty_nine_and_thirty_days()

        review_certification(bundle["certification_a"]["id"], "ACCEPT")
        review_certification(bundle["certification_b"]["id"], "ACCEPT")

        case_a = read_case(bundle["case_a"]["id"])
        case_b = read_case(bundle["case_b"]["id"])
        assert case_a["weekly_entitled_minutes"] == 360, (
            "twenty-nine days falls short of the inclusive thirty-day lower bound"
        )
        assert case_b["weekly_entitled_minutes"] == 390, (
            "exactly thirty days meets the inclusive lower bound"
        )
        assert (
            case_b["weekly_entitled_minutes"] - case_a["weekly_entitled_minutes"] == 30
        ), "one day of expected absence is worth the whole bonus at the boundary"

    def test_both_cases_resolve_to_the_same_published_rule(self):
        """Both cases become ELIGIBLE against the one published MIDDLE / IN_HOME rule,
        so the rule cannot explain the thirty-minute delta.

        The PRD states: "Next the case's `entitlement_rule_id` is resolved by matching
        the student's `grade_band` and the case's `delivery_mode` against the
        `PUBLISHED` entitlement catalogue, failing with
        `ERR_NO_PUBLISHED_ENTITLEMENT_RULE` if no such rule exists."

        Design: Difficulty/boundary_precision_check/mid_duration_bonus_applies_at_exactly_thirty_expected_absence_days_not_at_twenty_nine
        """
        bundle = _two_cases_awaiting_review_at_twenty_nine_and_thirty_days()

        review_certification(bundle["certification_a"]["id"], "ACCEPT")
        review_certification(bundle["certification_b"]["id"], "ACCEPT")

        case_a = read_case(bundle["case_a"]["id"])
        case_b = read_case(bundle["case_b"]["id"])
        assert case_a["service_status"] == "ELIGIBLE"
        assert case_b["service_status"] == "ELIGIBLE"
        assert case_a["entitlement_rule_id"] == bundle["rule"]["id"]
        assert case_b["entitlement_rule_id"] == bundle["rule"]["id"]


class TestForfeitRatioBoundary:
    """A ratio of exactly 0.50 reconciles; 0.46 forfeits."""

    def test_a_ratio_of_exactly_zero_point_five_zero_reconciles(self):
        """390 verified minutes against a 780-minute entitled total is a 0.50 ratio,
        which recaptures 98 of the 390-minute shortfall and settles at 292.

        The PRD states: "Note carefully that a ratio of exactly 0.50 lands in the
        twenty-five-percent band and does not forfeit."

        The PRD states: "In the three non-forfeit bands the shortfall is the entitled
        total minus the raw final figure, floored at 0; `final_apportionment_minutes`
        is set to the raw final figure; `recapture_minutes` is the shortfall multiplied
        by the band's recapture rate, rounded half up to whole minutes;
        `net_apportionment_minutes` is the raw final figure minus `recapture_minutes`,
        floored at 0; and the funding posture moves `ACCRUING → RECONCILED`."

        Design: Difficulty/boundary_precision_check/delivery_ratio_of_exactly_zero_point_five_zero_reconciles_while_zero_point_four_six_forfeits
        """
        bundle = _two_cases_astride_the_forfeit_boundary()

        reconciled = validate_success(
            api_client.reconcile_case_funding(bundle["a"]["case"]["id"], PA_HEADERS)
        )
        assert reconciled["final_apportionment_minutes"] == 390, (
            "240 minutes in ISO week 37 and 150 in ISO week 38, neither week capped"
        )
        assert reconciled["delivery_ratio_pct"] == 0.50
        assert reconciled["recapture_minutes"] == 98, (
            "a quarter of the 390-minute shortfall is 97.5, which rounds half up to 98"
        )
        assert reconciled["net_apportionment_minutes"] == 292
        assert reconciled["funding_status"] == "RECONCILED"

    def test_a_ratio_of_zero_point_four_six_forfeits_the_whole_claim(self):
        """The same case one thirty-minute session short reaches only 0.46 and forfeits
        every one of its 360 verified minutes.

        The PRD states: "A ratio below 0.50 forfeits."

        The PRD states: "In the forfeit band `final_apportionment_minutes` is set to
        the raw final figure, `recapture_minutes` is set to that same raw final figure,
        `net_apportionment_minutes` is 0, and the funding posture moves `ACCRUING →
        FORFEITED`, which is terminal."

        Design: Difficulty/boundary_precision_check/delivery_ratio_of_exactly_zero_point_five_zero_reconciles_while_zero_point_four_six_forfeits
        """
        bundle = _two_cases_astride_the_forfeit_boundary()

        reconciled = validate_success(
            api_client.reconcile_case_funding(bundle["b"]["case"]["id"], PA_HEADERS)
        )
        assert reconciled["final_apportionment_minutes"] == 360
        assert reconciled["delivery_ratio_pct"] == 0.46, (
            "360 divided by 780 is 0.4615, which rounds half up to 0.46"
        )
        assert reconciled["recapture_minutes"] == 360, (
            "the forfeit band recaptures the entire raw final figure"
        )
        assert reconciled["net_apportionment_minutes"] == 0
        assert reconciled["funding_status"] == "FORFEITED"


class TestDailyMinuteCeilingAndMinimumGap:
    """Exactly 240 minutes and exactly 15 minutes of gap both pass."""

    def test_the_exact_ceiling_passes_and_the_next_thirty_minutes_does_not(self):
        """A second visit starting exactly fifteen minutes later brings the day to
        exactly 240 minutes and is accepted; the next thirty minutes is refused.

        The PRD states: "Finally, the student's day is capped: the sum of
        `scheduled_minutes` over the case's sessions with `status` `SCHEDULED` or
        `DELIVERED` on the same `service_date`, plus the new session's own
        `scheduled_minutes`, may not exceed the rule's `max_daily_minutes`; a total
        exactly equal to `max_daily_minutes` passes, and any excess is
        `ERR_STUDENT_DAILY_LIMIT`."

        Design: Difficulty/boundary_precision_check/daily_minute_cap_accepts_exactly_two_hundred_forty_and_rejects_the_next_thirty_minutes
        """
        bundle = _case_holding_two_hundred_forty_minutes_on_one_day()
        second = _book_the_second_session_at_the_exact_gap(bundle)
        assert second["scheduled_minutes"] == 120
        assert second["status"] == "SCHEDULED"

        validate_error(
            api_client.create_session(
                create_session_payload(
                    bundle["case"]["id"],
                    bundle["primary_assignment"]["id"],
                    scheduled_start="2026-09-09T13:30:00Z",
                    scheduled_end="2026-09-09T14:00:00Z",
                    delivery_mode="IN_HOME",
                    subject="ELA",
                ),
                CM_HEADERS,
            ),
            ApiErrorId.ERR_STUDENT_DAILY_LIMIT.value,
            422,
        )

        same_day = [
            session
            for session in sessions_for_case(bundle["case"]["id"])
            if session["service_date"] == "2026-09-09"
        ]
        assert len(same_day) == 2, "the refused visit is not booked"
        assert {session["status"] for session in same_day} == {"SCHEDULED"}
        assert sum(session["scheduled_minutes"] for session in same_day) == 240, (
            "the day stands at exactly the ceiling, aggregated across both teachers"
        )

    def test_a_gap_one_step_below_the_minimum_is_refused_before_the_daily_cap(self):
        """A visit starting only ten minutes after the second one ends is refused for
        the gap, which is checked before the daily aggregate.

        The PRD states: "And two sessions of the same case on the same `service_date`
        must be separated by at least the rule's `min_gap_minutes`, measured as the
        closed-interval gap against every existing session of that case on that date
        whose `status` is `SCHEDULED` or `DELIVERED`: a gap exactly equal to
        `min_gap_minutes` passes, while any smaller gap — including endpoints that
        merely touch — fails with `ERR_SESSION_GAP_TOO_SHORT`."

        Design: Difficulty/boundary_precision_check/daily_minute_cap_accepts_exactly_two_hundred_forty_and_rejects_the_next_thirty_minutes
        """
        bundle = _case_holding_two_hundred_forty_minutes_on_one_day()
        _book_the_second_session_at_the_exact_gap(bundle)

        validate_error(
            api_client.create_session(
                create_session_payload(
                    bundle["case"]["id"],
                    bundle["primary_assignment"]["id"],
                    scheduled_start="2026-09-09T13:25:00Z",
                    scheduled_end="2026-09-09T13:55:00Z",
                    delivery_mode="IN_HOME",
                    subject="ELA",
                ),
                CM_HEADERS,
            ),
            ApiErrorId.ERR_SESSION_GAP_TOO_SHORT.value,
            409,
        )
        assert len(sessions_for_case(bundle["case"]["id"])) == 2


class TestAbsenceDurationFloorForAcceptance:
    """Exactly ten expected days is acceptable; nine is not."""

    def test_exactly_ten_days_is_accepted_and_earns_no_duration_bonus(self):
        """A ten-day certification is accepted, moves the case to ELIGIBLE, and leaves
        the entitlement at the unbonused 360 minutes.

        The PRD states: "It requires that the certification's `certified_end_date` not
        precede its `certified_start_date` and that `expected_absence_days` be at least
        10 — a shorter expected absence is rejected with
        `ERR_ABSENCE_DURATION_TOO_SHORT`, on the reasoning that a brief absence is a
        matter for the campus rather than for the homebound program."

        Design: Difficulty/boundary_precision_check/certification_acceptance_requires_exactly_ten_expected_absence_days_and_rejects_nine
        """
        bundle = _two_cases_awaiting_review_at_ten_and_nine_days()

        accepted = review_certification(bundle["certification_a"]["id"], "ACCEPT")
        assert accepted["status"] == "ACCEPTED"

        case = read_case(bundle["case_a"]["id"])
        assert case["service_status"] == "ELIGIBLE"
        assert case["weekly_entitled_minutes"] == 360, (
            "ten days is below the thirty-day bonus threshold"
        )

    def test_nine_days_is_refused_and_no_entitlement_leaks_onto_the_case(self):
        """A nine-day certification is refused, stays SUBMITTED, and leaves its case in
        PENDING_CERT_REVIEW with no rule and no entitlement resolved.

        The PRD states: "It requires that the certification's `certified_end_date` not
        precede its `certified_start_date` and that `expected_absence_days` be at least
        10 — a shorter expected absence is rejected with
        `ERR_ABSENCE_DURATION_TOO_SHORT`, on the reasoning that a brief absence is a
        matter for the campus rather than for the homebound program."

        Design: Difficulty/boundary_precision_check/certification_acceptance_requires_exactly_ten_expected_absence_days_and_rejects_nine
        """
        bundle = _two_cases_awaiting_review_at_ten_and_nine_days()

        validate_error(
            api_client.review_certification(
                bundle["certification_b"]["id"],
                review_certification_payload(
                    "ACCEPT", review_note="Nine days attempted"
                ),
                NR_HEADERS,
            ),
            ApiErrorId.ERR_ABSENCE_DURATION_TOO_SHORT.value,
            422,
        )

        certification = validate_success(
            api_client.get_certification(bundle["certification_b"]["id"], CM_HEADERS)
        )
        assert certification["status"] == "SUBMITTED", (
            "the refused review leaves the document where it was"
        )

        case = read_case(bundle["case_b"]["id"])
        assert case["service_status"] == "PENDING_CERT_REVIEW"
        assert case.get("entitlement_rule_id") is None, (
            "no partial entitlement resolution may leak from a failed review"
        )
