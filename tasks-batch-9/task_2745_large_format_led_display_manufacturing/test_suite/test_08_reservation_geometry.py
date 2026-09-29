"""Two reservation calendars with deliberately opposite interval conventions.

Chamber occupancy is closed at both ends, buffered by a cool-down and pooled as
an aggregate slot budget; crew occupancy is half-open, unbuffered and exclusive.
The same abutting instant is therefore a collision in one calendar and a legal
back-to-back booking in the other.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_errors import (
    ERR_CHAMBER_CAPACITY_EXCEEDED,
    ERR_CREW_DOUBLE_BOOKED,
)
from test_helpers.assertions import (
    assert_cabinet_fields,
    assert_chamber_fields,
    assert_instant_equals,
    assert_run_fields,
    assert_visit_fields,
)
from test_helpers.constants import (
    CABINET_BURN_IN,
    CABINET_POPULATED,
    RUN_SCHEDULED,
    SOAK_WINDOW_END,
    SOAK_WINDOW_START,
    VISIT_SCHEDULED,
    VISIT_WINDOW_END,
    VISIT_WINDOW_START,
)
from test_helpers.factories import burn_in_run_payload, commissioning_visit_payload
from test_helpers.fixtures import Scene

#: Run A holds three of the chamber's four slots and its cool-down ends here.
RUN_A_OCCUPIED_UNTIL = "2026-08-03T01:00:00.000Z"
#: A window that starts on the closed endpoint of run A's buffered occupancy.
TOUCHING_WINDOW_START = "2026-08-03T01:00:00.000Z"
TOUCHING_WINDOW_END = "2026-08-04T01:00:00.000Z"
TOUCHING_OCCUPIED_UNTIL = "2026-08-04T02:00:00.000Z"
#: The same window shifted one millisecond clear of run A's closed endpoint.
CLEAR_WINDOW_START = "2026-08-03T01:00:00.001Z"
CLEAR_WINDOW_END = "2026-08-04T01:00:00.001Z"
CLEAR_OCCUPIED_UNTIL = "2026-08-04T02:00:00.001Z"

#: A crew window that begins exactly where the first visit's window ends.
ABUTTING_WINDOW_START = "2026-08-05T16:00:00.000Z"
ABUTTING_WINDOW_END = "2026-08-05T20:00:00.000Z"
#: The same booking pulled one millisecond earlier, into genuine overlap.
OVERLAPPING_WINDOW_START = "2026-08-05T15:59:59.999Z"
#: A third window abutting the second one's end.
THIRD_WINDOW_START = "2026-08-05T20:00:00.000Z"
THIRD_WINDOW_END = "2026-08-05T23:00:00.000Z"


def _three_populated_cabinets_and_a_four_slot_chamber(plant):
    """Three finished wall panels and one chamber whose first run holds 3 slots."""
    scene = plant.approved_project_scene(
        project_overrides={"cabinet_grid_cols": 3, "cabinet_grid_rows": 1}
    )
    cabinets = []
    for column in (1, 2, 3):
        cabinet = plant.plan_cabinet(scene.project["id"], grid_row=1, grid_col=column)
        plant.populate_cabinet(cabinet["id"], scene.model["id"])
        cabinets.append(plant.cabinet(cabinet["id"]))
    chamber = plant.register_chamber()
    run_a = plant.schedule_run(
        cabinets[0]["id"],
        chamber["id"],
        window_start=SOAK_WINDOW_START,
        window_end=SOAK_WINDOW_END,
        slots_required=3,
    )
    scene.cabinets = cabinets
    scene.chamber = plant.chamber(chamber["id"])
    scene.run_a = plant.run(run_a["id"])
    return scene


class TestChamberClosedIntervalAggregateBudget:
    """Touching runs collide, but a collision only bites when the slots overflow."""

    def test_the_cool_down_extends_the_first_run_past_its_window(self, plant):
        """A successful booking creates the run in `run_state` `SCHEDULED`, stores
        its `occupied_until`, adds the run's `slots_required` to the chamber's
        `reserved_slot_total` and 1 to its `scheduled_run_count`.

        Design: Difficulty/resource_temporal_overlap/chamber_closed_interval_with_turnaround_aggregate_capacity
        """
        scene = _three_populated_cabinets_and_a_four_slot_chamber(plant)

        assert_run_fields(scene.run_a, run_state=RUN_SCHEDULED, slots_required=3)
        assert_instant_equals(
            scene.run_a["occupied_until"], RUN_A_OCCUPIED_UNTIL, "occupied_until"
        )
        assert_chamber_fields(
            plant.chamber(scene.chamber["id"]),
            slot_capacity=4,
            turnaround_minutes=60,
            reserved_slot_total=3,
            scheduled_run_count=1,
        )

    def test_a_touching_window_overflows_the_slot_budget(self, plant):
        """The candidate's `slots_required` plus the `slots_required` of every
        overlapping scheduled run is the concurrent slot demand, and if that sum
        exceeds the chamber's `slot_capacity` the booking is refused with
        `ERR_CHAMBER_CAPACITY_EXCEEDED`.

        Design: Difficulty/resource_temporal_overlap/chamber_closed_interval_with_turnaround_aggregate_capacity
        """
        scene = _three_populated_cabinets_and_a_four_slot_chamber(plant)

        response = plant.api.create_burn_in_run(
            burn_in_run_payload(
                scene.cabinets[1]["id"],
                scene.chamber["id"],
                window_start=TOUCHING_WINDOW_START,
                window_end=TOUCHING_WINDOW_END,
                slots_required=2,
            ),
            plant.qa,
        )

        validate_error(response, ERR_CHAMBER_CAPACITY_EXCEEDED, 409)
        assert_chamber_fields(
            plant.chamber(scene.chamber["id"]), reserved_slot_total=3, scheduled_run_count=1
        )
        assert_cabinet_fields(
            plant.cabinet(scene.cabinets[1]["id"]), cabinet_state=CABINET_POPULATED
        )

    def test_the_same_touching_window_fits_when_the_slot_sum_lands_on_capacity(self, plant):
        """Because capacity is an aggregate budget, two runs may legally share a
        chamber whenever their slot sums fit; because the intervals are closed, a
        run that starts at the exact instant a previous run's turnaround ends still
        collides with it.

        Design: Difficulty/resource_temporal_overlap/chamber_closed_interval_with_turnaround_aggregate_capacity
        """
        scene = _three_populated_cabinets_and_a_four_slot_chamber(plant)

        run_b = validate_success(
            plant.api.create_burn_in_run(
                burn_in_run_payload(
                    scene.cabinets[1]["id"],
                    scene.chamber["id"],
                    window_start=TOUCHING_WINDOW_START,
                    window_end=TOUCHING_WINDOW_END,
                    slots_required=1,
                ),
                plant.qa,
            ),
            201,
        )

        assert_run_fields(run_b, run_state=RUN_SCHEDULED, slots_required=1)
        assert_instant_equals(
            run_b["occupied_until"], TOUCHING_OCCUPIED_UNTIL, "occupied_until"
        )
        assert_chamber_fields(
            plant.chamber(scene.chamber["id"]), reserved_slot_total=4, scheduled_run_count=2
        )

    def test_one_millisecond_past_the_cool_down_drops_the_first_run_from_scope(self, plant):
        """A run's occupancy runs from its `window_start` through `occupied_until`,
        where `occupied_until` is the run's `window_end` advanced by the chamber's
        `turnaround_minutes` — the mandatory cool-down before the slots free up.

        Design: Difficulty/resource_temporal_overlap/chamber_closed_interval_with_turnaround_aggregate_capacity
        """
        scene = _three_populated_cabinets_and_a_four_slot_chamber(plant)
        plant.schedule_run(
            scene.cabinets[1]["id"],
            scene.chamber["id"],
            window_start=TOUCHING_WINDOW_START,
            window_end=TOUCHING_WINDOW_END,
            slots_required=1,
        )

        run_c = validate_success(
            plant.api.create_burn_in_run(
                burn_in_run_payload(
                    scene.cabinets[2]["id"],
                    scene.chamber["id"],
                    window_start=CLEAR_WINDOW_START,
                    window_end=CLEAR_WINDOW_END,
                    slots_required=3,
                ),
                plant.qa,
            ),
            201,
        )

        assert_run_fields(run_c, run_state=RUN_SCHEDULED, slots_required=3)
        assert_instant_equals(run_c["occupied_until"], CLEAR_OCCUPIED_UNTIL, "occupied_until")
        assert_chamber_fields(
            plant.chamber(scene.chamber["id"]), reserved_slot_total=7, scheduled_run_count=3
        )
        assert_cabinet_fields(
            plant.cabinet(scene.cabinets[2]["id"]), cabinet_state=CABINET_BURN_IN
        )


def _crew_holding_one_daytime_visit(plant):
    """Crew West booked from 08:00 to 16:00 on a single-panel wall in its region."""
    model = plant.register_model()
    project = plant.create_project(model["id"])
    crew = plant.register_crew()
    first = plant.book_visit(
        project["id"],
        crew["id"],
        window_start=VISIT_WINDOW_START,
        window_end=VISIT_WINDOW_END,
    )
    return Scene(
        model=model,
        project=project,
        crew=plant.crew(crew["id"]),
        first_visit=plant.visit(first["id"]),
    )


class TestCrewHalfOpenWindowExclusiveOccupancy:
    """Abutting windows are fine; a single millisecond of overlap is not."""

    def test_a_visit_beginning_at_the_previous_window_end_is_legal(self, plant):
        """Two windows collide when each one's start is strictly before the other's
        end, so a visit beginning at exactly the previous visit's `window_end` is
        legal while one beginning a millisecond earlier is refused.

        Design: Difficulty/resource_temporal_overlap/crew_half_open_window_adjacency_allowed_overlap_rejected
        """
        scene = _crew_holding_one_daytime_visit(plant)
        assert scene.crew["scheduled_visit_count"] == 1

        second = validate_success(
            plant.api.create_commissioning_visit(
                commissioning_visit_payload(
                    scene.project["id"],
                    scene.crew["id"],
                    window_start=ABUTTING_WINDOW_START,
                    window_end=ABUTTING_WINDOW_END,
                ),
                plant.admin,
            ),
            201,
        )

        assert_visit_fields(
            second, visit_state=VISIT_SCHEDULED, commissioning_crew_id=scene.crew["id"]
        )
        assert plant.crew(scene.crew["id"])["scheduled_visit_count"] == 2

    def test_one_millisecond_of_overlap_is_enough_to_reject_the_booking(self, plant):
        """A crew has capacity for one visit at a time: a single overlap is enough
        to reject the booking.

        Design: Difficulty/resource_temporal_overlap/crew_half_open_window_adjacency_allowed_overlap_rejected
        """
        scene = _crew_holding_one_daytime_visit(plant)
        plant.book_visit(
            scene.project["id"],
            scene.crew["id"],
            window_start=ABUTTING_WINDOW_START,
            window_end=ABUTTING_WINDOW_END,
        )

        response = plant.api.create_commissioning_visit(
            commissioning_visit_payload(
                scene.project["id"],
                scene.crew["id"],
                window_start=OVERLAPPING_WINDOW_START,
                window_end=ABUTTING_WINDOW_END,
            ),
            plant.admin,
        )

        validate_error(response, ERR_CREW_DOUBLE_BOOKED, 409)
        assert plant.crew(scene.crew["id"])["scheduled_visit_count"] == 2

    def test_a_third_booking_abuts_the_second_window_without_a_buffer(self, plant):
        """A booking that survives both is created with `visit_state` `SCHEDULED`,
        and the crew's `scheduled_visit_count` rises by 1.

        Design: Difficulty/resource_temporal_overlap/crew_half_open_window_adjacency_allowed_overlap_rejected
        """
        scene = _crew_holding_one_daytime_visit(plant)
        plant.book_visit(
            scene.project["id"],
            scene.crew["id"],
            window_start=ABUTTING_WINDOW_START,
            window_end=ABUTTING_WINDOW_END,
        )
        validate_error(
            plant.api.create_commissioning_visit(
                commissioning_visit_payload(
                    scene.project["id"],
                    scene.crew["id"],
                    window_start=OVERLAPPING_WINDOW_START,
                    window_end=ABUTTING_WINDOW_END,
                ),
                plant.admin,
            ),
            ERR_CREW_DOUBLE_BOOKED,
            409,
        )

        third = validate_success(
            plant.api.create_commissioning_visit(
                commissioning_visit_payload(
                    scene.project["id"],
                    scene.crew["id"],
                    window_start=THIRD_WINDOW_START,
                    window_end=THIRD_WINDOW_END,
                ),
                plant.admin,
            ),
            201,
        )

        assert_visit_fields(third, visit_state=VISIT_SCHEDULED)
        assert plant.crew(scene.crew["id"])["scheduled_visit_count"] == 3
        assert_visit_fields(
            plant.visit(scene.first_visit["id"]), visit_state=VISIT_SCHEDULED
        )
        assert_visit_fields(plant.visit(third["id"]), visit_state=VISIT_SCHEDULED)
