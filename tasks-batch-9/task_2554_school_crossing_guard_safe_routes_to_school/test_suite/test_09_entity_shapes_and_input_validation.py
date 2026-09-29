"""Created-resource shapes, list envelopes and the request-shape band.

Every entity in this program is created with server-stamped defaults rather than
nulls, list endpoints answer in a fixed envelope, and malformed or dangling
input is rejected before anything is written. These tests pin those contracts on
the schools, guards, assignments, intersections and projects.
"""
from test_helpers import (
    NON_EXISTENT_UUID,
    assert_timestamp_format,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_guard,
    assert_pagination_meta,
    assert_school,
)
from test_helpers.factories import (
    create_guard_payload,
    create_intersection_payload,
    create_project_payload,
    create_school_payload,
)
from test_helpers.fixtures import (
    ADMIN,
    ENGINEER,
    SUPERVISOR,
    create_active_post,
    create_assignment,
    create_grant_program,
    create_intersection,
    create_school,
    read_complaint,
    read_school,
    setup_staffed_post,
    setup_triaged_complaint,
    setup_warranted_intersection,
)

CLOCK_EPOCH = "2026-08-01T00:00:00Z"


def test_a_new_school_returns_its_declared_defaults_not_nulls(api):
    """A registration that omits all three optional calendar inputs still comes back
    with the declared defaults filled in.

    PRD: "A freshly registered school begins with `coverage_posture` at `OPEN`,
    `coverage_rate_pct` at 100.00, `active_post_count`, `covered_post_count` and
    `uncovered_post_count` all at 0, an empty `mode_share_surveys` array, and
    `walk_bike_mode_share_pct`, `walk_bike_mode_share_weighted_pct`,
    `mode_share_trend_pct` and `latest_survey_term_code` all null." ... "a signed
    minute offset that defaults to negative 120"

    Design: Corner/entities/corner_school_creation_returns_declared_defaults
    """
    payload = create_school_payload()
    assert "no_school_dates" not in payload
    assert "early_dismissal_dates" not in payload
    assert "early_dismissal_pm_offset_minutes" not in payload

    created = validate_success(api.create_school(payload, ADMIN), 201)

    assert_school(created)
    assert created["early_dismissal_pm_offset_minutes"] == -120
    assert created["no_school_dates"] == []
    assert created["early_dismissal_dates"] == []
    assert created["active_post_count"] == 0
    assert created["covered_post_count"] == 0
    assert created["uncovered_post_count"] == 0
    assert created["coverage_rate_pct"] == 100.00
    assert created["coverage_posture"] == "OPEN"
    assert created["mode_share_surveys"] == []
    assert created["walk_bike_mode_share_pct"] is None
    assert created["walk_bike_mode_share_weighted_pct"] is None
    assert created["mode_share_trend_pct"] is None
    assert created["latest_survey_term_code"] is None
    assert created["version"] == 1
    assert_timestamp_format(created["created_at"])
    assert created["created_at"].startswith("2026-08-01T00:00:00")
    assert read_school(created["id"]) == created


def test_a_new_guard_is_an_applicant_with_no_equipment_and_a_full_score(api):
    """Every system and computed field on a brand-new guard is server-stamped.

    PRD: "A new guard begins with `certification_status` at `APPLICANT`,
    `duty_status` at `UNASSIGNED`, `training_hours_completed` and
    `hours_since_last_certification` at 0, an empty `equipment_issued` array,
    `equipment_complete` false, `certified_on`, `certification_expires_on` and
    `suspension_reason` all null, and both reliability figures —
    `reliability_score_rolling_90d` and `reliability_score_season_to_date` — at
    100.00."

    Design: Corner/entities/corner_guard_creation_starts_applicant_with_no_equipment
    """
    created = validate_success(
        api.create_guard(create_guard_payload(full_name="Priya Raghavan"),
                         SUPERVISOR), 201)

    assert_guard(created)
    assert created["certification_status"] == "APPLICANT"
    assert created["duty_status"] == "UNASSIGNED"
    assert created["training_hours_completed"] == 0
    assert created["hours_since_last_certification"] == 0
    assert created["equipment_issued"] == []
    assert created["equipment_complete"] is False
    assert created["reliability_score_rolling_90d"] == 100.00
    assert created["reliability_score_season_to_date"] == 100.00
    assert created["certified_on"] is None
    assert created["certification_expires_on"] is None
    assert created["suspension_reason"] is None
    assert created["version"] == 1
    assert validate_success(api.get_guard(created["id"], SUPERVISOR)) == created


def test_the_assignment_list_pages_within_the_filtered_set(api):
    """Three assignments for one guard, read two at a time: total_count describes the
    filtered set and has_more closes on the last page.

    PRD: "their `meta` object includes the four pagination fields `limit`,
    `offset`, `total_count` and `has_more` — where `total_count` is the number of
    records matching the filters before the page window is applied, and `has_more`
    is true when records remain beyond the current window."

    Design: Corner/entities/corner_post_assignment_list_pagination_envelope
    """
    scenario = setup_staffed_post()
    guard_id = scenario["guard"]["id"]
    later_post = create_active_post(scenario["intersection"]["id"],
                                    post_label="Maple SE corner")
    afternoon_post = create_active_post(scenario["intersection"]["id"],
                                        post_label="Maple SW corner",
                                        required_shift="PM")
    second = create_assignment(later_post, guard_id, start_date="2026-09-19",
                               end_date="2026-09-25")
    third = create_assignment(afternoon_post, guard_id)
    expected = {scenario["assignment"]["id"], second["id"], third["id"]}

    first_page, first_meta = validate_paginated(api.list_post_assignments(
        SUPERVISOR, {"guard_id": guard_id, "limit": 2, "offset": 0}))
    second_page, second_meta = validate_paginated(api.list_post_assignments(
        SUPERVISOR, {"guard_id": guard_id, "limit": 2, "offset": 2}))

    assert len(first_page) == 2
    assert_pagination_meta(first_meta, 2, 0, 3, True)
    assert len(second_page) == 1
    assert_pagination_meta(second_meta, 2, 2, 3, False)
    seen = [row["id"] for row in first_page + second_page]
    assert len(seen) == len(set(seen))
    assert set(seen) == expected


def test_a_well_formed_id_that_names_no_intersection_is_a_404(api):
    """A missing row is reported through the error envelope, not as an empty object.

    PRD: "A `school_id` that resolves to nothing yields `ERR_SCHOOL_NOT_FOUND`;
    `intersection_id` yields `ERR_INTERSECTION_NOT_FOUND`"

    Design: Corner/entities/corner_intersection_not_found_returns_404
    """
    response = api.get_intersection(NON_EXISTENT_UUID, ADMIN)

    error = validate_error(response,
                           ApiErrorId.ERR_INTERSECTION_NOT_FOUND.value, 404)
    assert error["error_id"] == "ERR_INTERSECTION_NOT_FOUND"
    assert isinstance(error["message"], str) and error["message"]


def test_a_school_registration_missing_a_required_date_is_rejected(api):
    """Omitting `session_end_date` fails the request-shape band and writes nothing.

    PRD: "**Request shape** — `ERR_INVALID_REQUEST`. Every required body field
    must be present"

    Design: Corner/entities/corner_school_missing_required_field_rejected
    """
    existing = create_school()
    incomplete = create_school_payload(name="Willow Bend Elementary",
                                       district_code="D-12",
                                       enrollment_count=380)
    incomplete.pop("session_end_date")

    response = api.create_school(incomplete, ADMIN)

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)
    assert read_school(existing["id"]) == existing


def test_an_undeclared_enum_member_and_an_inverted_date_range_are_both_shape_errors(api):
    """Two different shape faults, one error id: a control type outside the declared
    set and a season that ends before it starts.

    PRD: "every enum-typed field must name a declared member; integers must be
    integral and within their declared bounds; dates must parse as ISO 8601 dates
    and datetimes as ISO 8601 UTC instants; `limit` must be an integer in the range
    1 to 100 and `offset` an integer of 0 or more; `session_end_date` must be on or
    after `session_start_date`"

    Design: Corner/entities/corner_intersection_invalid_enum_and_inverted_range_rejected
    """
    school = create_school()

    bad_enum = api.create_intersection(
        create_intersection_payload(school["id"], cross_streets="Oak St & 9th Ave",
                                    control_type="ROUNDABOUT"), ADMIN)
    inverted = api.create_school(
        create_school_payload(name="Willow Bend Elementary",
                              session_start_date="2027-06-11",
                              session_end_date="2026-08-24"), ADMIN)

    validate_error(bad_enum, ApiErrorId.ERR_INVALID_REQUEST.value, 400)
    validate_error(inverted, ApiErrorId.ERR_INVALID_REQUEST.value, 400)
    rows, meta = validate_paginated(api.list_school_intersections(school["id"], ADMIN))
    assert rows == []
    assert meta["total_count"] == 0
    assert read_school(school["id"]) == school


def test_a_body_foreign_key_naming_no_school_is_a_not_found(api):
    """The body-FK existence band answers with the parent's own not-found code rather
    than folding the fault into a shape error.

    PRD: "Foreign keys carried in the request body are resolved only after every
    path identifier has resolved, and among themselves they are checked in the order
    the endpoint declares its input fields. A `school_id` that resolves to nothing
    yields `ERR_SCHOOL_NOT_FOUND`"

    Design: Corner/entities/corner_intersection_requires_existing_parent_school
    """
    school = create_school()

    response = api.create_intersection(
        create_intersection_payload(NON_EXISTENT_UUID,
                                    cross_streets="Oak St & 9th Ave"), ADMIN)

    error = validate_error(response, ApiErrorId.ERR_SCHOOL_NOT_FOUND.value, 404)
    assert error["error_id"] != ApiErrorId.ERR_INVALID_REQUEST.value
    assert response.status_code != 400
    rows, meta = validate_paginated(api.list_school_intersections(school["id"], ADMIN))
    assert rows == []
    assert meta["total_count"] == 0


def test_a_project_cannot_cite_a_referable_complaint_from_a_different_intersection(api):
    """The complaint is perfectly referable — it is simply attached to the wrong
    crossing, and co-location is part of the referability test.

    PRD: "when supplied, that complaint must be in `TRIAGED` with `disposition` of
    `REFER_TO_ENGINEERING` **and** must sit on the same intersection as the project,
    or the proposal is refused with `ERR_COMPLAINT_NOT_REFERABLE` (HTTP 422)."

    Design: Corner/entities/corner_project_cannot_cite_complaint_from_another_intersection
    """
    scenario = setup_warranted_intersection()
    other = create_intersection(scenario["school"]["id"],
                                cross_streets="Birch St & 4th Ave")
    complaint = setup_triaged_complaint(other["id"])
    program = create_grant_program(total_cents=12_000_000)
    assert complaint["status"] == "TRIAGED"
    assert complaint["disposition"] == "REFER_TO_ENGINEERING"

    response = api.create_infrastructure_project(
        create_project_payload(program["id"], scenario["intersection"]["id"],
                               requested_cost_cents=3_000_000,
                               students_benefited=420,
                               source_complaint_id=complaint["id"]),
        ENGINEER)

    validate_error(response, ApiErrorId.ERR_COMPLAINT_NOT_REFERABLE.value, 422)
    unchanged = read_complaint(complaint["id"])
    assert unchanged["status"] == "TRIAGED"
    assert unchanged["referred_project_id"] is None
    assert unchanged["version"] == complaint["version"]
    rows, meta = validate_paginated(api.list_infrastructure_projects(
        ENGINEER, {"grant_program_id": program["id"]}))
    assert rows == []
    assert meta["total_count"] == 0
