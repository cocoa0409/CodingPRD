"""Two calculations whose two defensible variants diverge numerically.

The slot series reports both an as-operated and an as-filed utilization
percentage from different inputs; a tail reports both a contiguous-window and a
cumulative-ground maintenance figure from the same leg ordering. In both cases
only one variant gates anything.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_slot_holding,
    assert_utilization_math,
    create_aircraft,
    create_carrier,
    create_flight_leg,
    create_open_season,
    create_schedule_version,
    create_station,
    assign_aircraft,
    file_utilization_record,
    make_network_planner_headers,
    read_holding,
    read_rotation,
    read_aircraft,
    read_version,
    setup_monday_series_schedule,
    validate_error,
    validate_success,
    TEST_USERS,
)

COORDINATOR = TEST_USERS["slot_coordinator_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]


class TestSlotUtilizationVariantsDiverge:
    """One holding, two percentages, computed from different inputs."""

    def test_as_operated_and_as_filed_diverge_by_twenty_points(self):
        """Both variants live on the same series and disagree.

        PRD §3.5: "The two variants routinely disagree, and both must be
        maintained independently. Take a series with five planned operations.
        Four legs are attached, so `attached_operations` is 4 and
        `utilization_pct_as_filed` is 4 times 100 divided by 5, which is exactly
        80.00 - at the threshold, not below it, so `at_risk_of_loss` is false.
        Meanwhile four utilization records have been filed with outcomes
        `OPERATED`, `OPERATED`, `CANCELLED_ATC` and `CANCELLED_CARRIER`: three
        of those earn credit, so `credited_operations` is 3 and
        `utilization_pct` is 3 times 100 divided by 5, which is 60.00."

        Design: Difficulty/dual_variant_calc/slot_utilization_as_operated_versus_as_filed_diverge_on_one_holding
        """
        world = setup_monday_series_schedule(leg_count=4, series_weeks=5, attach_count=4)
        holding_id = world["holding"]["id"]

        for operation_date, outcome in (
            ("2026-11-16T08:00:00.000Z", "CANCELLED_ATC"),
            ("2026-11-02T08:00:00.000Z", "OPERATED"),
            ("2026-11-23T08:00:00.000Z", "CANCELLED_CARRIER"),
            ("2026-11-09T08:00:00.000Z", "OPERATED"),
        ):
            file_utilization_record(holding_id, operation_date, outcome)

        holding = validate_success(api_client.get_slot_holding(holding_id, COORDINATOR))
        assert_slot_holding(holding)

        assert holding["planned_operations"] == 5
        assert holding["credited_operations"] == 3
        assert holding["utilization_pct"] == pytest.approx(60.00, abs=0.01)
        assert holding["attached_operations"] == 4
        assert holding["utilization_pct_as_filed"] == pytest.approx(80.00, abs=0.01)
        assert holding["utilization_pct_as_filed"] - holding[
            "utilization_pct"
        ] == pytest.approx(20.00, abs=0.01)
        assert holding["holding_status"] == "HELD"
        assert_utilization_math(holding)

    def test_at_risk_keys_on_the_as_filed_variant_only(self):
        """The healthy-looking as-filed figure decides the risk flag.

        PRD §3.5: "This variant drives forward-looking risk: `at_risk_of_loss`
        is true exactly when the series is still `HELD`,
        `attached_operations` is at least 1, and `utilization_pct_as_filed` is
        strictly below 80.00."

        Design: Difficulty/dual_variant_calc/slot_utilization_as_operated_versus_as_filed_diverge_on_one_holding
        """
        world = setup_monday_series_schedule(leg_count=4, series_weeks=5, attach_count=4)
        holding_id = world["holding"]["id"]

        for operation_date, outcome in (
            ("2026-11-16T08:00:00.000Z", "CANCELLED_ATC"),
            ("2026-11-02T08:00:00.000Z", "OPERATED"),
            ("2026-11-23T08:00:00.000Z", "CANCELLED_CARRIER"),
            ("2026-11-09T08:00:00.000Z", "OPERATED"),
        ):
            file_utilization_record(holding_id, operation_date, outcome)

        holding = read_holding(holding_id, COORDINATOR)
        assert holding["utilization_pct"] == pytest.approx(60.00, abs=0.01)
        assert holding["at_risk_of_loss"] is False

        version = read_version(world["version"]["id"], world["planner"])
        assert version["at_risk_slot_count"] == 0
        assert version["schedule_compliance_score"] == pytest.approx(100.00, abs=0.01)
        assert version["compliance_state"] == "CLEAN"

    def test_credited_operations_ignores_the_posting_order(self):
        """Records arriving out of order credit the same total.

        PRD §3.5: "records may legitimately be posted out of chronological order
        and the derived figures must be identical whichever order they arrive
        in."

        Design: Difficulty/dual_variant_calc/slot_utilization_as_operated_versus_as_filed_diverge_on_one_holding
        """
        world = setup_monday_series_schedule(leg_count=4, series_weeks=5, attach_count=4)
        holding_id = world["holding"]["id"]

        posting_order = (
            ("2026-11-16T08:00:00.000Z", "CANCELLED_ATC"),
            ("2026-11-02T08:00:00.000Z", "OPERATED"),
            ("2026-11-23T08:00:00.000Z", "CANCELLED_CARRIER"),
            ("2026-11-09T08:00:00.000Z", "OPERATED"),
        )
        for operation_date, outcome in posting_order:
            file_utilization_record(holding_id, operation_date, outcome)

        holding = read_holding(holding_id, COORDINATOR)
        assert holding["credited_operations"] == 3
        assert holding["utilization_pct"] == pytest.approx(60.00, abs=0.01)
        # The as-filed variant is untouched by what happened on the day.
        assert holding["attached_operations"] == 4
        assert holding["utilization_pct_as_filed"] == pytest.approx(80.00, abs=0.01)


def _build_maintenance_rotation():
    """Five legs on one UTC date between a maintenance-capable base and a
    station that is not maintenance-capable."""
    carrier = create_carrier()
    muc = create_station("MUC")
    txl = create_station("TXL", maintenance_capable=False)
    season = create_open_season()
    aircraft = create_aircraft(
        carrier["id"],
        muc["id"],
        registration="D-AHXB",
        maintenance_check_required=True,
        required_check_minutes=240,
    )
    version = create_schedule_version(
        carrier["id"], season["id"], version_label="W26-MX"
    )

    rotation = (
        ("HX201", muc, txl, "06:00", "07:00"),
        ("HX202", txl, muc, "07:45", "08:45"),
        ("HX203", muc, txl, "11:15", "12:15"),
        ("HX204", txl, muc, "13:00", "14:00"),
        ("HX205", muc, txl, "16:00", "17:00"),
    )
    for flight_number, origin, dest, dep, arr in rotation:
        leg = create_flight_leg(
            carrier["id"],
            version["id"],
            origin["id"],
            dest["id"],
            f"2026-11-03T{dep}:00.000Z",
            f"2026-11-03T{arr}:00.000Z",
            flight_number=flight_number,
        )
        assign_aircraft(carrier["id"], leg["id"], aircraft["id"])

    return {
        "carrier": carrier,
        "aircraft": aircraft,
        "version": version,
        "planner": make_network_planner_headers(carrier["id"]),
    }


class TestMaintenanceOpportunityVariantsDiverge:
    """One tail, two ground-time figures, opposite verdicts against the check
    requirement."""

    def test_contiguous_window_reads_one_fifty_while_cumulative_reads_two_seventy(self):
        """The same tail at the same instant reports both figures.

        PRD §3.3: "The two intervals at the non-capable station, of 45 minutes
        each, are discarded outright. The two at the capable base measure 150
        minutes and 120 minutes. The contiguous-window figure is therefore 150
        while the cumulative-ground figure is 270 - a divergence of 120 minutes
        on the same tail at the same instant."

        Design: Difficulty/dual_variant_calc/maintenance_contiguous_window_versus_cumulative_ground_diverge_on_one_tail
        """
        world = _build_maintenance_rotation()

        rotation = read_rotation(world["aircraft"]["id"], world["planner"])
        assert rotation["maintenance_opportunity_minutes"] == 150
        assert rotation["cumulative_ground_minutes"] == 270
        assert (
            rotation["cumulative_ground_minutes"]
            - rotation["maintenance_opportunity_minutes"]
            == 120
        )
        assert rotation["rotation_feasibility_status"] == "FEASIBLE"
        assert rotation["total_block_minutes"] == 300

        tail = read_aircraft(world["aircraft"]["id"], world["planner"])
        assert tail["maintenance_opportunity_minutes"] == 150
        assert tail["cumulative_ground_minutes"] == 270

    def test_validation_gate_reads_the_contiguous_variant_and_refuses(self):
        """150 contiguous minutes fail a 240-minute check even though the
        cumulative 270 would have cleared.

        PRD §3.3: "A heavy check cannot be split across two separate ground
        periods, so `cumulative_ground_minutes` is never sufficient: with a
        `required_check_minutes` of 240, the tail above fails on its contiguous
        150 even though its cumulative 270 would have cleared."

        Design: Difficulty/dual_variant_calc/maintenance_contiguous_window_versus_cumulative_ground_diverge_on_one_tail
        """
        world = _build_maintenance_rotation()

        response = api_client.validate_schedule_version(world["version"]["id"], OFFICER)
        validate_error(response, ApiErrorId.ERR_MAINTENANCE_OPPORTUNITY_INSUFFICIENT)

        version = read_version(world["version"]["id"], world["planner"])
        assert version["filing_status"] == "DRAFT"
