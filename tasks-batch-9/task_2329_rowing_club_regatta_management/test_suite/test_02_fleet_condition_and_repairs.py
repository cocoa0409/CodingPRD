"""The fleet: decaying damage deductions, the two condition indices, and the
reschedule loop that hands a repair bay window back.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_damage_report,
    assert_shell,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    add_single,
    build_hull_with_two_reports,
    file_damage,
    make_scheduled_repair,
    read_report,
    read_shell,
    schedule_report_repair,
    triage_report,
)

BAY_WINDOW_START = "2026-08-03T08:00:00Z"
BAY_WINDOW_END = "2026-08-03T12:00:00Z"
LATER_WINDOW_END = "2026-08-03T16:00:00Z"
ONE_MINUTE_LATER = "2026-08-03T12:01:00Z"


@pytest.fixture
def hull_with_two_reports(cast):
    """A hull carrying an 89-day-old VERIFIED MAJOR and a 30-day-old TRIAGED MINOR."""
    return build_hull_with_two_reports(cast)


@pytest.fixture
def rescheduling_hull(cast):
    """A MAJOR report scheduled into BAY-A, so its hull sits IN_REPAIR."""
    shell = add_single(hull_name="Heron")
    report = make_scheduled_repair(
        shell["id"],
        cast["reporter"]["id"],
        cast["reporter_headers"],
        cast["boatman_headers"],
        severity="MAJOR",
        bay="BAY-A",
        start_at=BAY_WINDOW_START,
        end_at=BAY_WINDOW_END,
    )
    return {"shell": shell, "report": report}


@pytest.fixture
def three_triaged_hulls(cast):
    """Three hulls each carrying a triaged MAJOR report, one already in BAY-A."""
    hulls = []
    reports = []
    for index, hull_name in enumerate(("Teal", "Grebe", "Merlin")):
        shell = add_single(hull_name=hull_name)
        report = file_damage(
            shell["id"], cast["coach"]["id"], cast["coach_headers"], severity="MAJOR"
        )
        reports.append(triage_report(report["id"], cast["boatman_headers"]))
        hulls.append(shell)
    reports[0] = schedule_report_repair(
        reports[0]["id"], cast["boatman_headers"], "BAY-A", BAY_WINDOW_START, BAY_WINDOW_END
    )
    return {"hulls": hulls, "reports": reports}


class TestConditionIndexVariants:
    def test_verified_and_open_damage_diverge_across_the_two_indices(
        self, hull_with_two_reports
    ):
        """A repaired hull never fully recovers on the conservative reading.

        PRD: "For each index the contributions are summed at full precision,
        that single sum is rounded half up to a whole index point, and the
        rounded sum is subtracted from a ceiling of 100, with the result floored
        at 0 and never exceeding 100."

        Design: Difficulty/dual_variant_calc/shell_condition_index_conservative_vs_optimistic_divergence
        """
        shell = assert_shell(hull_with_two_reports["shell"])
        assert shell["condition_index_conservative"] == 90, (
            "a quarter of 17.0 plus 5.5 rounds to 10 points off a ceiling of 100, "
            f"expected 90, got {shell['condition_index_conservative']}"
        )
        assert shell["condition_index_optimistic"] == 94, (
            "the optimistic index drops the verified report entirely, leaving 5.5 "
            "points that round to 6 off a ceiling of 100, expected 94, got "
            f"{shell['condition_index_optimistic']}"
        )
        assert (
            shell["condition_index_conservative"] != shell["condition_index_optimistic"]
        ), "the two indices must diverge for this identical damage history"

    def test_deductions_decay_by_completed_thirty_day_periods(self, hull_with_two_reports):
        """Each finished decay period shaves half a point off the raw weight.

        PRD: "from it the server subtracts 0.5 points per completed decay
        period, and the result is floored at zero. That decayed figure is stored
        as the report's `severity_points`."

        Design: Difficulty/dual_variant_calc/shell_condition_index_conservative_vs_optimistic_divergence
        """
        major = assert_damage_report(hull_with_two_reports["major_report"])
        minor = assert_damage_report(hull_with_two_reports["minor_report"])
        assert major["severity_points"] == pytest.approx(17.0, abs=0.01), (
            "an 89-day-old MAJOR has completed two decay periods: 18 - 1.0 = 17.0, "
            f"got {major['severity_points']}"
        )
        assert minor["severity_points"] == pytest.approx(5.5, abs=0.01), (
            "a 30-day-old MINOR has completed one decay period: 6 - 0.5 = 5.5, "
            f"got {minor['severity_points']}"
        )

    def test_verification_returns_the_hull_to_service(self, hull_with_two_reports):
        """Signing off the repair puts the hull back on the water.

        PRD: "Verification moves the report `REPAIR_SCHEDULED → VERIFIED`,
        stamps `verified_by_user_id`, drives the hull `IN_REPAIR → AVAILABLE`,
        and recomputes both indices"

        Design: Difficulty/dual_variant_calc/shell_condition_index_conservative_vs_optimistic_divergence
        """
        assert hull_with_two_reports["major_report"]["status"] == "VERIFIED", (
            "the signed-off report is VERIFIED, got "
            f"{hull_with_two_reports['major_report']['status']}"
        )
        assert hull_with_two_reports["shell"]["status"] == "AVAILABLE", (
            "verification drives the hull IN_REPAIR -> AVAILABLE, got "
            f"{hull_with_two_reports['shell']['status']}"
        )


class TestRescheduleLoop:
    def test_retriage_walks_the_hull_back_out_of_repair_and_frees_the_bay(
        self, cast, rescheduling_hull
    ):
        """Re-triaging a scheduled repair releases everything it had reserved.

        PRD: "resets `assigned_repair_bay`, `repair_window_start_at` and
        `repair_window_end_at` to null, freeing the bay window; the hull follows
        `IN_REPAIR → DAMAGED`."

        Design: Difficulty/non_linear_state_machine/shell_damaged_in_repair_damaged_reschedule_cycle
        """
        report = assert_damage_report(
            triage_report(rescheduling_hull["report"]["id"], cast["boatman_headers"], "REPAIR")
        )
        assert report["status"] == "TRIAGED", (
            f"re-triage moves REPAIR_SCHEDULED -> TRIAGED, got {report['status']}"
        )
        assert report["assigned_repair_bay"] is None, (
            f"the bay label is cleared, got {report['assigned_repair_bay']}"
        )
        assert report["repair_window_start_at"] is None, (
            f"the window start is cleared, got {report['repair_window_start_at']}"
        )
        assert report["repair_window_end_at"] is None, (
            f"the window end is cleared, got {report['repair_window_end_at']}"
        )
        shell = assert_shell(read_shell(rescheduling_hull["shell"]["id"]))
        assert shell["status"] == "DAMAGED", (
            f"the hull follows IN_REPAIR -> DAMAGED, got {shell['status']}"
        )

    def test_released_window_can_be_reclaimed_by_the_same_report(
        self, cast, rescheduling_hull
    ):
        """The hull may travel round the repair loop as often as needed.

        PRD: "So a report may travel `TRIAGED → REPAIR_SCHEDULED → TRIAGED` as
        often as the boatman needs, and the hull with it, `DAMAGED → IN_REPAIR →
        DAMAGED`."

        Design: Difficulty/non_linear_state_machine/shell_damaged_in_repair_damaged_reschedule_cycle
        """
        report_id = rescheduling_hull["report"]["id"]
        triage_report(report_id, cast["boatman_headers"], "REPAIR")
        report = assert_damage_report(
            schedule_report_repair(
                report_id, cast["boatman_headers"], "BAY-A", BAY_WINDOW_START, BAY_WINDOW_END
            )
        )
        assert report["status"] == "REPAIR_SCHEDULED", (
            "the freed window is available to the very report that released it, "
            f"got {report['status']}"
        )
        assert report["assigned_repair_bay"] == "BAY-A", (
            f"the bay label is persisted again, got {report['assigned_repair_bay']}"
        )
        assert report["repair_window_start_at"] == BAY_WINDOW_START, (
            f"the window start is persisted again, got {report['repair_window_start_at']}"
        )
        shell = assert_shell(read_shell(rescheduling_hull["shell"]["id"]))
        assert shell["status"] == "IN_REPAIR", (
            f"rescheduling drives the hull DAMAGED -> IN_REPAIR, got {shell['status']}"
        )
        assert shell["status"] != "RETIRED", "the reschedule loop never retires a hull"


class TestRepairBayExclusivity:
    def test_windows_sharing_one_endpoint_instant_conflict(self, cast, three_triaged_hulls):
        """The bay reservation is exclusive over a closed window.

        PRD: "if any other report in status `REPAIR_SCHEDULED` on the same bay
        holds a window that intersects the requested one, the request is
        rejected with `ERR_REPAIR_BAY_CONFLICT`, and two windows that share
        exactly one endpoint instant do conflict."

        Design: Difficulty/resource_temporal_overlap/repair_bay_closed_interval_shared_endpoint_does_conflict
        """
        second = three_triaged_hulls["reports"][1]
        response = api_client.schedule_repair(
            second["id"],
            {
                "assigned_repair_bay": "BAY-A",
                "repair_window_start_at": BAY_WINDOW_END,
                "repair_window_end_at": LATER_WINDOW_END,
            },
            cast["boatman_headers"],
        )
        validate_error(response, ApiErrorId.ERR_REPAIR_BAY_CONFLICT.value)

        report = assert_damage_report(read_report(second["id"]))
        assert report["status"] == "TRIAGED", (
            f"the rejected report is untouched at TRIAGED, got {report['status']}"
        )
        assert report["assigned_repair_bay"] is None, (
            "a rejected scheduling persists no bay label, got "
            f"{report['assigned_repair_bay']}"
        )
        shell = read_shell(three_triaged_hulls["hulls"][1]["id"])
        assert shell["status"] == "DAMAGED", (
            f"the hull stays DAMAGED rather than IN_REPAIR, got {shell['status']}"
        )

    def test_a_different_bay_or_a_disjoint_window_is_accepted(
        self, cast, three_triaged_hulls
    ):
        """Exclusivity is scoped to one bay, and one minute of clearance is enough.

        PRD: "Scheduling a repair takes an `assigned_repair_bay` label with
        `repair_window_start_at` and `repair_window_end_at`, moves the report
        `TRIAGED → REPAIR_SCHEDULED`, persists all three fields, and drives the
        hull `DAMAGED → IN_REPAIR`."

        Design: Difficulty/resource_temporal_overlap/repair_bay_closed_interval_shared_endpoint_does_conflict
        """
        reports = three_triaged_hulls["reports"]
        elsewhere = validate_success(
            api_client.schedule_repair(
                reports[2]["id"],
                {
                    "assigned_repair_bay": "BAY-B",
                    "repair_window_start_at": BAY_WINDOW_START,
                    "repair_window_end_at": BAY_WINDOW_END,
                },
                cast["boatman_headers"],
            )
        )
        assert elsewhere["status"] == "REPAIR_SCHEDULED", (
            "the identical window in another bay is free, got "
            f"{elsewhere['status']}"
        )

        shifted = validate_success(
            api_client.schedule_repair(
                reports[1]["id"],
                {
                    "assigned_repair_bay": "BAY-A",
                    "repair_window_start_at": ONE_MINUTE_LATER,
                    "repair_window_end_at": LATER_WINDOW_END,
                },
                cast["boatman_headers"],
            )
        )
        assert shifted["status"] == "REPAIR_SCHEDULED", (
            "a window starting one minute after the incumbent ends no longer "
            f"intersects it, got {shifted['status']}"
        )
        assert shifted["repair_window_start_at"] == ONE_MINUTE_LATER, (
            f"the shifted start is persisted, got {shifted['repair_window_start_at']}"
        )
        for shell in three_triaged_hulls["hulls"]:
            current = read_shell(shell["id"])
            assert current["status"] == "IN_REPAIR", (
                f"hull {current['hull_name']} should be IN_REPAIR, got {current['status']}"
            )
