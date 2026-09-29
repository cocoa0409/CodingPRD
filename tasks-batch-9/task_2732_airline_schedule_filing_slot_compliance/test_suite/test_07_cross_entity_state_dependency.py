"""Two writes whose legality is decided by a *second* entity's status.

Assigning a tail to a leg is gated by the tail's airworthiness status, and
handing a series back is gated by the owning season's status. In both cases the
subject entity is perfectly ready; the gate lives on the other row.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_slot_holding,
    create_aircraft,
    create_carrier,
    create_flight_leg,
    create_open_season,
    create_schedule_version,
    create_slot_holding,
    create_station,
    make_network_planner_headers,
    read_aircraft,
    read_carrier,
    read_holding,
    read_leg,
    read_season,
    read_version,
    return_holding,
    validate_error,
    validate_success,
    TEST_USERS,
)

ADMIN = TEST_USERS["system_admin_headers"]
COORDINATOR = TEST_USERS["slot_coordinator_headers"]


def _one_grounded_and_one_live_tail():
    """A DRAFT domestic leg plus two identical tails in different statuses."""
    carrier = create_carrier()
    muc = create_station("MUC")
    txl = create_station("TXL")
    season = create_open_season()
    grounded = create_aircraft(
        carrier["id"],
        muc["id"],
        registration="D-AHXG",
        status="MAINTENANCE_GROUNDED",
    )
    live = create_aircraft(
        carrier["id"], muc["id"], registration="D-AHXA", status="IN_SERVICE"
    )
    version = create_schedule_version(
        carrier["id"], season["id"], version_label="W26-X1"
    )
    leg = create_flight_leg(
        carrier["id"],
        version["id"],
        muc["id"],
        txl["id"],
        "2026-11-03T08:00:00.000Z",
        "2026-11-03T09:00:00.000Z",
        flight_number="HX320",
    )
    return {
        "carrier": carrier,
        "planner": make_network_planner_headers(carrier["id"]),
        "version": version,
        "grounded": grounded,
        "live": live,
        "leg": leg,
    }


def _assign(world, tail):
    return api_client.assign_aircraft(
        world["leg"]["id"], {"aircraft_id": tail["id"]}, world["planner"]
    )


class TestLegAssignmentIsGatedByTheTailStatus:
    """The leg is a valid DRAFT either way; only the tail's status decides."""

    def test_a_grounded_tail_cannot_take_a_leg_that_is_otherwise_ready(self):
        """The gate is on the other entity, so the refusal cites the tail.

        PRD §3.3: "the tail's `status` must be `IN_SERVICE`, and a
        `MAINTENANCE_GROUNDED` or `RETIRED` tail is refused with
        `ERR_AIRCRAFT_NOT_IN_SERVICE`"

        Design: Difficulty/cross_entity_state_dependency/leg_assignment_is_gated_by_the_aircraft_status_dimension
        """
        world = _one_grounded_and_one_live_tail()
        assert world["grounded"]["status"] == "MAINTENANCE_GROUNDED"

        validate_error(
            _assign(world, world["grounded"]),
            ApiErrorId.ERR_AIRCRAFT_NOT_IN_SERVICE,
            expected_status=422,
        )

        leg = read_leg(world["leg"]["id"], world["planner"])
        assert leg["status"] == "DRAFT"
        assert leg["assigned_aircraft_id"] is None

    def test_the_refused_tail_keeps_an_empty_unchecked_rotation(self):
        """Nothing was written to the gating entity either.

        PRD §3.3: "`rotation_feasibility_status` is `UNCHECKED` only while that
        count is 0; once the tail carries at least one leg it must hold one of
        `FEASIBLE`, `INFEASIBLE_CONTINUITY`, `INFEASIBLE_TURN` or
        `INFEASIBLE_BLOCK_CAP`."

        Design: Difficulty/cross_entity_state_dependency/leg_assignment_is_gated_by_the_aircraft_status_dimension
        """
        world = _one_grounded_and_one_live_tail()
        validate_error(
            _assign(world, world["grounded"]), ApiErrorId.ERR_AIRCRAFT_NOT_IN_SERVICE
        )

        grounded = read_aircraft(world["grounded"]["id"], world["planner"])
        assert grounded["assigned_leg_count"] == 0
        assert grounded["rotation_feasibility_status"] == "UNCHECKED"
        assert grounded["status"] == "MAINTENANCE_GROUNDED"

    def test_an_in_service_tail_takes_the_identical_leg(self):
        """Same leg, same request shape: only the tail's status changed.

        PRD §3.3: "**Assigning a tail to a leg** advances the leg from `DRAFT` to
        `ASSIGNED` and is the moment the whole rotation is re-walked."

        Design: Difficulty/cross_entity_state_dependency/leg_assignment_is_gated_by_the_aircraft_status_dimension
        """
        world = _one_grounded_and_one_live_tail()
        validate_error(
            _assign(world, world["grounded"]), ApiErrorId.ERR_AIRCRAFT_NOT_IN_SERVICE
        )

        assigned = validate_success(_assign(world, world["live"]))
        # Neither MUC nor TXL is fully coordinated, so no slot is required and
        # the leg passes straight through `ASSIGNED`.
        assert assigned["status"] == "SLOT_BACKED"
        assert assigned["assigned_aircraft_id"] == world["live"]["id"]

        live = read_aircraft(world["live"]["id"], world["planner"])
        assert live["assigned_leg_count"] == 1
        assert live["rotation_feasibility_status"] == "FEASIBLE"

        version = read_version(world["version"]["id"], world["planner"])
        assert version["leg_count"] == 1
        assert version["unslotted_leg_count"] == 0
        assert version["schedule_compliance_score"] == pytest.approx(100.00, abs=0.01)
        assert version["compliance_state"] == "CLEAN"


def _two_grandfathered_series():
    """Two historic series at the same coordinated hub, an hour apart."""
    carrier = create_carrier()
    fra = create_station("FRA")
    season = create_open_season()

    def series(time_of_day):
        return create_slot_holding(
            fra["id"],
            season["id"],
            carrier["id"],
            movement_type="DEPARTURE",
            slot_time_utc=f"2026-11-02T{time_of_day}:00:00.000Z",
            days_of_week="1",
            series_weeks=5,
            historic_precedence=True,
        )

    return {
        "carrier": carrier,
        "planner": make_network_planner_headers(carrier["id"]),
        "season": season,
        "first": series("08"),
        "second": series("09"),
    }


class TestSlotReturnIsGatedByTheOwningSeasonStatus:
    """Identical returns, one before and one after the season closes."""

    def test_a_return_against_an_open_season_protects_the_grandfather_claim(self):
        """With the gating entity `OPEN`, the return succeeds in full.

        PRD §3.5: "On success `holding_status` moves `HELD → RETURNED`,
        `returned_reason` records the supplied reason, `returned_before_deadline`
        is set to true and `retains_historic_precedence` is set to true."

        Design: Difficulty/cross_entity_state_dependency/slot_return_is_gated_by_the_owning_season_status
        """
        world = _two_grandfathered_series()

        returned = return_holding(
            world["first"]["id"],
            reason="SEASONAL_RIGHTSIZING",
            carrier_id=world["carrier"]["id"],
        )
        assert_slot_holding(returned)
        assert returned["holding_status"] == "RETURNED"
        assert returned["returned_reason"] == "SEASONAL_RIGHTSIZING"
        assert returned["returned_before_deadline"] is True
        assert returned["retains_historic_precedence"] is True
        assert returned["attached_operations"] == 0
        assert returned["utilization_pct_as_filed"] == pytest.approx(0.00, abs=0.01)
        assert returned["at_risk_of_loss"] is False
        # The grandfather claim itself is untouched by the return.
        assert returned["historic_precedence"] is True

    def test_closing_the_season_blocks_the_identical_return_of_the_sibling(self):
        """The sibling series is still `HELD` and still inside the deadline.

        PRD §3.5: "the season must be `OPEN` (`ERR_SEASON_NOT_OPEN`)."

        Design: Difficulty/cross_entity_state_dependency/slot_return_is_gated_by_the_owning_season_status
        """
        world = _two_grandfathered_series()
        return_holding(
            world["first"]["id"], carrier_id=world["carrier"]["id"]
        )

        validate_success(
            api_client.transition_season(
                world["season"]["id"], {"to_status": "CLOSED"}, ADMIN
            )
        )

        validate_error(
            api_client.return_slot_holding(
                world["second"]["id"],
                {"reason": "SEASONAL_RIGHTSIZING"},
                world["planner"],
            ),
            ApiErrorId.ERR_SEASON_NOT_OPEN,
            expected_status=409,
        )

        second = read_holding(world["second"]["id"], COORDINATOR)
        assert second["holding_status"] == "HELD"
        assert second["returned_reason"] is None
        assert second["returned_before_deadline"] is None
        assert second["retains_historic_precedence"] is None

    def test_both_held_series_counters_agree_after_the_one_successful_return(self):
        """Exactly one series left `HELD`, on both derived counters.

        PRD §3.1: "That counter is derived, not stored by hand: it is always the
        number of slot series whose `carrier_id` is this carrier and whose
        `holding_status` is `HELD`, and it is recomputed whenever a series is
        created, returned, transferred away, or taken by the season audit."

        Design: Difficulty/cross_entity_state_dependency/slot_return_is_gated_by_the_owning_season_status
        """
        world = _two_grandfathered_series()
        return_holding(world["first"]["id"], carrier_id=world["carrier"]["id"])
        validate_success(
            api_client.transition_season(
                world["season"]["id"], {"to_status": "CLOSED"}, ADMIN
            )
        )
        validate_error(
            api_client.return_slot_holding(
                world["second"]["id"],
                {"reason": "SEASONAL_RIGHTSIZING"},
                world["planner"],
            ),
            ApiErrorId.ERR_SEASON_NOT_OPEN,
        )

        season = read_season(world["season"]["id"], ADMIN)
        assert season["status"] == "CLOSED"
        assert season["held_series_count"] == 1

        carrier = read_carrier(world["carrier"]["id"], ADMIN)
        assert carrier["held_series_count"] == 1
