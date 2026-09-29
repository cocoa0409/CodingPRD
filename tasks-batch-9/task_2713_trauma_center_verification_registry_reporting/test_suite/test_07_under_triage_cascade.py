"""One triage adjudication and the four entities it moves.

A single confirmation of under-triage is the smallest write in the contract that reaches
the center's rates, the event log, the posture ladder and an unrelated cycle's status.
"""

from prd_bench_local_runner.testing import get_success_data

from test_helpers import (
    ApiClient,
    CycleStatus,
    CycleType,
    DeficiencyClass,
    DesignationLevel,
    PiEventType,
    PiOrigin,
    PiSeverity,
    PiStatus,
    ReadinessPosture,
    TierCode,
    TriageReviewStatus,
    assert_decimal,
    assert_instant,
    fixtures as fx,
    make_system_admin_headers,
)


def _submittable_cycle_over_four_unreviewed_cases(api: ApiClient):
    """Four cases awaiting triage review, beside a cycle sitting exactly on its floor."""
    fx.anchor_clock(api)
    center, tier = fx.center_with_tier(
        api,
        name="Mesa Verde Trauma",
        state_code="NM",
        designation_level=DesignationLevel.LEVEL_I,
        tier_code=TierCode.TIER_1_FULL,
    )
    cases = fx.build_cases(
        api,
        center["id"],
        [
            {
                "activation_tier_id": tier["id"],
                "mrn": "MRN-C1",
                "arrival_at": "2026-07-20T08:00:00Z",
                "injury_severity_score": 12,
                "los_hours": 60.00,
            },
            {
                "activation_tier_id": tier["id"],
                "mrn": "MRN-C2",
                "arrival_at": "2026-07-21T08:00:00Z",
                "injury_severity_score": 14,
                "los_hours": 60.00,
            },
            {
                "activation_tier_id": tier["id"],
                "mrn": "MRN-C3",
                "arrival_at": "2026-07-22T08:00:00Z",
                "injury_severity_score": 16,
                "los_hours": 60.00,
            },
            {
                "activation_tier_id": tier["id"],
                "mrn": "MRN-C4",
                "arrival_at": "2026-07-23T08:00:00Z",
                "injury_severity_score": 18,
                "los_hours": 60.00,
            },
        ],
    )
    cycle = fx.create_cycle(
        api,
        center["id"],
        cycle_type=CycleType.NATIONAL_VERIFICATION,
        site_visit_date="2026-11-20T13:00:00Z",
    )
    fx.deficiencies_of_class(
        api,
        cycle,
        ["CD-07-01", "CD-07-02"],
        deficiency_class=DeficiencyClass.TYPE_II_MAJOR,
        remediation_due_at="2026-09-20T00:00:00Z",
    )
    return center, cases, fx.get_cycle(api, cycle["id"])


class TestUnderTriageCascade:
    """The propagation chain that starts at a single review outcome."""

    def test_confirming_under_triage_moves_the_rate_and_opens_a_system_event(
        self, api: ApiClient
    ) -> None:
        """One of four cases is 25.00 per cent, which is past the alert line.

        Design: Difficulty/transitive_cascade/under_triage_threshold_to_cycle_block
        """
        center, cases, _ = _submittable_cycle_over_four_unreviewed_cases(api)

        fx.triage_review(api, cases[0], TriageReviewStatus.UNDER_TRIAGE_CONFIRMED)

        after_center = fx.get_center(api, center["id"])
        assert_decimal(
            after_center["under_triage_rate_pct"], 25.00, "under_triage_rate_pct"
        )
        assert_decimal(after_center["over_triage_rate_pct"], 0.00, "over_triage_rate_pct")
        assert after_center["open_pi_event_count"] == 1

        events = get_success_data(
            api.list_pi_events(make_system_admin_headers(), {"center_id": center["id"]})
        )
        assert len(events) == 1
        alert = events[0]
        assert alert["event_type"] == PiEventType.UNDER_TRIAGE
        assert alert["origin"] == PiOrigin.SYSTEM_AUTO
        assert alert["severity"] == PiSeverity.HIGH
        assert alert["status"] == PiStatus.IDENTIFIED
        assert_instant(
            alert["loop_closure_due_at"], "2026-09-30T00:00:00Z", "loop_closure_due_at"
        )

    def test_the_cascade_reaches_the_posture_and_blocks_the_cycle(
        self, api: ApiClient
    ) -> None:
        """The cycle falls from exactly 70.00 to 66.00 and blocks without being asked to.

        Design: Difficulty/transitive_cascade/under_triage_threshold_to_cycle_block
        """
        center, cases, cycle = _submittable_cycle_over_four_unreviewed_cases(api)
        assert_decimal(cycle["readiness_score"], 70.00, "readiness_score")
        assert cycle["status"] == CycleStatus.PREP

        fx.triage_review(api, cases[0], TriageReviewStatus.UNDER_TRIAGE_CONFIRMED)

        assert fx.get_center(api, center["id"])["readiness_posture"] == (
            ReadinessPosture.AT_RISK
        )

        after_cycle = fx.get_cycle(api, cycle["id"])
        assert_decimal(after_cycle["readiness_score"], 66.00, "readiness_score")
        assert after_cycle["status"] == CycleStatus.PREP_BLOCKED

        after_case = fx.get_case(api, cases[0]["id"])
        assert after_case["triage_review_status"] == TriageReviewStatus.UNDER_TRIAGE_CONFIRMED
        assert after_case["version"] == 2
