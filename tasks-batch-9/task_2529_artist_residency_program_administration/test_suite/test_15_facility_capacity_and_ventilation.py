"""Beds counted night by night, and the air the discipline insists on."""

from test_helpers import (
    ADMIN_HEADERS,
    ERR_HOUSING_CAPACITY_EXCEEDED,
    ERR_HOUSING_INTERVAL_CONFLICT,
    ERR_STUDIO_CAPABILITY_MISMATCH,
    ERR_VENTILATION_INSUFFICIENT,
    FACILITIES_HEADERS,
    assert_housing_bed_night_ledger,
    assert_studio_day_ledger,
    assign_housing,
    assign_studio,
    create_applicant,
    create_housing_unit,
    create_residency,
    create_studio,
    get_success_data,
    make_housing_assignment_payload,
    make_studio_assignment_payload,
    refresh_housing_unit,
    refresh_residency,
    refresh_studio,
    release_housing_assignment,
    schedule_residency,
    setup_open_cycle,
    validate_error,
    validate_paginated,
)

CLOCK = "2026-08-01T00:00:00Z"
SESSION_START = "2026-11-02"
SESSION_END = "2026-12-27"
# The whole session plus the permitted one-day tail: 56 nights, the 2nd
# through the 27th of the closing month.
FULL_STAY = ("2026-11-02", "2026-12-28")
FULL_NIGHTS = 56
# Two halves that meet on a single date and therefore share no night.
FIRST_HALF = ("2026-11-02", "2026-12-01")
SECOND_HALF = ("2026-12-01", "2026-12-28")


def _shared_room(api, bed_count=2):
    """Three scheduled residents and one unit with the given number of beds."""
    cycle = setup_open_cycle(api, clock=CLOCK)
    residencies = []
    for _ in range(3):
        residency = create_residency(api, cycle, create_applicant(api))
        schedule_residency(api, residency, SESSION_START, 8)
        assert refresh_residency(api, residency)["session_end_date"] == SESSION_END
        residencies.append(residency)
    unit = create_housing_unit(api, bed_count=bed_count, meal_plan_included=False)
    assert_housing_bed_night_ledger(unit.unit, 0)
    return residencies, unit


def _book(api, unit, residency, window):
    """The booking call as an admin makes it, returning the raw response."""
    refresh_housing_unit(api, unit)
    return api.create_housing_assignment(
        make_housing_assignment_payload(
            unit.housing_unit_id,
            residency.residency_id,
            window[0],
            window[1],
            unit.version,
            meal_plan_selected=False,
        ),
        ADMIN_HEADERS,
    )


def _rows_in(api, unit):
    """Every assignment ever written against this unit, released ones included."""
    return validate_paginated(
        api.list_housing_assignments(
            ADMIN_HEADERS, {"housing_unit_id": unit.housing_unit_id}
        )
    )


def test_two_overlapping_bookings_fit_a_two_bed_unit(api):
    """The per-pair interval rule does not reach a unit with a second bed.

    PRD: "On a **multi-bed** unit that per-pair rule does not apply; instead, for
    every single night of the requested window, the number of `ACTIVE` assignments
    of that unit whose half-open interval contains that night, counting the
    request itself, must not exceed `bed_count`"

    Design: Corner/validations/multi_bed_housing_capacity_is_an_aggregate_over_shared_nights
    """
    residencies, unit = _shared_room(api)

    first = assign_housing(api, unit, residencies[0], *FULL_STAY, meal_plan_selected=False)
    second = assign_housing(api, unit, residencies[1], *FULL_STAY, meal_plan_selected=False)

    assert first["bed_nights"] == FULL_NIGHTS
    assert second["bed_nights"] == FULL_NIGHTS
    assert first["status"] == "ACTIVE" and second["status"] == "ACTIVE"
    assert_housing_bed_night_ledger(refresh_housing_unit(api, unit), 2 * FULL_NIGHTS)


def test_the_bed_nights_of_one_stay_exclude_the_departure_date(api):
    """The second of one month to the twenty-eighth of the next is fifty-six nights.

    PRD: "An assignment from the 2nd of one month to the 28th of the next occupies
    fifty-six bed-nights, the nights of the 2nd through the 27th. There is no
    turnaround buffer on housing."

    Design: Corner/validations/multi_bed_housing_capacity_is_an_aggregate_over_shared_nights
    """
    residencies, unit = _shared_room(api)

    only = assign_housing(api, unit, residencies[0], *FULL_STAY, meal_plan_selected=False)

    assert only["check_in_date"] == FULL_STAY[0]
    assert only["check_out_date"] == FULL_STAY[1]
    assert only["bed_nights"] == FULL_NIGHTS
    assert_housing_bed_night_ledger(refresh_housing_unit(api, unit), FULL_NIGHTS)


def test_the_third_overlapping_booking_names_the_capacity_error(api):
    """A two-bed unit is full at two tenants, and the excess has its own code.

    PRD: "the number of `ACTIVE` assignments of that unit whose half-open interval
    contains that night, counting the request itself, must not exceed `bed_count`,
    and the excess is `ERR_HOUSING_CAPACITY_EXCEEDED` (HTTP 409)."

    Design: Corner/validations/multi_bed_housing_capacity_is_an_aggregate_over_shared_nights
    """
    residencies, unit = _shared_room(api)
    assign_housing(api, unit, residencies[0], *FULL_STAY, meal_plan_selected=False)
    assign_housing(api, unit, residencies[1], *FULL_STAY, meal_plan_selected=False)
    before = refresh_housing_unit(api, unit)

    validate_error(
        _book(api, unit, residencies[2], FULL_STAY), ERR_HOUSING_CAPACITY_EXCEEDED
    )

    after = refresh_housing_unit(api, unit)
    assert_housing_bed_night_ledger(after, 2 * FULL_NIGHTS)
    assert after["version"] == before["version"]
    rows, meta = _rows_in(api, unit)
    assert meta["total_count"] == 2
    assert len(rows) == 2


def test_the_interval_code_is_reserved_for_single_bed_units(api):
    """The refusal above is about shared nights, not about a clashing pair.

    PRD: "On a **single-bed** unit, where `bed_count` is exactly 1, the requested
    window must share no night with any `ACTIVE` assignment of that unit: two
    half-open intervals overlap exactly when each one's check-in date falls
    strictly before the other's check-out date."

    Design: Corner/validations/multi_bed_housing_capacity_is_an_aggregate_over_shared_nights
    """
    residencies, unit = _shared_room(api, bed_count=1)
    assign_housing(api, unit, residencies[0], *FULL_STAY, meal_plan_selected=False)

    validate_error(
        _book(api, unit, residencies[1], FULL_STAY), ERR_HOUSING_INTERVAL_CONFLICT
    )

    assert_housing_bed_night_ledger(refresh_housing_unit(api, unit), FULL_NIGHTS)
    _rows, meta = _rows_in(api, unit)
    assert meta["total_count"] == 1


def test_three_active_rows_are_legal_when_no_night_holds_three(api):
    """The ceiling counts tenants per night, never rows per unit.

    PRD: "for every single night of the requested window, the number of `ACTIVE`
    assignments of that unit whose half-open interval contains that night,
    counting the request itself, must not exceed `bed_count`"

    Design: Corner/validations/multi_bed_housing_capacity_is_an_aggregate_over_shared_nights
    """
    residencies, unit = _shared_room(api)
    early_one = assign_housing(
        api, unit, residencies[0], *FIRST_HALF, meal_plan_selected=False
    )
    early_two = assign_housing(
        api, unit, residencies[1], *FIRST_HALF, meal_plan_selected=False
    )

    late = assign_housing(api, unit, residencies[2], *SECOND_HALF, meal_plan_selected=False)

    assert early_one["bed_nights"] == 29 and early_two["bed_nights"] == 29
    assert late["bed_nights"] == 27
    assert late["status"] == "ACTIVE"
    assert_housing_bed_night_ledger(refresh_housing_unit(api, unit), 29 + 29 + 27)
    _rows, meta = _rows_in(api, unit)
    assert meta["total_count"] == 3


def test_a_release_frees_the_shared_nights_at_once(api):
    """The vacated bed is available for the identical window immediately.

    PRD: "Only `ACTIVE` rows occupy beds; a `RELEASED` row frees its nights
    immediately."

    Design: Corner/validations/multi_bed_housing_capacity_is_an_aggregate_over_shared_nights
    """
    residencies, unit = _shared_room(api)
    leaving = assign_housing(
        api, unit, residencies[0], *FULL_STAY, meal_plan_selected=False
    )
    assign_housing(api, unit, residencies[1], *FULL_STAY, meal_plan_selected=False)
    validate_error(
        _book(api, unit, residencies[2], FULL_STAY), ERR_HOUSING_CAPACITY_EXCEEDED
    )

    released = release_housing_assignment(api, leaving["id"])
    assert released["status"] == "RELEASED"
    assert_housing_bed_night_ledger(refresh_housing_unit(api, unit), FULL_NIGHTS)

    replacement = assign_housing(
        api, unit, residencies[2], *FULL_STAY, meal_plan_selected=False
    )
    assert replacement["status"] == "ACTIVE"
    assert_housing_bed_night_ledger(refresh_housing_unit(api, unit), 2 * FULL_NIGHTS)


# Two disciplines that differ in nothing but the air they insist on.
VENTILATION_DISCIPLINES = [
    {
        "code": "CLAYWORK",
        "name": "Clay",
        "required_capability_tags": ["KILN"],
        "required_ventilation_class": "NONE",
        "cohort_max_slots": 5,
    },
    {
        "code": "ETCH",
        "name": "Etching",
        "required_capability_tags": ["KILN"],
        "required_ventilation_class": "FUME_HOOD",
        "cohort_max_slots": 5,
    },
]
STUDIO_WINDOW = (SESSION_START, SESSION_END)


def _kiln_yard(api, ventilation_class="NONE", capability_tags=("KILN",)):
    """One clay resident, one etching resident, and a single kiln studio for both."""
    cycle = setup_open_cycle(
        api, clock=CLOCK, discipline_specs=VENTILATION_DISCIPLINES
    )
    residencies = {}
    for code in ("CLAYWORK", "ETCH"):
        residency = create_residency(
            api, cycle, create_applicant(api), discipline_code=code
        )
        schedule_residency(api, residency, SESSION_START, 8)
        residencies[code] = residency
    studio = create_studio(
        api,
        code="S-N",
        capability_tags=list(capability_tags),
        ventilation_class=ventilation_class,
        max_concurrent_residents=2,
    )
    assert_studio_day_ledger(studio.studio, 0, 0)
    return residencies, studio


def _book_studio(api, residency, studio):
    """The explicit booking call as a facilities manager makes it."""
    refresh_residency(api, residency)
    return api.create_studio_assignment(
        make_studio_assignment_payload(
            residency.residency_id,
            STUDIO_WINDOW[0],
            STUDIO_WINDOW[1],
            residency.version,
            studio.studio_id,
        ),
        FACILITIES_HEADERS,
    )


def _regrade(api, studio, ventilation_class):
    """A facilities manager revising the studio's ventilation grade in place."""
    revised = get_success_data(
        api.update_studio(
            studio.studio_id,
            {"ventilation_class": ventilation_class},
            FACILITIES_HEADERS,
        )
    )
    assert revised["ventilation_class"] == ventilation_class
    return revised


def test_an_unventilated_studio_refuses_the_fume_hood_discipline(api):
    """Rank nought cannot serve a requirement of rank two.

    PRD: "Ventilation is graded on the ordered scale where `NONE` ranks 0, `LOCAL`
    ranks 1 and `FUME_HOOD` ranks 2, and the studio's rank must be at least the
    discipline's `required_ventilation_class` rank."

    Design: Corner/validations/ventilation_requirement_is_read_from_the_discipline_not_the_studio
    """
    residencies, studio = _kiln_yard(api)

    validate_error(
        _book_studio(api, residencies["ETCH"], studio), ERR_VENTILATION_INSUFFICIENT
    )

    assert_studio_day_ledger(refresh_studio(api, studio), 0, 0)


def test_the_same_studio_serves_the_discipline_that_requires_nothing(api):
    """A stated requirement of NONE is a real floor of nought, not an absent one.

    PRD: "The named studio's ventilation must be sufficient, or
    `ERR_VENTILATION_INSUFFICIENT` (HTTP 422)."

    Design: Corner/validations/ventilation_requirement_is_read_from_the_discipline_not_the_studio
    """
    residencies, studio = _kiln_yard(api)

    booked = assign_studio(api, residencies["CLAYWORK"], *STUDIO_WINDOW, studio=studio)

    # `assigned_studio_code` lives on the residency, which the booking sets to
    # the chosen studio's `code`.
    assert refresh_residency(api, residencies["CLAYWORK"])["assigned_studio_code"] == "S-N"
    assert booked["status"] == "ACTIVE"
    assert_studio_day_ledger(refresh_studio(api, studio), booked["occupied_days"], 1)


def test_a_higher_grade_than_required_is_still_sufficient(api):
    """Regrading to a fume hood admits both disciplines, so the test is not equality.

    PRD: "the studio's rank must be at least the discipline's
    `required_ventilation_class` rank"

    Design: Corner/validations/ventilation_requirement_is_read_from_the_discipline_not_the_studio
    """
    residencies, studio = _kiln_yard(api)
    validate_error(
        _book_studio(api, residencies["ETCH"], studio), ERR_VENTILATION_INSUFFICIENT
    )

    _regrade(api, studio, "FUME_HOOD")

    clay = assign_studio(api, residencies["CLAYWORK"], *STUDIO_WINDOW, studio=studio)
    etch = assign_studio(api, residencies["ETCH"], *STUDIO_WINDOW, studio=studio)
    assert clay["status"] == "ACTIVE" and etch["status"] == "ACTIVE"
    assert_studio_day_ledger(
        refresh_studio(api, studio), clay["occupied_days"] + etch["occupied_days"], 2
    )


def test_one_rank_short_of_the_requirement_still_fails(api):
    """Local extraction beats nothing at all and is still not a fume hood.

    PRD: "Ventilation is graded on the ordered scale where `NONE` ranks 0, `LOCAL`
    ranks 1 and `FUME_HOOD` ranks 2, and the studio's rank must be at least the
    discipline's `required_ventilation_class` rank."

    Design: Corner/validations/ventilation_requirement_is_read_from_the_discipline_not_the_studio
    """
    residencies, studio = _kiln_yard(api, ventilation_class="LOCAL")

    validate_error(
        _book_studio(api, residencies["ETCH"], studio), ERR_VENTILATION_INSUFFICIENT
    )

    clay = assign_studio(api, residencies["CLAYWORK"], *STUDIO_WINDOW, studio=studio)
    assert clay["status"] == "ACTIVE"
    assert_studio_day_ledger(refresh_studio(api, studio), clay["occupied_days"], 1)


def test_the_capability_check_answers_before_the_ventilation_one(api):
    """A perfectly ventilated studio without the kiln fails on the kiln.

    PRD: "The named studio's `capability_tags` must be a superset of the
    `required_capability_tags` of the discipline whose `code` matches the
    residency's `discipline_code` within the residency's cycle, or
    `ERR_STUDIO_CAPABILITY_MISMATCH` (HTTP 422)."

    Design: Corner/validations/ventilation_requirement_is_read_from_the_discipline_not_the_studio
    """
    residencies, studio = _kiln_yard(
        api, ventilation_class="FUME_HOOD", capability_tags=("WELDING",)
    )

    validate_error(
        _book_studio(api, residencies["ETCH"], studio), ERR_STUDIO_CAPABILITY_MISMATCH
    )

    assert_studio_day_ledger(refresh_studio(api, studio), 0, 0)


def test_the_refused_booking_leaves_the_residency_untouched(api):
    """No ledger moves and no version advances behind a ventilation refusal.

    PRD: "Only assignments in `ACTIVE` occupy a studio; a `RELEASED` assignment
    frees its window immediately, buffer included."

    Design: Corner/validations/ventilation_requirement_is_read_from_the_discipline_not_the_studio
    """
    residencies, studio = _kiln_yard(api)
    etch = residencies["ETCH"]
    before = refresh_residency(api, etch)

    validate_error(_book_studio(api, etch, studio), ERR_VENTILATION_INSUFFICIENT)

    assert refresh_residency(api, etch)["version"] == before["version"]
    assert refresh_residency(api, etch)["assigned_studio_code"] is None
    stayed = refresh_studio(api, studio)
    assert_studio_day_ledger(stayed, 0, 0)
    rows, meta = validate_paginated(
        api.list_studio_assignments(FACILITIES_HEADERS, {"residency_id": etch.residency_id})
    )
    assert meta["total_count"] == 0 and rows == []
