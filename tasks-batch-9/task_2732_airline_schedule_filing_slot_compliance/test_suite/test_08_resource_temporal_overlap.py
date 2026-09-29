"""Three resources whose overlap semantics are each different.

A tail's consecutive legs must be separated by a buffer whose width depends on
the previous leg; a station's gate occupancy is a half-open aggregate interval so
touching endpoints never collide; a slot series' recurrence is a discrete
day-of-week set that collides only on intersection.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    assign_aircraft,
    create_flight_leg,
    create_flight_leg_payload,
    create_slot_holding,
    create_slot_holding_payload,
    read_aircraft,
    read_leg,
    read_rotation,
    read_season,
    read_version,
    retime_leg,
    setup_gate_occupancy_base,
    setup_international_rotation_base,
    setup_reference_data,
    validate_error,
    validate_paginated,
    validate_success,
    TEST_USERS,
)

COORDINATOR = TEST_USERS["slot_coordinator_headers"]


# ─── Resource 1: the aircraft, with a buffered point adjacency ────────────

def _international_out_and_back(*, return_dep: str, return_arr: str):
    """MUC->LIS assigned to the tail, and the LIS->MUC return still in DRAFT."""
    world = setup_international_rotation_base(
        version_label="W26-R8",
        aircraft_overrides={
            "registration": "D-AHXI",
            "fleet_type_code": "A320",
            "min_turn_minutes": 45,
            "max_daily_block_minutes": 600,
            "required_check_minutes": 240,
        },
        station_overrides={
            "MUC": {"min_turn_override_minutes": 0},
            "LIS": {
                "gate_count": 2,
                "min_turn_override_minutes": 0,
                "maintenance_capable": False,
            },
        },
    )
    stations = world["stations"]
    outbound = create_flight_leg(
        world["carrier"]["id"],
        world["version"]["id"],
        stations["MUC"]["id"],
        stations["LIS"]["id"],
        "2026-11-03T09:30:00.000Z",
        "2026-11-03T12:00:00.000Z",
        flight_number="HX440",
        fleet_type_code="A320",
    )
    world["outbound"] = assign_aircraft(
        world["carrier"]["id"], outbound["id"], world["aircraft"]["id"]
    )
    world["inbound"] = create_flight_leg(
        world["carrier"]["id"],
        world["version"]["id"],
        stations["LIS"]["id"],
        stations["MUC"]["id"],
        return_dep,
        return_arr,
        flight_number="HX441",
        fleet_type_code="A320",
    )
    return world


class TestInternationalTurnBufferWidens:
    """45 ground minutes is legal after a domestic sector and illegal after an
    international one."""

    def test_a_domestic_length_turn_fails_after_an_international_inbound(self):
        """The buffer is a function of the previous leg, not a constant.

        PRD §3.3: "The required turn after an inbound leg is the larger of the
        tail's `min_turn_minutes` and the `min_turn_override_minutes` of the
        station the inbound leg arrives at, and then, when that inbound leg is
        international, 15 further minutes are added on top."

        Design: Difficulty/resource_temporal_overlap/aircraft_turn_buffer_widens_for_international_inbound_at_the_same_point_adjacency
        """
        world = _international_out_and_back(
            return_dep="2026-11-03T12:45:00.000Z",
            return_arr="2026-11-03T15:15:00.000Z",
        )
        assert world["outbound"]["is_international"] is True
        assert world["outbound"]["block_minutes"] == 150
        assert world["inbound"]["is_international"] is True

        validate_error(
            api_client.assign_aircraft(
                world["inbound"]["id"],
                {"aircraft_id": world["aircraft"]["id"]},
                world["planner"],
            ),
            ApiErrorId.ERR_TURN_TIME_VIOLATION,
            expected_status=422,
        )

        inbound = read_leg(world["inbound"]["id"], world["planner"])
        assert inbound["status"] == "DRAFT"
        assert inbound["assigned_aircraft_id"] is None

    def test_exactly_sixty_ground_minutes_clears_the_widened_buffer(self):
        """Retime the return by 15 minutes and the identical assignment
        succeeds.

        PRD §3.3: "and a 45-minute fleet turn after an international inbound
        sector at a station with no override becomes 60 minutes."

        Design: Difficulty/resource_temporal_overlap/aircraft_turn_buffer_widens_for_international_inbound_at_the_same_point_adjacency
        """
        world = _international_out_and_back(
            return_dep="2026-11-03T12:45:00.000Z",
            return_arr="2026-11-03T15:15:00.000Z",
        )
        validate_error(
            api_client.assign_aircraft(
                world["inbound"]["id"],
                {"aircraft_id": world["aircraft"]["id"]},
                world["planner"],
            ),
            ApiErrorId.ERR_TURN_TIME_VIOLATION,
        )

        retime_leg(
            world["carrier"]["id"],
            world["inbound"]["id"],
            "2026-11-03T13:00:00.000Z",
            "2026-11-03T15:30:00.000Z",
        )
        assigned = validate_success(
            api_client.assign_aircraft(
                world["inbound"]["id"],
                {"aircraft_id": world["aircraft"]["id"]},
                world["planner"],
            )
        )
        assert assigned["status"] == "SLOT_BACKED"
        assert assigned["assigned_aircraft_id"] == world["aircraft"]["id"]

        rotation = read_rotation(world["aircraft"]["id"], world["planner"])
        assert rotation["rotation_feasibility_status"] == "FEASIBLE"
        assert rotation["required_turn_minutes"] == 60
        assert rotation["total_block_minutes"] == 300
        assert rotation["first_violation_leg_id"] is None

    def test_the_only_ground_period_is_at_a_station_with_no_hangar(self):
        """Both duration variants discard the LIS interval.

        PRD §3.3: "Keep that interval only when the station where the aircraft is
        actually sitting - the earlier leg's `dest_station_id` - has
        `maintenance_capable` true; discard it otherwise."

        Design: Difficulty/resource_temporal_overlap/aircraft_turn_buffer_widens_for_international_inbound_at_the_same_point_adjacency
        """
        world = _international_out_and_back(
            return_dep="2026-11-03T13:00:00.000Z",
            return_arr="2026-11-03T15:30:00.000Z",
        )
        assign_aircraft(
            world["carrier"]["id"], world["inbound"]["id"], world["aircraft"]["id"]
        )

        tail = read_aircraft(world["aircraft"]["id"], world["planner"])
        assert tail["assigned_leg_count"] == 2
        assert tail["maintenance_opportunity_minutes"] == 0
        assert tail["cumulative_ground_minutes"] == 0
        # Both traffic rights are live, so neither heading was ever questioned.
        assert world["outbound"]["is_international"] is True
        assert world["inbound"]["is_international"] is True


# ─── Resource 2: the station, with half-open aggregate occupancy ──────────

def _two_departures_filling_both_gates():
    """FRA departures at 08:00 and 08:20 put the hub exactly at capacity."""
    world = setup_gate_occupancy_base(version_label="W26-G8")
    stations = world["stations"]
    world["legs"] = [
        create_flight_leg(
            world["carrier"]["id"],
            world["version"]["id"],
            stations["FRA"]["id"],
            stations["MUC"]["id"],
            f"2026-11-04T{dep}:00.000Z",
            f"2026-11-04T{arr}:00.000Z",
            flight_number=number,
        )
        for number, dep, arr in (
            ("HX501", "08:00", "09:00"),
            ("HX502", "08:20", "09:20"),
        )
    ]
    world["departure_at"] = lambda dep, arr, number: create_flight_leg_payload(
        world["version"]["id"],
        stations["FRA"]["id"],
        stations["MUC"]["id"],
        f"2026-11-04T{dep}:00.000Z",
        f"2026-11-04T{arr}:00.000Z",
        flight_number=number,
    )
    return world


class TestGateOccupancyIntervalsAreHalfOpen:
    """A third departure overflows at 08:40 but not at 08:45."""

    def test_a_third_overlapping_departure_is_refused_at_creation(self):
        """At 07:55 all three prep intervals are live against two gates.

        PRD §3.4: "At a station with two gates, departures at 08:00, 08:20 and
        08:40 produce intervals beginning at 07:15, 07:35 and 07:55; at 07:55 all
        three are active, peak concurrency is 3, and the third leg is refused with
        `ERR_GATE_CAPACITY_EXCEEDED`."

        Design: Difficulty/resource_temporal_overlap/station_gate_occupancy_intervals_are_half_open_so_touching_endpoints_do_not_overlap
        """
        world = _two_departures_filling_both_gates()

        validate_error(
            api_client.create_flight_leg(
                world["departure_at"]("08:40", "09:40", "HX503"), world["planner"]
            ),
            ApiErrorId.ERR_GATE_CAPACITY_EXCEEDED,
            expected_status=409,
        )

        version = read_version(world["version"]["id"], world["planner"])
        assert version["leg_count"] == 2
        assert version["gate_overflow_count"] == 0

    def test_a_departure_whose_interval_merely_touches_is_accepted(self):
        """[08:00, 08:45) does not overlap [07:15, 08:00).

        PRD §3.4: "A departure at 08:00 and another at 08:45 never overlap,
        because the first interval has already ended at the instant the second
        begins; but an arrival at 08:00 and a departure at 08:45 both occupy the
        instant 08:00 and do overlap, giving a peak of 2."

        Design: Difficulty/resource_temporal_overlap/station_gate_occupancy_intervals_are_half_open_so_touching_endpoints_do_not_overlap
        """
        world = _two_departures_filling_both_gates()
        validate_error(
            api_client.create_flight_leg(
                world["departure_at"]("08:40", "09:40", "HX503"), world["planner"]
            ),
            ApiErrorId.ERR_GATE_CAPACITY_EXCEEDED,
        )

        accepted = validate_success(
            api_client.create_flight_leg(
                world["departure_at"]("08:45", "09:45", "HX504"), world["planner"]
            ),
            expected_status=201,
        )
        assert accepted["status"] == "DRAFT"

        version = read_version(world["version"]["id"], world["planner"])
        assert version["leg_count"] == 3
        assert version["gate_overflow_count"] == 0
        assert version["unslotted_leg_count"] == 3
        assert version["schedule_compliance_score"] == pytest.approx(76.00, abs=0.01)
        assert version["compliance_state"] == "WARNED"

    def test_a_retime_into_the_congested_bank_records_the_overflow_instead(self):
        """The exact time that a POST refused, a PATCH accepts and penalises.

        PRD §3.4: "But a retime that creates a gate overflow is **accepted** and
        increments the version's `gate_overflow_count`, and a retime that creates
        a connect-time shortfall is **accepted** and increments the version's
        `mct_violation_count`."

        Design: Difficulty/resource_temporal_overlap/station_gate_occupancy_intervals_are_half_open_so_touching_endpoints_do_not_overlap
        """
        world = _two_departures_filling_both_gates()
        accepted = validate_success(
            api_client.create_flight_leg(
                world["departure_at"]("08:45", "09:45", "HX504"), world["planner"]
            ),
            expected_status=201,
        )

        retimed = retime_leg(
            world["carrier"]["id"],
            accepted["id"],
            "2026-11-04T08:40:00.000Z",
            "2026-11-04T09:40:00.000Z",
        )
        from test_helpers import assert_timestamp_equals

        assert_timestamp_equals(
            retimed["dep_utc"], "2026-11-04T08:40:00Z", "dep_utc"
        )

        version = read_version(world["version"]["id"], world["planner"])
        assert version["gate_overflow_count"] == 1
        assert version["schedule_compliance_score"] == pytest.approx(67.00, abs=0.01)
        assert version["compliance_state"] == "WARNED"


# ─── Resource 3: the runway coordinate, with a discrete recurrence set ────

def _incumbent_mask_135():
    """One FRA departure series on Mondays, Wednesdays and Fridays."""
    ref = setup_reference_data(("FRA",), with_partner=True)
    incumbent = create_slot_holding(
        ref["stations"]["FRA"]["id"],
        ref["season"]["id"],
        ref["carrier"]["id"],
        movement_type="DEPARTURE",
        slot_time_utc="2026-11-02T08:00:00.000Z",
        days_of_week="135",
        series_weeks=5,
        historic_precedence=False,
    )
    ref["incumbent"] = incumbent
    return ref


def _same_coordinate_payload(ref, *, owner_id, days_of_week, movement_type="DEPARTURE"):
    return create_slot_holding_payload(
        ref["stations"]["FRA"]["id"],
        ref["season"]["id"],
        owner_id,
        movement_type=movement_type,
        slot_time_utc="2026-11-02T08:00:00.000Z",
        days_of_week=days_of_week,
        series_weeks=5,
        historic_precedence=False,
    )


class TestSlotSeriesMasksCollideOnlyOnIntersection:
    """Same station, season, movement type and time-of-day; only the mask
    differs."""

    def test_disjoint_masks_coexist_at_the_identical_coordinate(self):
        """Masks 246 and 7 both clear an incumbent 135.

        PRD §3.5: "Masks that overlap on a single day conflict; masks that are
        disjoint - "135" against "246" at the same station, season, movement type
        and time-of-day - coexist happily."

        Design: Difficulty/resource_temporal_overlap/slot_series_day_of_week_masks_conflict_only_on_set_intersection
        """
        ref = _incumbent_mask_135()
        assert ref["incumbent"]["planned_operations"] == 15

        even_days = validate_success(
            api_client.create_slot_holding(
                _same_coordinate_payload(
                    ref, owner_id=ref["partner"]["id"], days_of_week="246"
                ),
                COORDINATOR,
            ),
            expected_status=201,
        )
        assert even_days["days_of_week"] == "246"
        assert even_days["planned_operations"] == 15

        sunday = validate_success(
            api_client.create_slot_holding(
                _same_coordinate_payload(
                    ref, owner_id=ref["partner"]["id"], days_of_week="7"
                ),
                COORDINATOR,
            ),
            expected_status=201,
        )
        assert sunday["planned_operations"] == 5

    def test_a_single_shared_day_is_enough_to_conflict(self):
        """Mask 57 meets the incumbent on day 5 alone and is refused.

        PRD §3.5: "A new series is refused with `ERR_SLOT_SERIES_CONFLICT` when
        some other series already in `holding_status` `HELD` shares this one's
        `station_id`, `season_id`, `movement_type` **and** the UTC time-of-day of
        its `slot_time_utc`, while the digit sets of the two `days_of_week` masks
        intersect in at least one day."

        Design: Difficulty/resource_temporal_overlap/slot_series_day_of_week_masks_conflict_only_on_set_intersection
        """
        ref = _incumbent_mask_135()
        validate_success(
            api_client.create_slot_holding(
                _same_coordinate_payload(
                    ref, owner_id=ref["partner"]["id"], days_of_week="246"
                ),
                COORDINATOR,
            ),
            expected_status=201,
        )

        validate_error(
            api_client.create_slot_holding(
                _same_coordinate_payload(
                    ref, owner_id=ref["partner"]["id"], days_of_week="57"
                ),
                COORDINATOR,
            ),
            ApiErrorId.ERR_SLOT_SERIES_CONFLICT,
            expected_status=409,
        )

    def test_movement_type_is_part_of_the_coordinate(self):
        """An arrival series repeats mask 135 at the same instant and clears.

        PRD §3.5: "Creating a series recomputes the holding carrier's
        `held_series_count` and the season's `held_series_count`."

        Design: Difficulty/resource_temporal_overlap/slot_series_day_of_week_masks_conflict_only_on_set_intersection
        """
        ref = _incumbent_mask_135()
        for owner, mask in (
            (ref["partner"]["id"], "246"),
            (ref["partner"]["id"], "7"),
        ):
            validate_success(
                api_client.create_slot_holding(
                    _same_coordinate_payload(ref, owner_id=owner, days_of_week=mask),
                    COORDINATOR,
                ),
                expected_status=201,
            )
        validate_error(
            api_client.create_slot_holding(
                _same_coordinate_payload(
                    ref, owner_id=ref["partner"]["id"], days_of_week="57"
                ),
                COORDINATOR,
            ),
            ApiErrorId.ERR_SLOT_SERIES_CONFLICT,
        )

        arrival = validate_success(
            api_client.create_slot_holding(
                _same_coordinate_payload(
                    ref,
                    owner_id=ref["carrier"]["id"],
                    days_of_week="135",
                    movement_type="ARRIVAL",
                ),
                COORDINATOR,
            ),
            expected_status=201,
        )
        assert arrival["movement_type"] == "ARRIVAL"
        assert arrival["planned_operations"] == 15

        rows, meta = validate_paginated(
            api_client.list_slot_holdings(
                COORDINATOR,
                params={
                    "station_id": ref["stations"]["FRA"]["id"],
                    "season_id": ref["season"]["id"],
                },
            )
        )
        assert meta["total_count"] == 4
        assert len(rows) == 4

        season = read_season(ref["season"]["id"])
        assert season["held_series_count"] == 4
