"""Entity-level projections: declared fields, defaults, computed fields and 404s."""

import pytest

from test_helpers import (
    RIVERBEND_SCHOOLS,
    TEST_USERS,
    ApiErrorId,
    activate_adoption,
    api_client,
    assert_area_adjacency,
    assert_school,
    create_housing_development,
    create_planning_area_payload,
    create_study_payload,
    create_transfer_request,
    create_variance_observation_payload,
    make_guardian_headers,
    riverbend_adopted,
    riverbend_board_ready,
    riverbend_engagement_open,
    riverbend_locked,
    set_clock,
    setup_study_with_inventory,
    travel_option,
)
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

PLANNER = TEST_USERS["planner_headers"]
BOARD = TEST_USERS["board_headers"]
OFFICER = TEST_USERS["officer_headers"]
CLOCK = "2026-09-01T00:00:00Z"


# ---------------------------------------------------------------------------
# Local setup: the Riverbend seed inventory left in SETUP, so seed creation is
# still open. Every literal matches the shared Riverbend ladder.
# ---------------------------------------------------------------------------
def _a01(school_ids):
    return {
        "area_code": "A-01",
        "grade_band": "ELEMENTARY",
        "current_school_id": school_ids["Cedar Elementary"],
        "resident_student_count": 300,
        "frl_student_count": 90,
        "ell_student_count": 40,
        "median_household_income_usd": 78000,
        "annual_absorption_cap_units": 120,
        "travel_options": [
            travel_option(school_ids["Cedar Elementary"], 0.6, 10, True),
            travel_option(school_ids["Birch Elementary"], 2.2, 22, False),
        ],
    }


def _a02(school_ids):
    return {
        "area_code": "A-02",
        "grade_band": "ELEMENTARY",
        "current_school_id": school_ids["Cedar Elementary"],
        "resident_student_count": 200,
        "frl_student_count": 100,
        "ell_student_count": 30,
        "median_household_income_usd": 52000,
        "annual_absorption_cap_units": 150,
        "travel_options": [
            travel_option(school_ids["Cedar Elementary"], 1.4, 9, False),
            travel_option(school_ids["Birch Elementary"], 0.8, 12, True),
        ],
    }


def _a03(school_ids):
    return {
        "area_code": "A-03",
        "grade_band": "ELEMENTARY",
        "current_school_id": school_ids["Birch Elementary"],
        "resident_student_count": 150,
        "frl_student_count": 30,
        "ell_student_count": 10,
        "median_household_income_usd": 96000,
        "annual_absorption_cap_units": 90,
        "travel_options": [
            travel_option(school_ids["Cedar Elementary"], 3.0, 26, False),
            travel_option(school_ids["Birch Elementary"], 0.9, 14, True),
        ],
    }


def _riverbend_in_setup(with_adjacencies=True):
    """Riverbend USD with two schools and three areas, still in SETUP."""
    specs = (("A-01", "A-02", 5200), ("A-02", "A-03", 4100)) if with_adjacencies else ()
    ctx = setup_study_with_inventory(
        school_payloads=RIVERBEND_SCHOOLS,
        area_builders=(_a01, _a02, _a03),
        adjacency_specs=specs,
        clock=CLOCK,
        lock=False,
    )
    ctx["cedar_id"] = ctx["school_ids"]["Cedar Elementary"]
    ctx["birch_id"] = ctx["school_ids"]["Birch Elementary"]
    ctx["a1_id"] = ctx["area_ids"]["A-01"]
    ctx["a2_id"] = ctx["area_ids"]["A-02"]
    ctx["a3_id"] = ctx["area_ids"]["A-03"]
    return ctx


# ---------------------------------------------------------------------------
# Creation projections
# ---------------------------------------------------------------------------
def test_study_creation_returns_every_declared_field():
    """A study create echoes its inputs and stamps every system field at its default.

    PRD: "A new study opens in `SETUP` with `comment_intake_open` false,
    `data_locked_at` null, `projection_stale` false, and both roll-up totals —
    `resident_student_total` and `enrolled_of_record_total` — at 0."

    Design: Corner/entities/study_creation_returns_every_declared_field
    """
    set_clock(CLOCK)

    response = api_client.create_study(create_study_payload(), PLANNER)

    study = validate_success(response, 201)
    body = response.json()
    assert body["response_type"] == "object", (
        f"a single resource is an object envelope, got {body['response_type']!r}"
    )
    assert body["meta"]["api_request_id"].startswith("req_"), (
        f"api_request_id must start with req_, got {body['meta']['api_request_id']!r}"
    )
    assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"]), (
        "meta.api_request_timestamp must be an ISO 8601 instant"
    )

    assert study["name"] == "2028 Elementary Boundary Study", "name is echoed verbatim"
    assert study["district_name"] == "Riverbend USD", "district_name is echoed verbatim"
    assert study["target_school_year"] == 2028, "target_school_year is echoed verbatim"
    assert study["horizon_years"] == 5, "horizon_years is echoed verbatim"
    assert study["capacity_target_low_pct"] == pytest.approx(85.00, abs=0.01)
    assert study["capacity_target_high_pct"] == pytest.approx(100.00, abs=0.01)
    assert study["portables_count_toward_capacity"] is True
    assert study["required_program_types"] == ["DUAL_LANGUAGE"]

    assert study["status"] == "SETUP", f"a new study opens in SETUP, got {study['status']}"
    assert study["comment_intake_open"] is False, "comment intake starts closed"
    assert study["data_locked_at"] is None, "data_locked_at starts null"
    assert study["resident_student_total"] == 0, "resident_student_total starts at 0"
    assert study["enrolled_of_record_total"] == 0, "enrolled_of_record_total starts at 0"
    assert study["projection_stale"] is False, "projection_stale starts false"

    assert study["version"] == 1, f"version is initialised to 1, got {study['version']}"
    assert is_valid_uuid(study["id"]), f"id must be a bare UUID, got {study['id']!r}"
    assert is_iso8601_timestamp(study["created_at"]), "created_at must be an ISO 8601 instant"
    assert is_iso8601_timestamp(study["updated_at"]), "updated_at must be an ISO 8601 instant"


def test_school_read_returns_stored_inputs_and_derived_capacity():
    """GET by id returns the stored school plus both derived capacity numbers.

    PRD: "On creation the server computes `effective_capacity_seats` as
    `core_capacity_seats` plus, only when the study's
    `portables_count_toward_capacity` is true, `portable_capacity_seats`;
    otherwise the portable seats are ignored entirely."

    Design: Corner/entities/school_retrieval_returns_stored_and_derived_capacity
    """
    ctx = _riverbend_in_setup()

    response = api_client.get_school(ctx["cedar_id"], PLANNER)

    school = validate_success(response, 200)
    assert response.json()["response_type"] == "object", "a single school is an object envelope"
    assert_school(school)

    assert school["study_id"] == ctx["study_id"], "the school belongs to the Riverbend study"
    assert school["name"] == "Cedar Elementary"
    assert school["level"] == "ELEMENTARY"
    assert school["core_capacity_seats"] == 500
    assert school["portable_capacity_seats"] == 40
    assert school["program_types"] == ["DUAL_LANGUAGE"]
    assert school["status"] == "ACTIVE", "an unadjusted school stays ACTIVE"
    assert school["effective_capacity_seats"] == 540, (
        "500 core seats plus 40 portable seats, because this study counts portables"
    )
    assert school["enrolled_students_of_record"] == 500, (
        "A-01's 300 residents plus A-02's 200 residents point at Cedar"
    )


def test_area_adjacency_create_mints_the_reciprocal_edge():
    """One authored adjacency POST yields the authored row plus a mirror row.

    PRD: "The row the client creates carries `is_reciprocal` false; in the same
    request the server mints a mirror row with the two endpoints swapped, the
    same `shared_boundary_length_ft` and `is_reciprocal` true, so that the graph
    is stored symmetrically and contiguity can be evaluated as an undirected
    traversal."

    Design: Corner/entities/area_adjacency_junction_mints_the_reciprocal_edge
    """
    ctx = _riverbend_in_setup(with_adjacencies=False)

    response = api_client.create_area_adjacency(
        {
            "area_id": ctx["a1_id"],
            "neighbor_area_id": ctx["a2_id"],
            "shared_boundary_length_ft": 5200,
        },
        PLANNER,
    )

    authored = validate_success(response, 201)
    assert_area_adjacency(authored)
    assert authored["is_reciprocal"] is False, "the authored row is not the reciprocal one"
    assert authored["area_id"] == ctx["a1_id"]
    assert authored["neighbor_area_id"] == ctx["a2_id"]
    assert authored["shared_boundary_length_ft"] == 5200

    a1_rows, a1_meta = validate_paginated(
        api_client.list_area_adjacencies(ctx["a1_id"], PLANNER, {"is_reciprocal": "false"})
    )
    assert a1_meta["total_count"] == 1, (
        f"A-01 authored exactly one edge, got total_count {a1_meta['total_count']}"
    )
    assert a1_rows[0]["neighbor_area_id"] == ctx["a2_id"]
    assert a1_rows[0]["is_reciprocal"] is False

    a2_rows, a2_meta = validate_paginated(
        api_client.list_area_adjacencies(ctx["a2_id"], PLANNER, {"is_reciprocal": "true"})
    )
    assert a2_meta["total_count"] == 1, (
        f"exactly one mirror row names A-02, got total_count {a2_meta['total_count']}"
    )
    mirror = a2_rows[0]
    assert mirror["area_id"] == ctx["a2_id"], "the mirror swaps the two endpoints"
    assert mirror["neighbor_area_id"] == ctx["a1_id"], "the mirror swaps the two endpoints"
    assert mirror["shared_boundary_length_ft"] == 5200, "the mirror carries the same edge weight"
    assert mirror["is_reciprocal"] is True

    _, a3_meta = validate_paginated(api_client.list_area_adjacencies(ctx["a3_id"], PLANNER))
    assert a3_meta["total_count"] == 0, (
        f"no edge names A-03 yet, got total_count {a3_meta['total_count']}"
    )


# ---------------------------------------------------------------------------
# Listing semantics
# ---------------------------------------------------------------------------
def test_planning_area_listing_paginates_with_total_count_and_has_more():
    """total_count counts the filtered set and has_more tracks the remainder.

    PRD: "Unless a specific endpoint states otherwise, list results are ordered
    by `created_at` ascending, and every list response carries `limit`, `offset`,
    `total_count` and `has_more` inside `meta`, where `total_count` is the number
    of records matching the filters before pagination is applied and `has_more`
    is true exactly when records remain beyond the current page."

    Design: Corner/entities/planning_area_listing_paginates_with_total_count_and_has_more
    """
    ctx = _riverbend_in_setup()
    study_id = ctx["study_id"]

    first = api_client.list_planning_areas(
        PLANNER, {"study_id": study_id, "limit": 2, "offset": 0}
    )
    page_one, meta_one = validate_paginated(first)
    assert first.json()["response_type"] == "array", "a collection read is an array envelope"
    assert meta_one["total_count"] == 3, (
        f"the study has three areas regardless of page size, got {meta_one['total_count']}"
    )
    assert meta_one["has_more"] is True, "a third row remains beyond page one"
    assert meta_one["limit"] == 2 and meta_one["offset"] == 0
    assert len(page_one) == 2, f"page one holds exactly two rows, got {len(page_one)}"

    second = api_client.list_planning_areas(
        PLANNER, {"study_id": study_id, "limit": 2, "offset": 2}
    )
    page_two, meta_two = validate_paginated(second)
    assert second.json()["response_type"] == "array", "a collection read is an array envelope"
    assert meta_two["total_count"] == 3, "total_count ignores pagination"
    assert meta_two["has_more"] is False, "nothing remains beyond page two"
    assert meta_two["offset"] == 2
    assert len(page_two) == 1, f"page two holds the last row only, got {len(page_two)}"

    codes = [row["area_code"] for row in page_one + page_two]
    assert sorted(codes) == ["A-01", "A-02", "A-03"], (
        f"the two pages together cover every area exactly once, got {codes}"
    )

    third = api_client.list_planning_areas(
        PLANNER, {"study_id": study_id, "current_school_id": ctx["cedar_id"]}
    )
    filtered, meta_three = validate_paginated(third)
    assert third.json()["response_type"] == "array", "a collection read is an array envelope"
    assert meta_three["total_count"] == 2, (
        f"only A-01 and A-02 name Cedar as school of record, got {meta_three['total_count']}"
    )
    assert meta_three["has_more"] is False, "both filtered rows fit on the page"
    for row in filtered:
        assert row["current_school_id"] == ctx["cedar_id"], (
            "every filtered row names Cedar as its school of record"
        )


# ---------------------------------------------------------------------------
# Not-found sweeps
# ---------------------------------------------------------------------------
def test_seed_inventory_reads_with_unknown_id_return_their_own_not_found():
    """Study, school, area and development reads each carry their own 404 code.

    PRD: "Each entity type has its own not-found code, all of them HTTP 404:
    `ERR_STUDY_NOT_FOUND`, `ERR_SCHOOL_NOT_FOUND`, `ERR_AREA_NOT_FOUND`,
    `ERR_DEVELOPMENT_NOT_FOUND`, `ERR_PROJECTION_RUN_NOT_FOUND`,
    `ERR_SCENARIO_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`,
    `ERR_COMMENT_NOT_FOUND`, `ERR_ADOPTION_NOT_FOUND`, `ERR_TRANSFER_NOT_FOUND`
    and `ERR_OBSERVATION_NOT_FOUND`."

    Design: Corner/entities/study_school_area_and_development_reads_with_unknown_id_not_found
    """
    ctx = riverbend_locked()
    create_housing_development(ctx["a1_id"])

    reads = (
        (api_client.get_study(NON_EXISTENT_UUID, PLANNER), ApiErrorId.ERR_STUDY_NOT_FOUND),
        (api_client.get_school(NON_EXISTENT_UUID, PLANNER), ApiErrorId.ERR_SCHOOL_NOT_FOUND),
        (
            api_client.get_planning_area(NON_EXISTENT_UUID, PLANNER),
            ApiErrorId.ERR_AREA_NOT_FOUND,
        ),
        (
            api_client.get_housing_development(NON_EXISTENT_UUID, PLANNER),
            ApiErrorId.ERR_DEVELOPMENT_NOT_FOUND,
        ),
    )
    for response, expected in reads:
        error = validate_error(response, expected.value)
        assert response.json()["response_type"] == "error", "an error envelope is typed 'error'"
        assert error["message"].strip(), f"{expected.value} carries a human-readable message"


def test_planning_artifact_reads_with_unknown_id_return_their_own_not_found():
    """Run, scenario, assignment and comment reads each carry their own 404 code.

    PRD: "Each entity type has its own not-found code, all of them HTTP 404:
    `ERR_STUDY_NOT_FOUND`, `ERR_SCHOOL_NOT_FOUND`, `ERR_AREA_NOT_FOUND`,
    `ERR_DEVELOPMENT_NOT_FOUND`, `ERR_PROJECTION_RUN_NOT_FOUND`,
    `ERR_SCENARIO_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`,
    `ERR_COMMENT_NOT_FOUND`, `ERR_ADOPTION_NOT_FOUND`, `ERR_TRANSFER_NOT_FOUND`
    and `ERR_OBSERVATION_NOT_FOUND`."

    Design: Corner/entities/run_scenario_assignment_and_comment_reads_with_unknown_id_not_found
    """
    ctx = riverbend_engagement_open()

    validate_error(
        api_client.get_projection_run(NON_EXISTENT_UUID, PLANNER),
        ApiErrorId.ERR_PROJECTION_RUN_NOT_FOUND.value,
    )
    validate_error(
        api_client.get_scenario(NON_EXISTENT_UUID, PLANNER),
        ApiErrorId.ERR_SCENARIO_NOT_FOUND.value,
    )
    validate_error(
        api_client.get_assignment(NON_EXISTENT_UUID, PLANNER),
        ApiErrorId.ERR_ASSIGNMENT_NOT_FOUND.value,
    )
    validate_error(
        api_client.get_comment(NON_EXISTENT_UUID, PLANNER),
        ApiErrorId.ERR_COMMENT_NOT_FOUND.value,
    )

    _, meta = validate_paginated(
        api_client.list_assignments(PLANNER, {"scenario_id": ctx["scenario_id"]})
    )
    assert meta["total_count"] == 3, (
        f"the assignment collection itself is intact, got total_count {meta['total_count']}"
    )


def test_implementation_reads_with_unknown_id_return_their_own_not_found():
    """Adoption, transfer and observation reads 404 on their own code, nested paths included.

    PRD: "When a path names a parent and then a child, the parent is resolved
    first and its absence is reported before the child is looked at; when a
    request body names several references, the missing one reported is the first
    one that fails to resolve."

    Design: Corner/entities/adoption_transfer_and_observation_reads_with_unknown_id_not_found
    """
    ctx = riverbend_adopted()
    set_clock("2027-07-01T00:00:00Z", api_client, OFFICER)
    activate_adoption(ctx["adoption_id"], api_client, OFFICER)
    get_success_data(
        api_client.create_variance_observation(
            ctx["adoption_id"],
            create_variance_observation_payload(ctx["cedar_id"], 500, 500),
            OFFICER,
        ),
        201,
    )
    create_transfer_request(
        ctx["adoption_id"],
        ctx["a3_id"],
        ctx["cedar_id"],
        api_client,
        make_guardian_headers("guardian-3"),
        student_reference="STU-900",
        student_grade=4,
        reason="HARDSHIP",
    )

    validate_error(
        api_client.get_adoption(NON_EXISTENT_UUID, OFFICER),
        ApiErrorId.ERR_ADOPTION_NOT_FOUND.value,
    )
    validate_error(
        api_client.list_phase_in_rules(NON_EXISTENT_UUID, OFFICER),
        ApiErrorId.ERR_ADOPTION_NOT_FOUND.value,
    )
    validate_error(
        api_client.get_transfer_request(NON_EXISTENT_UUID, OFFICER),
        ApiErrorId.ERR_TRANSFER_NOT_FOUND.value,
    )
    validate_error(
        api_client.get_variance_observation(NON_EXISTENT_UUID, OFFICER),
        ApiErrorId.ERR_OBSERVATION_NOT_FOUND.value,
    )

    _, meta = validate_paginated(
        api_client.list_variance_observations(OFFICER, {"adoption_id": ctx["adoption_id"]})
    )
    assert meta["total_count"] == 1, (
        f"the observation collection is intact, got total_count {meta['total_count']}"
    )


def test_child_creates_under_unknown_parent_return_parent_not_found():
    """A child create resolves its path parent before it looks at the body.

    PRD: "Identifiers are resolved left to right and outside in. When a path
    names a parent and then a child, the parent is resolved first and its absence
    is reported before the child is looked at; when a request body names several
    references, the missing one reported is the first one that fails to resolve."

    Design: Corner/entities/school_create_under_unknown_study_returns_not_found
    """
    ctx = riverbend_locked()

    validate_error(
        api_client.create_school(
            NON_EXISTENT_UUID,
            {"name": "Orphan Elementary", "level": "ELEMENTARY", "core_capacity_seats": 300},
            PLANNER,
        ),
        ApiErrorId.ERR_STUDY_NOT_FOUND.value,
    )
    validate_error(
        api_client.create_housing_development(
            NON_EXISTENT_UUID,
            {
                "name": "Orphan Ridge",
                "unit_type": "SINGLE_FAMILY",
                "total_units": 40,
                "first_occupancy_date": "2027-05-01T00:00:00Z",
                "buildout_months": 12,
            },
            PLANNER,
        ),
        ApiErrorId.ERR_AREA_NOT_FOUND.value,
    )

    _, schools_meta = validate_paginated(
        api_client.list_study_schools(ctx["study_id"], PLANNER)
    )
    assert schools_meta["total_count"] == 2, (
        f"no orphan school was created, got total_count {schools_meta['total_count']}"
    )
    _, pipeline_meta = validate_paginated(
        api_client.list_housing_developments(ctx["a1_id"], PLANNER)
    )
    assert pipeline_meta["total_count"] == 0, (
        f"no orphan development was created, got total_count {pipeline_meta['total_count']}"
    )


# ---------------------------------------------------------------------------
# Schema enforcement
# ---------------------------------------------------------------------------
def test_study_and_area_creates_missing_required_fields_are_rejected():
    """A required input that is simply absent is a schema failure, not a default.

    PRD: "**Schema** — `ERR_INVALID_REQUEST`: a required input field absent or
    null, an enum value outside its declared member list, a positive-integer
    field (`total_units`, `buildout_months`, `regime_years`,
    `core_capacity_seats`, `board_member_count`) at zero or below, a negative
    vote count or negative `seats`, a `student_grade` outside 0 through 12, a
    `grade_low` greater than `grade_high`, a percent field outside 0 through
    1000, a `limit` outside 1 through 200, a negative `offset`, an empty
    `travel_options` or `program_placements` array, a travel option entry missing
    `school_id`, `walk_distance_miles`, `bus_minutes` or `has_safe_route`, or a
    program placement entry missing `program_type`, `school_id` or `seats`."

    Design: Corner/entities/study_and_area_creates_missing_required_fields_returns_4XX
    """
    ctx = _riverbend_in_setup()
    version_before = validate_success(api_client.get_study(ctx["study_id"], PLANNER))["version"]

    without_name = create_study_payload(required_program_types=[])
    del without_name["name"]
    validate_error(
        api_client.create_study(without_name, PLANNER), ApiErrorId.ERR_INVALID_REQUEST.value
    )

    without_high_band = create_study_payload(
        name="Incomplete Study", required_program_types=[]
    )
    del without_high_band["capacity_target_high_pct"]
    validate_error(
        api_client.create_study(without_high_band, PLANNER),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )

    without_travel = create_planning_area_payload(
        ctx["study_id"],
        ctx["cedar_id"],
        [],
        area_code="A-99",
        resident_student_count=100,
        frl_student_count=10,
        ell_student_count=5,
        median_household_income_usd=80000,
        annual_absorption_cap_units=100,
    )
    del without_travel["travel_options"]
    validate_error(
        api_client.create_planning_area(without_travel, PLANNER),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )

    _, meta = validate_paginated(
        api_client.list_planning_areas(PLANNER, {"study_id": ctx["study_id"]})
    )
    assert meta["total_count"] == 3, (
        f"no partial area row was written, got total_count {meta['total_count']}"
    )
    version_after = validate_success(api_client.get_study(ctx["study_id"], PLANNER))["version"]
    assert version_after == version_before, (
        f"none of the three rejected calls touched the existing study: version moved "
        f"from {version_before} to {version_after}"
    )


def test_area_and_school_creates_with_bad_enum_or_range_rejected():
    """A bad enum, an empty travel table and a zero seat count are each rejected.

    PRD: "**Schema** — `ERR_INVALID_REQUEST`: a required input field absent or
    null, an enum value outside its declared member list, a positive-integer
    field (`total_units`, `buildout_months`, `regime_years`,
    `core_capacity_seats`, `board_member_count`) at zero or below, a negative
    vote count or negative `seats`, a `student_grade` outside 0 through 12, a
    `grade_low` greater than `grade_high`, a percent field outside 0 through
    1000, a `limit` outside 1 through 200, a negative `offset`, an empty
    `travel_options` or `program_placements` array, a travel option entry missing
    `school_id`, `walk_distance_miles`, `bus_minutes` or `has_safe_route`, or a
    program placement entry missing `program_type`, `school_id` or `seats`."

    Design: Corner/entities/area_and_school_creates_with_bad_enum_or_range_rejected
    """
    ctx = _riverbend_in_setup()

    bad_enum = create_planning_area_payload(
        ctx["study_id"],
        ctx["cedar_id"],
        [travel_option(ctx["cedar_id"], 0.5, 10, True)],
        area_code="A-90",
        grade_band="K8",
        resident_student_count=100,
        frl_student_count=10,
        ell_student_count=5,
        median_household_income_usd=80000,
        annual_absorption_cap_units=100,
    )
    validate_error(
        api_client.create_planning_area(bad_enum, PLANNER),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )

    empty_travel = create_planning_area_payload(
        ctx["study_id"],
        ctx["cedar_id"],
        [],
        area_code="A-91",
        resident_student_count=100,
        frl_student_count=10,
        ell_student_count=5,
        median_household_income_usd=80000,
        annual_absorption_cap_units=100,
    )
    validate_error(
        api_client.create_planning_area(empty_travel, PLANNER),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )

    validate_error(
        api_client.create_school(
            ctx["study_id"],
            {"name": "Zero Seat Elementary", "level": "ELEMENTARY", "core_capacity_seats": 0},
            PLANNER,
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )

    _, areas_meta = validate_paginated(
        api_client.list_planning_areas(PLANNER, {"study_id": ctx["study_id"]})
    )
    assert areas_meta["total_count"] == 3, (
        f"neither rejected area was created, got total_count {areas_meta['total_count']}"
    )
    _, schools_meta = validate_paginated(
        api_client.list_study_schools(ctx["study_id"], PLANNER)
    )
    assert schools_meta["total_count"] == 2, (
        f"no zero-seat school was created, got total_count {schools_meta['total_count']}"
    )


# ---------------------------------------------------------------------------
# Declared defaults
# ---------------------------------------------------------------------------
def test_school_create_omitting_optional_inputs_applies_declared_defaults():
    """The three optional School inputs resolve to 0, [] and ACTIVE, never null.

    PRD: "**Schools** are registered with a `name` that must be unique within the
    study, a `level` of `ELEMENTARY`, `MIDDLE` or `HIGH`, a
    `core_capacity_seats` count of at least 1, an optional
    `portable_capacity_seats` count of at least 0 defaulting to 0, an optional
    `program_types` array naming the programs the building can physically host
    (defaulting to empty), and an optional operational `status` of `ACTIVE` or
    `MOTHBALLED` that defaults to `ACTIVE`."

    Design: Corner/entities/school_create_omitting_optional_inputs_applies_declared_defaults
    """
    ctx = _riverbend_in_setup()

    response = api_client.create_school(
        ctx["study_id"],
        {"name": "Alder Elementary", "level": "ELEMENTARY", "core_capacity_seats": 300},
        PLANNER,
    )

    school = validate_success(response, 201)
    assert_school(school)
    assert school["portable_capacity_seats"] == 0, "portable seats default to 0, not null"
    assert school["program_types"] == [], "program_types defaults to an empty array"
    assert school["status"] == "ACTIVE", "operational status defaults to ACTIVE"
    assert school["effective_capacity_seats"] == 300, (
        "with zero portable seats effective capacity equals the core seat count"
    )
    assert school["enrolled_students_of_record"] == 0, (
        "no planning area names Alder as its school of record"
    )
    assert school["version"] == 1, f"version is initialised to 1, got {school['version']}"


def test_adoption_create_omitting_optional_inputs_applies_declared_defaults():
    """The four optional AdoptionRecord inputs default to 3, 95.0, 3.0 and 0.

    PRD: "A `BoardMember` records it against a `study_id` and the `scenario_id`
    being adopted, supplying the `effective_date` on or after which the new
    boundaries may be switched on, the `effective_school_year` that begins the
    boundary regime, an optional `regime_years` length defaulting to 3 school
    years, a `transfer_deadline_date`, an optional `transfer_cap_pct` defaulting
    to 95.0, an optional `variance_tolerance_pct` defaulting to 3.0, the three
    tallies `votes_for`, `votes_against` and an optional `votes_abstain`
    defaulting to 0, and the `board_member_count` of seated members."

    Design: Corner/entities/adoption_create_omitting_optional_inputs_applies_declared_defaults
    """
    ctx = riverbend_board_ready()

    response = api_client.create_adoption(
        {
            "study_id": ctx["study_id"],
            "scenario_id": ctx["scenario_id"],
            "effective_date": "2027-07-01T00:00:00Z",
            "effective_school_year": 2028,
            "transfer_deadline_date": "2027-08-15T00:00:00Z",
            "votes_for": 5,
            "votes_against": 2,
            "board_member_count": 7,
        },
        BOARD,
    )

    adoption = validate_success(response, 201)
    assert adoption["regime_years"] == 3, "regime_years defaults to 3 school years"
    assert adoption["transfer_cap_pct"] == pytest.approx(95.00, abs=0.01), (
        "transfer_cap_pct defaults to 95.0"
    )
    assert adoption["variance_tolerance_pct"] == pytest.approx(3.00, abs=0.01), (
        "variance_tolerance_pct defaults to 3.0"
    )
    assert adoption["votes_abstain"] == 0, (
        "votes_abstain defaults to 0, so the cast count is 7 and quorum is met"
    )
    assert adoption["supermajority_required"] is False, (
        "the scenario reassigns no students, so 0.00 percent needs only a simple majority"
    )
    assert adoption["adopted_by_user_id"] == "board-1", "the adopting member is stamped"
    assert adoption["implementation_status"] == "PENDING_EFFECTIVE"
    assert adoption["transfer_window_status"] == "TRANSFER_WINDOW_OPEN"

    scenario = validate_success(api_client.get_scenario(ctx["scenario_id"], PLANNER))
    assert scenario["status"] == "ADOPTED", "the adopted scenario moves BOARD_READY to ADOPTED"
    study = validate_success(api_client.get_study(ctx["study_id"], PLANNER))
    assert study["status"] == "IMPLEMENTATION", (
        "the owning study moves BOARD_DECISION to IMPLEMENTATION"
    )


# ---------------------------------------------------------------------------
# Computed and system fields
# ---------------------------------------------------------------------------
def test_school_computed_capacity_fields_ignore_client_supplied_values():
    """A create shipping the two computed School fields still derives them server-side.

    PRD: "On creation the server computes `effective_capacity_seats` as
    `core_capacity_seats` plus, only when the study's
    `portables_count_toward_capacity` is true, `portable_capacity_seats`;
    otherwise the portable seats are ignored entirely."

    Design: Corner/entities/school_effective_capacity_is_computed_and_input_ignored
    """
    ctx = _riverbend_in_setup()

    response = api_client.create_school(
        ctx["study_id"],
        {
            "name": "Hazel Elementary",
            "level": "ELEMENTARY",
            "core_capacity_seats": 300,
            "portable_capacity_seats": 20,
            "effective_capacity_seats": 9999,
            "enrolled_students_of_record": 12345,
        },
        PLANNER,
    )

    school = validate_success(response, 201)
    assert_school(school)
    assert school["effective_capacity_seats"] == 320, (
        f"300 core plus 20 portable seats, not the supplied 9999, got "
        f"{school['effective_capacity_seats']}"
    )
    assert school["enrolled_students_of_record"] == 0, (
        f"the derived head count starts at 0, not the supplied 12345, got "
        f"{school['enrolled_students_of_record']}"
    )
    assert school["core_capacity_seats"] == 300, "the declared input was honoured"
    assert school["portable_capacity_seats"] == 20, "the declared input was honoured"
    assert school["version"] == 1, f"version is initialised to 1, got {school['version']}"


def test_comment_system_fields_are_server_stamped():
    """A comment's identity and status come from the server, never from the body.

    PRD: "The `guardian_user_id` is stamped from the `X-User-ID` header and never
    accepted from the body. A new comment sits in `SUBMITTED` with `theme`,
    `priority` and `dismissal_reason` all null."

    Design: Corner/entities/comment_system_fields_are_server_stamped_input_ignored
    """
    ctx = riverbend_engagement_open()

    response = api_client.create_comment(
        {
            "scenario_id": ctx["scenario_id"],
            "area_id": ctx["a1_id"],
            "body": "Please keep A-01 at Cedar.",
            "guardian_user_id": "impostor-1",
            "status": "TRIAGED",
            "theme": "EQUITY",
            "priority": "HIGH",
        },
        make_guardian_headers("guardian-5"),
    )

    comment = validate_success(response, 201)
    assert comment["guardian_user_id"] == "guardian-5", (
        f"the filer comes from X-User-ID, not the body, got {comment['guardian_user_id']!r}"
    )
    assert comment["status"] == "SUBMITTED", (
        f"a new comment sits in SUBMITTED, got {comment['status']}"
    )
    assert comment["theme"] is None, "theme stays null until triage"
    assert comment["priority"] is None, "priority stays null until triage"
    assert comment["dismissal_reason"] is None, "dismissal_reason starts null"
    assert comment["scenario_id"] == ctx["scenario_id"]
    assert comment["area_id"] == ctx["a1_id"]
    assert comment["body"] == "Please keep A-01 at Cedar."
    assert is_valid_uuid(comment["id"]), f"id must be a bare UUID, got {comment['id']!r}"
    assert is_iso8601_timestamp(comment["created_at"]), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(comment["updated_at"]), "updated_at must be ISO 8601"
    assert comment["version"] == 1, f"version is initialised to 1, got {comment['version']}"


def test_area_adjacency_rows_are_immutable_and_carry_no_version():
    """Adjacency rows carry only id and created_at, with no updated_at or version.

    PRD: "Three record types are immutable once written and therefore carry only
    `id` and `created_at`; for these, both `updated_at` and `version` are absent
    from the response entirely: **area adjacencies**, **phase-in rules** and
    **variance observations**."

    Design: Corner/entities/area_adjacency_rows_are_immutable_and_carry_no_version
    """
    ctx = _riverbend_in_setup()

    rows, _ = validate_paginated(api_client.list_area_adjacencies(ctx["a2_id"], PLANNER))
    assert rows, "A-02 sits on at least one declared edge"
    for row in rows:
        assert_area_adjacency(row)
        assert "updated_at" not in row, (
            "an area adjacency is immutable and carries no updated_at"
        )
        assert "version" not in row, "an area adjacency is immutable and carries no version"
        assert is_valid_uuid(row["id"]), f"id must be a bare UUID, got {row['id']!r}"
        assert is_iso8601_timestamp(row["created_at"]), "created_at must be ISO 8601"

    mirrors, mirror_meta = validate_paginated(
        api_client.list_area_adjacencies(ctx["a3_id"], PLANNER, {"is_reciprocal": "true"})
    )
    assert mirror_meta["total_count"] == 1, (
        f"exactly one mirror row names A-03, got total_count {mirror_meta['total_count']}"
    )
    mirror = mirrors[0]
    assert mirror["area_id"] == ctx["a3_id"]
    assert mirror["neighbor_area_id"] == ctx["a2_id"]
    assert mirror["shared_boundary_length_ft"] == 4100
    assert mirror["is_reciprocal"] is True
    assert "updated_at" not in mirror, "the mirror row is immutable too"
    assert "version" not in mirror, "the mirror row is immutable too"
