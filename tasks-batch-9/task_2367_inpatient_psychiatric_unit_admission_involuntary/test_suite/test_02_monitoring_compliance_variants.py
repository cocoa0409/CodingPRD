"""The two monitoring-compliance measures a released episode publishes.

The interval grid and the raw tally count the same log entries, but only the grid
can tell that two checks landed inside the same fifteen-minute slot — and only the
grid gates the debriefing.
"""

from test_helpers import (
    ApiErrorId,
    CheckType,
    InterventionType,
    MONITORING_INTERVAL_MINUTES,
    RestraintStatus,
    assert_compliance_pct,
    assert_error,
    assert_monitoring_compliance,
    assert_observation_quarter_hours,
    active_restraint,
    build_ward,
    debrief_payload,
    involuntary_placed_admission,
    log_monitoring_checks,
    read_admission,
    read_restraint,
    release_restraint,
)

WARD_BEDS = (
    {"room_number": "401", "wing_code": "A", "bed_label": "A"},
    {"room_number": "402", "wing_code": "A", "bed_label": "A"},
    {"room_number": "403", "wing_code": "B", "bed_label": "A"},
)

ORDERED_MINUTES = 30
FIRST_CHECK_AT = "2026-09-03T08:03:00Z"
SECOND_CHECK_AT = "2026-09-03T08:07:00Z"
RELEASE_AT = "2026-09-03T08:30:00Z"


def _released_episode_with_clustered_checks(api, roster):
    """A 30-minute mechanical restraint whose two checks both land in slot one."""
    ward = build_ward(api, bed_specs=WARD_BEDS)
    case = involuntary_placed_admission(
        api,
        roster,
        ward,
        mrn="MRN-2367-C",
        legal_name="Corin Ash",
        age_years=37,
        gender_care_category="MALE",
        bed_id=ward.beds[0]["id"],
    )
    episode = active_restraint(
        api,
        roster,
        case["admission"]["id"],
        InterventionType.MECHANICAL_RESTRAINT.value,
        ORDERED_MINUTES,
    )
    log_monitoring_checks(
        api, roster, episode["id"], [FIRST_CHECK_AT], CheckType.CIRCULATION.value
    )
    log_monitoring_checks(
        api,
        roster,
        episode["id"],
        [SECOND_CHECK_AT],
        CheckType.HYDRATION_OFFERED.value,
    )
    released = release_restraint(api, roster, episode["id"], release_clock=RELEASE_AT)
    return case, released


class TestMonitoringComplianceVariants:
    """One log, two percentages, and only one of them with teeth."""

    def test_grid_and_raw_compliance_diverge_for_checks_clustered_at_the_start(
        self, api, clock, roster
    ):
        """Two early checks credit one slot of two, so 50.0 stands against 100.0.

        PRD 3.6: "The two diverge routinely — a 30-minute mechanical restraint
        with checks logged at 3 and 7 minutes after the start records a
        `grid_compliance_pct` of 50.0 against a `raw_compliance_pct` of 100.0."

        Design: Difficulty/dual_variant_calc/restraint_monitoring_grid_vs_raw_compliance_diverge
        """
        _, released = _released_episode_with_clustered_checks(api, roster)

        assert released["actual_duration_minutes"] == ORDERED_MINUTES
        assert (
            released["monitoring_interval_minutes"]
            == MONITORING_INTERVAL_MINUTES[InterventionType.MECHANICAL_RESTRAINT.value]
        )
        assert_monitoring_compliance(released, required=2, grid_satisfied=1, logged=2)
        assert_compliance_pct(released["grid_compliance_pct"], 50.0, "grid_compliance_pct")
        assert_compliance_pct(released["raw_compliance_pct"], 100.0, "raw_compliance_pct")
        assert released["grid_compliance_pct"] != released["raw_compliance_pct"]

    def test_debriefing_consults_the_grid_measure_and_not_the_raw_one(
        self, api, clock, roster
    ):
        """A full raw tally cannot buy a debriefing when a slot went unchecked.

        PRD 3.6: "`raw_compliance_pct` is published for quality dashboards and
        never gates a transition; `grid_compliance_pct` is the only figure a
        debriefing consults."

        Design: Difficulty/dual_variant_calc/restraint_monitoring_grid_vs_raw_compliance_diverge
        """
        _, released = _released_episode_with_clustered_checks(api, roster)

        refusal = api.debrief_restraint(
            roster.psychiatrist_headers,
            released["id"],
            debrief_payload(
                patient_participated_in_debrief=True, staff_participants_count=3
            ),
        )
        assert_error(refusal, ApiErrorId.MONITORING_INCOMPLETE)

        unchanged = read_restraint(api, released["id"])
        assert unchanged["status"] == RestraintStatus.RELEASED.value
        assert unchanged["debrief_completed_at"] is None

    def test_release_bills_the_episode_in_quarter_hours_on_the_admission(
        self, api, clock, roster
    ):
        """A thirty-minute episode contributes exactly two quarter hours.

        PRD 3.6: "`observation_staff_quarter_hours` is the sum, over every
        episode of that admission whose `status` is `RELEASED`, `DEBRIEFED` or
        `EXPIRED_UNAUTHORIZED`, of that episode's `actual_duration_minutes`
        divided by 15 and rounded up to the next whole number."

        Design: Difficulty/dual_variant_calc/restraint_monitoring_grid_vs_raw_compliance_diverge
        """
        case, released = _released_episode_with_clustered_checks(api, roster)

        admission = read_admission(api, case["admission"]["id"])
        assert_observation_quarter_hours(admission, [released["actual_duration_minutes"]])
        assert admission["observation_staff_quarter_hours"] == 2
