"""Responder documentation and the inclusive boundary of the tier's response limit.

A response that arrives on the limit to the second is compliant; one that arrives 36
seconds past it is late and opens an event nobody asked for.
"""

from prd_bench_local_runner.testing import get_success_data

from test_helpers import (
    ApiClient,
    ComplianceStatus,
    DesignationLevel,
    OMIT,
    PiEventType,
    PiOrigin,
    ReadinessPosture,
    ResponderRole,
    SURGEON_1,
    TierCode,
    assert_decimal,
    assert_response_log,
    fixtures as fx,
    make_system_admin_headers,
)

NEUROSURGEON_1 = "u_neuro_1"


def _clearwater_with_two_activations(api: ApiClient):
    """One center with the standard fifteen minute surgeon limit and two open cases."""
    fx.anchor_clock(api)
    center, tier = fx.center_with_tier(
        api,
        name="Clearwater Trauma",
        state_code="FL",
        designation_level=DesignationLevel.LEVEL_I,
        tier_code=TierCode.TIER_1_FULL,
        surgeon_response_limit_minutes=15,
        specialty_response_limit_minutes=30,
        iss_threshold=16,
    )
    on_time_case = fx.create_case(
        api,
        center["id"],
        tier["id"],
        mrn="MRN-R1",
        arrival_at="2026-07-26T08:00:00Z",
        injury_severity_score=26,
        los_hours=120.00,
    )
    late_case = fx.create_case(
        api,
        center["id"],
        tier["id"],
        mrn="MRN-R2",
        arrival_at="2026-07-27T08:00:00Z",
        injury_severity_score=28,
        los_hours=120.00,
    )
    return center, on_time_case, late_case


class TestResponseLimitBoundary:
    """The comparison against the tier limit includes the limit itself."""

    def test_a_response_exactly_on_the_limit_is_compliant(self, api: ApiClient) -> None:
        """Fifteen minutes against a fifteen minute limit is not a breach.

        Design: Difficulty/boundary_precision_check/surgeon_response_exactly_at_limit_is_compliant
        """
        _, on_time_case, _ = _clearwater_with_two_activations(api)

        log = fx.log_response(
            api,
            on_time_case,
            responder_role=ResponderRole.SURGEON,
            responder_user_id=SURGEON_1,
            notified_at="2026-07-26T08:00:00Z",
            arrived_at="2026-07-26T08:15:00Z",
        )
        assert_response_log(log, on_time_case["id"])
        assert_decimal(log["response_minutes"], 15.00, "response_minutes")
        assert log["applicable_limit_minutes"] == 15
        assert log["compliance_status"] == ComplianceStatus.COMPLIANT

    def test_thirty_six_seconds_past_the_limit_is_late(self, api: ApiClient) -> None:
        """15.60 minutes is over the limit, and the fractional minute is not rounded away.

        Design: Difficulty/boundary_precision_check/surgeon_response_exactly_at_limit_is_compliant
        """
        center, on_time_case, late_case = _clearwater_with_two_activations(api)
        fx.log_response(
            api,
            on_time_case,
            responder_role=ResponderRole.SURGEON,
            responder_user_id=SURGEON_1,
            notified_at="2026-07-26T08:00:00Z",
            arrived_at="2026-07-26T08:15:00Z",
        )

        late_log = fx.log_response(
            api,
            late_case,
            responder_role=ResponderRole.SURGEON,
            responder_user_id=SURGEON_1,
            notified_at="2026-07-27T09:00:00Z",
            arrived_at="2026-07-27T09:15:36Z",
        )
        assert_response_log(late_log, late_case["id"])
        assert_decimal(late_log["response_minutes"], 15.60, "response_minutes")
        assert late_log["applicable_limit_minutes"] == 15
        assert late_log["compliance_status"] == ComplianceStatus.LATE

        events = get_success_data(
            api.list_pi_events(make_system_admin_headers(), {"center_id": center["id"]})
        )
        assert len(events) == 1, "only the late response opens an event"
        breach = events[0]
        assert breach["event_type"] == PiEventType.DELAYED_SURGEON
        assert breach["origin"] == PiOrigin.SYSTEM_AUTO
        assert breach["case_id"] == late_case["id"]

        after_center = fx.get_center(api, center["id"])
        assert after_center["open_pi_event_count"] == 1
        assert after_center["readiness_posture"] == ReadinessPosture.READY


class TestUndocumentedResponse:
    """A responder who was notified but never documented as arriving is undocumented."""

    def test_a_missing_arrival_is_undocumented_against_the_specialty_limit(
        self, api: ApiClient
    ) -> None:
        """No elapsed time can be computed, yet the limit that applied is still recorded.

        Design: Corner/calculations/response_log_without_arrival_is_undocumented_against_specialty_limit
        """
        fx.anchor_clock(api)
        center, tier = fx.center_with_tier(
            api,
            name="Stonebridge Trauma",
            state_code="KY",
            designation_level=DesignationLevel.LEVEL_II,
            tier_code=TierCode.TIER_2_MODIFIED,
            surgeon_response_limit_minutes=30,
            specialty_response_limit_minutes=60,
            iss_threshold=9,
        )
        case = fx.create_case(
            api,
            center["id"],
            tier["id"],
            mrn="MRN-SB1",
            arrival_at="2026-07-24T22:00:00Z",
            injury_severity_score=16,
            los_hours=36.00,
        )

        log = fx.log_response(
            api,
            case,
            responder_role=ResponderRole.NEUROSURGERY,
            responder_user_id=NEUROSURGEON_1,
            notified_at="2026-07-24T22:05:00Z",
            arrived_at=OMIT,
        )
        assert_response_log(log, case["id"])
        assert log["compliance_status"] == ComplianceStatus.UNDOCUMENTED
        assert log["response_minutes"] is None
        assert log["applicable_limit_minutes"] == 60, (
            "a non-surgeon responder is measured against the specialty limit"
        )

        assert (
            get_success_data(
                api.list_pi_events(
                    make_system_admin_headers(), {"center_id": center["id"]}
                )
            )
            == []
        ), "an undocumented response is not a documented breach"

        after_center = fx.get_center(api, center["id"])
        assert after_center["open_pi_event_count"] == 0
        assert after_center["readiness_posture"] == ReadinessPosture.READY
