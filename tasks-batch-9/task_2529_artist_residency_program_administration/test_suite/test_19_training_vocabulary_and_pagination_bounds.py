"""The safety courses a residency actually owes, and the page bounds of every list."""

from test_helpers import (
    ADMIN_HEADERS,
    ERR_TRAINING_TYPE_NOT_REQUIRED,
    ERR_UNAUTHORIZED,
    ERR_VALIDATION,
    FACILITIES_HEADERS,
    FUNDER_HEADERS,
    create_applicant,
    create_application,
    create_residency,
    get_success_data,
    make_training_payload,
    record_training,
    refresh_application,
    refresh_residency,
    schedule_residency,
    setup_accepted_residency,
    setup_open_cycle,
    validate_error,
    validate_paginated,
)

CLOCK = "2026-08-01T00:00:00Z"
SESSION_START = "2026-11-02"
SESSION_WEEKS = 8
KILN_DISCIPLINE = {
    "code": "KILNWORK",
    "name": "Kiln Work",
    "required_capability_tags": ["KILN"],
    "required_ventilation_class": "NONE",
}
WELDING_VOCABULARY = ["EQUIPMENT_WELDING", "SAFETY_ORIENTATION"]


def _two_scheduled_residencies(api):
    """One resident in a welding category and one in a kiln category."""
    cycle = setup_open_cycle(
        api, clock=CLOCK, discipline_specs=[{}, KILN_DISCIPLINE]
    )
    residencies = {}
    for code in ("SCULPT", "KILNWORK"):
        residency = create_residency(
            api, cycle, create_applicant(api), discipline_code=code
        )
        schedule_residency(api, residency, SESSION_START, SESSION_WEEKS)
        residencies[code] = residency
    return cycle, residencies


def _submit_training(api, residency, training_type):
    """The clearance call as a facilities manager files it, returning the response."""
    return api.record_training(
        residency.residency_id, make_training_payload(training_type), FACILITIES_HEADERS
    )


def test_a_course_the_residency_does_not_owe_is_refused(api):
    """Hazardous-materials handling is a real course and not this resident's course.

    PRD: "A `FacilitiesManager` or `ProgramAdmin` submits one `training_type`, which
    must be a member of the residency's `required_training_types` — a training the
    residency does not owe is `ERR_TRAINING_TYPE_NOT_REQUIRED` (HTTP 422)"

    Design: Corner/errors/only_the_trainings_the_discipline_actually_requires_can_be_recorded
    """
    _cycle, residencies = _two_scheduled_residencies(api)
    welder = residencies["SCULPT"]
    before = refresh_residency(api, welder)

    validate_error(
        _submit_training(api, welder, "HAZMAT_HANDLING"), ERR_TRAINING_TYPE_NOT_REQUIRED
    )

    held = refresh_residency(api, welder)
    assert held["completed_training_types"] == []
    assert held["compliance_status"] == "TRAINING_PENDING"
    assert held["version"] == before["version"]


def test_the_derived_vocabulary_is_one_entry_per_tag_plus_the_orientation(api):
    """Two entries for a single-tag category: the tag's course and the universal one.

    PRD: "It derives `required_training_types` as a sorted ascending list built from
    three sources: the single entry `SAFETY_ORIENTATION`, always present; one entry
    per capability tag on the residency's discipline, written as `EQUIPMENT_`
    followed by the tag"

    Design: Corner/errors/only_the_trainings_the_discipline_actually_requires_can_be_recorded
    """
    _cycle, residencies = _two_scheduled_residencies(api)

    welder = refresh_residency(api, residencies["SCULPT"])
    potter = refresh_residency(api, residencies["KILNWORK"])

    assert welder["required_training_types"] == WELDING_VOCABULARY
    assert potter["required_training_types"] == ["EQUIPMENT_KILN", "SAFETY_ORIENTATION"]


def test_both_members_are_accepted_and_the_second_clears_compliance(api):
    """The append is sorted, and completing the set moves the compliance axis.

    PRD: "When, after the append, every member of `required_training_types` appears
    in `completed_training_types`, the compliance axis moves `TRAINING_PENDING →
    CLEARED` in the same request."

    Design: Corner/errors/only_the_trainings_the_discipline_actually_requires_can_be_recorded
    """
    _cycle, residencies = _two_scheduled_residencies(api)
    welder = residencies["SCULPT"]

    first = record_training(api, welder, "EQUIPMENT_WELDING")
    second = record_training(api, welder, "SAFETY_ORIENTATION")

    assert first["completed_training_types"] == ["EQUIPMENT_WELDING"]
    assert first["compliance_status"] == "TRAINING_PENDING"
    assert second["completed_training_types"] == WELDING_VOCABULARY
    assert second["compliance_status"] == "CLEARED"


def test_an_equipment_course_for_a_tag_this_category_lacks_is_refused(api):
    """The very same course is owed next door and not owed here.

    PRD: "so a discipline requiring welding and a kiln yields `EQUIPMENT_WELDING`
    and `EQUIPMENT_KILN`"

    Design: Corner/errors/only_the_trainings_the_discipline_actually_requires_can_be_recorded
    """
    _cycle, residencies = _two_scheduled_residencies(api)

    validate_error(
        _submit_training(api, residencies["SCULPT"], "EQUIPMENT_KILN"),
        ERR_TRAINING_TYPE_NOT_REQUIRED,
    )

    accepted = record_training(api, residencies["KILNWORK"], "EQUIPMENT_KILN")
    assert accepted["completed_training_types"] == ["EQUIPMENT_KILN"]
    assert refresh_residency(api, residencies["SCULPT"])["completed_training_types"] == []


def test_the_hazmat_course_appears_only_under_the_conjunction(api):
    """A hazmat-reviewed category plus a hazardous work sample owes the third course.

    PRD: "and the entry `HAZMAT_HANDLING`, present only when the discipline's
    `requires_hazmat_review` is true **and** the source application's
    `hazardous_materials_declared` is also true."

    Design: Corner/errors/only_the_trainings_the_discipline_actually_requires_can_be_recorded
    """
    _cycle, app, residency = setup_accepted_residency(
        api,
        clock=CLOCK,
        discipline_overrides={"requires_hazmat_review": True},
        application_overrides={"hazardous": True},
    )
    assert refresh_application(api, app)["hazardous_materials_declared"] is True

    scheduled = schedule_residency(api, residency, SESSION_START, SESSION_WEEKS)

    assert scheduled["required_training_types"] == [
        "EQUIPMENT_WELDING",
        "HAZMAT_HANDLING",
        "SAFETY_ORIENTATION",
    ]
    owed = get_success_data(_submit_training(api, residency, "HAZMAT_HANDLING"))
    assert owed["completed_training_types"] == ["HAZMAT_HANDLING"]


def test_recording_the_same_course_twice_changes_nothing_but_the_version(api):
    """The list is a set, so a repeated course neither doubles nor clears.

    PRD: "The type is appended to `completed_training_types`, which is kept sorted
    ascending and de-duplicated, so recording the same training twice is accepted
    and idempotent in effect."

    Design: Corner/errors/only_the_trainings_the_discipline_actually_requires_can_be_recorded
    """
    _cycle, residencies = _two_scheduled_residencies(api)
    welder = residencies["SCULPT"]
    first = record_training(api, welder, "EQUIPMENT_WELDING")

    again = record_training(api, welder, "EQUIPMENT_WELDING")

    assert again["completed_training_types"] == ["EQUIPMENT_WELDING"]
    assert again["compliance_status"] == "TRAINING_PENDING"
    assert again["version"] == first["version"] + 1


MAX_LIMIT = 100
DEFAULT_LIMIT = 10


def _two_applications(api):
    """A cycle carrying two applications, so a page can be smaller than the whole."""
    cycle = setup_open_cycle(api, clock=CLOCK)
    for statement in ("One", "Two"):
        create_application(
            api, cycle, create_applicant(api), project_statement=statement
        )
    return cycle


def _page(api, cycle, **params):
    """The list call with the cycle filter plus whatever page parameters are given."""
    return api.list_applications(
        ADMIN_HEADERS, dict({"cycle_id": cycle.cycle_id}, **params)
    )


def test_a_limit_above_the_maximum_is_refused_and_the_maximum_itself_is_not(api):
    """One hundred is inside the range and one hundred and one is outside it.

    PRD: "`limit` controls page size: it defaults to 10 when the caller omits it,
    may be no smaller than 1 and no larger than 100."

    Design: Corner/errors/pagination_bounds_are_rejected_before_any_row_is_returned
    """
    cycle = _two_applications(api)

    validate_error(_page(api, cycle, limit=MAX_LIMIT + 1), ERR_VALIDATION)

    rows, meta = validate_paginated(_page(api, cycle, limit=MAX_LIMIT))
    assert meta["total_count"] == 2
    assert len(rows) == 2


def test_the_refused_page_returns_no_rows_at_all(api):
    """The rejection is a rejection, not a truncated or clamped page.

    PRD: "A `limit` outside the range of 1 through 100 inclusive, or a negative
    `offset`, is a malformed request and is rejected with `ERR_VALIDATION` (HTTP
    400)."

    Design: Corner/errors/pagination_bounds_are_rejected_before_any_row_is_returned
    """
    cycle = _two_applications(api)

    refused = _page(api, cycle, limit=MAX_LIMIT + 1)

    validate_error(refused, ERR_VALIDATION)
    body = refused.json()
    assert "data" not in body or not isinstance(body.get("data"), list)


def test_the_lower_bound_of_the_page_size_is_one_and_not_zero(api):
    """A page of nothing is malformed; a page of one is a page with more to come.

    PRD: "may be no smaller than 1 and no larger than 100"

    Design: Corner/errors/pagination_bounds_are_rejected_before_any_row_is_returned
    """
    cycle = _two_applications(api)

    validate_error(_page(api, cycle, limit=0), ERR_VALIDATION)

    rows, meta = validate_paginated(_page(api, cycle, limit=1))
    assert len(rows) == 1
    assert meta["total_count"] == 2
    assert meta["has_more"] is True


def test_the_starting_position_has_a_floor_but_no_ceiling(api):
    """A negative start is malformed; a start beyond the end is simply empty.

    PRD: "`offset` controls the starting position: it defaults to 0 and may be no
    smaller than 0."

    Design: Corner/errors/pagination_bounds_are_rejected_before_any_row_is_returned
    """
    cycle = _two_applications(api)

    validate_error(_page(api, cycle, offset=-1), ERR_VALIDATION)

    rows, meta = validate_paginated(_page(api, cycle, offset=99))
    assert rows == []
    assert meta["total_count"] == 2
    assert meta["has_more"] is False


def test_the_defaults_apply_when_the_parameters_are_omitted(api):
    """Two rows fit inside a page of ten starting at the beginning.

    PRD: "List responses populate four fields in the `meta` object: the effective
    `limit`, the effective `offset`, `total_count` (the number of rows matching the
    filter before the page window is applied) and `has_more` (true when rows
    matching the filter remain beyond the current page)."

    Design: Corner/errors/pagination_bounds_are_rejected_before_any_row_is_returned
    """
    cycle = _two_applications(api)

    rows, meta = validate_paginated(_page(api, cycle))

    assert meta["limit"] == DEFAULT_LIMIT
    assert meta["offset"] == 0
    assert len(rows) == 2
    assert meta["has_more"] is False


def test_the_rule_belongs_to_every_collection_and_not_to_one(api):
    """Six unrelated listings answer the over-large page identically.

    PRD: "Every collection-listing endpoint accepts two optional query parameters."

    Design: Corner/errors/pagination_bounds_are_rejected_before_any_row_is_returned
    """
    _two_applications(api)
    oversized = {"limit": MAX_LIMIT + 1}

    for listing in (
        api.list_cycles,
        api.list_residencies,
        api.list_studios,
        api.list_housing_assignments,
        api.list_disbursements,
        api.list_obligations,
    ):
        validate_error(listing(ADMIN_HEADERS, oversized), ERR_VALIDATION)


def test_the_role_check_still_answers_above_the_page_check(api):
    """A reader who may not see the money is told so, not told about the page size.

    PRD: "Only once both headers are well-formed does the service ask whether that
    role is permitted to perform the requested operation at all; when it is not, the
    answer is `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/errors/pagination_bounds_are_rejected_before_any_row_is_returned
    """
    _two_applications(api)

    validate_error(
        api.list_disbursements(FUNDER_HEADERS, {"limit": MAX_LIMIT + 1}),
        ERR_UNAUTHORIZED,
    )

    _rows, meta = validate_paginated(
        api.list_disbursements(ADMIN_HEADERS, {"limit": MAX_LIMIT})
    )
    assert meta["total_count"] == 0
