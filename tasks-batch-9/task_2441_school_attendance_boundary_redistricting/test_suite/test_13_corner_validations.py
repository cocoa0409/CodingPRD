"""Validation-rule corner cases: uniqueness scope, cross-study references, temporal
gates, the seed-data lock, and the submit-for-review structural gate."""

import pytest

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    BOARD,
    COORDINATOR,
    OFFICER,
    PLANNER,
    RIVERBEND_CLOCK,
    RIVERBEND_SCHOOLS,
    ApiErrorId,
    api_client,
    assign_area,
    create_adoption_payload,
    create_phase_in_rule_payload,
    create_planning_area_payload,
    create_projection_run,
    create_scenario,
    create_school,
    create_study,
    create_transfer_request_payload,
    make_guardian_headers,
    program_placement,
    replace_program_placements,
    riverbend_adopted,
    riverbend_board_ready,
    riverbend_engagement_open,
    riverbend_locked,
    riverbend_scenario_assigned,
    riverbend_scenario_draft,
    scenario_version,
    set_clock,
    setup_study_with_inventory,
    travel_option,
)

# ---------------------------------------------------------------------------
# Local setup builders (the shared ladder fixtures always lock the study, and
# several instances below need a study that is still in SETUP, or a third school)
# ---------------------------------------------------------------------------
def _riverbend_area_builders():
    """The three canonical Riverbend planning areas, keyed off school name."""

    def a01(school_ids):
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

    def a02(school_ids):
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

    def a03(school_ids):
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

    return (a01, a02, a03)


def _riverbend_setup_phase():
    """Riverbend USD with its full seed inventory, deliberately left in SETUP."""
    return setup_study_with_inventory(
        school_payloads=RIVERBEND_SCHOOLS,
        area_builders=_riverbend_area_builders(),
        adjacency_specs=(("A-01", "A-02", 5200), ("A-02", "A-03", 4100)),
        clock=RIVERBEND_CLOCK,
        lock=False,
    )


def _harborview_setup_phase():
    """A second district, Harborview USD, also still in SETUP."""

    def h01(school_ids):
        return {
            "area_code": "H-01",
            "grade_band": "ELEMENTARY",
            "current_school_id": school_ids["Quay Elementary"],
            "resident_student_count": 300,
            "frl_student_count": 90,
            "ell_student_count": 30,
            "median_household_income_usd": 74000,
            "annual_absorption_cap_units": 150,
            "travel_options": [
                travel_option(school_ids["Quay Elementary"], 0.6, 10, True),
                travel_option(school_ids["Pier Elementary"], 0.9, 13, True),
            ],
        }

    def h02(school_ids):
        return {
            "area_code": "H-02",
            "grade_band": "ELEMENTARY",
            "current_school_id": school_ids["Quay Elementary"],
            "resident_student_count": 200,
            "frl_student_count": 60,
            "ell_student_count": 20,
            "median_household_income_usd": 81000,
            "annual_absorption_cap_units": 150,
            "travel_options": [
                travel_option(school_ids["Quay Elementary"], 0.6, 10, True),
                travel_option(school_ids["Pier Elementary"], 0.9, 13, True),
            ],
        }

    return setup_study_with_inventory(
        study_payload={
            "name": "2029 Boundary Pilot",
            "district_name": "Harborview USD",
            "target_school_year": 2029,
            "horizon_years": 5,
            "capacity_target_low_pct": 85.0,
            "capacity_target_high_pct": 100.0,
            "portables_count_toward_capacity": False,
            "required_program_types": ["DUAL_LANGUAGE"],
        },
        school_payloads=(
            {
                "name": "Quay Elementary",
                "level": "ELEMENTARY",
                "core_capacity_seats": 500,
                "program_types": ["DUAL_LANGUAGE"],
            },
            {"name": "Pier Elementary", "level": "ELEMENTARY", "core_capacity_seats": 400},
        ),
        area_builders=(h01, h02),
        adjacency_specs=(("H-01", "H-02", 4800),),
        clock=None,
        lock=False,
    )


def _total_count(response):
    _, meta = validate_paginated(response)
    return meta["total_count"]


# ---------------------------------------------------------------------------
# Uniqueness scope
# ---------------------------------------------------------------------------
def test_area_code_and_school_name_collide_only_inside_the_same_study():
    """The same area_code and school name are free in another study but duplicate inside one.

    PRD: "A duplicate `area_code` inside the study is rejected with
    `ERR_DUPLICATE_NAME`."
    PRD: "A duplicate school name inside the study is rejected with
    `ERR_DUPLICATE_NAME`."

    Design: Corner/validations/area_code_and_school_name_are_unique_per_study_not_globally
    """
    riverbend = _riverbend_setup_phase()
    harborview = _harborview_setup_phase()

    duplicate_area = api_client.create_planning_area(
        create_planning_area_payload(
            riverbend["study_id"],
            riverbend["school_ids"]["Birch Elementary"],
            [
                travel_option(riverbend["school_ids"]["Cedar Elementary"], 1.1, 13, True),
                travel_option(riverbend["school_ids"]["Birch Elementary"], 0.7, 11, True),
            ],
            area_code="A-01",
            resident_student_count=100,
            frl_student_count=20,
            ell_student_count=5,
            median_household_income_usd=88000,
            annual_absorption_cap_units=100,
        ),
        PLANNER,
    )
    validate_error(duplicate_area, ApiErrorId.ERR_DUPLICATE_NAME.value)

    foreign_area = api_client.create_planning_area(
        create_planning_area_payload(
            harborview["study_id"],
            harborview["school_ids"]["Pier Elementary"],
            [
                travel_option(harborview["school_ids"]["Quay Elementary"], 0.8, 12, True),
                travel_option(harborview["school_ids"]["Pier Elementary"], 1.1, 15, True),
            ],
            area_code="A-01",
            resident_student_count=100,
            frl_student_count=40,
            ell_student_count=10,
            median_household_income_usd=83000,
            annual_absorption_cap_units=150,
        ),
        PLANNER,
    )
    accepted = validate_success(foreign_area, 201)
    assert accepted["area_code"] == "A-01", (
        "A-01 is free inside Harborview because uniqueness is scoped to the study, got "
        f"{accepted['area_code']!r}"
    )
    assert accepted["study_id"] == harborview["study_id"]

    duplicate_school = api_client.create_school(
        riverbend["study_id"],
        {"name": "Cedar Elementary", "level": "ELEMENTARY", "core_capacity_seats": 250},
        PLANNER,
    )
    validate_error(duplicate_school, ApiErrorId.ERR_DUPLICATE_NAME.value)

    assert (
        _total_count(
            api_client.list_planning_areas(PLANNER, {"study_id": riverbend["study_id"]})
        )
        == 3
    ), "the rejected duplicate must not have been persisted under Riverbend"
    assert (
        _total_count(
            api_client.list_planning_areas(PLANNER, {"study_id": harborview["study_id"]})
        )
        == 3
    ), "Harborview keeps its two seeded areas plus the accepted A-01"
    assert (
        _total_count(api_client.list_study_schools(riverbend["study_id"], PLANNER)) == 2
    ), "the rejected duplicate school must not have been persisted"


# ---------------------------------------------------------------------------
# Single-study referential integrity
# ---------------------------------------------------------------------------
def test_references_that_span_two_studies_are_rejected():
    """Both referenced rows exist, yet a reference that straddles two studies is refused.

    PRD: "Any request whose references straddle two studies is rejected with
    `ERR_CROSS_STUDY_REFERENCE` (HTTP 422): a planning area whose school of record
    belongs to another study, two adjacency endpoints in different studies, a scenario
    whose projection run belongs to another study, an assignment whose area and school
    do not share the scenario's study, a program placement naming a school outside the
    scenario's study, an adoption whose scenario belongs to another study, and a
    variance observation naming a school outside the adoption's study."

    Design: Corner/validations/references_that_span_two_studies_are_rejected
    """
    riverbend = _riverbend_setup_phase()
    harborview = _harborview_setup_phase()
    a1_id = riverbend["area_ids"]["A-01"]
    g1_id = harborview["area_ids"]["H-01"]

    foreign_school_of_record = api_client.create_planning_area(
        create_planning_area_payload(
            riverbend["study_id"],
            harborview["school_ids"]["Quay Elementary"],
            [
                travel_option(riverbend["school_ids"]["Cedar Elementary"], 1.1, 13, True),
                travel_option(riverbend["school_ids"]["Birch Elementary"], 0.7, 11, True),
            ],
            area_code="A-09",
            resident_student_count=100,
            frl_student_count=20,
            ell_student_count=5,
            median_household_income_usd=88000,
            annual_absorption_cap_units=100,
        ),
        PLANNER,
    )
    validate_error(foreign_school_of_record, ApiErrorId.ERR_CROSS_STUDY_REFERENCE.value)

    foreign_edge = api_client.create_area_adjacency(
        {
            "area_id": a1_id,
            "neighbor_area_id": g1_id,
            "shared_boundary_length_ft": 3300,
        },
        PLANNER,
    )
    validate_error(foreign_edge, ApiErrorId.ERR_CROSS_STUDY_REFERENCE.value)

    assert (
        _total_count(
            api_client.list_planning_areas(PLANNER, {"study_id": riverbend["study_id"]})
        )
        == 3
    ), "no A-09 row may have been created"

    riverbend_edges, _ = validate_paginated(api_client.list_area_adjacencies(a1_id, PLANNER))
    assert all(
        g1_id not in (row["area_id"], row["neighbor_area_id"]) for row in riverbend_edges
    ), "no cross-study edge may appear on A-01"
    harborview_edges, _ = validate_paginated(
        api_client.list_area_adjacencies(g1_id, PLANNER)
    )
    assert all(
        a1_id not in (row["area_id"], row["neighbor_area_id"]) for row in harborview_edges
    ), "no mirror row may have been minted on H-01"


# ---------------------------------------------------------------------------
# Temporal gates
# ---------------------------------------------------------------------------
def test_activation_is_refused_before_the_effective_instant_and_succeeds_at_it():
    """Activation is strictly gated: one second short fails, the instant itself succeeds.

    PRD: "Activation requires `implementation_status` to be `PENDING_EFFECTIVE`
    (`ERR_ADOPTION_STATE_INVALID`), the adopted scenario to be in `ADOPTED`, and the
    logical clock to have reached the `effective_date` — an attempt while the clock is
    strictly before that instant is rejected with `ERR_EFFECTIVE_DATE_NOT_REACHED`, and
    an attempt at exactly that instant succeeds."

    Design: Corner/validations/activate_before_the_effective_date_is_rejected_and_succeeds_at_the_instant
    """
    ctx = riverbend_adopted()
    adoption_id = ctx["adoption_id"]

    validate_error(
        api_client.activate_adoption(adoption_id, OFFICER),
        ApiErrorId.ERR_EFFECTIVE_DATE_NOT_REACHED.value,
    )

    set_clock("2027-06-30T23:59:59Z", headers=OFFICER)
    validate_error(
        api_client.activate_adoption(adoption_id, OFFICER),
        ApiErrorId.ERR_EFFECTIVE_DATE_NOT_REACHED.value,
    )

    pending = validate_success(api_client.get_adoption(adoption_id, OFFICER))
    assert pending["implementation_status"] == "PENDING_EFFECTIVE", (
        "a refused activation leaves the implementation dimension untouched, got "
        f"{pending['implementation_status']!r}"
    )
    untouched_area = validate_success(api_client.get_planning_area(ctx["a1_id"], PLANNER))
    assert untouched_area["previous_school_id"] is None, (
        "previous_school_id is written only by the activation cascade, got "
        f"{untouched_area['previous_school_id']!r}"
    )

    set_clock("2027-07-01T00:00:00Z", headers=OFFICER)
    activated = validate_success(api_client.activate_adoption(adoption_id, OFFICER))
    assert activated["implementation_status"] == "IN_EFFECT", (
        f"activation at the effective instant must succeed, got {activated['implementation_status']!r}"
    )

    area = validate_success(api_client.get_planning_area(ctx["a1_id"], PLANNER))
    assert area["previous_school_id"] == ctx["cedar_id"], (
        "A-01's outgoing school of record is Cedar Elementary"
    )
    assert area["current_school_id"] == ctx["cedar_id"], (
        "the adopted scenario keeps A-01 at Cedar Elementary"
    )

    study = validate_success(api_client.get_study(ctx["study_id"], PLANNER))
    assert study["enrolled_of_record_total"] == 650, (
        f"Expected enrolled_of_record_total 650, got {study['enrolled_of_record_total']}"
    )


def test_transfer_request_at_the_deadline_is_accepted_and_one_second_later_is_not():
    """The deadline gate is strict, and it never closes the transfer-window dimension.

    PRD: "Intake is gated twice over: a request filed when the logical clock is strictly
    after the adoption's `transfer_deadline_date` is rejected with
    `ERR_TRANSFER_WINDOW_EXPIRED`, and a request filed once `transfer_window_status` is
    `TRANSFER_WINDOW_CLOSED` is rejected with `ERR_TRANSFER_WINDOW_CLOSED` regardless of
    the deadline date."

    Design: Corner/validations/transfer_request_filed_after_the_deadline_is_rejected
    """
    ctx = riverbend_adopted()
    guardian = make_guardian_headers("guardian-5")
    set_clock("2027-08-15T00:00:00Z", headers=guardian)

    at_deadline = validate_success(
        api_client.create_transfer_request(
            create_transfer_request_payload(
                ctx["adoption_id"],
                ctx["a3_id"],
                ctx["cedar_id"],
                student_reference="STU-401",
                student_grade=4,
                reason="HARDSHIP",
            ),
            guardian,
        ),
        201,
    )
    assert at_deadline["status"] == "SUBMITTED", (
        f"a new request sits in SUBMITTED, got {at_deadline['status']!r}"
    )
    assert at_deadline["resolved_reason"] == "HARDSHIP_REVIEW", (
        "reason HARDSHIP resolves at the fourth rung of the waterfall, got "
        f"{at_deadline['resolved_reason']!r}"
    )
    assert at_deadline["consumes_seat_pool"] is True, (
        "a HARDSHIP_REVIEW entitlement consumes a seat"
    )

    set_clock("2027-08-15T00:00:01Z", headers=guardian)
    validate_error(
        api_client.create_transfer_request(
            create_transfer_request_payload(
                ctx["adoption_id"],
                ctx["a3_id"],
                ctx["cedar_id"],
                student_reference="STU-402",
                student_grade=4,
                reason="HARDSHIP",
            ),
            guardian,
        ),
        ApiErrorId.ERR_TRANSFER_WINDOW_EXPIRED.value,
    )

    adoption = validate_success(api_client.get_adoption(ctx["adoption_id"], OFFICER))
    assert adoption["transfer_window_status"] == "TRANSFER_WINDOW_OPEN", (
        "the deadline rule never moves the window dimension, got "
        f"{adoption['transfer_window_status']!r}"
    )
    assert (
        _total_count(
            api_client.list_transfer_requests(
                OFFICER, {"adoption_id": ctx["adoption_id"]}
            )
        )
        == 1
    ), "only the request filed at the deadline instant was persisted"


def test_adoption_date_and_school_year_window_must_be_ordered():
    """Three orderings, one error id, and the phase-in endpoint enforces it too.

    PRD: "The date window must be ordered — `transfer_deadline_date` strictly after
    `effective_date`, and `effective_school_year` not below the study's
    `target_school_year` — or the request is rejected with `ERR_INVALID_DATE_WINDOW`."
    PRD: "A `grade_low` above `grade_high` is a malformed request
    (`ERR_INVALID_REQUEST`), and a `sunset_school_year` below the adoption's
    `effective_school_year` is rejected with `ERR_INVALID_DATE_WINDOW`."

    Design: Corner/validations/adoption_date_and_school_year_window_must_be_ordered
    """
    ctx = riverbend_board_ready()
    passing_vote = {
        "regime_years": 3,
        "transfer_cap_pct": 95.0,
        "variance_tolerance_pct": 5.0,
        "votes_for": 5,
        "votes_against": 2,
        "votes_abstain": 0,
        "board_member_count": 7,
    }

    deadline_not_after = api_client.create_adoption(
        create_adoption_payload(
            ctx["study_id"],
            ctx["scenario_id"],
            effective_date="2027-07-01T00:00:00Z",
            effective_school_year=2028,
            transfer_deadline_date="2027-07-01T00:00:00Z",
            **passing_vote,
        ),
        BOARD,
    )
    validate_error(deadline_not_after, ApiErrorId.ERR_INVALID_DATE_WINDOW.value)

    year_below_target = api_client.create_adoption(
        create_adoption_payload(
            ctx["study_id"],
            ctx["scenario_id"],
            effective_date="2027-07-01T00:00:00Z",
            effective_school_year=2027,
            transfer_deadline_date="2027-08-15T00:00:00Z",
            **passing_vote,
        ),
        BOARD,
    )
    validate_error(year_below_target, ApiErrorId.ERR_INVALID_DATE_WINDOW.value)

    scenario = validate_success(api_client.get_scenario(ctx["scenario_id"], BOARD))
    assert scenario["status"] == "BOARD_READY", (
        f"a refused vote leaves the scenario board-ready, got {scenario['status']!r}"
    )
    assert (
        _total_count(api_client.list_adoptions(BOARD, {"study_id": ctx["study_id"]})) == 0
    ), "neither refused adoption may have been persisted"

    adoption = validate_success(
        api_client.create_adoption(
            create_adoption_payload(
                ctx["study_id"],
                ctx["scenario_id"],
                effective_date="2027-07-01T00:00:00Z",
                effective_school_year=2028,
                transfer_deadline_date="2027-08-15T00:00:00Z",
                **passing_vote,
            ),
            BOARD,
        ),
        201,
    )
    assert adoption["effective_school_year"] == 2028, (
        f"Expected effective_school_year 2028, got {adoption['effective_school_year']}"
    )

    early_sunset = api_client.create_phase_in_rule(
        adoption["id"],
        create_phase_in_rule_payload(
            rule_type="PHASE_IN_GRADE_BAND",
            grade_low=1,
            grade_high=3,
            sunset_school_year=2027,
        ),
        BOARD,
    )
    validate_error(early_sunset, ApiErrorId.ERR_INVALID_DATE_WINDOW.value)
    assert _total_count(api_client.list_phase_in_rules(adoption["id"], BOARD)) == 0, (
        "the refused rule may not have been persisted"
    )


# ---------------------------------------------------------------------------
# Derived capacity
# ---------------------------------------------------------------------------
def test_portables_flag_of_the_parent_study_conditions_effective_capacity():
    """Identical school payloads land on different effective capacities under the two studies.

    PRD: "On creation the server computes `effective_capacity_seats` as
    `core_capacity_seats` plus, only when the study's `portables_count_toward_capacity`
    is true, `portable_capacity_seats`; otherwise the portable seats are ignored
    entirely."

    Design: Corner/validations/portables_flag_conditions_effective_capacity
    """
    set_clock(RIVERBEND_CLOCK)
    counted_study = create_study(
        name="Portables Counted Study",
        district_name="Eastmere USD",
        target_school_year=2029,
        horizon_years=5,
        capacity_target_low_pct=85.0,
        capacity_target_high_pct=100.0,
        portables_count_toward_capacity=True,
        required_program_types=[],
    )
    alder = create_school(
        counted_study["id"],
        name="Alder Elementary",
        level="ELEMENTARY",
        core_capacity_seats=500,
        portable_capacity_seats=40,
    )
    ignored_study = create_study(
        name="Portables Ignored Study",
        district_name="Eastmere USD",
        target_school_year=2029,
        horizon_years=5,
        capacity_target_low_pct=85.0,
        capacity_target_high_pct=100.0,
        portables_count_toward_capacity=False,
        required_program_types=[],
    )

    fir = validate_success(
        api_client.create_school(
            ignored_study["id"],
            {
                "name": "Fir Elementary",
                "level": "ELEMENTARY",
                "core_capacity_seats": 500,
                "portable_capacity_seats": 40,
            },
            PLANNER,
        ),
        201,
    )

    assert alder["effective_capacity_seats"] == 540, (
        "Alder's study counts portables, so 500 + 40, got "
        f"{alder['effective_capacity_seats']}"
    )
    assert fir["effective_capacity_seats"] == 500, (
        "Fir's study ignores portables, so the 40 relocatable seats drop out, got "
        f"{fir['effective_capacity_seats']}"
    )
    assert fir["portable_capacity_seats"] == 40, (
        "the supplied portable seat count is still stored verbatim"
    )
    assert alder["enrolled_students_of_record"] == 0
    assert fir["enrolled_students_of_record"] == 0


# ---------------------------------------------------------------------------
# The seed-data lock
# ---------------------------------------------------------------------------
def test_every_seed_inventory_create_after_the_lock_is_refused():
    """One rule guards three creates, and it runs ahead of the uniqueness check.

    PRD: "From that moment the three seed-creation operations — adding a school to the
    study, registering a planning area and declaring an adjacency — are frozen and
    answer `ERR_STUDY_DATA_LOCKED`."

    Design: Corner/validations/seed_inventory_creates_after_lock_are_all_rejected
    """
    ctx = riverbend_locked()

    duplicate_named_school = api_client.create_school(
        ctx["study_id"],
        {"name": "Cedar Elementary", "level": "ELEMENTARY", "core_capacity_seats": 300},
        PLANNER,
    )
    validate_error(duplicate_named_school, ApiErrorId.ERR_STUDY_DATA_LOCKED.value)

    fourth_area = api_client.create_planning_area(
        create_planning_area_payload(
            ctx["study_id"],
            ctx["birch_id"],
            [
                travel_option(ctx["cedar_id"], 1.2, 14, True),
                travel_option(ctx["birch_id"], 0.5, 9, True),
            ],
            area_code="A-04",
            resident_student_count=80,
            frl_student_count=10,
            ell_student_count=4,
            median_household_income_usd=91000,
            annual_absorption_cap_units=100,
        ),
        PLANNER,
    )
    validate_error(fourth_area, ApiErrorId.ERR_STUDY_DATA_LOCKED.value)

    missing_edge = api_client.create_area_adjacency(
        {
            "area_id": ctx["a1_id"],
            "neighbor_area_id": ctx["a3_id"],
            "shared_boundary_length_ft": 3100,
        },
        PLANNER,
    )
    validate_error(missing_edge, ApiErrorId.ERR_STUDY_DATA_LOCKED.value)

    assert _total_count(api_client.list_study_schools(ctx["study_id"], PLANNER)) == 2
    assert (
        _total_count(api_client.list_planning_areas(PLANNER, {"study_id": ctx["study_id"]}))
        == 3
    )
    edges, _ = validate_paginated(api_client.list_area_adjacencies(ctx["a1_id"], PLANNER))
    assert all(
        ctx["a3_id"] not in (row["area_id"], row["neighbor_area_id"]) for row in edges
    ), "the refused A-01 to A-03 edge must not appear in either direction"

    patched = validate_success(
        api_client.patch_school(ctx["cedar_id"], {"portable_capacity_seats": 50}, PLANNER)
    )
    assert patched["portable_capacity_seats"] == 50, (
        "adjusting an existing school is not one of the frozen operations"
    )
    assert patched["effective_capacity_seats"] == 550, (
        f"Expected recomputed effective_capacity_seats 550, got {patched['effective_capacity_seats']}"
    )


# ---------------------------------------------------------------------------
# Assignment guards in precedence order
# ---------------------------------------------------------------------------
def test_mothballed_school_masks_the_missing_travel_option_on_assignment():
    """Reviving the school removes the state objection and exposes the referential one.

    PRD: "The school must not be `MOTHBALLED` (`ERR_SCHOOL_NOT_ACTIVE`)."
    PRD: "The area's `travel_options` must contain an entry whose `school_id` is the
    assigned school, because without it walkability and ride time for the pair are
    unknown; a missing entry is rejected with `ERR_TRAVEL_OPTION_MISSING`."
    PRD: "Checks are evaluated in the following order, and the first failing check
    wins:" — with "11. **Referenced-record state** — `ERR_SCHOOL_NOT_ACTIVE` and
    `ERR_COMMENT_STATE_INVALID`." ahead of "16. **Referential business rules** —
    `ERR_TRAVEL_OPTION_MISSING`, then `ERR_SCHOOL_LEVEL_MISMATCH`, then
    `ERR_CROSS_STUDY_REFERENCE`, `ERR_SELF_ADJACENCY` and
    `ERR_PROGRAM_HOST_INCAPABLE`, then `ERR_SIBLING_LINK_INVALID`."

    Design: Corner/validations/assignment_to_a_mothballed_then_optionless_school_is_rejected_in_priority_order
    """
    ctx = setup_study_with_inventory(
        school_payloads=RIVERBEND_SCHOOLS
        + (
            {
                "name": "Spruce Elementary",
                "level": "ELEMENTARY",
                "core_capacity_seats": 300,
                "status": "MOTHBALLED",
            },
        ),
        area_builders=_riverbend_area_builders(),
        adjacency_specs=(("A-01", "A-02", 5200), ("A-02", "A-03", 4100)),
        clock=RIVERBEND_CLOCK,
        lock=True,
    )
    study_id = ctx["study_id"]
    cedar_id = ctx["school_ids"]["Cedar Elementary"]
    spruce_id = ctx["school_ids"]["Spruce Elementary"]
    a2_id = ctx["area_ids"]["A-02"]

    run = create_projection_run(study_id, variant="COHORT_SURVIVAL")
    scenario = create_scenario(
        study_id, run["id"], [program_placement(cedar_id, 30)]
    )
    assign_area(scenario["id"], ctx["area_ids"]["A-01"], cedar_id)
    pinned_version = scenario_version(scenario["id"])

    mothballed_attempt = api_client.create_assignment(
        {
            "scenario_id": scenario["id"],
            "area_id": a2_id,
            "assigned_school_id": spruce_id,
            "expected_scenario_version": pinned_version,
        },
        PLANNER,
    )
    validate_error(mothballed_attempt, ApiErrorId.ERR_SCHOOL_NOT_ACTIVE.value)

    revived = validate_success(
        api_client.patch_school(spruce_id, {"status": "ACTIVE"}, PLANNER)
    )
    assert revived["status"] == "ACTIVE", (
        f"Expected Spruce to be revived to ACTIVE, got {revived['status']!r}"
    )

    optionless_attempt = api_client.create_assignment(
        {
            "scenario_id": scenario["id"],
            "area_id": a2_id,
            "assigned_school_id": spruce_id,
            "expected_scenario_version": pinned_version,
        },
        PLANNER,
    )
    validate_error(optionless_attempt, ApiErrorId.ERR_TRAVEL_OPTION_MISSING.value)

    assert scenario_version(scenario["id"]) == pinned_version, (
        "neither refusal may increment the parent scenario's version"
    )
    assert (
        _total_count(api_client.list_assignments(PLANNER, {"scenario_id": scenario["id"]}))
        == 1
    ), "only the A-01 assignment exists"
    assert (
        _total_count(
            api_client.list_study_schools(study_id, PLANNER, {"status": "ACTIVE"})
        )
        == 3
    ), "Cedar, Birch and the revived Spruce are all ACTIVE"


# ---------------------------------------------------------------------------
# The submit-for-review structural gate
# ---------------------------------------------------------------------------
def test_submit_for_review_requires_every_area_assigned_exactly_once():
    """An incomplete partition is refused, and the same submit succeeds once repaired.

    PRD: "First, the scenario must partition the study exactly: every planning area of
    the study must have exactly one non-superseded assignment in this scenario — none
    unassigned, none assigned twice — or the submission is rejected with
    `ERR_AREA_UNASSIGNED`."

    Design: Corner/validations/submit_for_review_requires_every_area_assigned_exactly_once
    """
    ctx = riverbend_scenario_draft()
    scenario_id = ctx["scenario_id"]
    assign_area(scenario_id, ctx["a1_id"], ctx["cedar_id"])
    assign_area(scenario_id, ctx["a2_id"], ctx["cedar_id"])

    validate_error(
        api_client.submit_scenario_for_review(scenario_id, PLANNER),
        ApiErrorId.ERR_AREA_UNASSIGNED.value,
    )

    refused = validate_success(api_client.get_scenario(scenario_id, PLANNER))
    assert refused["status"] == "DRAFT", (
        f"a refused submission leaves the scenario in DRAFT, got {refused['status']!r}"
    )
    assert refused["total_assigned_students"] == 0, (
        "no score is persisted by a refused submission, got "
        f"{refused['total_assigned_students']}"
    )

    assign_area(scenario_id, ctx["a3_id"], ctx["birch_id"])
    rows, meta = validate_paginated(
        api_client.list_assignments(PLANNER, {"scenario_id": scenario_id})
    )
    assert meta["total_count"] == 3, (
        f"Expected three assignments after the repair, got {meta['total_count']}"
    )
    assert all(row["is_superseded"] is False for row in rows), (
        "no assignment was superseded, so all three are live"
    )

    submitted = validate_success(
        api_client.submit_scenario_for_review(scenario_id, PLANNER)
    )
    assert submitted["status"] == "UNDER_REVIEW", (
        f"Expected UNDER_REVIEW after the repaired submit, got {submitted['status']!r}"
    )
    assert submitted["total_assigned_students"] == 588, (
        f"Expected total_assigned_students 588, got {submitted['total_assigned_students']}"
    )
    assert submitted["max_utilization_pct"] == pytest.approx(89.26, abs=0.01), (
        f"Expected max_utilization_pct 89.26, got {submitted['max_utilization_pct']}"
    )
    assert submitted["contiguity_ok"] is True
    assert submitted["noncontiguous_school_ids"] == []


def test_required_program_placed_twice_blocks_submit_for_review():
    """Too many placements violate the count rule just as surely as too few.

    PRD: "Then program placement is checked in two ways: every member of the study's
    `required_program_types` must appear exactly once across the scenario's
    `program_placements`, and appearing zero times or more than once is rejected with
    `ERR_PROGRAM_PLACEMENT_INCOMPLETE`; and every school named by a placement must
    itself have at least one non-superseded assignment in the scenario, since a host
    school with no attendance area has no students to draw from, which is rejected with
    `ERR_PROGRAM_HOST_UNASSIGNED`."

    Design: Corner/validations/required_program_placed_twice_blocks_submit_for_review
    """
    ctx = riverbend_scenario_assigned()
    scenario_id = ctx["scenario_id"]

    replaced = replace_program_placements(
        scenario_id,
        [
            program_placement(ctx["cedar_id"], 18),
            program_placement(ctx["cedar_id"], 12),
        ],
    )
    assert len(replaced["program_placements"]) == 2, (
        "the replacement itself is legal and stores both entries, got "
        f"{len(replaced['program_placements'])}"
    )

    validate_error(
        api_client.submit_scenario_for_review(scenario_id, PLANNER),
        ApiErrorId.ERR_PROGRAM_PLACEMENT_INCOMPLETE.value,
    )

    scenario = validate_success(api_client.get_scenario(scenario_id, PLANNER))
    assert scenario["status"] == "DRAFT", (
        f"a refused submission leaves the scenario in DRAFT, got {scenario['status']!r}"
    )
    assert scenario["max_utilization_pct"] == pytest.approx(0.00, abs=0.01), (
        "utilization is persisted only by a successful submission, got "
        f"{scenario['max_utilization_pct']}"
    )
    assert scenario["revision_round"] == 0
    assert scenario["revision_reason"] is None


def test_program_host_without_an_assigned_area_blocks_submit_for_review():
    """A capable host that draws from no attendance area still fails the structural gate.

    PRD: "Then program placement is checked in two ways: every member of the study's
    `required_program_types` must appear exactly once across the scenario's
    `program_placements`, and appearing zero times or more than once is rejected with
    `ERR_PROGRAM_PLACEMENT_INCOMPLETE`; and every school named by a placement must
    itself have at least one non-superseded assignment in the scenario, since a host
    school with no attendance area has no students to draw from, which is rejected with
    `ERR_PROGRAM_HOST_UNASSIGNED`."

    Design: Corner/validations/program_host_without_an_assigned_area_blocks_submit_for_review
    """
    ctx = riverbend_scenario_draft()
    scenario_id = ctx["scenario_id"]
    assign_area(scenario_id, ctx["a1_id"], ctx["cedar_id"])
    assign_area(scenario_id, ctx["a2_id"], ctx["cedar_id"])
    assign_area(scenario_id, ctx["a3_id"], ctx["cedar_id"])

    capable_birch = validate_success(
        api_client.patch_school(
            ctx["birch_id"], {"program_types": ["DUAL_LANGUAGE"]}, PLANNER
        )
    )
    assert "DUAL_LANGUAGE" in capable_birch["program_types"], (
        "Birch must be able to host the program so the capability rule cannot fire"
    )

    replaced = replace_program_placements(
        scenario_id, [program_placement(ctx["birch_id"], 30)]
    )
    assert [entry["school_id"] for entry in replaced["program_placements"]] == [
        ctx["birch_id"]
    ], "the single placement now names Birch Elementary"

    validate_error(
        api_client.submit_scenario_for_review(scenario_id, PLANNER),
        ApiErrorId.ERR_PROGRAM_HOST_UNASSIGNED.value,
    )

    scenario = validate_success(api_client.get_scenario(scenario_id, PLANNER))
    assert scenario["status"] == "DRAFT", (
        f"a refused submission leaves the scenario in DRAFT, got {scenario['status']!r}"
    )
    assert scenario["total_assigned_students"] == 0, (
        "no score is persisted by a refused submission, got "
        f"{scenario['total_assigned_students']}"
    )
    assert (
        _total_count(
            api_client.list_assignments(
                PLANNER,
                {"scenario_id": scenario_id, "assigned_school_id": ctx["birch_id"]},
            )
        )
        == 0
    ), "Birch holds no attendance area under this scenario"


def test_scenario_satisfying_every_submit_time_rule_clears_the_review_gate():
    """The positive control for the whole submit gate, with every objective score persisted.

    PRD: "On success the scenario's `status` becomes `UNDER_REVIEW`, all four
    calculations are persisted, and its `version` is incremented."
    PRD: "Those per-assignment costs are accumulated **unrounded**, and only the
    accumulated scenario total is rounded half up to 2 decimal places, exactly once, to
    give `transport_cost_annual_usd`."

    Design: Corner/validations/scenario_satisfying_every_submit_time_rule_clears_the_review_gate
    """
    ctx = riverbend_scenario_assigned()
    scenario_id = ctx["scenario_id"]

    submitted = validate_success(
        api_client.submit_scenario_for_review(scenario_id, PLANNER)
    )
    assert submitted["status"] == "UNDER_REVIEW", (
        f"Expected UNDER_REVIEW, got {submitted['status']!r}"
    )
    assert submitted["revision_round"] == 0
    assert submitted["revision_reason"] is None

    analysis = validate_success(api_client.get_impact_analysis(scenario_id, PLANNER))
    assert analysis["total_assigned_students"] == 588, (
        f"Expected total_assigned_students 588, got {analysis['total_assigned_students']}"
    )
    assert analysis["max_utilization_pct"] == pytest.approx(89.26, abs=0.01), (
        f"Expected max_utilization_pct 89.26, got {analysis['max_utilization_pct']}"
    )
    assert analysis["contiguity_ok"] is True
    assert analysis["noncontiguous_school_ids"] == []
    assert analysis["critical_school_ids"] == [], (
        "no school reaches the 110.00 percent critical ceiling"
    )
    assert analysis["walk_eligible_pct"] == pytest.approx(69.22, abs=0.01), (
        f"Expected walk_eligible_pct 69.22, got {analysis['walk_eligible_pct']}"
    )
    assert analysis["transport_cost_annual_usd"] == pytest.approx(66285.00, abs=0.01), (
        f"Expected transport_cost_annual_usd 66285.00, got {analysis['transport_cost_annual_usd']}"
    )
    assert analysis["frl_dissimilarity_index"] == pytest.approx(0.1427, abs=0.0001), (
        f"Expected frl_dissimilarity_index 0.1427, got {analysis['frl_dissimilarity_index']}"
    )

    study = validate_success(api_client.get_study(ctx["study_id"], PLANNER))
    assert study["status"] == "SCENARIO_DEVELOPMENT", (
        f"submitting a scenario does not move the study phase, got {study['status']!r}"
    )


# ---------------------------------------------------------------------------
# Engagement gate on a different entity's state
# ---------------------------------------------------------------------------
def test_untriaged_comment_blocks_the_board_reading():
    """One comment still in SUBMITTED refuses the certification; triaging it clears the way.

    PRD: "It requires the study to be in `ENGAGEMENT`, the scenario to be in
    `UNDER_REVIEW` (`ERR_SCENARIO_NOT_REVIEWABLE`), the scenario's `projection_stale` to
    be false (`ERR_PROJECTION_STALE`), and the public record to be clean: no comment of
    that scenario may still be in `SUBMITTED`, since every comment must be triaged or
    dismissed before the board reads the map, and an untriaged comment is rejected with
    `ERR_UNADDRESSED_COMMENTS`."

    Design: Corner/validations/untriaged_comment_blocks_the_board_reading
    """
    ctx = riverbend_engagement_open()
    scenario_id = ctx["scenario_id"]
    comment = get_success_data(
        api_client.create_comment(
            {
                "scenario_id": scenario_id,
                "area_id": ctx["a1_id"],
                "body": "Please keep A-01 at Cedar.",
            },
            make_guardian_headers("guardian-7"),
        ),
        201,
    )

    validate_error(
        api_client.advance_scenario_to_board(scenario_id, COORDINATOR),
        ApiErrorId.ERR_UNADDRESSED_COMMENTS.value,
    )

    blocked = validate_success(api_client.get_scenario(scenario_id, COORDINATOR))
    assert blocked["status"] == "UNDER_REVIEW", (
        f"a refused certification leaves the scenario under review, got {blocked['status']!r}"
    )
    blocked_study = validate_success(api_client.get_study(ctx["study_id"], COORDINATOR))
    assert blocked_study["status"] == "ENGAGEMENT", (
        f"the study stays in ENGAGEMENT, got {blocked_study['status']!r}"
    )

    triaged = validate_success(
        api_client.triage_comment(
            comment["id"], {"theme": "CAPACITY", "priority": "LOW"}, COORDINATOR
        )
    )
    assert triaged["status"] == "TRIAGED", (
        f"Expected TRIAGED, got {triaged['status']!r}"
    )
    assert triaged["theme"] == "CAPACITY"
    assert triaged["priority"] == "LOW"

    certified = validate_success(
        api_client.advance_scenario_to_board(scenario_id, COORDINATOR)
    )
    assert certified["status"] == "BOARD_READY", (
        f"Expected BOARD_READY once the record is clean, got {certified['status']!r}"
    )

    study = validate_success(api_client.get_study(ctx["study_id"], COORDINATOR))
    assert study["status"] == "BOARD_DECISION", (
        f"Expected BOARD_DECISION, got {study['status']!r}"
    )
    assert study["comment_intake_open"] is False, (
        "certifying the scenario closes intake for the reading"
    )
    assert (
        _total_count(
            api_client.list_comments(
                COORDINATOR, {"scenario_id": scenario_id, "status": "SUBMITTED"}
            )
        )
        == 0
    ), "no comment of the scenario remains in SUBMITTED"
