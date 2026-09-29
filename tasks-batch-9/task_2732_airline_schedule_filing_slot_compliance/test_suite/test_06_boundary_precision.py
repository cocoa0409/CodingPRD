"""Two thresholds probed one unit either side of the boundary.

The required turn is compared inclusively in whole minutes; the as-filed
utilization threshold is guarded by a second conjunct that keeps an empty series
off the at-risk list even at 0.00 percent.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_slot_holding,
    assign_aircraft,
    attach_slot,
    create_flight_leg,
    read_aircraft,
    read_holding,
    read_leg,
    read_rotation,
    read_version,
    setup_domestic_rotation_base,
    setup_monday_series_schedule,
    validate_error,
    validate_success,
    TEST_USERS,
)

COORDINATOR = TEST_USERS["slot_coordinator_headers"]


def _turn_pair_at(dep_utc: str, arr_utc: str):
    """An assigned MUC->TXL leg followed by a TXL->MUC leg still in DRAFT."""
    world = setup_domestic_rotation_base(
        version_label="W26-T6",
        station_overrides={
            "MUC": {"min_turn_override_minutes": 0},
            "TXL": {"min_turn_override_minutes": 0, "maintenance_capable": False},
        },
        aircraft_overrides={"registration": "D-AHXT", "status": "IN_SERVICE"},
    )
    stations = world["stations"]
    leg_a = create_flight_leg(
        world["carrier"]["id"],
        world["version"]["id"],
        stations["MUC"]["id"],
        stations["TXL"]["id"],
        "2026-11-03T08:00:00.000Z",
        "2026-11-03T09:00:00.000Z",
        flight_number="HX310",
    )
    world["leg_a"] = assign_aircraft(
        world["carrier"]["id"], leg_a["id"], world["aircraft"]["id"]
    )
    world["leg_b"] = create_flight_leg(
        world["carrier"]["id"],
        world["version"]["id"],
        stations["TXL"]["id"],
        stations["MUC"]["id"],
        dep_utc,
        arr_utc,
        flight_number="HX311",
    )
    return world


class TestTurnTimeBoundaryIsInclusive:
    """44 minutes is refused, 45 is accepted, 46 stays accepted."""

    def test_one_minute_short_of_the_required_turn_is_refused(self):
        """44 ground minutes against a required 45 is a turn violation.

        PRD §3.3: "the comparison is inclusive, so a tail arriving at 09:00 with
        a required turn of 45 minutes may legally depart again at exactly 09:45,
        while 09:44 is refused with `ERR_TURN_TIME_VIOLATION` and the verdict is
        `INFEASIBLE_TURN`."

        Design: Difficulty/boundary_precision_check/turn_time_boundary_is_inclusive_at_exactly_required_turn_minutes
        """
        world = _turn_pair_at(
            "2026-11-03T09:44:00.000Z", "2026-11-03T10:44:00.000Z"
        )

        validate_error(
            api_client.assign_aircraft(
                world["leg_b"]["id"],
                {"aircraft_id": world["aircraft"]["id"]},
                world["planner"],
            ),
            ApiErrorId.ERR_TURN_TIME_VIOLATION,
            expected_status=422,
        )

        leg_b = read_leg(world["leg_b"]["id"], world["planner"])
        assert leg_b["status"] == "DRAFT"
        assert leg_b["assigned_aircraft_id"] is None

        rotation = read_rotation(world["aircraft"]["id"], world["planner"])
        assert rotation["rotation_feasibility_status"] == "FEASIBLE"
        assert rotation["ordered_leg_ids"] == [world["leg_a"]["id"]]
        assert rotation["total_block_minutes"] == 60

    def test_exactly_the_required_turn_is_accepted(self):
        """45 ground minutes clears, and the rotation view reports the required
        turn.

        PRD §3.3: "`required_turn_minutes` is the required turn computed at the
        first consecutive pair, and `total_block_minutes` is the summed block
        time of the tail's non-cancelled legs."

        Design: Difficulty/boundary_precision_check/turn_time_boundary_is_inclusive_at_exactly_required_turn_minutes
        """
        world = _turn_pair_at(
            "2026-11-03T09:45:00.000Z", "2026-11-03T10:45:00.000Z"
        )

        leg_b = validate_success(
            api_client.assign_aircraft(
                world["leg_b"]["id"],
                {"aircraft_id": world["aircraft"]["id"]},
                world["planner"],
            )
        )
        assert leg_b["status"] == "SLOT_BACKED"
        assert leg_b["assigned_aircraft_id"] == world["aircraft"]["id"]

        rotation = read_rotation(world["aircraft"]["id"], world["planner"])
        assert rotation["rotation_feasibility_status"] == "FEASIBLE"
        assert rotation["required_turn_minutes"] == 45
        assert rotation["total_block_minutes"] == 120
        assert rotation["first_violation_leg_id"] is None
        assert rotation["ordered_leg_ids"] == [
            world["leg_a"]["id"],
            world["leg_b"]["id"],
        ]

    def test_the_safe_side_of_the_boundary_stays_safe_at_forty_six(self):
        """One minute of slack changes nothing about the verdict.

        PRD §3.3: "Keep that interval only when the station where the aircraft is
        actually sitting - the earlier leg's `dest_station_id` - has
        `maintenance_capable` true; discard it otherwise."

        Design: Difficulty/boundary_precision_check/turn_time_boundary_is_inclusive_at_exactly_required_turn_minutes
        """
        world = _turn_pair_at(
            "2026-11-03T09:46:00.000Z", "2026-11-03T10:46:00.000Z"
        )
        validate_success(
            api_client.assign_aircraft(
                world["leg_b"]["id"],
                {"aircraft_id": world["aircraft"]["id"]},
                world["planner"],
            )
        )

        tail = read_aircraft(world["aircraft"]["id"], world["planner"])
        assert tail["rotation_feasibility_status"] == "FEASIBLE"
        assert tail["assigned_leg_count"] == 2
        # The only ground interval sits at TXL, which is not maintenance
        # capable, so both variants discard it.
        assert tail["maintenance_opportunity_minutes"] == 0
        assert tail["cumulative_ground_minutes"] == 0

        version = read_version(world["version"]["id"], world["planner"])
        assert version["unslotted_leg_count"] == 0
        assert version["schedule_compliance_score"] == pytest.approx(100.00, abs=0.01)


def _empty_series_and_one_unattached_leg():
    """A five-week series with nothing attached and one assigned leg waiting."""
    return setup_monday_series_schedule(
        leg_count=1, series_weeks=5, attach_count=0, version_label="W26-Z1"
    )


class TestAtRiskGuardAtTheEmptyBoundary:
    """0 attached operations is not at risk; 1 is."""

    def test_an_empty_series_is_dormant_rather_than_at_risk(self):
        """0.00 percent is far below the threshold and still not at risk.

        PRD §3.5: "A series with five planned operations and no legs attached at
        all has an as-filed figure of 0.00, which is far below the threshold, yet
        `at_risk_of_loss` stays false because the second conjunct fails - a series
        nobody has begun planning against is dormant, not at risk."

        Design: Difficulty/boundary_precision_check/at_risk_of_loss_stays_false_at_zero_attached_operations_and_flips_at_one
        """
        world = _empty_series_and_one_unattached_leg()

        holding = read_holding(world["holding"]["id"], COORDINATOR)
        assert_slot_holding(holding)
        assert holding["planned_operations"] == 5
        assert holding["attached_operations"] == 0
        assert holding["utilization_pct_as_filed"] == pytest.approx(0.00, abs=0.01)
        assert holding["utilization_pct"] == pytest.approx(0.00, abs=0.01)
        assert holding["credited_operations"] == 0
        assert holding["at_risk_of_loss"] is False

        version = read_version(world["version"]["id"], world["planner"])
        assert version["at_risk_slot_count"] == 0
        assert version["unslotted_leg_count"] == 1
        assert version["schedule_compliance_score"] == pytest.approx(92.00, abs=0.01)
        assert version["compliance_state"] == "CLEAN"

    def test_the_first_attachment_flips_the_flag_at_twenty_percent(self):
        """Moving the count from 0 to 1 satisfies every conjunct at once.

        PRD §3.5: "Attach a single leg and the figure becomes 20.00 with
        `at_risk_of_loss` now true."

        Design: Difficulty/boundary_precision_check/at_risk_of_loss_stays_false_at_zero_attached_operations_and_flips_at_one
        """
        world = _empty_series_and_one_unattached_leg()

        leg = attach_slot(
            world["carrier"]["id"],
            world["legs"][0]["id"],
            world["holding"]["id"],
            "DEPARTURE",
        )
        assert leg["status"] == "SLOT_BACKED"

        holding = read_holding(world["holding"]["id"], COORDINATOR)
        assert holding["attached_operations"] == 1
        assert holding["utilization_pct_as_filed"] == pytest.approx(20.00, abs=0.01)
        assert holding["at_risk_of_loss"] is True
        # The as-operated variant reads credited operations, and none exist.
        assert holding["utilization_pct"] == pytest.approx(0.00, abs=0.01)

    def test_one_at_risk_series_blocks_a_version_scoring_exactly_eighty_five(self):
        """85.00 is not below the warning threshold, yet the version is
        blocked.

        PRD §3.7: "the version scoring exactly 85.00 because of a single at-risk
        slot would be `CLEAN` on score alone - 85.00 is not below 85.00 - yet it
        is `BLOCKED`, because a single at-risk series blocks a plan outright
        regardless of how good the rest of the score looks."

        Design: Difficulty/boundary_precision_check/at_risk_of_loss_stays_false_at_zero_attached_operations_and_flips_at_one
        """
        world = _empty_series_and_one_unattached_leg()
        attach_slot(
            world["carrier"]["id"],
            world["legs"][0]["id"],
            world["holding"]["id"],
            "DEPARTURE",
        )

        version = read_version(world["version"]["id"], world["planner"])
        assert version["unslotted_leg_count"] == 0
        assert version["at_risk_slot_count"] == 1
        assert version["schedule_compliance_score"] == pytest.approx(85.00, abs=0.01)
        assert version["compliance_state"] == "BLOCKED"
