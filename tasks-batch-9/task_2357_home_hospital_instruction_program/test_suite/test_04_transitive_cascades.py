"""Cascades that travel three or more hops from a single write.

One void reverses a ledger row, which moves the funding posture, which resets
campus coordination and regresses a ready transition plan. One safety
finalization rewrites the delivery mode, which re-resolves the entitlement rule,
which re-runs the allocation across two assignments and two teacher rows. One
extension decision does the same from the other end of the case.
"""

from test_helpers import (
    CLASSROOM_TEACHER,
    CM_HEADERS,
    MIDDLE_IN_HOME_RULE,
    MIDDLE_VIRTUAL_RULE,
    PA_HEADERS,
    acknowledge_pacing_sync,
    add_support_assignment,
    api_client,
    decide_extension_payload,
    entries_for_session,
    finalize_safety_review,
    log_session_delivered,
    open_extension_request,
    open_pacing_sync,
    open_transition_plan,
    read_assignment,
    read_case,
    read_session,
    read_teacher,
    record_safety_review,
    register_teacher,
    schedule_session,
    set_clock,
    setup_active_case,
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

FIRST_SAFETY_REVIEW = {"hazard_findings": ["UNLIT_ACCESS"], "escort_available": False}

VIRTUAL_ONLY_HAZARDS = {
    "evidence_source": "ONSITE_WALKTHROUGH",
    "review_date": "2026-09-08",
    "hazard_findings": ["AGGRESSIVE_ANIMAL", "NO_SECONDARY_EXIT", "UNLIT_ACCESS"],
    "escort_available": True,
}


def _reconciled_case_with_a_ready_plan() -> dict:
    """A reconciled case carrying one acknowledged pacing row and a READY plan.

    Four verified 120-minute visits put 480 minutes on the ledger, the case is
    reconciled, one MATH coordination row is opened and acknowledged, and the
    plan is coordinated so that it settles at `READY`. The clock ends at
    2026-09-21T00:00:00Z.
    """
    bundle = setup_active_case(
        rules=[MIDDLE_IN_HOME_RULE],
        certification=dict(CERT_WINDOW),
        safety_review=dict(FIRST_SAFETY_REVIEW),
    )
    case_id = bundle["case"]["id"]
    slots = [
        ("2026-09-07T09:00:00Z", "2026-09-07T11:00:00Z", "MATH"),
        ("2026-09-07T13:00:00Z", "2026-09-07T15:00:00Z", "ELA"),
        ("2026-09-08T09:00:00Z", "2026-09-08T11:00:00Z", "MATH"),
        ("2026-09-08T13:00:00Z", "2026-09-08T15:00:00Z", "ELA"),
    ]
    sessions = [
        schedule_session(
            case_id,
            bundle["primary_assignment"]["id"],
            scheduled_start=start,
            scheduled_end=end,
            delivery_mode="IN_HOME",
            subject=subject,
        )
        for start, end, subject in slots
    ]
    set_clock("2026-09-09T18:00:00Z")
    for session in sessions:
        log_session_delivered(session["id"], bundle["teacher"]["id"], 120)
    for session in sessions:
        verify_session(session["id"])

    set_clock("2026-09-20T00:00:00Z")
    validate_success(api_client.reconcile_case_funding(case_id, PA_HEADERS))

    classroom_teacher = register_teacher(**CLASSROOM_TEACHER)
    sync = open_pacing_sync(
        case_id,
        classroom_teacher["id"],
        subject="MATH",
        pacing_target_unit="Algebra Unit 3",
        assessment_accommodation="EXTENDED_TIME",
    )
    plan = open_transition_plan(
        case_id,
        target_return_date="2026-10-05",
        reintegration_mode="PARTIAL_DAY_RAMP",
        ramp_weeks=2,
    )
    validate_success(api_client.coordinate_transition_plan(plan["id"], CM_HEADERS))
    acknowledge_pacing_sync(sync["id"], classroom_teacher["id"])

    set_clock("2026-09-21T00:00:00Z")
    bundle["classroom_teacher"] = classroom_teacher
    bundle["sync"] = validate_success(api_client.get_pacing_sync(sync["id"], CM_HEADERS))
    bundle["plan"] = validate_success(
        api_client.get_transition_plan(plan["id"], CM_HEADERS)
    )
    bundle["sessions"] = sessions
    bundle["case"] = read_case(case_id)
    return bundle


def _in_home_case_with_two_teachers_and_a_draft_virtual_only_review() -> dict:
    """An in-home case at 390 weekly minutes with a primary and a support row, one
    future scheduled in-home visit, and a second safety review still in DRAFT."""
    bundle = setup_active_case(
        rules=[MIDDLE_IN_HOME_RULE, MIDDLE_VIRTUAL_RULE],
        certification=dict(CERT_WINDOW),
        safety_review=dict(FIRST_SAFETY_REVIEW),
    )
    add_support_assignment(bundle, teacher={"max_weekly_caseload_minutes": 600})
    bundle["future_session"] = schedule_session(
        bundle["case"]["id"],
        bundle["primary_assignment"]["id"],
        scheduled_start="2026-09-14T09:00:00Z",
        scheduled_end="2026-09-14T11:00:00Z",
        delivery_mode="IN_HOME",
        subject="MATH",
    )
    bundle["second_review"] = record_safety_review(
        bundle["case"]["id"], **VIRTUAL_ONLY_HAZARDS
    )
    bundle["rule_virtual"] = bundle["rules"][1]
    bundle["case"] = read_case(bundle["case"]["id"])
    return bundle


def _case_with_two_teachers_and_an_extension_under_review() -> dict:
    """An in-home case at 390 weekly minutes with a primary and a support row and one
    thirty-day extension request sitting at UNDER_REVIEW."""
    bundle = setup_active_case(
        rules=[MIDDLE_IN_HOME_RULE],
        certification=dict(CERT_WINDOW),
        safety_review=dict(FIRST_SAFETY_REVIEW),
    )
    add_support_assignment(bundle, teacher={"max_weekly_caseload_minutes": 600})
    request = open_extension_request(
        bundle["case"]["id"],
        bundle["certification"]["id"],
        requested_additional_days=30,
        justification="Recovery extended by thirty days",
    )
    bundle["extension_request"] = validate_success(
        api_client.start_extension_review(request["id"], PA_HEADERS)
    )
    bundle["case"] = read_case(bundle["case"]["id"])
    return bundle


class TestVoidCascadesThroughFundingIntoCoordination:
    """One reversal row travels from the ledger to the plan's readiness."""

    def test_reversal_row_drops_the_reported_total_and_pulls_the_posture_into_a_hold(
        self,
    ):
        """Voiding one of the four verified visits appends a −120 reversal, drops the
        reported total to 360, lifts the gap to 420 and moves RECONCILED to HELD.

        The PRD states: "It appends a compensating ledger row with
        `attendance_code` `HB_REVERSAL`, whose `reversal_of_entry_id` points at the
        entry being reversed and whose `apportionment_minutes` is the arithmetic
        negation of that entry's `apportionment_minutes`."

        The PRD states: "The reversal path matters because it is the second way into
        a hold — an audit void against a case that had already reconciled reopens it,
        moving the funding posture from `RECONCILED` straight to `HELD` under the same
        threshold."

        Design: Difficulty/transitive_cascade/void_cascades_ledger_reversal_to_funding_hold_to_plan_and_pacing_regression
        """
        bundle = _reconciled_case_with_a_ready_plan()
        voided_session = bundle["sessions"][0]
        present_entry = entries_for_session(voided_session["id"])[0]

        voided = validate_success(
            api_client.void_session(
                voided_session["id"],
                void_session_payload(void_reason="AUDIT_REVERSAL"),
                PA_HEADERS,
            )
        )
        assert voided["status"] == "VOIDED"
        assert voided["credited_minutes"] == 0

        entries = entries_for_session(voided_session["id"])
        assert [entry["attendance_code"] for entry in entries] == [
            "HB_PRESENT",
            "HB_REVERSAL",
        ]
        assert entries[1]["apportionment_minutes"] == -120
        assert entries[1]["reversal_of_entry_id"] == present_entry["id"], (
            "the reversal points at the present row it negates"
        )

        case = read_case(bundle["case"]["id"])
        assert case["reported_apportionment_minutes"] == 360, (
            "480 delivered minutes net of the 120-minute reversal"
        )
        assert case["service_gap_minutes"] == 420, (
            "two completed service weeks owed 780 minutes against 360 reported"
        )
        assert case["funding_status"] == "HELD", (
            "a gap of 420 minutes reaches one 390-minute weekly entitlement"
        )

    def test_the_hold_resets_the_acknowledged_row_and_regresses_the_ready_plan(self):
        """The funding hold alone resets the ACKED pacing row to PENDING and drops the
        READY plan back to CLASSROOM_COORD_PENDING with its counters at 1 and 0.

        The PRD states: "Entering `HELD` carries a conditional cascade into campus
        coordination: every pacing coordination row of that case whose `ack_status`
        is `ACKED` is reset to `PENDING` with `acked_at` cleared, while rows already
        at `DISPUTED` are left untouched, and any transition plan of that case whose
        `status` is `READY` falls back to `CLASSROOM_COORD_PENDING`."

        Design: Difficulty/transitive_cascade/void_cascades_ledger_reversal_to_funding_hold_to_plan_and_pacing_regression
        """
        bundle = _reconciled_case_with_a_ready_plan()
        assert bundle["case"]["funding_status"] == "RECONCILED"
        assert bundle["sync"]["ack_status"] == "ACKED"
        assert bundle["plan"]["status"] == "READY", (
            "one acknowledged row out of one required leaves the plan ready"
        )

        validate_success(
            api_client.void_session(
                bundle["sessions"][0]["id"],
                void_session_payload(void_reason="AUDIT_REVERSAL"),
                PA_HEADERS,
            )
        )

        sync = validate_success(
            api_client.get_pacing_sync(bundle["sync"]["id"], CM_HEADERS)
        )
        assert sync["ack_status"] == "PENDING", (
            "the hold resets the acknowledgement without any teacher acting"
        )
        assert sync.get("acked_at") is None

        plan = validate_success(
            api_client.get_transition_plan(bundle["plan"]["id"], CM_HEADERS)
        )
        assert plan["status"] == "CLASSROOM_COORD_PENDING"
        assert plan["required_ack_count"] == 1
        assert plan["classroom_ack_count"] == 0, (
            "the reset row no longer counts towards readiness"
        )

        assert read_case(bundle["case"]["id"])["service_status"] == (
            "TRANSITION_PLANNED"
        ), "the funding cascade never touches the service dimension"


class TestVirtualOnlyClearanceCascadesTheWholeCase:
    """A safety artifact rewrites mode, rule, entitlement, allocation and calendar."""

    def test_finalization_supersedes_the_earlier_review_and_rewrites_mode_and_rule(self):
        """The onsite review scores 35, bands VIRTUAL_ONLY, supersedes the earlier
        clearance, rewrites the case onto the virtual rule at 270 minutes and cancels
        the scheduled in-home visit.

        The PRD states: "When the resulting `clearance` is `VIRTUAL_ONLY` and the
        case's `delivery_mode` is `IN_HOME` or `HYBRID`, the case's `delivery_mode` is
        rewritten to `VIRTUAL_SYNC`; its `entitlement_rule_id` is re-resolved against
        the student's `grade_band` paired with `VIRTUAL_SYNC`, failing with
        `ERR_NO_PUBLISHED_ENTITLEMENT_RULE` when no published rule covers that pair;
        its `weekly_entitled_minutes` is recomputed per §3.3; the weekly allocation is
        recomputed across the case's active assignments; `committed_weekly_minutes`
        and `over_cap` are recomputed for every affected teacher; and every session of
        that case whose `status` is `SCHEDULED` and whose own `delivery_mode` is
        `IN_HOME` is moved to `CANCELLED_ADMIN`."

        Design: Difficulty/transitive_cascade/virtual_only_clearance_cascades_mode_entitlement_allocation_teachers_and_cancels_in_home_sessions
        """
        bundle = _in_home_case_with_two_teachers_and_a_draft_virtual_only_review()

        finalized = finalize_safety_review(bundle["second_review"]["id"])
        assert finalized["risk_score"] == 35
        assert finalized["clearance"] == "VIRTUAL_ONLY"
        assert finalized["status"] == "FINALIZED"

        earlier = validate_success(
            api_client.get_safety_review(bundle["safety_review"]["id"], CM_HEADERS)
        )
        assert earlier["status"] == "SUPERSEDED", (
            "only the newest finalized review governs the case"
        )

        case = read_case(bundle["case"]["id"])
        assert case["delivery_mode"] == "VIRTUAL_SYNC"
        assert case["entitlement_rule_id"] == bundle["rule_virtual"]["id"]
        assert case["weekly_entitled_minutes"] == 270, (
            "240 virtual base minutes plus the 30-minute mid-duration bonus"
        )
        assert case["escort_required"] is False

        assert read_session(bundle["future_session"]["id"])["status"] == (
            "CANCELLED_ADMIN"
        ), "a scheduled in-home visit cannot survive a virtual-only clearance"

    def test_the_new_entitlement_re_runs_the_waterfall_over_both_teacher_rows(self):
        """390 minutes split 275 / 115 becomes 270 split 190 / 80, and both teacher
        caseloads are re-summed rather than adjusted.

        The PRD states: "Support staff share thirty percent of the entitlement: when
        the case has at least one active support assignment, multiply
        `weekly_entitled_minutes` by 0.30, divide by the number of active support
        assignments, divide by five, round half up to a whole number, and multiply
        back by five; every active support assignment receives that same per-support
        figure, and the support total is that figure multiplied by the number of
        support assignments."

        The PRD states: "A teacher's own `committed_weekly_minutes` is the sum of
        `weekly_committed_minutes` across every assignment of that teacher whose
        `status` is `ACTIVE`, across every case, with no time window."

        Design: Difficulty/transitive_cascade/virtual_only_clearance_cascades_mode_entitlement_allocation_teachers_and_cancels_in_home_sessions
        """
        bundle = _in_home_case_with_two_teachers_and_a_draft_virtual_only_review()
        assert bundle["case"]["weekly_entitled_minutes"] == 390
        assert bundle["primary_assignment"]["weekly_committed_minutes"] == 275
        assert bundle["support_assignment"]["weekly_committed_minutes"] == 115

        finalize_safety_review(bundle["second_review"]["id"])

        support = read_assignment(bundle["support_assignment"]["id"])
        primary = read_assignment(bundle["primary_assignment"]["id"])
        assert support["weekly_committed_minutes"] == 80, (
            "270 minutes at thirty percent is 81, which rounds down to 80 in "
            "five-minute steps"
        )
        assert primary["weekly_committed_minutes"] == 190, (
            "the primary row absorbs the whole rounding residual"
        )

        assert read_teacher(bundle["teacher"]["id"])["committed_weekly_minutes"] == 190
        assert (
            read_teacher(bundle["support_teacher"]["id"])["committed_weekly_minutes"]
            == 80
        )


class TestExtensionApprovalCascadesThroughBothCaseloads:
    """A review decision reaches two teacher rows by way of a bonus threshold."""

    def test_approval_advances_the_window_and_crosses_the_duration_bonus_threshold(self):
        """Thirty approved days push the certified end date to 2026-11-06, lift the
        effective absence to sixty days and raise the entitlement to 420 minutes.

        The PRD states: "An `APPROVED` decision moves the request `UNDER_REVIEW →
        APPROVED` and cascades into the case: `certified_end_date` is advanced by
        `requested_additional_days` calendar days from its current value,
        `extension_count` increments by one, `weekly_entitled_minutes` is recomputed
        per §3.3 — where the newly approved days now feed the effective absence
        duration and may cross a duration-bonus threshold — the weekly allocation is
        recomputed across the case's active assignments, and `committed_weekly_minutes`
        is recomputed for every affected teacher."

        Design: Difficulty/transitive_cascade/extension_approval_cascades_entitlement_to_allocation_to_both_teacher_caseloads
        """
        bundle = _case_with_two_teachers_and_an_extension_under_review()

        decided = validate_success(
            api_client.decide_extension_request(
                bundle["extension_request"]["id"],
                decide_extension_payload("APPROVED", decision_note="Extension granted"),
                PA_HEADERS,
            )
        )
        assert decided["status"] == "APPROVED"

        case = read_case(bundle["case"]["id"])
        assert case["certified_end_date"] == "2026-11-06"
        assert case["extension_count"] == 1
        assert case["weekly_entitled_minutes"] == 420, (
            "an effective absence of sixty days earns the 60-minute bonus"
        )
        assert case["service_status"] == "ACTIVE", (
            "either decision returns the case from EXTENSION_PENDING to ACTIVE"
        )

    def test_the_raised_entitlement_re_allocates_across_both_assignments(self):
        """275 / 115 becomes 295 / 125, both teacher caseloads follow, and the support
        teacher's 600-minute cap is still not exceeded.

        The PRD states: "The primary assignment nominally carries the remaining
        seventy percent, and concretely it receives the case's
        `weekly_entitled_minutes` minus the support total — so the primary row absorbs
        the entire rounding residual and the sum of `weekly_committed_minutes` across
        active assignments equals `weekly_entitled_minutes` exactly."

        The PRD states: "The derived flag `over_cap` is true when
        `committed_weekly_minutes` is strictly greater than that teacher's
        `max_weekly_caseload_minutes`, and false when the two are equal."

        Design: Difficulty/transitive_cascade/extension_approval_cascades_entitlement_to_allocation_to_both_teacher_caseloads
        """
        bundle = _case_with_two_teachers_and_an_extension_under_review()
        assert bundle["case"]["weekly_entitled_minutes"] == 390
        assert bundle["primary_assignment"]["weekly_committed_minutes"] == 275
        assert bundle["support_assignment"]["weekly_committed_minutes"] == 115

        validate_success(
            api_client.decide_extension_request(
                bundle["extension_request"]["id"],
                decide_extension_payload("APPROVED", decision_note="Extension granted"),
                PA_HEADERS,
            )
        )

        support = read_assignment(bundle["support_assignment"]["id"])
        primary = read_assignment(bundle["primary_assignment"]["id"])
        assert support["weekly_committed_minutes"] == 125, (
            "420 minutes at thirty percent is 126, which rounds to 125"
        )
        assert primary["weekly_committed_minutes"] == 295
        allocated = (
            support["weekly_committed_minutes"] + primary["weekly_committed_minutes"]
        )
        assert allocated == 420, "the two active rows sum to the entitlement exactly"

        assert read_teacher(bundle["teacher"]["id"])["committed_weekly_minutes"] == 295
        support_teacher = read_teacher(bundle["support_teacher"]["id"])
        assert support_teacher["committed_weekly_minutes"] == 125
        assert support_teacher["over_cap"] is False, (
            "125 committed minutes sits well under the 600-minute caseload cap"
        )
