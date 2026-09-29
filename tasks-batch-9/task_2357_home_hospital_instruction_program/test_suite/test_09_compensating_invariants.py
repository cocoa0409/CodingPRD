"""Corrections that must cancel out exactly rather than approximately.

An attendance ledger is never edited, so undoing a delivery means appending an
opposite row and watching the signed sum return to where it started. An
allocation is never decremented, so releasing a staffing row means re-dividing
the whole entitlement and watching the active rows still sum to it exactly.
"""

from test_helpers import (
    ApiErrorId,
    MIDDLE_IN_HOME_RULE,
    PA_HEADERS,
    accept_assignment,
    add_support_assignment,
    api_client,
    entries_for_session,
    ledger_entries_for_case,
    log_session_delivered,
    propose_assignment,
    read_assignment,
    read_case,
    read_session,
    read_teacher,
    register_teacher,
    release_assignment_payload,
    schedule_session,
    set_clock,
    setup_active_case,
    validate_error,
    validate_success,
    verify_session,
    void_session_payload,
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


def _case_with_one_verified_delivery() -> dict:
    """An ACTIVE / ACCRUING case holding a single verified 120-minute delivery, with
    the clock at 2026-09-08T09:00:00Z so no service week has completed."""
    bundle = setup_active_case(
        rules=[MIDDLE_IN_HOME_RULE],
        certification=dict(CERT_WINDOW),
        safety_review=dict(CLEARED_SAFETY_REVIEW),
    )
    session = schedule_session(
        bundle["case"]["id"],
        bundle["primary_assignment"]["id"],
        scheduled_start="2026-09-07T09:00:00Z",
        scheduled_end="2026-09-07T11:00:00Z",
        delivery_mode="IN_HOME",
        subject="MATH",
    )
    set_clock("2026-09-07T18:00:00Z")
    log_session_delivered(session["id"], bundle["teacher"]["id"], 120)
    bundle["session"] = verify_session(session["id"])
    set_clock("2026-09-08T09:00:00Z")
    bundle["case"] = read_case(bundle["case"]["id"])
    return bundle


def _case_with_a_primary_and_one_support_row() -> dict:
    """An ACTIVE case at 390 weekly minutes split 275 / 115 across one primary and one
    support assignment, with no session referencing the support row."""
    bundle = setup_active_case(
        rules=[MIDDLE_IN_HOME_RULE],
        certification=dict(CERT_WINDOW),
        safety_review=dict(CLEARED_SAFETY_REVIEW),
    )
    return add_support_assignment(
        bundle, teacher={"max_weekly_caseload_minutes": 600}
    )


def _case_staffed_with_four_roles() -> dict:
    """An ACTIVE case at 390 weekly minutes carrying an active primary row, two active
    support rows and one active special-education-service row."""
    bundle = setup_active_case(
        rules=[MIDDLE_IN_HOME_RULE],
        certification=dict(CERT_WINDOW),
        safety_review=dict(CLEARED_SAFETY_REVIEW),
    )
    case_id = bundle["case"]["id"]

    bundle["support_1"] = add_support_assignment(
        bundle, teacher={"max_weekly_caseload_minutes": 600}
    )["support_assignment"]
    bundle["support_teacher_1"] = bundle["support_teacher"]

    second_support_teacher = register_teacher(
        full_name="Ivy Chen",
        employee_number="E-1003",
        credential_areas=["SOCIAL_STUDIES"],
        grade_bands=["MIDDLE"],
        max_weekly_caseload_minutes=600,
    )
    proposal = propose_assignment(case_id, "SUPPORT", second_support_teacher["id"])
    bundle["support_teacher_2"] = second_support_teacher
    bundle["support_2"] = accept_assignment(
        proposal["id"], second_support_teacher["id"]
    )

    sped_teacher = register_teacher(
        full_name="Omar Diaz",
        employee_number="E-1005",
        credential_areas=["SPED"],
        grade_bands=["MIDDLE"],
        max_weekly_caseload_minutes=600,
    )
    sped_proposal = propose_assignment(case_id, "SPED_SERVICE", sped_teacher["id"])
    bundle["sped_teacher"] = sped_teacher
    bundle["sped_assignment"] = accept_assignment(
        sped_proposal["id"], sped_teacher["id"]
    )
    return bundle


def _active_allocation_total(bundle: dict) -> int:
    rows = [
        read_assignment(bundle[key]["id"])
        for key in ("primary_assignment", "support_1", "support_2", "sped_assignment")
    ]
    return sum(
        row["weekly_committed_minutes"] for row in rows if row["status"] == "ACTIVE"
    )


class TestVoidCancelsTheLedgerWithoutEditingIt:
    """The correction is a new opposite row, not a change to the old one."""

    def test_the_reversal_row_returns_the_signed_sum_to_zero(self):
        """One HB_PRESENT row of 120 minutes becomes two rows summing to zero, and the
        original row is left exactly as it was.

        The PRD states: "Attendance ledger rows are append-only: once written they are
        never updated, corrected in place, or deleted."

        The PRD states: "It appends a compensating ledger row with `attendance_code`
        `HB_REVERSAL`, whose `reversal_of_entry_id` points at the entry being reversed
        and whose `apportionment_minutes` is the arithmetic negation of that entry's
        `apportionment_minutes`."

        Design: Difficulty/compensating_invariant/void_writes_a_reversal_row_that_returns_the_ledger_sum_to_zero_without_deleting_history
        """
        bundle = _case_with_one_verified_delivery()
        case_id = bundle["case"]["id"]

        before = ledger_entries_for_case(case_id)
        assert len(before) == 1
        assert before[0]["attendance_code"] == "HB_PRESENT"
        assert before[0]["apportionment_minutes"] == 120
        assert bundle["case"]["reported_apportionment_minutes"] == 120

        voided = validate_success(
            api_client.void_session(
                bundle["session"]["id"],
                void_session_payload(void_reason="DOCUMENTATION_DEFECT"),
                PA_HEADERS,
            )
        )
        assert voided["status"] == "VOIDED"
        assert voided["credited_minutes"] == 0

        after = ledger_entries_for_case(case_id)
        assert len(after) == 2, "the correction adds a row rather than replacing one"
        original, reversal = after[0], after[1]
        assert original["id"] == before[0]["id"]
        assert original["apportionment_minutes"] == 120, (
            "the delivered row is never rewritten"
        )
        assert "version" not in original, (
            "an attendance row carries no version because nothing mutates it"
        )
        assert "updated_at" not in original

        assert reversal["attendance_code"] == "HB_REVERSAL"
        assert reversal["apportionment_minutes"] == -120
        assert reversal["delivery_mode"] == "IN_HOME"
        assert reversal["service_date"] == "2026-09-07"
        assert reversal["reversal_of_entry_id"] == original["id"]

        signed_sum = sum(entry["apportionment_minutes"] for entry in after)
        assert signed_sum == 0
        assert read_case(case_id)["reported_apportionment_minutes"] == signed_sum, (
            "the case figure is the signed sum of the whole ledger"
        )

    def test_the_posture_holds_and_a_second_void_appends_nothing(self):
        """No service week has completed, so the funding posture stays ACCRUING, and a
        second void of the same session is refused without touching the ledger.

        The PRD states: "Count the completed service weeks as the number of whole
        seven-day spans between the case's `service_start_date` and the clock date,
        taking the floor so a partial week contributes nothing."

        The PRD states: "Separately, a `ProgramAdministrator` may void a `DELIVERED`
        session, recording a `void_reason` of `DOCUMENTATION_DEFECT`, `DUPLICATE_ENTRY`,
        `AUDIT_REVERSAL`, or `MODE_INELIGIBLE`; voiding a session that is not
        `DELIVERED` is `ERR_SESSION_NOT_DELIVERED`."

        Design: Difficulty/compensating_invariant/void_writes_a_reversal_row_that_returns_the_ledger_sum_to_zero_without_deleting_history
        """
        bundle = _case_with_one_verified_delivery()
        session_id = bundle["session"]["id"]

        validate_success(
            api_client.void_session(
                session_id,
                void_session_payload(void_reason="DOCUMENTATION_DEFECT"),
                PA_HEADERS,
            )
        )
        case = read_case(bundle["case"]["id"])
        assert case["service_gap_minutes"] == 0, (
            "one elapsed day is not a completed service week"
        )
        assert case["funding_status"] == "ACCRUING", (
            "with nothing yet owed the reversal cannot open a hold"
        )

        validate_error(
            api_client.void_session(
                session_id,
                void_session_payload(void_reason="DUPLICATE_ENTRY"),
                PA_HEADERS,
            ),
            ApiErrorId.ERR_SESSION_NOT_DELIVERED.value,
            409,
        )
        assert len(entries_for_session(session_id)) == 2, (
            "the refused second void appends no third row"
        )
        assert read_session(session_id)["status"] == "VOIDED"


class TestSupportReleaseReturnsEveryMinuteToThePrimaryRow:
    """The allocation is re-divided, never decremented."""

    def test_release_moves_the_whole_entitlement_onto_the_primary_row(self):
        """275 plus 115 becomes 390 plus nothing: the released row is zeroed and the
        primary row absorbs every minute.

        The PRD states: "Only assignments whose `status` is `ACTIVE` participate;
        `PROPOSED`, `DECLINED` and `RELEASED` assignments are excluded and always hold
        `weekly_committed_minutes` 0."

        The PRD states: "The primary assignment nominally carries the remaining seventy
        percent, and concretely it receives the case's `weekly_entitled_minutes` minus
        the support total — so the primary row absorbs the entire rounding residual and
        the sum of `weekly_committed_minutes` across active assignments equals
        `weekly_entitled_minutes` exactly."

        Design: Difficulty/compensating_invariant/support_assignment_release_returns_every_minute_to_the_primary_row_and_zeroes_the_teacher
        """
        bundle = _case_with_a_primary_and_one_support_row()
        assert bundle["case"]["weekly_entitled_minutes"] == 390
        assert bundle["primary_assignment"]["weekly_committed_minutes"] == 275
        assert bundle["support_assignment"]["weekly_committed_minutes"] == 115

        released = validate_success(
            api_client.release_assignment(
                bundle["support_assignment"]["id"],
                release_assignment_payload(release_reason="CASELOAD_REBALANCE"),
                PA_HEADERS,
            )
        )
        assert released["status"] == "RELEASED"
        assert released["release_reason"] == "CASELOAD_REBALANCE"
        assert released["weekly_committed_minutes"] == 0, (
            "a released row cannot double-count"
        )

        primary = read_assignment(bundle["primary_assignment"]["id"])
        assert primary["weekly_committed_minutes"] == 390, (
            "with no active support row the support total is 0"
        )

    def test_the_teacher_totals_are_re_summed_and_a_second_release_is_refused(self):
        """The released teacher lands on exactly zero and the primary teacher on exactly
        390, and releasing the same row again is refused.

        The PRD states: "It is recomputed as a complete re-sum rather than an
        incremental adjustment whenever an allocation changes, which is what makes
        accept-and-release pairs exactly conservative."

        The PRD states: "Release is a `ProgramAdministrator` action against an `ACTIVE`
        assignment; releasing anything else is `ERR_ASSIGNMENT_NOT_ACTIVE`."

        Design: Difficulty/compensating_invariant/support_assignment_release_returns_every_minute_to_the_primary_row_and_zeroes_the_teacher
        """
        bundle = _case_with_a_primary_and_one_support_row()
        support_assignment_id = bundle["support_assignment"]["id"]

        validate_success(
            api_client.release_assignment(
                support_assignment_id,
                release_assignment_payload(release_reason="CASELOAD_REBALANCE"),
                PA_HEADERS,
            )
        )

        support_teacher = read_teacher(bundle["support_teacher"]["id"])
        assert support_teacher["committed_weekly_minutes"] == 0
        assert support_teacher["over_cap"] is False
        primary_teacher = read_teacher(bundle["teacher"]["id"])
        assert primary_teacher["committed_weekly_minutes"] == 390
        assert primary_teacher["over_cap"] is False

        validate_error(
            api_client.release_assignment(
                support_assignment_id,
                release_assignment_payload(release_reason="STAFF_LEAVE"),
                PA_HEADERS,
            ),
            ApiErrorId.ERR_ASSIGNMENT_NOT_ACTIVE.value,
            409,
        )
        assert read_assignment(support_assignment_id)["weekly_committed_minutes"] == 0
        assert (
            read_teacher(bundle["teacher"]["id"])["committed_weekly_minutes"] == 390
        ), "the refused release changes no minute total"


class TestTwoSupportRowsSplitWithRoundingResidual:
    """Neither share divides cleanly, so the primary row carries the remainder."""

    def test_two_support_rows_each_take_sixty_and_the_sped_row_takes_nothing(self):
        """A second support row re-divides the thirty-percent share into 60 and 60,
        leaving 270 on the primary row, and the special-education row receives 0.

        The PRD states: "Support staff share thirty percent of the entitlement: when the
        case has at least one active support assignment, multiply
        `weekly_entitled_minutes` by 0.30, divide by the number of active support
        assignments, divide by five, round half up to a whole number, and multiply back
        by five; every active support assignment receives that same per-support figure,
        and the support total is that figure multiplied by the number of support
        assignments."

        The PRD states: "Every active special-education-service assignment always
        receives 0."

        Design: Difficulty/compensating_invariant/two_support_rows_split_with_rounding_and_the_primary_row_absorbs_the_residual_on_every_change
        """
        bundle = _case_staffed_with_four_roles()

        assert read_assignment(bundle["support_1"]["id"])["weekly_committed_minutes"] == 60
        assert read_assignment(bundle["support_2"]["id"])["weekly_committed_minutes"] == 60
        assert (
            read_assignment(bundle["primary_assignment"]["id"])[
                "weekly_committed_minutes"
            ]
            == 270
        ), "390 minutes less a 120-minute support total"

        sped = read_assignment(bundle["sped_assignment"]["id"])
        assert sped["status"] == "ACTIVE"
        assert sped["weekly_committed_minutes"] == 0
        assert read_teacher(bundle["sped_teacher"]["id"])["committed_weekly_minutes"] == 0

        assert _active_allocation_total(bundle) == 390, (
            "the four active rows sum to the entitlement exactly"
        )

    def test_releasing_one_support_row_re_divides_by_one_instead_of_two(self):
        """The per-support figure jumps from 60 to 115 and the primary residual from 270
        to 275, with the active rows still summing to exactly 390.

        The PRD states: "A release records a `release_reason` from `CASE_CLOSED`,
        `MODE_CHANGE`, `CASELOAD_REBALANCE`, `CLEARANCE_LAPSED`, and `STAFF_LEAVE`,
        moves the assignment `ACTIVE → RELEASED`, stamps `released_at` with the clock
        instant, sets its `weekly_committed_minutes` to 0, recomputes the allocation
        across the case's remaining active assignments, and recomputes
        `committed_weekly_minutes` and `over_cap` for every teacher whose allocation
        changed."

        Design: Difficulty/compensating_invariant/two_support_rows_split_with_rounding_and_the_primary_row_absorbs_the_residual_on_every_change
        """
        bundle = _case_staffed_with_four_roles()
        assert _active_allocation_total(bundle) == 390

        released = validate_success(
            api_client.release_assignment(
                bundle["support_2"]["id"],
                release_assignment_payload(release_reason="CASELOAD_REBALANCE"),
                PA_HEADERS,
            )
        )
        assert released["status"] == "RELEASED"
        assert released["weekly_committed_minutes"] == 0

        assert (
            read_assignment(bundle["support_1"]["id"])["weekly_committed_minutes"] == 115
        ), "the remaining support row now divides the share by one"
        assert (
            read_assignment(bundle["primary_assignment"]["id"])[
                "weekly_committed_minutes"
            ]
            == 275
        )
        assert _active_allocation_total(bundle) == 390, (
            "the invariant holds across the divisor change, never 385 or 395"
        )

        assert read_teacher(bundle["teacher"]["id"])["committed_weekly_minutes"] == 275
        assert (
            read_teacher(bundle["support_teacher_1"]["id"])["committed_weekly_minutes"]
            == 115
        )
        assert (
            read_teacher(bundle["support_teacher_2"]["id"])["committed_weekly_minutes"]
            == 0
        )
