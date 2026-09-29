"""State machines that loop, fork and terminate rather than run straight through.

The case service dimension cycles through extension review and back; an
extension request cycles between review and information-requested under a hard
loop bound; and a session forks into a non-delivery branch, spawns a make-up and
then reaches a terminal voided state.
"""

from test_helpers import (
    ApiErrorId,
    CM_HEADERS,
    MIDDLE_IN_HOME_RULE,
    PA_HEADERS,
    api_client,
    decide_extension_payload,
    entries_for_session,
    ledger_entries_for_case,
    log_delivered_payload,
    log_session,
    log_student_unavailable_payload,
    makeup_session_payload,
    open_extension_request,
    read_assignment,
    read_case,
    read_session,
    read_teacher,
    request_extension_info_payload,
    resubmit_extension_payload,
    schedule_session,
    set_clock,
    setup_active_case,
    validate_error,
    validate_success,
    void_session_payload,
)

CERT_WINDOW = {
    "expected_absence_days": 30,
    "certified_start_date": "2026-09-07",
    "certified_end_date": "2026-10-07",
    "signature_date": "2026-09-01",
}


def _active_case() -> dict:
    """An ACTIVE / ACCRUING grade-7 in-home case at 390 weekly minutes."""
    return setup_active_case(
        rules=[MIDDLE_IN_HOME_RULE],
        certification=dict(CERT_WINDOW),
        safety_review={"hazard_findings": ["UNLIT_ACCESS"], "escort_available": False},
    )


def _request_under_review(bundle: dict) -> dict:
    """One extension request on the bundle's case, moved to UNDER_REVIEW."""
    request = open_extension_request(
        bundle["case"]["id"],
        bundle["certification"]["id"],
        requested_additional_days=30,
        justification="Surgeon extended the recovery window by thirty days",
    )
    return validate_success(
        api_client.start_extension_review(request["id"], PA_HEADERS)
    )


class TestCaseExtensionCycle:
    """ACTIVE leaves for EXTENSION_PENDING and comes back carrying a new window."""

    def test_service_dimension_cycles_while_the_funding_dimension_stays_accruing(self):
        """Opening the request moves the case to EXTENSION_PENDING and approving it
        returns the case to ACTIVE, with funding ACCRUING throughout.

        The PRD states: "Either decision stamps `decided_by_user_id` with the acting
        `X-User-ID`, moves the case `EXTENSION_PENDING → ACTIVE`, and increments the
        case's `version` by one — the loop `ACTIVE → EXTENSION_PENDING → ACTIVE` is
        deliberately cyclic, and `extension_count` reaching 2 is what terminates it."

        Design: Difficulty/non_linear_state_machine/case_extension_cycle_returns_to_active_while_funding_dimension_stays_accruing
        """
        bundle = _active_case()

        request = open_extension_request(
            bundle["case"]["id"],
            bundle["certification"]["id"],
            requested_additional_days=30,
            justification="Surgeon extended the recovery window by thirty days",
        )
        pending = read_case(bundle["case"]["id"])
        assert pending["service_status"] == "EXTENSION_PENDING"
        assert pending["funding_status"] == "ACCRUING", (
            "the funding dimension is untouched by an extension request"
        )
        assert request["submitted_by_user_id"] == "cm-001"
        assert request["resubmit_count"] == 0

        validate_success(api_client.start_extension_review(request["id"], PA_HEADERS))
        decided = validate_success(
            api_client.decide_extension_request(
                request["id"],
                decide_extension_payload("APPROVED", decision_note="Extension granted"),
                PA_HEADERS,
            )
        )
        assert decided["status"] == "APPROVED"
        assert decided["decided_by_user_id"] == "pa-001"

        settled = read_case(bundle["case"]["id"])
        assert settled["service_status"] == "ACTIVE", "the cycle closes back on ACTIVE"
        assert settled["funding_status"] == "ACCRUING"

    def test_return_trip_carries_a_new_window_entitlement_and_allocation(self):
        """The approved thirty days push the certified end date to 2026-11-06, cross
        the sixty-day bonus threshold and re-allocate 420 minutes to the primary row.

        The PRD states: "An `APPROVED` decision moves the request `UNDER_REVIEW →
        APPROVED` and cascades into the case: `certified_end_date` is advanced by
        `requested_additional_days` calendar days from its current value,
        `extension_count` increments by one, `weekly_entitled_minutes` is recomputed
        per §3.3 — where the newly approved days now feed the effective absence
        duration and may cross a duration-bonus threshold — the weekly allocation is
        recomputed across the case's active assignments, and `committed_weekly_minutes`
        is recomputed for every affected teacher."

        Design: Difficulty/non_linear_state_machine/case_extension_cycle_returns_to_active_while_funding_dimension_stays_accruing
        """
        bundle = _active_case()
        request = _request_under_review(bundle)

        validate_success(
            api_client.decide_extension_request(
                request["id"],
                decide_extension_payload("APPROVED", decision_note="Extension granted"),
                PA_HEADERS,
            )
        )

        case = read_case(bundle["case"]["id"])
        assert case["extension_count"] == 1
        assert case["certified_end_date"] == "2026-11-06", (
            "thirty calendar days beyond 2026-10-07"
        )
        assert case["weekly_entitled_minutes"] == 420, (
            "an effective absence of sixty days earns the sixty-minute bonus"
        )

        assignment = read_assignment(bundle["primary_assignment"]["id"])
        assert assignment["weekly_committed_minutes"] == 420, (
            "with no active support row the primary row carries the whole entitlement"
        )
        teacher = read_teacher(bundle["teacher"]["id"])
        assert teacher["committed_weekly_minutes"] == 420


class TestExtensionInfoRequestedLoop:
    """UNDER_REVIEW and INFO_REQUESTED loop twice and then stop."""

    def test_the_loop_can_be_traversed_exactly_twice(self):
        """Each resubmission moves the request back to UNDER_REVIEW and increments the
        resubmit counter, reaching two.

        The PRD states: "resubmission replaces the request's `certification_id` with
        that newer accepted certification, increments `resubmit_count` by one, and
        moves the request `INFO_REQUESTED → UNDER_REVIEW`."

        Design: Difficulty/non_linear_state_machine/extension_info_requested_cycle_caps_resubmit_count_at_two
        """
        bundle = _active_case()
        request = _request_under_review(bundle)
        certification_id = bundle["certification"]["id"]

        for expected_count, note in ((1, "Attach the updated physician letter"),
                                     (2, "Letter is unsigned; resend")):
            sent_back = validate_success(
                api_client.request_extension_info(
                    request["id"], request_extension_info_payload(info_note=note),
                    PA_HEADERS,
                )
            )
            assert sent_back["status"] == "INFO_REQUESTED"

            resubmitted = validate_success(
                api_client.resubmit_extension_request(
                    request["id"],
                    resubmit_extension_payload(certification_id),
                    CM_HEADERS,
                )
            )
            assert resubmitted["status"] == "UNDER_REVIEW"
            assert resubmitted["resubmit_count"] == expected_count, (
                "each resubmission increments the counter by exactly one"
            )

    def test_the_third_resubmission_is_refused_and_nothing_moves(self):
        """A third resubmission is rejected, the request stays in INFO_REQUESTED at a
        resubmit count of two, and the case's window is untouched.

        The PRD states: "This `UNDER_REVIEW ↔ INFO_REQUESTED` loop is bounded:
        `resubmit_count` must be less than 2 at the moment of resubmission, so a
        request can cycle back into review at most twice, and a further attempt is
        rejected with `ERR_EXTENSION_RESUBMIT_LIMIT`."

        Design: Difficulty/non_linear_state_machine/extension_info_requested_cycle_caps_resubmit_count_at_two
        """
        bundle = _active_case()
        request = _request_under_review(bundle)
        certification_id = bundle["certification"]["id"]

        for note in ("Attach the updated physician letter", "Letter is unsigned; resend"):
            validate_success(
                api_client.request_extension_info(
                    request["id"], request_extension_info_payload(info_note=note),
                    PA_HEADERS,
                )
            )
            validate_success(
                api_client.resubmit_extension_request(
                    request["id"],
                    resubmit_extension_payload(certification_id),
                    CM_HEADERS,
                )
            )
        validate_success(
            api_client.request_extension_info(
                request["id"],
                request_extension_info_payload(
                    info_note="Still missing the diagnosis update"
                ),
                PA_HEADERS,
            )
        )

        validate_error(
            api_client.resubmit_extension_request(
                request["id"], resubmit_extension_payload(certification_id), CM_HEADERS
            ),
            ApiErrorId.ERR_EXTENSION_RESUBMIT_LIMIT.value,
        )

        stuck = validate_success(
            api_client.get_extension_request(request["id"], CM_HEADERS)
        )
        assert stuck["status"] == "INFO_REQUESTED", (
            "the refused resubmission leaves the request where it was"
        )
        assert stuck["resubmit_count"] == 2

        case = read_case(bundle["case"]["id"])
        assert case["service_status"] == "EXTENSION_PENDING"
        assert case["certified_end_date"] == "2026-10-07", (
            "no decision has been taken, so the certified window is unchanged"
        )
        assert case["extension_count"] == 0, (
            "extension_count counts only APPROVED extension requests"
        )


class TestSessionBranchesThenVoidsTerminally:
    """A non-delivery fork, a make-up that delivers, and a terminal void."""

    def test_student_unavailable_forks_the_session_and_a_makeup_delivers(self):
        """The missed session codes HB_ABSENT_MEDICAL at zero minutes and adds its
        scheduled minutes to the make-up obligation; the make-up then delivers 120.

        The PRD states: "A `STUDENT_UNAVAILABLE` outcome requires the payload to
        carry an `absence_kind` of either `MEDICAL` or `UNEXCUSED`, advances the
        session `SCHEDULED → STUDENT_UNAVAILABLE`, sets `credited_minutes` to 0, and
        appends a ledger row with `attendance_code` `HB_ABSENT_MEDICAL` when
        `absence_kind` is `MEDICAL` and `HB_ABSENT_UNEXCUSED` when it is
        `UNEXCUSED`, with `apportionment_minutes` 0."

        Design: Difficulty/non_linear_state_machine/session_branches_to_student_unavailable_then_makeup_delivered_then_voided_terminal
        """
        bundle = _active_case()
        missed = schedule_session(
            bundle["case"]["id"],
            bundle["primary_assignment"]["id"],
            scheduled_start="2026-09-07T09:00:00Z",
            scheduled_end="2026-09-07T11:00:00Z",
        )
        set_clock("2026-09-07T12:00:00Z")

        logged = log_session(
            missed["id"],
            bundle["teacher"]["id"],
            log_student_unavailable_payload("MEDICAL"),
        )
        assert logged["status"] == "STUDENT_UNAVAILABLE"
        assert logged["credited_minutes"] == 0

        entries = entries_for_session(missed["id"])
        assert len(entries) == 1, "each outcome writes exactly one ledger row"
        assert entries[0]["attendance_code"] == "HB_ABSENT_MEDICAL"
        assert entries[0]["apportionment_minutes"] == 0

        assert read_case(bundle["case"]["id"])["makeup_obligation_minutes"] == 120, (
            "a non-delivery outcome adds the session's scheduled minutes to the "
            "make-up obligation"
        )

        makeup = validate_success(
            api_client.create_makeup_session(
                missed["id"],
                makeup_session_payload(
                    bundle["primary_assignment"]["id"],
                    scheduled_start="2026-09-09T09:00:00Z",
                    scheduled_end="2026-09-09T11:00:00Z",
                ),
                CM_HEADERS,
            ),
            201,
        )
        assert makeup["makeup_for_session_id"] == missed["id"], (
            "the new session points at the missed one"
        )

        set_clock("2026-09-09T18:00:00Z")
        delivered = log_session(
            makeup["id"], bundle["teacher"]["id"], log_delivered_payload(120)
        )
        assert delivered["credited_minutes"] == 120
        assert read_case(bundle["case"]["id"])["reported_apportionment_minutes"] == 120

    def test_voided_is_terminal_and_a_second_void_is_refused(self):
        """Voiding the delivered make-up returns the case to zero reported minutes
        across three ledger rows, and a second void is rejected.

        The PRD states: "Voiding moves the session `DELIVERED → VOIDED`, sets its
        `credited_minutes` to 0, and clears both `verified_at` and
        `verified_by_user_id`."

        Design: Difficulty/non_linear_state_machine/session_branches_to_student_unavailable_then_makeup_delivered_then_voided_terminal
        """
        bundle = _active_case()
        missed = schedule_session(
            bundle["case"]["id"],
            bundle["primary_assignment"]["id"],
            scheduled_start="2026-09-07T09:00:00Z",
            scheduled_end="2026-09-07T11:00:00Z",
        )
        set_clock("2026-09-07T12:00:00Z")
        log_session(
            missed["id"],
            bundle["teacher"]["id"],
            log_student_unavailable_payload("MEDICAL"),
        )
        makeup = validate_success(
            api_client.create_makeup_session(
                missed["id"],
                makeup_session_payload(
                    bundle["primary_assignment"]["id"],
                    scheduled_start="2026-09-09T09:00:00Z",
                    scheduled_end="2026-09-09T11:00:00Z",
                ),
                CM_HEADERS,
            ),
            201,
        )
        set_clock("2026-09-09T18:00:00Z")
        log_session(makeup["id"], bundle["teacher"]["id"], log_delivered_payload(120))

        voided = validate_success(
            api_client.void_session(
                makeup["id"],
                void_session_payload(void_reason="DOCUMENTATION_DEFECT"),
                PA_HEADERS,
            )
        )
        assert voided["status"] == "VOIDED"
        assert voided["credited_minutes"] == 0
        assert voided.get("verified_at") is None

        assert read_case(bundle["case"]["id"])["reported_apportionment_minutes"] == 0, (
            "the reversal is exactly the negation of the entry it reverses"
        )

        entries = ledger_entries_for_case(bundle["case"]["id"])
        assert [entry["attendance_code"] for entry in entries] == [
            "HB_ABSENT_MEDICAL",
            "HB_PRESENT",
            "HB_REVERSAL",
        ], "ledger rows are appended in order and never edited"
        assert [entry["apportionment_minutes"] for entry in entries] == [0, 120, -120]

        validate_error(
            api_client.void_session(
                makeup["id"],
                void_session_payload(void_reason="DUPLICATE_ENTRY"),
                PA_HEADERS,
            ),
            ApiErrorId.ERR_SESSION_NOT_DELIVERED.value,
        )
        assert read_session(makeup["id"])["status"] == "VOIDED", (
            "the refused second void changes nothing"
        )
