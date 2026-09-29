"""Corner cases in the redistricting service's derived calculations."""

import pytest

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    advance_entitlement,
    api_client,
    assign_areas,
    create_adoption_payload,
    create_housing_development,
    create_phase_in_rule_payload,
    create_projection_run,
    create_scenario,
    create_transfer_request,
    create_variance_observation_payload,
    make_guardian_headers,
    program_placement,
    riverbend_board_ready,
    riverbend_adopted,
    riverbend_locked,
    riverbend_scenario_assigned,
    riverbend_scenario_draft,
    set_clock,
    setup_study_with_inventory,
    travel_option,
)

PLANNER = TEST_USERS["planner_headers"]
BOARD = TEST_USERS["board_headers"]
OFFICER = TEST_USERS["officer_headers"]


def _projection_entry(run, area_id):
    """Pick the area_projections entry of ``run`` belonging to ``area_id``."""
    matches = [
        entry for entry in run["area_projections"] if entry["area_id"] == area_id
    ]
    assert len(matches) == 1, f"expected exactly one projection entry for {area_id}"
    return matches[0]


# ---------------------------------------------------------------------------
# Capacity utilization
# ---------------------------------------------------------------------------
def test_utilization_counts_program_seats_over_effective_capacity():
    """Cedar's utilization folds in its 30 program seats and its portable seats.

    PRD 3.5: "Its load under a scenario is the sum of `projected_students` over
    the scenario's non-superseded assignments pointing at it, plus the sum of
    `seats` over the scenario's `program_placements` entries naming it."
    PRD 3.5: "A school's effective capacity is its `core_capacity_seats` plus,
    only when the study's `portables_count_toward_capacity` is true, its
    `portable_capacity_seats`."

    Cedar holds A-01 (271) and A-02 (181) plus 30 DUAL_LANGUAGE seats against
    500 core + 40 portable = 540 effective seats, so 100 * 482 / 540 = 89.26.
    Birch holds A-03 (136) against 400 seats, well under the maximum.

    Design: Corner/calculations/capacity_utilization_counts_program_seats_over_effective_capacity
    """
    ctx = riverbend_scenario_assigned()

    cedar = validate_success(api_client.get_school(ctx["cedar_id"], PLANNER))
    birch = validate_success(api_client.get_school(ctx["birch_id"], PLANNER))
    assert cedar["effective_capacity_seats"] == 540, (
        "Cedar counts its 40 portable seats because the study counts portables"
    )
    assert birch["effective_capacity_seats"] == 400, (
        "Birch has no portable seats, so effective capacity is its core capacity"
    )

    submitted = validate_success(
        api_client.submit_scenario_for_review(ctx["scenario_id"], PLANNER)
    )
    assert submitted["status"] == "UNDER_REVIEW", (
        "a scenario at 89.26 percent is nowhere near the critical ceiling"
    )
    assert submitted["total_assigned_students"] == 588, (
        "271 + 181 + 136 projected students are assigned"
    )
    assert submitted["max_utilization_pct"] == pytest.approx(89.26, abs=0.01), (
        "100 * (452 students + 30 program seats) / 540 effective seats = 89.26"
    )

    analysis = validate_success(
        api_client.get_impact_analysis(ctx["scenario_id"], PLANNER)
    )
    assert analysis["max_utilization_pct"] == pytest.approx(89.26, abs=0.01), (
        "the computed read reproduces the stored utilization maximum"
    )
    assert analysis["critical_school_ids"] == [], (
        "no ACTIVE school reaches the 110.00 percent critical ceiling"
    )
    assert analysis["contiguity_ok"] is True, (
        "Cedar holds the adjacent pair A-01 / A-02 and Birch holds A-03 alone"
    )


def test_utilization_one_seat_below_the_critical_threshold_is_accepted():
    """109.78 percent is below the ceiling, so the submission is accepted.

    PRD 3.5: "A submission whose `max_utilization_pct` reaches or exceeds 110.00
    is rejected with `ERR_SCHOOL_CAPACITY_CRITICAL`."

    Aspen carries 271 + 271 projected students plus 8 program seats = 550. With
    `portables_count_toward_capacity` false its 60 portable seats are ignored, so
    raising `core_capacity_seats` from 500 to 501 gives an effective capacity of
    501 and 100 * 550 / 501 = 109.78, one notch under the 110.00 ceiling.

    Design: Corner/calculations/utilization_one_seat_below_the_critical_threshold_is_accepted
    """

    def e01(school_ids):
        return {
            "area_code": "E-01",
            "grade_band": "ELEMENTARY",
            "current_school_id": school_ids["Aspen Elementary"],
            "resident_student_count": 300,
            "frl_student_count": 90,
            "ell_student_count": 30,
            "median_household_income_usd": 72000,
            "annual_absorption_cap_units": 200,
            "travel_options": [
                travel_option(school_ids["Aspen Elementary"], 0.5, 10, True),
                travel_option(school_ids["Larch Elementary"], 2.4, 24, False),
            ],
        }

    def e02(school_ids):
        return {
            "area_code": "E-02",
            "grade_band": "ELEMENTARY",
            "current_school_id": school_ids["Aspen Elementary"],
            "resident_student_count": 300,
            "frl_student_count": 80,
            "ell_student_count": 25,
            "median_household_income_usd": 76000,
            "annual_absorption_cap_units": 200,
            "travel_options": [
                travel_option(school_ids["Aspen Elementary"], 0.6, 11, True),
                travel_option(school_ids["Larch Elementary"], 1.9, 20, False),
            ],
        }

    def e03(school_ids):
        return {
            "area_code": "E-03",
            "grade_band": "ELEMENTARY",
            "current_school_id": school_ids["Larch Elementary"],
            "resident_student_count": 100,
            "frl_student_count": 20,
            "ell_student_count": 5,
            "median_household_income_usd": 98000,
            "annual_absorption_cap_units": 200,
            "travel_options": [
                travel_option(school_ids["Aspen Elementary"], 2.6, 25, False),
                travel_option(school_ids["Larch Elementary"], 0.5, 9, True),
            ],
        }

    ctx = setup_study_with_inventory(
        study_payload={
            "name": "2028 Capacity Stress Study",
            "district_name": "Westvale USD",
            "target_school_year": 2028,
            "horizon_years": 5,
            "capacity_target_low_pct": 85.0,
            "capacity_target_high_pct": 100.0,
            "portables_count_toward_capacity": False,
            "required_program_types": ["DUAL_LANGUAGE"],
        },
        school_payloads=(
            {
                "name": "Aspen Elementary",
                "level": "ELEMENTARY",
                "core_capacity_seats": 500,
                "portable_capacity_seats": 60,
                "program_types": ["DUAL_LANGUAGE"],
            },
            {
                "name": "Larch Elementary",
                "level": "ELEMENTARY",
                "core_capacity_seats": 900,
            },
        ),
        area_builders=(e01, e02, e03),
        adjacency_specs=(("E-01", "E-02", 5100), ("E-02", "E-03", 4700)),
    )
    aspen_id = ctx["school_ids"]["Aspen Elementary"]
    larch_id = ctx["school_ids"]["Larch Elementary"]

    run = create_projection_run(ctx["study_id"], variant="COHORT_SURVIVAL")
    scenario = create_scenario(
        ctx["study_id"],
        run["id"],
        [program_placement(aspen_id, 8)],
        name="Stress Corner",
    )
    assign_areas(
        scenario["id"],
        [
            (ctx["area_ids"]["E-01"], aspen_id),
            (ctx["area_ids"]["E-02"], aspen_id),
            (ctx["area_ids"]["E-03"], larch_id),
        ],
    )

    patched = validate_success(
        api_client.patch_school(aspen_id, {"core_capacity_seats": 501}, PLANNER)
    )
    assert patched["effective_capacity_seats"] == 501, (
        "the study does not count portables, so the 60 portable seats stay out"
    )

    submitted = validate_success(
        api_client.submit_scenario_for_review(scenario["id"], PLANNER)
    )
    assert submitted["status"] == "UNDER_REVIEW", (
        "109.78 does not reach 110.00, so ERR_SCHOOL_CAPACITY_CRITICAL must not fire"
    )
    assert submitted["max_utilization_pct"] == pytest.approx(109.78, abs=0.01), (
        "100 * (542 students + 8 program seats) / 501 effective seats = 109.78"
    )
    assert submitted["total_assigned_students"] == 632, (
        "271 + 271 + 90 projected students are assigned"
    )

    analysis = validate_success(api_client.get_impact_analysis(scenario["id"], PLANNER))
    assert analysis["critical_school_ids"] == [], (
        "a school at 109.78 percent is OVER, not CRITICAL"
    )


# ---------------------------------------------------------------------------
# Enrollment projection
# ---------------------------------------------------------------------------
def test_projection_excludes_withdrawn_developments_from_the_pipeline():
    """A withdrawn development contributes nothing to a DEVELOPMENT_WEIGHTED run.

    PRD 3.3: "Under `DEVELOPMENT_WEIGHTED` — the planning-department view used to
    size capacity against the pipeline — every development except a `WITHDRAWN`
    one is admitted, but each is discounted twice."

    A-01 carries Willow Ridge (120 single-family units, PROPOSED) and Cinder Row
    (50 townhomes, withdrawn). Willow Ridge alone contributes
    120 * 0.42 * 0.25 * 1.00 = 12.60 students on top of a base of
    round(300 * 0.98 ** 5) = 271, giving 284 for A-01 and a study total of
    284 + 181 + 136 = 601.

    Design: Corner/calculations/projection_excludes_withdrawn_developments_from_the_pipeline
    """
    ctx = riverbend_locked()

    willow = create_housing_development(
        ctx["a1_id"],
        name="Willow Ridge",
        unit_type="SINGLE_FAMILY",
        total_units=120,
        first_occupancy_date="2027-01-01T00:00:00Z",
        buildout_months=24,
    )
    cinder = create_housing_development(
        ctx["a1_id"],
        name="Cinder Row",
        unit_type="TOWNHOME",
        total_units=50,
        first_occupancy_date="2027-06-01T00:00:00Z",
        buildout_months=12,
    )
    withdrawn = advance_entitlement(cinder["id"], "WITHDRAWN")
    assert withdrawn["entitlement_status"] == "WITHDRAWN", (
        "PROPOSED -> WITHDRAWN is a legal withdrawal edge"
    )
    assert willow["entitlement_status"] == "PROPOSED", (
        "Willow Ridge stays at its opening entitlement stage"
    )

    run = create_projection_run(ctx["study_id"], variant="DEVELOPMENT_WEIGHTED")
    assert run["status"] == "COMPLETE"
    assert run["variant"] == "DEVELOPMENT_WEIGHTED"

    a1 = _projection_entry(run, ctx["a1_id"])
    assert a1["base_students"] == 271, "round_half_up(300 * 0.98 ** 5) == 271"
    assert a1["development_students"] == pytest.approx(12.60, abs=0.01), (
        "only Willow Ridge is admitted: 120 * 0.42 * 0.25 * 1.00 == 12.60"
    )
    assert a1["projected_students"] == 284, "round_half_up(271 + 12.60) == 284"

    a2 = _projection_entry(run, ctx["a2_id"])
    assert a2["development_students"] == pytest.approx(0.00, abs=0.01)
    assert a2["projected_students"] == 181

    a3 = _projection_entry(run, ctx["a3_id"])
    assert a3["development_students"] == pytest.approx(0.00, abs=0.01)
    assert a3["projected_students"] == 136

    assert run["projected_total_students"] == 601, (
        "284 + 181 + 136 == 601; counting the withdrawn townhomes would give more"
    )

    proposed, meta = validate_paginated(
        api_client.list_housing_developments(
            ctx["a1_id"], PLANNER, {"entitlement_status": "PROPOSED"}
        )
    )
    assert meta["total_count"] == 1, "only Willow Ridge is still PROPOSED"
    assert proposed[0]["id"] == willow["id"]


# ---------------------------------------------------------------------------
# Walkability and transportation cost
# ---------------------------------------------------------------------------
def test_walk_eligibility_is_inclusive_at_the_limit_and_needs_a_safe_route():
    """Two areas at exactly 1.0 mile diverge only on has_safe_route.

    PRD 3.5: "The pair is walk-eligible when the entry's `walk_distance_miles` is
    less than or equal to the walk limit for the school's `level` — 1.0 mile for
    `ELEMENTARY`, 1.5 miles for `MIDDLE`, 2.0 miles for `HIGH` — **and** its
    `has_safe_route` is true; a distance exactly equal to the limit is
    walk-eligible."

    W-01 (1.0 mile, safe route) walks and W-03 (0.5 miles, safe route) walks, so
    the walking population is 271 + 90 = 361 of 542 = 66.61 percent. W-02 sits at
    the same 1.0 mile but has no safe route, so its 181 students ride:
    ceil(181 / 71) = 3 buses at max(40, 15) billed minutes gives
    3 * (95.00 + 40 * 1.85) * 180 = 91260.00.

    Design: Corner/calculations/walk_eligibility_is_inclusive_at_the_level_limit_and_needs_a_safe_route
    """

    def w01(school_ids):
        return {
            "area_code": "W-01",
            "grade_band": "ELEMENTARY",
            "current_school_id": school_ids["Ash Elementary"],
            "resident_student_count": 300,
            "frl_student_count": 90,
            "ell_student_count": 30,
            "median_household_income_usd": 70000,
            "annual_absorption_cap_units": 300,
            "travel_options": [
                travel_option(school_ids["Ash Elementary"], 1.0, 30, True),
                travel_option(school_ids["Beech Elementary"], 2.0, 20, False),
            ],
        }

    def w02(school_ids):
        return {
            "area_code": "W-02",
            "grade_band": "ELEMENTARY",
            "current_school_id": school_ids["Ash Elementary"],
            "resident_student_count": 200,
            "frl_student_count": 60,
            "ell_student_count": 20,
            "median_household_income_usd": 74000,
            "annual_absorption_cap_units": 300,
            "travel_options": [
                travel_option(school_ids["Ash Elementary"], 1.0, 40, False),
                travel_option(school_ids["Beech Elementary"], 1.5, 18, True),
            ],
        }

    def w03(school_ids):
        return {
            "area_code": "W-03",
            "grade_band": "ELEMENTARY",
            "current_school_id": school_ids["Beech Elementary"],
            "resident_student_count": 100,
            "frl_student_count": 20,
            "ell_student_count": 5,
            "median_household_income_usd": 99000,
            "annual_absorption_cap_units": 300,
            "travel_options": [
                travel_option(school_ids["Ash Elementary"], 3.0, 26, False),
                travel_option(school_ids["Beech Elementary"], 0.5, 12, True),
            ],
        }

    ctx = setup_study_with_inventory(
        study_payload={
            "name": "2029 Walk Audit Study",
            "district_name": "Millbrook USD",
            "target_school_year": 2029,
            "horizon_years": 5,
            "capacity_target_low_pct": 80.0,
            "capacity_target_high_pct": 100.0,
            "portables_count_toward_capacity": False,
            "required_program_types": ["DUAL_LANGUAGE"],
        },
        school_payloads=(
            {
                "name": "Ash Elementary",
                "level": "ELEMENTARY",
                "core_capacity_seats": 1000,
                "program_types": ["DUAL_LANGUAGE"],
            },
            {
                "name": "Beech Elementary",
                "level": "ELEMENTARY",
                "core_capacity_seats": 1000,
            },
        ),
        area_builders=(w01, w02, w03),
        adjacency_specs=(("W-01", "W-02", 4600), ("W-02", "W-03", 4200)),
    )
    ash_id = ctx["school_ids"]["Ash Elementary"]
    beech_id = ctx["school_ids"]["Beech Elementary"]

    run = create_projection_run(ctx["study_id"], variant="COHORT_SURVIVAL")
    scenario = create_scenario(
        ctx["study_id"],
        run["id"],
        [program_placement(ash_id, 10)],
        name="Walk Draft",
    )
    assign_areas(
        scenario["id"],
        [
            (ctx["area_ids"]["W-01"], ash_id),
            (ctx["area_ids"]["W-02"], ash_id),
            (ctx["area_ids"]["W-03"], beech_id),
        ],
    )

    submitted = validate_success(
        api_client.submit_scenario_for_review(scenario["id"], PLANNER)
    )
    assert submitted["status"] == "UNDER_REVIEW"
    assert submitted["total_assigned_students"] == 542, "271 + 181 + 90 == 542"
    assert submitted["walk_eligible_pct"] == pytest.approx(66.61, abs=0.01), (
        "W-01 walks at exactly the 1.0 mile limit; W-02 has no safe route and rides"
    )
    assert submitted["transport_cost_annual_usd"] == pytest.approx(91260.00, abs=0.01), (
        "3 buses * (95.00 + 40 * 1.85) * 180 school days == 91260.00"
    )
    assert submitted["max_utilization_pct"] == pytest.approx(46.20, abs=0.01), (
        "Ash carries 452 students plus 10 program seats against 1000 seats"
    )

    analysis = validate_success(api_client.get_impact_analysis(scenario["id"], PLANNER))
    assert analysis["walk_eligible_pct"] == pytest.approx(66.61, abs=0.01)
    assert analysis["transport_cost_annual_usd"] == pytest.approx(91260.00, abs=0.01)


# ---------------------------------------------------------------------------
# Contiguity
# ---------------------------------------------------------------------------
def test_contiguity_detects_a_school_split_into_two_components():
    """Cedar holding A-01 and A-03 across the chain is two components.

    PRD 3.5: "Otherwise the traversal starts at the member of that set with the
    earliest `created_at` and walks the graph breadth-first, following an edge
    only when **both** of its endpoints are members of that school's own set; the
    school is contiguous exactly when the traversal reaches every member of the
    set."
    PRD 3.5: "A submission whose evaluation reports `contiguity_ok` false is
    rejected with `ERR_CONTIGUITY_BROKEN`."
    PRD 3.5: "A rejected submission, at any precedence level, leaves `status`,
    `revision_round`, `version` and every stored score field byte-identical to
    their pre-call values."

    The adjacency graph is the chain A-01 - A-02 - A-03. Cedar takes A-01 and
    A-03 while Birch takes A-02, so the only path between Cedar's two areas runs
    through an area Birch owns.

    Design: Corner/calculations/contiguity_detects_a_school_split_into_two_components
    """
    ctx = riverbend_scenario_draft()
    assign_areas(
        ctx["scenario_id"],
        [
            (ctx["a1_id"], ctx["cedar_id"]),
            (ctx["a2_id"], ctx["birch_id"]),
            (ctx["a3_id"], ctx["cedar_id"]),
        ],
    )

    validate_error(
        api_client.submit_scenario_for_review(ctx["scenario_id"], PLANNER),
        ApiErrorId.ERR_CONTIGUITY_BROKEN,
    )

    stored = validate_success(api_client.get_scenario(ctx["scenario_id"], PLANNER))
    assert stored["status"] == "DRAFT", "the rejected submit left the scenario in DRAFT"
    assert stored["revision_round"] == 0
    assert stored["contiguity_ok"] is True, (
        "the rejected submit persisted nothing, so the empty-scenario value stands"
    )
    assert stored["noncontiguous_school_ids"] == []
    assert stored["max_utilization_pct"] == pytest.approx(0.00, abs=0.01)
    assert stored["total_assigned_students"] == 0

    analysis = validate_success(
        api_client.get_impact_analysis(ctx["scenario_id"], PLANNER)
    )
    assert analysis["contiguity_ok"] is False, (
        "the computed read exposes the split the rejected submit refused to store"
    )
    assert analysis["noncontiguous_school_ids"] == [ctx["cedar_id"]], (
        "Birch's single area and any empty set are vacuously contiguous"
    )
    assert analysis["total_assigned_students"] == 588, "271 + 181 + 136 == 588"
    assert analysis["max_utilization_pct"] == pytest.approx(80.93, abs=0.01), (
        "Cedar carries 271 + 136 students plus 30 program seats against 540 seats"
    )


# ---------------------------------------------------------------------------
# Variance monitoring
# ---------------------------------------------------------------------------
def test_variance_pct_rounds_half_up_rather_than_truncating():
    """4.857142... percent is stored as 4.86, not 4.85.

    PRD 3.9: "Otherwise `variance_pct` is 100 multiplied by the signed difference
    of `observed_enrollment` minus `projected_enrollment`, divided by
    `projected_enrollment`, rounded half up to 2 decimal places — negative when
    the school under-enrolled."
    PRD 2.6: "Wherever a value is rounded, the method is **round half up** — a tie
    rounds away from zero."

    100 * (734 - 700) / 700 == 4.857142..., so round half up to two places gives
    4.86 while truncation would give 4.85. Both land WITHIN_TOLERANCE against the
    adoption's 5.00 percent tolerance, which isolates the rounding mode.

    Design: Corner/calculations/variance_pct_rounds_half_up_rather_than_truncating
    """
    ctx = riverbend_adopted()
    set_clock("2027-07-01T00:00:00Z", headers=OFFICER)
    activated = validate_success(
        api_client.activate_adoption(ctx["adoption_id"], OFFICER)
    )
    assert activated["implementation_status"] == "IN_EFFECT"

    observation = validate_success(
        api_client.create_variance_observation(
            ctx["adoption_id"],
            create_variance_observation_payload(ctx["cedar_id"], 734, 700),
            OFFICER,
        ),
        201,
    )
    assert observation["variance_pct"] == pytest.approx(4.86, abs=0.001), (
        "round half up of 4.857142... is 4.86, not the truncated 4.85"
    )
    assert observation["flag"] == "WITHIN_TOLERANCE", (
        "4.86 is at or below the 5.00 percent tolerance"
    )
    assert observation["adoption_id"] == ctx["adoption_id"]
    assert observation["school_id"] == ctx["cedar_id"]
    assert "version" not in observation, (
        "a variance observation is immutable and carries no version"
    )
    assert "updated_at" not in observation, (
        "a variance observation is immutable and carries no updated_at"
    )

    _rows, meta = validate_paginated(
        api_client.list_variance_observations(
            OFFICER, {"adoption_id": ctx["adoption_id"]}
        )
    )
    assert meta["total_count"] == 1


def test_variance_flag_bands_are_inclusive_at_tolerance_and_double_tolerance():
    """Both variance band edges belong to the gentler band.

    PRD 3.9: "The `flag` is then set by comparing the **absolute value** of
    `variance_pct` against the adoption's `variance_tolerance_pct`:
    `WITHIN_TOLERANCE` when the absolute variance is at or below the tolerance,
    `WATCH` when it is above the tolerance but at or below twice the tolerance,
    and `CORRECTIVE_ACTION_REQUIRED` when it exceeds twice the tolerance."
    PRD 3.9: "Both band edges belong to the gentler band, so an absolute variance
    exactly equal to the tolerance is `WITHIN_TOLERANCE` and one exactly equal to
    twice the tolerance is `WATCH`."

    Against a projection of 500 and a tolerance of 5.00, five observations walk
    both edges: 525 gives 5.00, 526 gives 5.20, 550 gives 10.00, 551 gives 10.20
    and 475 gives -5.00, whose absolute value is the tolerance itself.

    Design: Corner/calculations/variance_flag_bands_are_inclusive_at_tolerance_and_double_tolerance
    """
    ctx = riverbend_adopted()
    set_clock("2027-07-01T00:00:00Z", headers=OFFICER)
    validate_success(api_client.activate_adoption(ctx["adoption_id"], OFFICER))

    cases = [
        ("2027-10-01T00:00:00Z", 525, 5.00, "WITHIN_TOLERANCE"),
        ("2027-10-02T00:00:00Z", 526, 5.20, "WATCH"),
        ("2027-10-03T00:00:00Z", 550, 10.00, "WATCH"),
        ("2027-10-04T00:00:00Z", 551, 10.20, "CORRECTIVE_ACTION_REQUIRED"),
        ("2027-10-05T00:00:00Z", 475, -5.00, "WITHIN_TOLERANCE"),
    ]
    for observed_on, observed, expected_pct, expected_flag in cases:
        row = validate_success(
            api_client.create_variance_observation(
                ctx["adoption_id"],
                create_variance_observation_payload(
                    ctx["cedar_id"], observed, 500, observed_on=observed_on
                ),
                OFFICER,
            ),
            201,
        )
        assert row["variance_pct"] == pytest.approx(expected_pct, abs=0.001), (
            f"100 * ({observed} - 500) / 500 == {expected_pct}"
        )
        assert row["flag"] == expected_flag, (
            f"variance_pct {expected_pct} belongs to band {expected_flag}"
        )

    _watch, watch_meta = validate_paginated(
        api_client.list_variance_observations(
            OFFICER, {"adoption_id": ctx["adoption_id"], "flag": "WATCH"}
        )
    )
    assert watch_meta["total_count"] == 2, (
        "5.20 and the inclusive 10.00 edge are both WATCH"
    )

    _corrective, corrective_meta = validate_paginated(
        api_client.list_variance_observations(
            OFFICER,
            {
                "adoption_id": ctx["adoption_id"],
                "flag": "CORRECTIVE_ACTION_REQUIRED",
            },
        )
    )
    assert corrective_meta["total_count"] == 1, "only 10.20 exceeds twice the tolerance"


# ---------------------------------------------------------------------------
# Board vote arithmetic
# ---------------------------------------------------------------------------
def test_board_quorum_counts_abstentions_but_the_majority_test_does_not():
    """Abstentions reach quorum and then vanish from the majority denominator.

    PRD 3.7: "The quorum threshold is `board_member_count` divided by two,
    rounded **up** to a whole member, and quorum is met when the cast count
    reaches or exceeds that threshold — abstentions **do** count toward quorum."
    PRD 3.7: "When `supermajority_required` is false, the majority is met when
    twice `votes_for` is strictly greater than the sum of `votes_for` and
    `votes_against`."
    PRD 3.7: "Abstentions are excluded from the majority denominator in both
    branches, so they help reach quorum and then vanish from the decision."

    3-1-0 of nine seats casts four ballots against a threshold of ceil(9 / 2) = 5
    and fails quorum. 3-3-1 of seven casts seven ballots, clearing quorum only
    because the abstention counts, then fails the majority test because
    2 * 3 == 6 is not strictly greater than 3 + 3 == 6. 4-3-0 of seven clears
    both, since 2 * 4 == 8 is strictly greater than 7.

    Design: Corner/calculations/board_quorum_counts_abstentions_but_the_majority_test_does_not
    """
    ctx = riverbend_board_ready()

    def vote(votes_for, votes_against, votes_abstain, board_member_count):
        return api_client.create_adoption(
            create_adoption_payload(
                ctx["study_id"],
                ctx["scenario_id"],
                effective_date="2027-07-01T00:00:00Z",
                effective_school_year=2028,
                regime_years=3,
                transfer_deadline_date="2027-08-15T00:00:00Z",
                transfer_cap_pct=95.0,
                variance_tolerance_pct=5.0,
                votes_for=votes_for,
                votes_against=votes_against,
                votes_abstain=votes_abstain,
                board_member_count=board_member_count,
            ),
            BOARD,
        )

    validate_error(vote(3, 1, 0, 9), ApiErrorId.ERR_QUORUM_NOT_MET)
    validate_error(vote(3, 3, 1, 7), ApiErrorId.ERR_MAJORITY_NOT_MET)

    scenario = validate_success(api_client.get_scenario(ctx["scenario_id"], PLANNER))
    assert scenario["status"] == "BOARD_READY", (
        "a rejected vote leaves the scenario available for the next attempt"
    )
    study = validate_success(api_client.get_study(ctx["study_id"], PLANNER))
    assert study["status"] == "BOARD_DECISION"

    adoption = validate_success(vote(4, 3, 0, 7), 201)
    assert adoption["implementation_status"] == "PENDING_EFFECTIVE"
    assert adoption["supermajority_required"] is False, (
        "no area changes school, so students_reassigned_pct is 0.00 percent"
    )
    assert adoption["votes_abstain"] == 0

    scenario = validate_success(api_client.get_scenario(ctx["scenario_id"], PLANNER))
    assert scenario["status"] == "ADOPTED"
    study = validate_success(api_client.get_study(ctx["study_id"], PLANNER))
    assert study["status"] == "IMPLEMENTATION"

    _rows, meta = validate_paginated(
        api_client.list_adoptions(BOARD, {"study_id": ctx["study_id"]})
    )
    assert meta["total_count"] == 1, "the two rejected votes persisted nothing"


# ---------------------------------------------------------------------------
# Transfer eligibility waterfall
# ---------------------------------------------------------------------------
def test_eligibility_waterfall_stops_at_the_first_matching_rung():
    """Four requests observe rungs one, three, four and the NONE fallthrough.

    PRD 3.8: "At submission, and again at decision time, the server resolves
    which entitlement the student actually holds by walking four rungs in exactly
    this order and stopping at the first match."
    PRD 3.8: "If no rung matches, `resolved_reason` is `NONE` and
    `consumes_seat_pool` is false; such a request may be created and sits in
    `SUBMITTED`, but it can only ever be denied."

    The adoption carries a TERMINAL_GRADE_GRANDFATHER band on grade 5 and a
    PHASE_IN_GRADE_BAND band on grades 2 through 4. Grade 5 stops at rung one,
    grade 3 falls through to rung three, grade 6 with reason HARDSHIP reaches
    rung four, and grade 6 with reason PROGRAM matches nothing.

    Design: Corner/calculations/eligibility_waterfall_stops_at_the_first_matching_rung
    """
    ctx = riverbend_adopted()

    grandfather = validate_success(
        api_client.create_phase_in_rule(
            ctx["adoption_id"],
            create_phase_in_rule_payload(
                rule_type="TERMINAL_GRADE_GRANDFATHER",
                grade_low=5,
                grade_high=5,
                sunset_school_year=2030,
            ),
            BOARD,
        ),
        201,
    )
    phase_in = validate_success(
        api_client.create_phase_in_rule(
            ctx["adoption_id"],
            create_phase_in_rule_payload(
                rule_type="PHASE_IN_GRADE_BAND",
                grade_low=2,
                grade_high=4,
                sunset_school_year=2030,
            ),
            BOARD,
        ),
        201,
    )
    assert grandfather["consumes_seat_pool"] is False, (
        "TERMINAL_GRADE_GRANDFATHER bypasses the seat pool"
    )
    assert phase_in["consumes_seat_pool"] is False, (
        "PHASE_IN_GRADE_BAND bypasses the seat pool"
    )

    expectations = [
        ("guardian-1", "STU-301", 5, "GRANDFATHER", "TERMINAL_GRADE_GRANDFATHER", False),
        ("guardian-2", "STU-302", 3, "PHASE_IN", "PHASE_IN_GRADE_BAND", False),
        ("guardian-3", "STU-303", 6, "HARDSHIP", "HARDSHIP_REVIEW", True),
        ("guardian-4", "STU-304", 6, "PROGRAM", "NONE", False),
    ]
    for guardian, reference, grade, reason, expected_rung, consumes in expectations:
        request = create_transfer_request(
            ctx["adoption_id"],
            ctx["a3_id"],
            ctx["cedar_id"],
            headers=make_guardian_headers(guardian),
            student_reference=reference,
            student_grade=grade,
            reason=reason,
        )
        assert request["resolved_reason"] == expected_rung, (
            f"grade {grade} with reason {reason} resolves to {expected_rung}"
        )
        assert request["consumes_seat_pool"] is consumes, (
            f"{expected_rung} sets consumes_seat_pool to {consumes}"
        )
        assert request["status"] == "SUBMITTED"
        assert request["origin_school_id"] == ctx["birch_id"], (
            "A-03 keeps Birch under the adopted scenario, so that is the origin"
        )

    _rows, meta = validate_paginated(
        api_client.list_transfer_requests(
            OFFICER, {"adoption_id": ctx["adoption_id"], "resolved_reason": "NONE"}
        )
    )
    assert meta["total_count"] == 1, "only the grade-6 PROGRAM request matches no rung"
