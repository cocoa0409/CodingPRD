"""The performance-improvement loop, which has no terminal state.

A closed loop can be reopened, and the reopen has to leave the event distinguishable from
its first round while restoring the counters it moved on the way out.
"""

from typing import Any, Dict, Tuple

from prd_bench_local_runner.testing import get_success_data

from test_helpers import (
    ActionType,
    ApiClient,
    CompletionStatus,
    DesignationLevel,
    PiEventType,
    PiOrigin,
    PiSeverity,
    PiStatus,
    ReadinessPosture,
    TierCode,
    assert_instant,
    assert_pi_partition,
    factories as f,
    fixtures as fx,
    make_trauma_medical_director_headers,
    make_trauma_program_manager_headers,
    make_verification_reviewer_headers,
    make_system_admin_headers,
)

OWNER_OUTSIDE_THE_LOOP = "u_owner_1"
PROGRAM_OWNER = "u_pm_1"


def _closed_mortality_loop(api: ApiClient) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """A high-severity mortality review closed after its single action was verified.

    The action is completed by the program manager and verified by the medical director,
    so no one both owns and verifies the same work.
    """
    fx.anchor_clock(api)
    center = fx.create_center(
        api,
        name="Grand Prairie Trauma",
        state_code="KS",
        designation_level=DesignationLevel.LEVEL_II,
    )
    event = fx.create_pi_event(
        api,
        center["id"],
        event_type=PiEventType.MORTALITY_REVIEW,
        severity=PiSeverity.HIGH,
    )
    fx.start_pi_review(api, event)
    action = get_success_data(
        api.create_corrective_action(
            event["id"],
            f.corrective_action_payload(
                action_type=ActionType.PROTOCOL_CHANGE,
                owner_user_id=OWNER_OUTSIDE_THE_LOOP,
                due_at="2026-09-15T00:00:00Z",
            ),
            make_trauma_medical_director_headers(),
        )
    )
    get_success_data(
        api.complete_corrective_action(
            action["id"],
            make_trauma_program_manager_headers(center["id"]),
            f.complete_action_payload("Massive transfusion protocol reissued."),
        )
    )
    get_success_data(
        api.verify_corrective_action(
            action["id"], make_trauma_medical_director_headers()
        )
    )
    get_success_data(
        api.close_pi_loop(
            event["id"],
            f.close_loop_payload("Audit of ten subsequent activations shows compliance."),
            make_trauma_medical_director_headers(),
        )
    )
    return center, fx.get_event(api, event["id"]), action


def _transfer_delay_loop_with_verified_action(
    api: ApiClient,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """A medium transfer-delay event at ACTION_PLANNED whose only action is verified."""
    fx.anchor_clock(api)
    center = fx.create_center(
        api,
        name="Elk River Trauma",
        state_code="MN",
        designation_level=DesignationLevel.LEVEL_II,
    )
    event, action = fx.pi_loop_with_verified_action(
        api,
        center["id"],
        event_type=PiEventType.TRANSFER_DELAY,
        severity=PiSeverity.MEDIUM,
        action_type=ActionType.PROTOCOL_CHANGE,
        owner_user_id=PROGRAM_OWNER,
        due_at="2026-09-01T00:00:00Z",
    )
    return center, event, action


class TestSecondReviewRound:
    """Reopening returns the event to a state it already occupied."""

    def test_a_reopened_event_re_enters_review_on_a_second_round(
        self, api: ApiClient
    ) -> None:
        """The event reaches UNDER_REVIEW again with review_round 2 and no closure stamp.

        Design: Difficulty/non_linear_state_machine/pi_event_reopen_cycles_into_second_review_round
        """
        _, event, _ = _closed_mortality_loop(api)
        assert event["status"] == PiStatus.LOOP_CLOSED
        assert event["review_round"] == 1

        reopened = get_success_data(
            api.reopen_pi_event(
                event["id"],
                f.reopen_payload("Site reviewer found the audit sample unrepresentative."),
                make_verification_reviewer_headers(),
            )
        )
        assert reopened["status"] == PiStatus.REOPENED

        second_round = get_success_data(
            api.start_pi_review(event["id"], make_trauma_medical_director_headers())
        )
        assert second_round["status"] == PiStatus.UNDER_REVIEW
        assert second_round["review_round"] == 2
        assert second_round["closed_at"] is None

    def test_the_second_round_starts_with_no_verified_work(self, api: ApiClient) -> None:
        """The action survives the reopen but returns to the work queue.

        Design: Difficulty/non_linear_state_machine/pi_event_reopen_cycles_into_second_review_round
        """
        center, event, action = _closed_mortality_loop(api)

        get_success_data(
            api.reopen_pi_event(
                event["id"],
                f.reopen_payload("Site reviewer found the audit sample unrepresentative."),
                make_verification_reviewer_headers(),
            )
        )
        get_success_data(
            api.start_pi_review(event["id"], make_trauma_medical_director_headers())
        )

        after_event = fx.get_event(api, event["id"])
        assert after_event["corrective_action_count"] == 1
        assert after_event["verified_action_count"] == 0

        after_action = fx.get_corrective_action(api, event["id"], action["id"])
        assert after_action["completion_status"] == CompletionStatus.OPEN

        assert_pi_partition(
            fx.get_center(api, center["id"]), open_count=1, closed_count=0
        )


class TestOpenClosedPartitionConservation:
    """The two event counters are conserved across a closure and its reversal."""

    def test_closing_and_reopening_restores_the_pre_closure_partition(
        self, api: ApiClient
    ) -> None:
        """The counters move 1/0 to 0/1 and back to exactly 1/0.

        Design: Difficulty/compensating_invariant/pi_loop_reopen_restores_open_closed_event_partition
        """
        center, event, _ = _transfer_delay_loop_with_verified_action(api)
        assert_pi_partition(
            fx.get_center(api, center["id"]), open_count=1, closed_count=0
        )

        closed = fx.close_loop(
            api,
            event,
            loop_closure_note="Loop closed: verified process change with 30 day audit.",
        )
        assert closed["status"] == PiStatus.LOOP_CLOSED
        assert_instant(closed["closed_at"], "2026-08-01T00:00:00Z", "closed_at")
        assert_pi_partition(
            fx.get_center(api, center["id"]), open_count=0, closed_count=1
        )

        fx.reopen_loop(
            api, event, reopen_reason="Recurrence found in the following month's audit."
        )
        assert_pi_partition(
            fx.get_center(api, center["id"]), open_count=1, closed_count=0
        )

    def test_the_reopened_event_carries_a_fresh_closure_deadline(
        self, api: ApiClient
    ) -> None:
        """Reopening clears closed_at, advances the round and re-dates the loop deadline.

        Design: Difficulty/compensating_invariant/pi_loop_reopen_restores_open_closed_event_partition
        """
        _, event, _ = _transfer_delay_loop_with_verified_action(api)
        fx.close_loop(
            api,
            event,
            loop_closure_note="Loop closed: verified process change with 30 day audit.",
        )

        reopened = fx.reopen_loop(
            api, event, reopen_reason="Recurrence found in the following month's audit."
        )
        assert reopened["status"] == PiStatus.REOPENED
        assert reopened["closed_at"] is None
        assert reopened["review_round"] == 2
        assert_instant(
            reopened["loop_closure_due_at"],
            "2026-08-31T00:00:00Z",
            "loop_closure_due_at",
        )


class TestPiEventCaseLinkage:
    """A case-linked event is reachable from the case filter and the center filter alike."""

    def test_the_case_link_is_visible_from_both_reverse_lookups(
        self, api: ApiClient
    ) -> None:
        """Filtering by case returns only the linked event; filtering by center returns both.

        Design: Corner/endpoints/pi_event_case_link_is_visible_from_both_reverse_lookups
        """
        fx.anchor_clock(api)
        center, tier = fx.center_with_tier(
            api,
            name="Kestrel Ridge Trauma",
            state_code="OR",
            designation_level=DesignationLevel.LEVEL_II,
            tier_code=TierCode.TIER_1_FULL,
        )
        case = fx.create_case(
            api,
            center["id"],
            tier["id"],
            mrn="MRN-KR1",
            arrival_at="2026-07-21T09:00:00Z",
            injury_severity_score=25,
            los_hours=60.00,
        )
        linked = fx.create_pi_event(
            api,
            center["id"],
            event_type=PiEventType.MORTALITY_REVIEW,
            severity=PiSeverity.LOW,
            case_id=case["id"],
        )
        free = fx.create_pi_event(
            api,
            center["id"],
            event_type=PiEventType.TRANSFER_DELAY,
            severity=PiSeverity.LOW,
        )
        assert linked["case_id"] == case["id"]
        assert free["case_id"] is None
        assert linked["origin"] == PiOrigin.MANUAL

        by_case = get_success_data(
            api.list_pi_events(make_system_admin_headers(), {"case_id": case["id"]})
        )
        assert [row["id"] for row in by_case] == [linked["id"]]

        by_center = get_success_data(
            api.list_pi_events(make_system_admin_headers(), {"center_id": center["id"]})
        )
        assert {row["id"] for row in by_center} == {linked["id"], free["id"]}

        after = fx.get_center(api, center["id"])
        assert after["open_pi_event_count"] == 2
        assert after["readiness_posture"] == ReadinessPosture.READY
