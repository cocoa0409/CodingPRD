"""The occupancy census and the consolidation waterfall."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_student,
    place_student,
    read_building,
    read_room,
    read_student,
    setup_hall_with_rooms,
    unique_email,
    validate_error,
    validate_success,
)

THREE_DOUBLES = [
    {"room_number": "201", "bed_capacity": 2},
    {"room_number": "202", "bed_capacity": 2},
    {"room_number": "203", "bed_capacity": 2},
]


class TestConsolidationWithNoSourceRoom:
    def test_plan_reports_zero_moves_when_every_occupied_room_is_full(
        self, api, director_headers
    ):
        """PRD §3.9: "**Source rooms** are those that are `OCCUPIED` with at least one
        occupant and strictly fewer occupants than beds; a room filled to its
        `bed_capacity` is never a source."
        PRD §3.9: "An empty source set is **not** an error: the run succeeds and simply
        reports no moves."
        PRD §3.9: "The response carries the `mode` it ran in, the `planned_move_count`
        of resident-and-target pairs the waterfall produced, the `executed_move_count` —
        equal to the planned count under `EXECUTE` and zero under `PLAN` — the
        `vacated_room_ids` of the sources fully emptied, the `moved_student_ids` in the
        order they were placed, the `occupied_beds_after` figure and the
        `vacancy_rate_before` the run started from."

        Design: Difficulty/boundary_precision_check/consolidation_empty_source_pool_returns_zero_moves
        """
        base = setup_hall_with_rooms(room_specs=THREE_DOUBLES)
        full_room = base["rooms"][0]
        for name, stem, year in (("Dee Sun", "dee", "JUNIOR"), ("Eli Cross", "eli", "SENIOR")):
            resident = create_student(
                full_name=name, email=unique_email(stem), class_year=year
            )
            place_student(resident["id"], full_room["id"])

        planned = validate_success(
            api.run_consolidation(base["building"]["id"], {"mode": "PLAN"}, director_headers)
        )

        assert planned["planned_move_count"] == 0
        assert planned["executed_move_count"] == 0
        assert planned["vacancy_rate_before"] == pytest.approx(0.6667, abs=1e-6)
        assert planned["occupied_beds_after"] == 2

    def test_execute_with_no_source_leaves_every_room_and_resident_untouched(
        self, api, director_headers
    ):
        """PRD §3.9: "Under `EXECUTE` every planned move is applied — each resident's
        `current_room_id` is rewritten and both rooms' `occupied_beds` adjusted — and
        each fully emptied source then moves `OCCUPIED → CONSOLIDATED`, which is
        terminal."
        PRD §3.9: "An empty source set is **not** an error: the run succeeds and simply
        reports no moves."

        Design: Difficulty/boundary_precision_check/consolidation_empty_source_pool_returns_zero_moves
        """
        base = setup_hall_with_rooms(room_specs=THREE_DOUBLES)
        full_room, spare_one, spare_two = base["rooms"]
        residents = []
        for name, stem, year in (("Dee Sun", "dee", "JUNIOR"), ("Eli Cross", "eli", "SENIOR")):
            resident = create_student(
                full_name=name, email=unique_email(stem), class_year=year
            )
            place_student(resident["id"], full_room["id"])
            residents.append(resident)

        executed = validate_success(
            api.run_consolidation(
                base["building"]["id"], {"mode": "EXECUTE"}, director_headers
            )
        )

        assert executed["executed_move_count"] == 0
        assert executed["vacated_room_ids"] == []
        assert executed["moved_student_ids"] == []
        occupied = read_room(full_room["id"])
        assert occupied["status"] == "OCCUPIED"
        assert occupied["occupied_beds"] == 2
        assert read_room(spare_one["id"])["status"] == "AVAILABLE"
        assert read_room(spare_two["id"])["status"] == "AVAILABLE"
        assert read_building(base["building"]["id"])["assigned_bed_count"] == 2
        for resident in residents:
            assert read_student(resident["id"])["current_room_id"] == full_room["id"]


def test_consolidation_packs_the_fullest_target_and_consolidates_the_emptied_source(
    api, director_headers
):
    """PRD §3.9: "Sources are taken emptiest first — ordered by ascending
    `occupied_beds`, then by descending `bed_capacity`, then by earliest creation — so
    the fewest residents move."
    PRD §3.9: "**Target rooms** are those that are `AVAILABLE` or `OCCUPIED` and still
    have a free bed, excluding any source already emptied by this run, and they are
    taken fullest first — ordered by descending `occupied_beds`, then by descending
    `bed_capacity`, then by earliest creation — so vacancies concentrate rather than
    scatter."
    PRD §3.9: "A source whose occupants cannot all be placed is skipped whole — partial
    evacuation is never planned."

    Design: Corner/calculations/consolidation_execute_packs_the_fullest_target_and_consolidates_the_emptied_source
    """
    base = setup_hall_with_rooms(
        room_specs=[
            {"room_number": "201", "bed_capacity": 2},
            {"room_number": "202", "bed_capacity": 2},
            {"room_number": "203", "bed_capacity": 3, "last_renovation_year": 2018},
        ]
    )
    room_201, room_202, room_203 = base["rooms"]
    dee = create_student(full_name="Dee Sun", email=unique_email("dee"))
    eli = create_student(full_name="Eli Cross", email=unique_email("eli"), class_year="SENIOR")
    fay = create_student(full_name="Fay Ito", email=unique_email("fay"), class_year="SOPHOMORE")
    gil = create_student(
        full_name="Gil Roy", email=unique_email("gil"), class_year="FIRST_YEAR"
    )
    place_student(dee["id"], room_201["id"])
    place_student(eli["id"], room_202["id"])
    place_student(fay["id"], room_202["id"])
    place_student(gil["id"], room_203["id"])

    census = validate_success(api.get_census(base["building"]["id"], director_headers))
    assert census["total_beds"] == 7
    assert census["occupied_beds"] == 4
    assert census["vacancy_rate"] == pytest.approx(0.4286, abs=1e-6)
    assert census["underfilled_room_count"] == 2
    assert census["offline_room_count"] == 0

    executed = validate_success(
        api.run_consolidation(base["building"]["id"], {"mode": "EXECUTE"}, director_headers)
    )

    assert executed["planned_move_count"] == 1
    assert executed["executed_move_count"] == 1
    assert executed["vacated_room_ids"] == [room_203["id"]]
    assert executed["moved_student_ids"] == [gil["id"]]
    assert executed["occupied_beds_after"] == 4
    assert read_student(gil["id"])["current_room_id"] == room_201["id"]
    packed = read_room(room_201["id"])
    assert packed["occupied_beds"] == 2 and packed["status"] == "OCCUPIED"
    untouched = read_room(room_202["id"])
    assert untouched["occupied_beds"] == 2 and untouched["status"] == "OCCUPIED"
    emptied = read_room(room_203["id"])
    assert emptied["occupied_beds"] == 0 and emptied["status"] == "CONSOLIDATED"
    assert read_building(base["building"]["id"])["assigned_bed_count"] == 4


def test_consolidating_a_hall_with_no_occupants_reports_an_empty_census(
    api, director_headers
):
    """PRD §3.9: "The census must show at least one occupied bed; a hall with nobody in
    it draws `ERR_CENSUS_EMPTY` (HTTP 422)."
    PRD §3.9: "`vacancy_rate` is the unoccupied share of total beds — total beds less
    occupied beds, divided by total beds — rounded half-up to four decimal places, and
    reported as zero when the hall has no beds at all."

    Design: Corner/errors/consolidation_on_a_hall_with_no_occupants_returns_census_empty
    """
    base = setup_hall_with_rooms(
        room_specs=[
            {"room_number": "201", "bed_capacity": 2},
            {"room_number": "202", "bed_capacity": 2},
        ]
    )

    response = api.run_consolidation(
        base["building"]["id"], {"mode": "PLAN"}, director_headers
    )

    validate_error(response, ApiErrorId.ERR_CENSUS_EMPTY.value, 422)
    census = validate_success(api.get_census(base["building"]["id"], director_headers))
    assert census["total_beds"] == 4
    assert census["occupied_beds"] == 0
    assert census["vacancy_rate"] == pytest.approx(1.0, abs=1e-6)
    for room in base["rooms"]:
        assert read_room(room["id"])["status"] == "AVAILABLE"


def test_consolidating_a_full_hall_reports_that_it_is_not_warranted(api, director_headers):
    """PRD §3.9: "And the census `vacancy_rate` must be at least twenty-five hundredths
    — a hall that is too full to be worth consolidating draws
    `ERR_CONSOLIDATION_NOT_WARRANTED`."

    Design: Corner/errors/consolidation_below_the_vacancy_threshold_returns_consolidation_not_warranted
    """
    base = setup_hall_with_rooms(room_specs=[{"room_number": "201", "bed_capacity": 2}])
    room = base["rooms"][0]
    for name, stem, year in (("Dee Sun", "dee", "JUNIOR"), ("Eli Cross", "eli", "SENIOR")):
        resident = create_student(full_name=name, email=unique_email(stem), class_year=year)
        place_student(resident["id"], room["id"])

    response = api.run_consolidation(
        base["building"]["id"], {"mode": "EXECUTE"}, director_headers
    )

    validate_error(response, ApiErrorId.ERR_CONSOLIDATION_NOT_WARRANTED.value, 409)
    census = validate_success(api.get_census(base["building"]["id"], director_headers))
    assert census["occupied_beds"] == 2
    assert census["vacancy_rate"] == pytest.approx(0.0, abs=1e-6)
    occupied = read_room(room["id"])
    assert occupied["status"] == "OCCUPIED"
    assert occupied["occupied_beds"] == 2
    assert read_building(base["building"]["id"])["assigned_bed_count"] == 2
