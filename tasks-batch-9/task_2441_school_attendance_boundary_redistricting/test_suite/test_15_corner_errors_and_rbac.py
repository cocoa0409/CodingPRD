"""Corner cases: rejected writes and the role / segregation-of-duties boundaries."""

import pytest

from prd_bench_local_runner.testing import (
    get_success_data,
    is_iso8601_timestamp,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    RIVERBEND_SCHOOLS,
    TEST_USERS,
    ApiErrorId,
    activate_adoption,
    api_client,
    create_adoption_payload,
    create_assignment_payload,
    create_comment,
    create_phase_in_rule_payload,
    create_planning_area_payload,
    create_projection_run,
    create_scenario,
    create_school,
    create_study,
    create_study_payload,
    create_transfer_request,
    create_transfer_request_payload,
    create_variance_observation_payload,
    make_board_headers,
    make_coordinator_headers,
    make_guardian_headers,
    make_officer_headers,
    make_planner_headers,
    program_placement,
    riverbend_adopted,
    riverbend_engagement_open,
    riverbend_locked,
    riverbend_scenario_assigned,
    scenario_version,
    set_clock,
    setup_study_with_inventory,
    submit_for_review,
    travel_option,
)

PLANNER = TEST_USERS["planner_headers"]
COORDINATOR = TEST_USERS["coordinator_headers"]
BOARD = TEST_USERS["board_headers"]
OFFICER = TEST_USERS["officer_headers"]
GUARDIAN = TEST_USERS["guardian_headers"]

CANONICAL_ADOPTION = {
    "effective_date": "2027-07-01T00:00:00Z",
    "effective_school_year": 2028,
    "regime_years": 3,
    "transfer_deadline_date": "2027-08-15T00:00:00Z",
    "transfer_cap_pct": 84.1,
    "variance_tolerance_pct": 5.0,
    "votes_for": 5,
    "votes_against": 2,
    "votes_abstain": 0,
    "board_member_count": 7,
}


# ===========================================================================
# Rejected writes
# ===========================================================================
def test_study_create_without_user_id_header_is_unauthenticated():
    """Identity is checked before the body: a valid study payload sent without
    X-User-ID is refused 401 and nothing is created.

    PRD: "If either header is absent or empty, the request is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/errors/study_create_with_missing_x_user_header_returns_unauthenticated
    """
    headerless = {"X-User-Role": "DistrictPlanner", "Content-Type": "application/json"}
    payload = create_study_payload(
        name="Headerless Study",
        district_name="Nowhere USD",
        target_school_year=2030,
        horizon_years=5,
        capacity_target_low_pct=85.0,
        capacity_target_high_pct=100.0,
    )

    response = api_client.create_study(payload, headerless)
    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED)

    body = response.json()
    assert body["response_type"] == "error", "an error envelope declares response_type error"
    assert isinstance(body["data"].get("error_id"), str), "data carries error_id"
    assert isinstance(body["data"].get("message"), str), "data carries message"
    assert body["meta"]["api_request_id"].startswith("req_"), (
        f"api_request_id must start with req_, got {body['meta']['api_request_id']!r}"
    )
    assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"]), (
        "error meta carries an ISO 8601 api_request_timestamp"
    )


def test_self_and_reverse_duplicate_adjacency_are_rejected():
    """An area may not neighbour itself, and re-posting a declared pair in the
    reverse direction collides with the server-minted mirror row.

    PRD: "An area may not be declared adjacent to itself (`ERR_SELF_ADJACENCY`),
    both endpoints must live in the same study, and a pair already declared in
    either direction is rejected with `ERR_DUPLICATE_ADJACENCY`."

    Design: Corner/errors/self_adjacency_and_reverse_duplicate_adjacency_rejected
    """
    ctx = setup_study_with_inventory(
        school_payloads=RIVERBEND_SCHOOLS,
        area_builders=(
            lambda ids: {
                "area_code": "A-01",
                "grade_band": "ELEMENTARY",
                "current_school_id": ids["Cedar Elementary"],
                "resident_student_count": 300,
                "frl_student_count": 90,
                "ell_student_count": 40,
                "median_household_income_usd": 78000,
                "annual_absorption_cap_units": 120,
                "travel_options": [
                    travel_option(ids["Cedar Elementary"], 0.6, 10, True),
                    travel_option(ids["Birch Elementary"], 2.2, 22, False),
                ],
            },
            lambda ids: {
                "area_code": "A-02",
                "grade_band": "ELEMENTARY",
                "current_school_id": ids["Cedar Elementary"],
                "resident_student_count": 200,
                "frl_student_count": 100,
                "ell_student_count": 30,
                "median_household_income_usd": 52000,
                "annual_absorption_cap_units": 150,
                "travel_options": [
                    travel_option(ids["Cedar Elementary"], 1.4, 9, False),
                    travel_option(ids["Birch Elementary"], 0.8, 12, True),
                ],
            },
            lambda ids: {
                "area_code": "A-03",
                "grade_band": "ELEMENTARY",
                "current_school_id": ids["Birch Elementary"],
                "resident_student_count": 150,
                "frl_student_count": 30,
                "ell_student_count": 10,
                "median_household_income_usd": 96000,
                "annual_absorption_cap_units": 90,
                "travel_options": [
                    travel_option(ids["Cedar Elementary"], 3.0, 26, False),
                    travel_option(ids["Birch Elementary"], 0.9, 14, True),
                ],
            },
        ),
        adjacency_specs=(("A-01", "A-02", 5200), ("A-02", "A-03", 4100)),
        lock=False,
    )
    a1_id = ctx["area_ids"]["A-01"]
    a2_id = ctx["area_ids"]["A-02"]
    a3_id = ctx["area_ids"]["A-03"]

    self_edge = api_client.create_area_adjacency(
        {"area_id": a1_id, "neighbor_area_id": a1_id, "shared_boundary_length_ft": 900},
        PLANNER,
    )
    validate_error(self_edge, ApiErrorId.ERR_SELF_ADJACENCY)

    reversed_edge = api_client.create_area_adjacency(
        {"area_id": a2_id, "neighbor_area_id": a1_id, "shared_boundary_length_ft": 5200},
        PLANNER,
    )
    validate_error(reversed_edge, ApiErrorId.ERR_DUPLICATE_ADJACENCY)

    fresh_edge = api_client.create_area_adjacency(
        {"area_id": a1_id, "neighbor_area_id": a3_id, "shared_boundary_length_ft": 2700},
        PLANNER,
    )
    created = validate_success(fresh_edge, 201)
    assert created["is_reciprocal"] is False, (
        "the row the client creates carries is_reciprocal false"
    )

    rows, meta = validate_paginated(
        api_client.list_area_adjacencies(a3_id, PLANNER, params={"is_reciprocal": "true"})
    )
    assert meta["total_count"] == 2, (
        f"A-03 owns two server-minted mirror rows, got {meta['total_count']}"
    )
    assert all(row["is_reciprocal"] is True for row in rows), "the filter selects mirror rows only"


def test_program_placement_at_an_incapable_host_is_rejected():
    """Birch Elementary hosts no program, so naming it the DUAL_LANGUAGE host is
    refused and the stored placement set is untouched.

    PRD: "The named school must belong to the scenario's study
    (`ERR_CROSS_STUDY_REFERENCE`), must not be `MOTHBALLED`
    (`ERR_SCHOOL_NOT_ACTIVE`), and must be physically able to host the program —
    that is, the program type must appear in the school's `program_types` array,
    or the replacement is rejected with `ERR_PROGRAM_HOST_INCAPABLE`."

    Design: Corner/errors/program_placement_at_an_incapable_host_rejected
    """
    ctx = riverbend_scenario_assigned()
    version_before = scenario_version(ctx["scenario_id"])

    response = api_client.replace_program_placements(
        ctx["scenario_id"],
        {
            "program_placements": [program_placement(ctx["birch_id"], 30)],
            "expected_scenario_version": version_before,
        },
        PLANNER,
    )
    validate_error(response, ApiErrorId.ERR_PROGRAM_HOST_INCAPABLE)

    scenario = get_success_data(api_client.get_scenario(ctx["scenario_id"], PLANNER))
    assert len(scenario["program_placements"]) == 1, (
        "the rejected replacement left the prior placement set intact"
    )
    assert scenario["program_placements"][0]["school_id"] == ctx["cedar_id"], (
        "the surviving placement still names Cedar Elementary"
    )
    assert scenario["version"] == version_before, "a rejected replace bumps nothing"
    assert scenario["status"] == "DRAFT", "the scenario is still editable"


def test_sibling_request_without_an_approved_anchor_is_rejected():
    """A SIBLING request needs a present link that resolves to an APPROVED
    request for the same school: omitting it and pointing at a SUBMITTED anchor
    both fail at creation.

    PRD: "When the reason is `SIBLING`, the link must be usable:
    `sibling_transfer_id` must be present, must resolve
    (`ERR_TRANSFER_NOT_FOUND`), must belong to the same adoption, must itself be
    `APPROVED`, must name the same `requested_school_id`, and must not be the
    request itself; any failure is rejected with `ERR_SIBLING_LINK_INVALID`."

    Design: Corner/errors/sibling_transfer_link_that_is_absent_or_unapproved_rejected
    """
    ctx = riverbend_adopted()
    rule = get_success_data(
        api_client.create_phase_in_rule(
            ctx["adoption_id"],
            create_phase_in_rule_payload(
                rule_type="SIBLING_LINK", grade_low=0, grade_high=6, sunset_school_year=2030
            ),
            BOARD,
        ),
        201,
    )
    anchor = create_transfer_request(
        ctx["adoption_id"],
        ctx["a3_id"],
        ctx["cedar_id"],
        api_client,
        GUARDIAN,
        student_reference="STU-701",
        student_grade=5,
        reason="HARDSHIP",
    )

    unlinked = api_client.create_transfer_request(
        create_transfer_request_payload(
            ctx["adoption_id"],
            ctx["a3_id"],
            ctx["cedar_id"],
            student_reference="STU-702",
            student_grade=2,
            reason="SIBLING",
        ),
        GUARDIAN,
    )
    validate_error(unlinked, ApiErrorId.ERR_SIBLING_LINK_INVALID)

    unapproved = api_client.create_transfer_request(
        create_transfer_request_payload(
            ctx["adoption_id"],
            ctx["a3_id"],
            ctx["cedar_id"],
            student_reference="STU-703",
            student_grade=2,
            reason="SIBLING",
            sibling_transfer_id=anchor["id"],
        ),
        GUARDIAN,
    )
    validate_error(unapproved, ApiErrorId.ERR_SIBLING_LINK_INVALID)

    assert rule["rule_type"] == "SIBLING_LINK", "the sibling rung is genuinely available"
    assert rule["consumes_seat_pool"] is True, "a SIBLING_LINK rule consumes the seat pool"

    stored_anchor = get_success_data(api_client.get_transfer_request(anchor["id"], OFFICER))
    assert stored_anchor["status"] == "SUBMITTED", "the anchor was never approved"
    assert stored_anchor["resolved_reason"] == "HARDSHIP_REVIEW", (
        "the anchor resolves on the hardship rung"
    )

    _, meta = validate_paginated(
        api_client.list_transfer_requests(OFFICER, params={"adoption_id": ctx["adoption_id"]})
    )
    assert meta["total_count"] == 1, (
        f"only the anchor was persisted, got {meta['total_count']} requests"
    )


def test_variance_observation_against_a_zero_projection_is_rejected():
    """A zero denominator is refused and stores nothing, while a zero observed
    head count against a real projection is legal and stores -100.00.

    PRD: "A `projected_enrollment` of 0 leaves the variance percentage
    undefined, so the request is rejected with `ERR_ZERO_PROJECTION_BASE` and no
    observation row is created."

    Design: Corner/errors/variance_observation_against_a_zero_projection_rejected
    """
    ctx = riverbend_adopted()
    set_clock("2027-07-01T00:00:00Z", api_client, OFFICER)
    activate_adoption(ctx["adoption_id"], api_client, OFFICER)

    refused = api_client.create_variance_observation(
        ctx["adoption_id"],
        create_variance_observation_payload(
            ctx["cedar_id"], 480, 0, observed_on="2027-10-01T00:00:00Z"
        ),
        OFFICER,
    )
    validate_error(refused, ApiErrorId.ERR_ZERO_PROJECTION_BASE)

    accepted = api_client.create_variance_observation(
        ctx["adoption_id"],
        create_variance_observation_payload(
            ctx["cedar_id"], 0, 500, observed_on="2027-10-02T00:00:00Z"
        ),
        OFFICER,
    )
    observation = validate_success(accepted, 201)
    assert observation["variance_pct"] == pytest.approx(-100.00, abs=0.01), (
        "0 observed against 500 projected is a -100.00 percent variance"
    )
    assert observation["flag"] == "CORRECTIVE_ACTION_REQUIRED", (
        "100 percent absolute variance exceeds twice the 5.00 percent tolerance"
    )

    _, meta = validate_paginated(
        api_client.list_variance_observations(
            OFFICER, params={"adoption_id": ctx["adoption_id"]}
        )
    )
    assert meta["total_count"] == 1, (
        f"the refused call created nothing, got {meta['total_count']} observations"
    )


def test_assignment_whose_bus_ride_exceeds_the_level_limit_is_rejected():
    """A 52-minute unsafe-route ride to an ELEMENTARY school breaks the 45-minute
    cap, while a 20-minute ride to the same school is accepted.

    PRD: "Finally, student safety caps the commute: when the matching travel
    option is **not** walk-eligible, its `bus_minutes` may not exceed the maximum
    ride time for the school's level — 45 minutes for `ELEMENTARY`, 55 minutes
    for `MIDDLE` and 60 minutes for `HIGH` — and a longer ride is rejected with
    `ERR_RIDE_TIME_EXCEEDED`."

    Design: Corner/errors/assignment_whose_bus_ride_exceeds_the_level_limit_rejected
    """
    ctx = setup_study_with_inventory(
        study_payload={
            "name": "2029 Rural Ride Study",
            "district_name": "Foxglove USD",
            "target_school_year": 2029,
            "horizon_years": 5,
            "capacity_target_low_pct": 80.0,
            "capacity_target_high_pct": 100.0,
            "portables_count_toward_capacity": False,
            "required_program_types": ["DUAL_LANGUAGE"],
        },
        school_payloads=(
            {
                "name": "Gorse Elementary",
                "level": "ELEMENTARY",
                "core_capacity_seats": 600,
                "program_types": ["DUAL_LANGUAGE"],
            },
            {"name": "Heath Elementary", "level": "ELEMENTARY", "core_capacity_seats": 600},
        ),
        area_builders=(
            lambda ids: {
                "area_code": "X-01",
                "grade_band": "ELEMENTARY",
                "current_school_id": ids["Gorse Elementary"],
                "resident_student_count": 300,
                "frl_student_count": 50,
                "ell_student_count": 10,
                "median_household_income_usd": 64000,
                "annual_absorption_cap_units": 200,
                "travel_options": [
                    travel_option(ids["Gorse Elementary"], 0.5, 10, True),
                    travel_option(ids["Heath Elementary"], 6.0, 52, False),
                ],
            },
            lambda ids: {
                "area_code": "X-02",
                "grade_band": "ELEMENTARY",
                "current_school_id": ids["Gorse Elementary"],
                "resident_student_count": 200,
                "frl_student_count": 50,
                "ell_student_count": 10,
                "median_household_income_usd": 64000,
                "annual_absorption_cap_units": 200,
                "travel_options": [
                    travel_option(ids["Gorse Elementary"], 0.7, 12, True),
                    travel_option(ids["Heath Elementary"], 2.0, 20, False),
                ],
            },
            lambda ids: {
                "area_code": "X-03",
                "grade_band": "ELEMENTARY",
                "current_school_id": ids["Heath Elementary"],
                "resident_student_count": 100,
                "frl_student_count": 50,
                "ell_student_count": 10,
                "median_household_income_usd": 64000,
                "annual_absorption_cap_units": 200,
                "travel_options": [
                    travel_option(ids["Gorse Elementary"], 2.5, 24, False),
                    travel_option(ids["Heath Elementary"], 0.6, 11, True),
                ],
            },
        ),
        adjacency_specs=(("X-01", "X-02", 4500), ("X-02", "X-03", 4000)),
    )
    gorse_id = ctx["school_ids"]["Gorse Elementary"]
    heath_id = ctx["school_ids"]["Heath Elementary"]
    run = create_projection_run(ctx["study_id"], variant="COHORT_SURVIVAL")
    scenario = create_scenario(
        ctx["study_id"],
        run["id"],
        [program_placement(gorse_id, 12)],
        name="Ride Draft",
    )
    draft_version = scenario["version"]

    too_long = api_client.create_assignment(
        create_assignment_payload(
            scenario["id"], ctx["area_ids"]["X-01"], heath_id, draft_version
        ),
        PLANNER,
    )
    validate_error(too_long, ApiErrorId.ERR_RIDE_TIME_EXCEEDED)

    accepted = api_client.create_assignment(
        create_assignment_payload(
            scenario["id"], ctx["area_ids"]["X-02"], heath_id, draft_version
        ),
        PLANNER,
    )
    assignment = validate_success(accepted, 201)
    assert assignment["assigned_school_id"] == heath_id, (
        "the 20-minute ride to the same school is accepted"
    )
    assert assignment["projected_students"] == 181, (
        f"X-02 projects 181 students at the five-year horizon, got {assignment['projected_students']}"
    )

    _, meta = validate_paginated(
        api_client.list_assignments(PLANNER, params={"scenario_id": scenario["id"]})
    )
    assert meta["total_count"] == 1, (
        f"the refused assignment persisted nothing, got {meta['total_count']} rows"
    )


def test_pagination_and_enum_query_inputs_out_of_range_are_rejected():
    """limit 0 and offset -1 are each a 422 rather than a clamped page, while a
    well-formed page reports the unpaginated total.

    (The undeclared-`grade_band`-filter assertion was removed: the PRD states only
    that planning-area listings are "filterable by ... `grade_band`" and never says
    an out-of-member *filter* value is rejected, so an empty 200 page is an equally
    faithful reading. The body-level enum rejection is covered by test_10.)

    PRD: "A `limit` below 1 or above 200, or a negative `offset`, is rejected
    with `ERR_INVALID_REQUEST` (HTTP 422)."

    PRD: "**Schema** — `ERR_INVALID_REQUEST`: a required input field absent or
    null, an enum value outside its declared member list, a positive-integer
    field (`total_units`, `buildout_months`, `regime_years`,
    `core_capacity_seats`, `board_member_count`) at zero or below, a negative
    vote count or negative `seats`, a `student_grade` outside 0 through 12, a
    `grade_low` greater than `grade_high`, a percent field outside 0 through
    1000, a `limit` outside 1 through 200, a negative `offset`, an empty
    `travel_options` or `program_placements` array, a travel option entry
    missing `school_id`, `walk_distance_miles`, `bus_minutes` or
    `has_safe_route`, or a program placement entry missing `program_type`,
    `school_id` or `seats`."

    Design: Corner/errors/pagination_and_enum_inputs_out_of_range_returns_invalid_request
    """
    ctx = riverbend_locked()
    study_id = ctx["study_id"]

    validate_error(
        api_client.list_planning_areas(PLANNER, params={"study_id": study_id, "limit": 0}),
        ApiErrorId.ERR_INVALID_REQUEST,
    )
    validate_error(
        api_client.list_planning_areas(PLANNER, params={"study_id": study_id, "offset": -1}),
        ApiErrorId.ERR_INVALID_REQUEST,
    )
    rows, meta = validate_paginated(
        api_client.list_planning_areas(
            PLANNER, params={"study_id": study_id, "limit": 2, "offset": 2}
        )
    )
    assert meta["total_count"] == 3, (
        f"total_count counts matches before pagination, got {meta['total_count']}"
    )
    assert meta["has_more"] is False, "no records remain beyond the second page"
    assert len(rows) == 1, f"the second page holds the last row alone, got {len(rows)}"
    assert rows[0]["id"] == ctx["a3_id"], "listings are ordered by created_at ascending"


def test_transfer_with_no_eligibility_basis_may_only_be_denied():
    """A resolved_reason of NONE refuses both APPROVE and WAITLIST and leaves the
    request untouched; DENY is the one decision that lands.

    PRD: "`APPROVE` and `WAITLIST` both require a real entitlement: a request
    whose re-evaluated `resolved_reason` is `NONE` may only be denied, and an
    attempt to approve or waitlist it is rejected with
    `ERR_NO_ELIGIBILITY_BASIS`."

    Design: Corner/errors/approving_a_transfer_with_no_eligibility_basis_rejected
    """
    ctx = riverbend_adopted()
    request = create_transfer_request(
        ctx["adoption_id"],
        ctx["a3_id"],
        ctx["cedar_id"],
        api_client,
        make_guardian_headers("guardian-4"),
        student_reference="STU-801",
        student_grade=3,
        reason="PROGRAM",
    )

    validate_error(
        api_client.decide_transfer_request(request["id"], {"decision": "APPROVE"}, OFFICER),
        ApiErrorId.ERR_NO_ELIGIBILITY_BASIS,
    )
    validate_error(
        api_client.decide_transfer_request(request["id"], {"decision": "WAITLIST"}, OFFICER),
        ApiErrorId.ERR_NO_ELIGIBILITY_BASIS,
    )

    after_refusals = get_success_data(api_client.get_transfer_request(request["id"], OFFICER))
    assert after_refusals["status"] == "SUBMITTED", "both refusals left the request undecided"
    assert after_refusals["decided_by_user_id"] is None, "no decider was stamped"

    denied = get_success_data(
        api_client.decide_transfer_request(
            request["id"], {"decision": "DENY", "decision_notes": "No basis."}, OFFICER
        )
    )
    assert denied["status"] == "DENIED", "denial is the only available outcome"
    assert denied["decided_by_user_id"] == "officer-1", "the decision stamps the acting officer"
    assert denied["resolved_reason"] == "NONE", "no rung of the waterfall matched"
    assert denied["promotion_source"] is None, "a denial never sets a promotion source"


def test_editing_an_adopted_scenario_is_rejected():
    """ADOPTED freezes the map: a fresh assignment and a placement replacement
    are both refused even though the supplied version is current.

    PRD: "A scenario's content — its assignments and its program placements —
    may be edited only while its `status` is `DRAFT` or `REVISION`; in any other
    state the content is frozen and an edit or a resubmission is rejected with
    `ERR_SCENARIO_NOT_EDITABLE`."

    Design: Corner/errors/editing_an_adopted_scenario_rejected
    """
    ctx = riverbend_adopted()
    version_before = scenario_version(ctx["scenario_id"])

    validate_error(
        api_client.create_assignment(
            create_assignment_payload(
                ctx["scenario_id"], ctx["a3_id"], ctx["cedar_id"], version_before
            ),
            PLANNER,
        ),
        ApiErrorId.ERR_SCENARIO_NOT_EDITABLE,
    )
    validate_error(
        api_client.replace_program_placements(
            ctx["scenario_id"],
            {
                "program_placements": [program_placement(ctx["cedar_id"], 40)],
                "expected_scenario_version": version_before,
            },
            PLANNER,
        ),
        ApiErrorId.ERR_SCENARIO_NOT_EDITABLE,
    )

    scenario = get_success_data(api_client.get_scenario(ctx["scenario_id"], PLANNER))
    assert scenario["status"] == "ADOPTED", "the terminal state is untouched"
    assert scenario["version"] == version_before, "neither refusal bumped the version"
    assert len(scenario["program_placements"]) == 1, "the placement set survived intact"
    assert scenario["program_placements"][0]["school_id"] == ctx["cedar_id"], (
        "the surviving placement still names Cedar Elementary"
    )
    assert scenario["program_placements"][0]["seats"] == 30, "the stored seat count is unchanged"

    rows, meta = validate_paginated(
        api_client.list_assignments(PLANNER, params={"scenario_id": ctx["scenario_id"]})
    )
    assert meta["total_count"] == 3, (
        f"the adopted map still holds three assignments, got {meta['total_count']}"
    )
    assert all(row["is_superseded"] is False for row in rows), (
        "no assignment was superseded by the refused create"
    )


# ===========================================================================
# Role authorization and segregation of duties
# ===========================================================================
def test_guardian_cannot_read_internal_planning_artifacts():
    """The public role keeps the study, scenario and impact reads but is closed
    out of projection runs, assignments, adjacencies, housing and variance.

    PRD: "A `Guardian` cannot read internal planning artifacts — projection
    runs, adjacency listings, housing pipelines, assignment tables and variance
    monitoring are all closed to that role."

    Design: Corner/rbac/guardian_cannot_read_internal_planning_artifacts
    """
    ctx = riverbend_adopted()
    set_clock("2027-07-01T00:00:00Z", api_client, OFFICER)
    activate_adoption(ctx["adoption_id"], api_client, OFFICER)
    guardian = make_guardian_headers("guardian-7")

    validate_error(
        api_client.list_projection_runs(ctx["study_id"], guardian),
        ApiErrorId.ERR_UNAUTHORIZED,
    )
    validate_error(
        api_client.list_assignments(guardian, params={"scenario_id": ctx["scenario_id"]}),
        ApiErrorId.ERR_UNAUTHORIZED,
    )
    validate_error(
        api_client.list_variance_observations(
            guardian, params={"adoption_id": ctx["adoption_id"]}
        ),
        ApiErrorId.ERR_UNAUTHORIZED,
    )
    validate_error(
        api_client.list_area_adjacencies(ctx["a1_id"], guardian),
        ApiErrorId.ERR_UNAUTHORIZED,
    )
    validate_error(
        api_client.list_housing_developments(ctx["a1_id"], guardian),
        ApiErrorId.ERR_UNAUTHORIZED,
    )

    analysis = get_success_data(api_client.get_impact_analysis(ctx["scenario_id"], guardian))
    assert analysis["max_utilization_pct"] == pytest.approx(89.26, abs=0.01), (
        f"Cedar carries 482 of 540 seats, got {analysis['max_utilization_pct']}"
    )

    study = get_success_data(api_client.get_study(ctx["study_id"], guardian))
    assert study["status"] == "IMPLEMENTATION", "the public study read still works"


def test_district_planner_cannot_run_the_engagement_or_board_steps():
    """The planner authors the map but owns none of the downstream gates:
    engagement, triage, certification and the board vote are all 403.

    PRD: "If both headers are present but the named role is not permitted to
    invoke the endpoint, the rejection is `ERR_UNAUTHORIZED` (HTTP 403)."

    PRD: "**`EngagementCoordinator`** — owns the community engagement cycle:
    opening comment intake, triaging and dismissing public comment, pushing a
    reviewed scenario back for revision, and certifying a reviewed scenario onto
    the board agenda."

    Design: Corner/rbac/district_planner_cannot_run_the_engagement_or_board_steps
    """
    ctx = riverbend_engagement_open()
    comment = create_comment(
        ctx["scenario_id"],
        api_client,
        GUARDIAN,
        area_id=ctx["a1_id"],
        body="Please keep A-01 at Cedar.",
    )

    validate_error(
        api_client.open_engagement(ctx["study_id"], PLANNER), ApiErrorId.ERR_UNAUTHORIZED
    )
    validate_error(
        api_client.triage_comment(
            comment["id"], {"theme": "TRANSPORTATION", "priority": "HIGH"}, PLANNER
        ),
        ApiErrorId.ERR_UNAUTHORIZED,
    )
    validate_error(
        api_client.advance_scenario_to_board(ctx["scenario_id"], PLANNER),
        ApiErrorId.ERR_UNAUTHORIZED,
    )
    validate_error(
        api_client.create_adoption(
            create_adoption_payload(ctx["study_id"], ctx["scenario_id"], **CANONICAL_ADOPTION),
            PLANNER,
        ),
        ApiErrorId.ERR_UNAUTHORIZED,
    )

    stored_comment = get_success_data(api_client.get_comment(comment["id"], COORDINATOR))
    assert stored_comment["status"] == "SUBMITTED", "the refused triage stamped nothing"
    assert stored_comment["theme"] is None, "no theme was stored"

    scenario = get_success_data(api_client.get_scenario(ctx["scenario_id"], PLANNER))
    assert scenario["status"] == "UNDER_REVIEW", "the scenario never reached the board agenda"

    study = get_success_data(api_client.get_study(ctx["study_id"], PLANNER))
    assert study["status"] == "ENGAGEMENT", "the study phase is unchanged"
    assert study["comment_intake_open"] is True, "intake stays open"

    _, meta = validate_paginated(
        api_client.list_adoptions(PLANNER, params={"study_id": ctx["study_id"]})
    )
    assert meta["total_count"] == 0, (
        f"no adoption was recorded, got {meta['total_count']}"
    )


def test_engagement_coordinator_cannot_adopt_or_attach_phase_in_rules():
    """The coordinator who certified the scenario still cannot cast the adopting
    vote, attach a grandfathering rule or rescind.

    PRD: "**`BoardMember`** — owns the board decision: recording the adopting
    vote, attaching grandfathering and phase-in rules to an adoption, pushing a
    board-ready scenario back for revision, and rescinding an adoption that is
    already in effect."

    Design: Corner/rbac/engagement_coordinator_cannot_adopt_or_attach_phase_in_rules
    """
    ctx = riverbend_adopted()

    validate_error(
        api_client.create_adoption(
            create_adoption_payload(ctx["study_id"], ctx["scenario_id"], **CANONICAL_ADOPTION),
            COORDINATOR,
        ),
        ApiErrorId.ERR_UNAUTHORIZED,
    )
    validate_error(
        api_client.create_phase_in_rule(
            ctx["adoption_id"],
            create_phase_in_rule_payload(
                rule_type="TERMINAL_GRADE_GRANDFATHER",
                grade_low=5,
                grade_high=5,
                sunset_school_year=2029,
            ),
            COORDINATOR,
        ),
        ApiErrorId.ERR_UNAUTHORIZED,
    )
    validate_error(
        api_client.rescind_adoption(
            ctx["adoption_id"], {"rescind_reason": "Coordinator override."}, COORDINATOR
        ),
        ApiErrorId.ERR_UNAUTHORIZED,
    )

    _, rule_meta = validate_paginated(
        api_client.list_phase_in_rules(ctx["adoption_id"], BOARD)
    )
    assert rule_meta["total_count"] == 0, (
        f"no phase-in rule was attached, got {rule_meta['total_count']}"
    )

    adoption = get_success_data(api_client.get_adoption(ctx["adoption_id"], BOARD))
    assert adoption["implementation_status"] == "PENDING_EFFECTIVE", (
        "the refused rescission changed nothing"
    )

    _, adoption_meta = validate_paginated(
        api_client.list_adoptions(BOARD, params={"study_id": ctx["study_id"]})
    )
    assert adoption_meta["total_count"] == 1, (
        f"only the board's own adoption exists, got {adoption_meta['total_count']}"
    )


def test_transfer_officer_cannot_build_the_plan_it_will_implement():
    """Authoring a scenario, an assignment, a planning area or a capacity patch
    are all closed to the officer who will implement the map.

    PRD: "**`DistrictPlanner`** — owns study setup, the school and planning-area
    inventory, the adjacency graph, the housing pipeline, enrollment projection
    runs, scenario construction, area assignments and program placement."

    Design: Corner/rbac/transfer_officer_cannot_build_the_plan_it_will_implement
    """
    ctx = riverbend_scenario_assigned()
    version_before = scenario_version(ctx["scenario_id"], api_client, OFFICER)

    validate_error(
        api_client.create_scenario(
            {
                "study_id": ctx["study_id"],
                "projection_run_id": ctx["run_id"],
                "name": "Officer Draft",
                "program_placements": [program_placement(ctx["cedar_id"], 30)],
                "impact_variant": "RESIDENT_BASED",
            },
            OFFICER,
        ),
        ApiErrorId.ERR_UNAUTHORIZED,
    )
    validate_error(
        api_client.create_assignment(
            create_assignment_payload(
                ctx["scenario_id"], ctx["a3_id"], ctx["cedar_id"], version_before
            ),
            OFFICER,
        ),
        ApiErrorId.ERR_UNAUTHORIZED,
    )
    validate_error(
        api_client.patch_school(ctx["cedar_id"], {"core_capacity_seats": 600}, OFFICER),
        ApiErrorId.ERR_UNAUTHORIZED,
    )
    validate_error(
        api_client.create_planning_area(
            create_planning_area_payload(
                ctx["study_id"],
                ctx["cedar_id"],
                [
                    travel_option(ctx["cedar_id"], 0.5, 8, True),
                    travel_option(ctx["birch_id"], 1.1, 15, True),
                ],
                area_code="A-04",
                resident_student_count=50,
                frl_student_count=10,
                ell_student_count=5,
                median_household_income_usd=80000,
                annual_absorption_cap_units=60,
            ),
            OFFICER,
        ),
        ApiErrorId.ERR_UNAUTHORIZED,
    )

    _, scenario_meta = validate_paginated(
        api_client.list_scenarios(OFFICER, params={"study_id": ctx["study_id"]})
    )
    assert scenario_meta["total_count"] == 1, (
        f"no officer-authored scenario exists, got {scenario_meta['total_count']}"
    )

    scenario = get_success_data(api_client.get_scenario(ctx["scenario_id"], OFFICER))
    assert scenario["version"] == version_before, "the refused assignment bumped nothing"

    school = get_success_data(api_client.get_school(ctx["cedar_id"], OFFICER))
    assert school["core_capacity_seats"] == 500, "the refused patch changed no seat count"
    assert school["effective_capacity_seats"] == 540, "portables still count toward capacity"

    _, area_meta = validate_paginated(
        api_client.list_planning_areas(OFFICER, params={"study_id": ctx["study_id"]})
    )
    assert area_meta["total_count"] == 3, (
        f"the seed inventory is unchanged, got {area_meta['total_count']} areas"
    )


def test_board_member_cannot_activate_or_decide_transfers():
    """Activation, transfer decisions and variance recording belong to the
    officer, even for the board member who adopted the plan.

    PRD: "**`TransferOfficer`** — owns implementation: activating the adopted
    regime, deciding transfer requests against each school's seat pool, closing
    the transfer window, recording post-implementation variance observations and
    closing monitoring."

    Design: Corner/rbac/board_member_cannot_activate_or_decide_transfers
    """
    ctx = riverbend_adopted()
    request = create_transfer_request(
        ctx["adoption_id"],
        ctx["a3_id"],
        ctx["cedar_id"],
        api_client,
        make_guardian_headers("guardian-5"),
        student_reference="STU-901",
        student_grade=4,
        reason="HARDSHIP",
    )
    set_clock("2027-07-01T00:00:00Z", api_client, BOARD)

    validate_error(
        api_client.activate_adoption(ctx["adoption_id"], BOARD), ApiErrorId.ERR_UNAUTHORIZED
    )
    validate_error(
        api_client.decide_transfer_request(request["id"], {"decision": "APPROVE"}, BOARD),
        ApiErrorId.ERR_UNAUTHORIZED,
    )
    validate_error(
        api_client.create_variance_observation(
            ctx["adoption_id"],
            create_variance_observation_payload(
                ctx["cedar_id"], 500, 500, observed_on="2027-09-01T00:00:00Z"
            ),
            BOARD,
        ),
        ApiErrorId.ERR_UNAUTHORIZED,
    )

    adoption = get_success_data(api_client.get_adoption(ctx["adoption_id"], BOARD))
    assert adoption["implementation_status"] == "PENDING_EFFECTIVE", (
        "the refused activation left the regime pending"
    )

    stored_request = get_success_data(api_client.get_transfer_request(request["id"], BOARD))
    assert stored_request["status"] == "SUBMITTED", "the refused decision stamped nothing"
    assert stored_request["decided_by_user_id"] is None, "no decider was recorded"

    _, meta = validate_paginated(
        api_client.list_variance_observations(
            OFFICER, params={"adoption_id": ctx["adoption_id"]}
        )
    )
    assert meta["total_count"] == 0, (
        f"the refused observation created nothing, got {meta['total_count']}"
    )


def test_every_role_may_read_a_school_and_advance_the_clock():
    """The school read, the study read and the logical-clock write are shared by
    all five roles, Guardian included.

    PRD: "All five roles may drive the clock, and the two identity headers are
    still required."

    PRD: "Submits public comment while intake is open, files transfer requests,
    and reads the public-facing study, school, planning-area, scenario, comment,
    adoption, phase-in-rule and transfer records."

    Design: Corner/rbac/every_role_may_read_a_school_and_advance_the_clock
    """
    set_clock("2026-09-01T00:00:00Z", api_client, PLANNER)
    study = create_study(api_client, PLANNER)
    cedar = create_school(study["id"], api_client, PLANNER, **RIVERBEND_SCHOOLS[0])
    create_school(study["id"], api_client, PLANNER, **RIVERBEND_SCHOOLS[1])
    guardian = make_guardian_headers("guardian-8")

    bodies = []
    for headers in (PLANNER, COORDINATOR, BOARD, OFFICER, guardian):
        data = validate_success(api_client.get_school(cedar["id"], headers))
        assert data["effective_capacity_seats"] == 540, (
            f"500 core plus 40 portable seats count as 540, got {data['effective_capacity_seats']}"
        )
        bodies.append(data)
    assert all(body == bodies[0] for body in bodies), (
        "every permitted role reads an identical school body"
    )

    clock = validate_success(api_client.set_current_utc("2026-10-01T00:00:00Z", guardian))
    assert clock["current_utc"].startswith("2026-10-01T00:00:00"), (
        f"the Guardian clock write took effect, got {clock['current_utc']}"
    )

    public_study = validate_success(api_client.get_study(study["id"], guardian))
    assert public_study["status"] == "SETUP", "the study is still assembling its inventory"
    assert public_study["district_name"] == "Riverbend USD", "the public read carries the district"


def test_scenario_author_cannot_certify_or_adopt_their_own_scenario():
    """author_user_id blocks the same human from certifying and from adopting,
    whatever role they wear; a different user succeeds on the same body.

    PRD: "First, the planner who authored a scenario is separated from every
    downstream judgement on it: an operator whose `X-User-ID` equals the
    scenario's `author_user_id` may not push that scenario back for revision and
    may not certify it for the board agenda — both are rejected with
    `ERR_SELF_REVIEW_FORBIDDEN` (HTTP 403) — and may not record the board vote
    adopting it, nor rescind an adoption of it, which are rejected with
    `ERR_SELF_ADOPTION_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/scenario_author_cannot_certify_or_adopt_their_own_scenario
    """
    ctx = riverbend_locked()
    author_planner = make_planner_headers("dual-1")
    run = create_projection_run(ctx["study_id"])
    scenario = create_scenario(
        ctx["study_id"],
        run["id"],
        [program_placement(ctx["cedar_id"], 30)],
        api_client,
        author_planner,
    )
    assert scenario["author_user_id"] == "dual-1", "the author is stamped from X-User-ID"

    for area_id, school_id in (
        (ctx["a1_id"], ctx["cedar_id"]),
        (ctx["a2_id"], ctx["cedar_id"]),
        (ctx["a3_id"], ctx["birch_id"]),
    ):
        api_client.create_assignment(
            create_assignment_payload(
                scenario["id"], area_id, school_id, scenario_version(scenario["id"])
            ),
            PLANNER,
        )
    submit_for_review(scenario["id"], api_client, author_planner)
    get_success_data(api_client.open_engagement(ctx["study_id"], COORDINATOR))

    validate_error(
        api_client.advance_scenario_to_board(scenario["id"], make_coordinator_headers("dual-1")),
        ApiErrorId.ERR_SELF_REVIEW_FORBIDDEN,
    )
    still_reviewing = get_success_data(api_client.get_scenario(scenario["id"], PLANNER))
    assert still_reviewing["status"] == "UNDER_REVIEW", "the author's certification was refused"

    certified = get_success_data(
        api_client.advance_scenario_to_board(scenario["id"], COORDINATOR)
    )
    assert certified["status"] == "BOARD_READY", "a different coordinator may certify"

    adoption_payload = create_adoption_payload(
        ctx["study_id"], scenario["id"], **CANONICAL_ADOPTION
    )
    validate_error(
        api_client.create_adoption(adoption_payload, make_board_headers("dual-1")),
        ApiErrorId.ERR_SELF_ADOPTION_FORBIDDEN,
    )
    after_refusal = get_success_data(api_client.get_scenario(scenario["id"], PLANNER))
    assert after_refusal["status"] == "BOARD_READY", "the refused vote adopted nothing"
    study = get_success_data(api_client.get_study(ctx["study_id"], PLANNER))
    assert study["status"] == "BOARD_DECISION", "the study still awaits its vote"

    adoption = validate_success(api_client.create_adoption(adoption_payload, BOARD), 201)
    assert adoption["adopted_by_user_id"] == "board-1", "the adopting member is stamped"
    adopted = get_success_data(api_client.get_scenario(scenario["id"], PLANNER))
    assert adopted["status"] == "ADOPTED", "the identical body succeeds for another user"

    _, meta = validate_paginated(
        api_client.list_adoptions(BOARD, params={"study_id": ctx["study_id"]})
    )
    assert meta["total_count"] == 1, f"exactly one vote was recorded, got {meta['total_count']}"


def test_transfer_officer_cannot_decide_a_request_they_filed():
    """guardian_user_id disqualifies the filer from deciding even while wearing
    TransferOfficer, and another officer succeeds on the identical body.

    PRD: "Second, the operator who filed a transfer request is separated from
    its decision: when the acting `X-User-ID` equals the request's
    `guardian_user_id`, the decision is rejected with
    `ERR_SELF_DECISION_FORBIDDEN` (HTTP 403), even though the caller
    legitimately holds the `TransferOfficer` role."

    Design: Corner/rbac/transfer_officer_cannot_decide_a_request_they_filed
    """
    ctx = riverbend_adopted()
    request = create_transfer_request(
        ctx["adoption_id"],
        ctx["a3_id"],
        ctx["cedar_id"],
        api_client,
        make_guardian_headers("dual-2"),
        student_reference="STU-902",
        student_grade=4,
        reason="HARDSHIP",
    )
    assert request["guardian_user_id"] == "dual-2", "the filer is stamped from X-User-ID"
    assert request["resolved_reason"] == "HARDSHIP_REVIEW", "the hardship rung resolves"

    validate_error(
        api_client.decide_transfer_request(
            request["id"], {"decision": "APPROVE"}, make_officer_headers("dual-2")
        ),
        ApiErrorId.ERR_SELF_DECISION_FORBIDDEN,
    )
    after_refusal = get_success_data(api_client.get_transfer_request(request["id"], OFFICER))
    assert after_refusal["status"] == "SUBMITTED", "the filer's own decision was refused"
    assert after_refusal["decided_by_user_id"] is None, "no decider was stamped"

    approved = get_success_data(
        api_client.decide_transfer_request(request["id"], {"decision": "APPROVE"}, OFFICER)
    )
    assert approved["status"] == "APPROVED", "a different officer may decide the same request"
    assert approved["decided_by_user_id"] == "officer-1", "the deciding officer is stamped"
