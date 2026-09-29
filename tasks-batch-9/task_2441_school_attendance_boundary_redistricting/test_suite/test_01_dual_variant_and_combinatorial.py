"""Variant-switched projection and equity figures, plus the nested/ordered formulas."""

import math

import pytest

from prd_bench_local_runner.testing import (
    validate_paginated,
    validate_success,
)

from test_helpers import (
    BUS_CAPACITY,
    DAILY_BUS_BASE_USD,
    MIN_BILLED_MINUTES,
    PER_MINUTE_USD,
    SCHOOL_DAYS_PER_YEAR,
    TEST_USERS,
    advance_entitlement_to,
    api_client,
    assign_areas,
    create_housing_development,
    create_projection_run,
    create_scenario,
    create_transfer_request,
    decide_transfer,
    make_guardian_headers,
    program_placement,
    riverbend_adopted,
    riverbend_locked,
    riverbend_scenario_draft,
    set_clock,
    setup_study_with_inventory,
    travel_option,
)

PLANNER = TEST_USERS["planner_headers"]
OFFICER = TEST_USERS["officer_headers"]


# ---------------------------------------------------------------------------
# Local setup builders
# ---------------------------------------------------------------------------
def _riverbend_with_pipeline():
    """Riverbend locked, plus the three-development housing pipeline.

    Willow Ridge on A-01 is walked up to UNDER_CONSTRUCTION; Maple Flats on
    A-02 and Juniper Commons on A-03 stay PROPOSED. Juniper's buildout runs
    past the horizon end, so its occupancy factor is fractional.
    """
    ctx = riverbend_locked()
    ctx["willow"] = create_housing_development(
        ctx["a1_id"],
        name="Willow Ridge",
        unit_type="SINGLE_FAMILY",
        total_units=120,
        first_occupancy_date="2027-01-01T00:00:00Z",
        buildout_months=24,
    )
    advance_entitlement_to(ctx["willow"]["id"], "UNDER_CONSTRUCTION")
    ctx["maple"] = create_housing_development(
        ctx["a2_id"],
        name="Maple Flats",
        unit_type="MULTI_FAMILY",
        total_units=200,
        first_occupancy_date="2027-03-01T00:00:00Z",
        buildout_months=20,
    )
    ctx["juniper"] = create_housing_development(
        ctx["a3_id"],
        name="Juniper Commons",
        unit_type="TOWNHOME",
        total_units=90,
        first_occupancy_date="2031-01-01T00:00:00Z",
        buildout_months=36,
    )
    return ctx


def _projection_row(run, area_id):
    """The area_projections entry of ``run`` for ``area_id``."""
    matches = [row for row in run["area_projections"] if row["area_id"] == area_id]
    assert len(matches) == 1, "every planning area of the study is projected exactly once"
    return matches[0]


def _brookfield_locked():
    """A second district whose B-01 carries three identically shaped developments."""
    def b01(school_ids):
        return {
            "area_code": "B-01",
            "grade_band": "ELEMENTARY",
            "current_school_id": school_ids["Alder Elementary"],
            "resident_student_count": 111,
            "frl_student_count": 40,
            "ell_student_count": 12,
            "median_household_income_usd": 61000,
            "annual_absorption_cap_units": 300,
            "travel_options": [
                travel_option(school_ids["Alder Elementary"], 0.5, 10, True),
                travel_option(school_ids["Poplar Elementary"], 2.0, 20, False),
            ],
        }

    def b02(school_ids):
        return {
            "area_code": "B-02",
            "grade_band": "ELEMENTARY",
            "current_school_id": school_ids["Alder Elementary"],
            "resident_student_count": 100,
            "frl_student_count": 30,
            "ell_student_count": 8,
            "median_household_income_usd": 74000,
            "annual_absorption_cap_units": 100,
            "travel_options": [
                travel_option(school_ids["Alder Elementary"], 0.7, 11, True),
                travel_option(school_ids["Poplar Elementary"], 1.9, 18, False),
            ],
        }

    def b03(school_ids):
        return {
            "area_code": "B-03",
            "grade_band": "ELEMENTARY",
            "current_school_id": school_ids["Poplar Elementary"],
            "resident_student_count": 100,
            "frl_student_count": 25,
            "ell_student_count": 6,
            "median_household_income_usd": 88000,
            "annual_absorption_cap_units": 100,
            "travel_options": [
                travel_option(school_ids["Alder Elementary"], 2.6, 23, False),
                travel_option(school_ids["Poplar Elementary"], 0.8, 13, True),
            ],
        }

    ctx = setup_study_with_inventory(
        study_payload={
            "name": "2029 Feeder Pattern Study",
            "district_name": "Brookfield USD",
            "target_school_year": 2029,
            "horizon_years": 5,
            "capacity_target_low_pct": 85.0,
            "capacity_target_high_pct": 100.0,
            "portables_count_toward_capacity": False,
            "required_program_types": ["DUAL_LANGUAGE"],
        },
        school_payloads=(
            {
                "name": "Alder Elementary",
                "level": "ELEMENTARY",
                "core_capacity_seats": 400,
                "program_types": ["DUAL_LANGUAGE"],
            },
            {
                "name": "Poplar Elementary",
                "level": "ELEMENTARY",
                "core_capacity_seats": 400,
            },
        ),
        area_builders=(b01, b02, b03),
        adjacency_specs=(("B-01", "B-02", 3300), ("B-02", "B-03", 2900)),
    )
    for name in ("Kestrel Park I", "Kestrel Park II", "Kestrel Park III"):
        create_housing_development(
            ctx["area_ids"]["B-01"],
            name=name,
            unit_type="SINGLE_FAMILY",
            total_units=80,
            first_occupancy_date="2027-01-01T00:00:00Z",
            buildout_months=12,
            student_yield_override=1.6749,
        )
    return ctx


def _seat_pool_ladder():
    """The adopted Riverbend map with two approvals, two waitlistings and one outbound.

    Cedar's capped capacity is 454 seats against a post-boundary enrollment of
    452, so STU-001 and STU-002 exhaust the pool, STU-003 and STU-004 are
    waitlisted in that filing order, and the outbound approval of STU-005 hands
    exactly one seat back.
    """
    ctx = riverbend_adopted()
    specs = [
        ("guardian-1", "STU-001", 3, "a3_id", "cedar_id"),
        ("guardian-2", "STU-002", 4, "a3_id", "cedar_id"),
        ("guardian-3", "STU-003", 5, "a3_id", "cedar_id"),
        ("guardian-4", "STU-004", 6, "a3_id", "cedar_id"),
        ("guardian-5", "STU-005", 2, "a1_id", "birch_id"),
    ]
    requests = []
    for guardian, reference, grade, area_key, school_key in specs:
        requests.append(
            create_transfer_request(
                ctx["adoption_id"],
                ctx[area_key],
                ctx[school_key],
                headers=make_guardian_headers(guardian),
                student_reference=reference,
                student_grade=grade,
                reason="HARDSHIP",
            )
        )
    decisions = ["APPROVE", "APPROVE", "WAITLIST", "WAITLIST", "APPROVE"]
    for request, decision in zip(requests, decisions):
        decide_transfer(request["id"], decision, decision_notes="Hardship review.")
    ctx["requests"] = requests
    return ctx


# ---------------------------------------------------------------------------
# dual_variant_calc / projection_variant_divergence_...
# ---------------------------------------------------------------------------
def test_cohort_survival_run_admits_only_under_construction_developments():
    """The conservative variant admits Willow Ridge alone, at full weight and occupancy.

    A-01 bases at round_half_up(300 * 0.98**5) == 271 and takes 120 * 0.42 == 50.40
    development students; A-02's PROPOSED Maple Flats and A-03's PROPOSED Juniper
    Commons are skipped outright, so the study totals 638 projected students.

    PRD: "Under `COHORT_SURVIVAL` — the conservative demographer view used for
    board-facing baselines — only developments whose `entitlement_status` is
    `UNDER_CONSTRUCTION` or `COMPLETE` are admitted; every other stage, including
    `WITHDRAWN`, is skipped, and each admitted development enters at full
    entitlement weight of 1.00 and full occupancy of 1.00 regardless of its
    `first_occupancy_date` or `buildout_months`."

    Design: Difficulty/dual_variant_calc/projection_variant_divergence_cohort_survival_vs_development_weighted
    """
    ctx = _riverbend_with_pipeline()

    run = create_projection_run(ctx["study_id"], variant="COHORT_SURVIVAL")

    assert run["variant"] == "COHORT_SURVIVAL"
    assert run["status"] == "COMPLETE", "a successful run is stored COMPLETE"
    assert run["projected_total_students"] == 638

    a1 = _projection_row(run, ctx["a1_id"])
    assert a1["base_students"] == 271
    assert a1["development_students"] == pytest.approx(50.40, abs=0.01), (
        "the UNDER_CONSTRUCTION development enters at weight 1.00 and occupancy 1.00"
    )
    assert a1["projected_students"] == 321

    a2 = _projection_row(run, ctx["a2_id"])
    assert a2["base_students"] == 181
    assert a2["development_students"] == pytest.approx(0.00, abs=0.01), (
        "a PROPOSED development is skipped by COHORT_SURVIVAL"
    )
    assert a2["projected_students"] == 181

    a3 = _projection_row(run, ctx["a3_id"])
    assert a3["base_students"] == 136
    assert a3["development_students"] == pytest.approx(0.00, abs=0.01)
    assert a3["projected_students"] == 136

    study = validate_success(api_client.get_study(ctx["study_id"], PLANNER))
    assert study["status"] == "SCENARIO_DEVELOPMENT", (
        "the first COMPLETE run auto-advances a DATA_LOCKED study"
    )


def test_development_weighted_run_discounts_every_live_development():
    """The planning view admits all three developments and beats the baseline by 8.

    Maple Flats contributes 200 * 0.13 * 0.25 == 6.50 and Juniper Commons
    90 * 0.25 * 0.25 * (8/36) == 1.25, lifting the total from 638 to 646 over
    byte-identical study data.

    PRD: "Under `DEVELOPMENT_WEIGHTED` — the planning-department view used to
    size capacity against the pipeline — every development except a `WITHDRAWN`
    one is admitted, but each is discounted twice."

    PRD: "Its occupancy factor is the number of whole 30-day months from its
    `first_occupancy_date` to the horizon end — that elapsed span divided by 30
    days and rounded down to a whole month — divided by its `buildout_months`,
    then clamped so that a negative result becomes 0.0 and a result above 1.0
    becomes 1.0."

    Design: Difficulty/dual_variant_calc/projection_variant_divergence_cohort_survival_vs_development_weighted
    """
    ctx = _riverbend_with_pipeline()

    baseline = create_projection_run(ctx["study_id"], variant="COHORT_SURVIVAL")
    weighted = create_projection_run(ctx["study_id"], variant="DEVELOPMENT_WEIGHTED")

    assert weighted["variant"] == "DEVELOPMENT_WEIGHTED"
    assert weighted["status"] == "COMPLETE"
    assert weighted["projected_total_students"] == 646

    reread_baseline = validate_success(
        api_client.get_projection_run(baseline["id"], PLANNER)
    )
    assert reread_baseline["status"] == "COMPLETE", (
        "supersession applies only to an earlier run of the same variant"
    )

    a1 = _projection_row(weighted, ctx["a1_id"])
    assert a1["development_students"] == pytest.approx(50.40, abs=0.01)
    assert a1["projected_students"] == 321

    a2 = _projection_row(weighted, ctx["a2_id"])
    assert a2["development_students"] == pytest.approx(6.50, abs=0.01), (
        "a PROPOSED multi-family development enters at entitlement weight 0.25"
    )
    assert a2["projected_students"] == 188

    a3 = _projection_row(weighted, ctx["a3_id"])
    assert a3["development_students"] == pytest.approx(1.25, abs=0.01), (
        "a buildout running past the horizon end yields a fractional occupancy"
    )
    assert a3["projected_students"] == 137

    assert (
        weighted["projected_total_students"]
        - reread_baseline["projected_total_students"]
        == 8
    ), "identical study data must diverge by 8 students across the two variants"


# ---------------------------------------------------------------------------
# dual_variant_calc / impact_index_variant_divergence_...
# ---------------------------------------------------------------------------
def _pipeline_scenario(ctx, name, impact_variant, run_id):
    """One DRAFT scenario over ``run_id`` with A-01/A-02 at Cedar and A-03 at Birch."""
    scenario = create_scenario(
        ctx["study_id"],
        run_id,
        [program_placement(ctx["cedar_id"], 30)],
        name=name,
        impact_variant=impact_variant,
    )
    assign_areas(
        scenario["id"],
        [
            (ctx["a1_id"], ctx["cedar_id"]),
            (ctx["a2_id"], ctx["cedar_id"]),
            (ctx["a3_id"], ctx["birch_id"]),
        ],
    )
    return scenario


def test_resident_based_impact_index_reads_todays_head_counts():
    """RESIDENT_BASED ignores the pipeline entirely and reports 0.1427.

    Cedar tallies 190 FRL against 310 non-FRL and Birch 30 against 120, so the
    district split is 220 / 430 and the dissimilarity index is
    0.5 * (|190/220 - 310/430| + |30/220 - 120/430|) == 0.1427.

    PRD: "Under `RESIDENT_BASED`, the view the board sees at first reading, the
    split is today's head count unchanged: the area's `frl_student_count` as the
    FRL part and its `resident_student_count` minus its `frl_student_count` as
    the non-FRL part, and the housing pipeline is ignored entirely."

    Design: Difficulty/dual_variant_calc/impact_index_variant_divergence_resident_vs_projected
    """
    ctx = _riverbend_with_pipeline()
    run = create_projection_run(ctx["study_id"], variant="DEVELOPMENT_WEIGHTED")
    scenario = _pipeline_scenario(ctx, "Equity View R", "RESIDENT_BASED", run["id"])

    analysis = validate_success(api_client.get_impact_analysis(scenario["id"], PLANNER))

    assert analysis["impact_variant"] == "RESIDENT_BASED"
    assert analysis["frl_dissimilarity_index"] == pytest.approx(0.1427, abs=0.0001)
    assert analysis["total_assigned_students"] == 646, (
        "the assignment snapshots come from the DEVELOPMENT_WEIGHTED run"
    )
    assert analysis["students_reassigned_count"] == 0, (
        "every area keeps its school of record under this map"
    )
    assert analysis["students_reassigned_pct"] == pytest.approx(0.00, abs=0.01)


def test_projected_based_impact_index_rescales_to_the_horizon():
    """PROJECTED_BASED reports 0.1219 where RESIDENT_BASED reports 0.1427.

    Scaling to the horizon gives Cedar 184.38 FRL against 324.62 non-FRL and
    Birch 27.60 against 109.40, a district split of 211.98 / 434.02, so two
    scenarios with byte-identical assignments over the same run diverge.

    PRD: "The FRL part is then the entry's `base_students` multiplied by the
    resident FRL rate plus its `development_students` multiplied by the
    development FRL rate, rounded half up to 2 decimal places, and the non-FRL
    part is the entry's `projected_students` minus that FRL part, likewise
    rounded half up to 2 decimal places."

    PRD: "Otherwise it is one half of the sum, over the `ACTIVE` schools, of the
    absolute difference between that school's share of the district FRL
    population and its share of the district non-FRL population, rounded half up
    to 4 decimal places."

    Design: Difficulty/dual_variant_calc/impact_index_variant_divergence_resident_vs_projected
    """
    ctx = _riverbend_with_pipeline()
    run = create_projection_run(ctx["study_id"], variant="DEVELOPMENT_WEIGHTED")
    resident = _pipeline_scenario(
        ctx, "Equity View R", "RESIDENT_BASED", run["id"]
    )
    projected = _pipeline_scenario(
        ctx, "Equity View P", "PROJECTED_BASED", run["id"]
    )

    resident_analysis = validate_success(
        api_client.get_impact_analysis(resident["id"], PLANNER)
    )
    projected_analysis = validate_success(
        api_client.get_impact_analysis(projected["id"], PLANNER)
    )

    assert projected_analysis["impact_variant"] == "PROJECTED_BASED"
    assert projected_analysis["frl_dissimilarity_index"] == pytest.approx(
        0.1219, abs=0.0001
    )
    assert resident_analysis["impact_variant"] == "RESIDENT_BASED"
    assert resident_analysis["frl_dissimilarity_index"] == pytest.approx(
        0.1427, abs=0.0001
    )
    assert (
        projected_analysis["frl_dissimilarity_index"]
        != resident_analysis["frl_dissimilarity_index"]
    ), "the two equity views must not collapse onto one number"

    for analysis in (resident_analysis, projected_analysis):
        assert analysis["total_assigned_students"] == 646
        assert analysis["students_reassigned_count"] == 0
        assert analysis["students_reassigned_pct"] == pytest.approx(0.00, abs=0.01)


# ---------------------------------------------------------------------------
# combinatorial_formula / transport_cost_nested_ceil_max_and_walk_branch
# ---------------------------------------------------------------------------
def test_transport_cost_nests_ceil_over_max_billed_minutes():
    """A-02 is the only bused row: ceil(181 / 71) buses billed at max(9, 15) minutes.

    The annual bill is 3 * (95.00 + 1.85 * 15) * 180 == 66285.00, a figure that
    is unreachable if the 15-minute floor, the bus-capacity ceiling or the
    walk-eligibility branch is dropped.

    PRD: "The billed ride length is the greater of the entry's `bus_minutes` and
    a 15-minute minimum."

    PRD: "The bus count is the rider count divided by a bus capacity of 71
    seats, rounded **up** to a whole bus, so zero riders means zero buses."

    PRD: "That assignment's cost is the bus count multiplied by the sum of a
    daily base of 95.00 US dollars and 1.85 US dollars per billed minute,
    multiplied by 180 school days per year."

    Design: Difficulty/combinatorial_formula/transport_cost_nested_ceil_max_and_walk_branch
    """
    ctx = riverbend_scenario_draft()
    assign_areas(
        ctx["scenario_id"],
        [
            (ctx["a1_id"], ctx["cedar_id"]),
            (ctx["a2_id"], ctx["cedar_id"]),
            (ctx["a3_id"], ctx["birch_id"]),
        ],
    )

    analysis = validate_success(
        api_client.get_impact_analysis(ctx["scenario_id"], PLANNER)
    )

    riders = 181
    buses = math.ceil(riders / BUS_CAPACITY)
    billed_minutes = max(9, MIN_BILLED_MINUTES)
    expected = (
        buses
        * (DAILY_BUS_BASE_USD + PER_MINUTE_USD * billed_minutes)
        * SCHOOL_DAYS_PER_YEAR
    )

    assert buses == 3, "181 riders need three 71-seat buses"
    assert billed_minutes == 15, "A-02's 9-minute ride bills at the 15-minute floor"
    assert expected == pytest.approx(66285.00, abs=0.01)
    assert analysis["transport_cost_annual_usd"] == pytest.approx(66285.00, abs=0.01)
    assert analysis["total_assigned_students"] == 588, (
        "the COHORT_SURVIVAL run projects 271 + 181 + 136 students"
    )


def test_walk_eligible_assignments_generate_no_riders():
    """A-01 and A-03 fall down the walk branch and bill exactly nothing.

    A-01 to Cedar is 0.6 mile with a safe route and A-03 to Birch is 0.9 mile
    with a safe route, both inside the 1.0-mile elementary limit, so 407 of the
    588 assigned students walk and the whole annual bill is A-02's alone.

    PRD: "The pair is walk-eligible when the entry's `walk_distance_miles` is
    less than or equal to the walk limit for the school's `level` — 1.0 mile for
    `ELEMENTARY`, 1.5 miles for `MIDDLE`, 2.0 miles for `HIGH` — **and** its
    `has_safe_route` is true; a distance exactly equal to the limit is
    walk-eligible."

    PRD: "Alongside it, `walk_eligible_pct` is 100 multiplied by the walking
    population divided by `total_assigned_students`, rounded half up to 2 decimal
    places, and is 0.00 when `total_assigned_students` is 0."

    Design: Difficulty/combinatorial_formula/transport_cost_nested_ceil_max_and_walk_branch
    """
    ctx = riverbend_scenario_draft()
    assign_areas(
        ctx["scenario_id"],
        [
            (ctx["a1_id"], ctx["cedar_id"]),
            (ctx["a2_id"], ctx["cedar_id"]),
            (ctx["a3_id"], ctx["birch_id"]),
        ],
    )

    analysis = validate_success(
        api_client.get_impact_analysis(ctx["scenario_id"], PLANNER)
    )

    assert analysis["walk_eligible_pct"] == pytest.approx(69.22, abs=0.01), (
        "271 + 136 walkers of 588 assigned students is 69.22 percent"
    )

    a02_only = (
        math.ceil(181 / BUS_CAPACITY)
        * (DAILY_BUS_BASE_USD + PER_MINUTE_USD * MIN_BILLED_MINUTES)
        * SCHOOL_DAYS_PER_YEAR
    )
    assert analysis["transport_cost_annual_usd"] == pytest.approx(a02_only, abs=0.01), (
        "the two walk-eligible assignments contribute exactly 0.00"
    )
    assert analysis["max_utilization_pct"] == pytest.approx(89.26, abs=0.01), (
        "Cedar carries 271 + 181 students plus 30 program seats against 540 seats"
    )


# ---------------------------------------------------------------------------
# combinatorial_formula / projection_rounds_each_development_before_summing
# ---------------------------------------------------------------------------
def test_projection_rounds_each_development_before_summing():
    """Three raw 33.498 contributions round to 33.50 each, giving 100.50 and 201.

    B-01 bases at round_half_up(111 * 0.98**5) == 100, and rounding per
    development before summing pushes projected_students to
    round_half_up(100 + 100.50) == 201 rather than the 200 a round-once-at-the-end
    order would report.

    PRD: "Its contribution is then its `total_units` multiplied by that yield,
    multiplied by its entitlement weight, multiplied by its occupancy factor —
    **and rounded half up to 2 decimal places before it is added to the running
    total**."

    PRD: "The area's `development_students` is the sum of those already-rounded
    per-development contributions; summing the raw contributions and rounding the
    sum once is a different and incorrect result."

    Design: Difficulty/combinatorial_formula/projection_rounds_each_development_before_summing
    """
    ctx = _brookfield_locked()

    run = create_projection_run(ctx["study_id"], variant="DEVELOPMENT_WEIGHTED")

    b01 = _projection_row(run, ctx["area_ids"]["B-01"])
    assert b01["base_students"] == 100
    assert b01["development_students"] == pytest.approx(100.50, abs=0.005), (
        "each of the three 33.498 contributions rounds to 33.50 before summing"
    )
    assert b01["development_students"] != pytest.approx(100.494, abs=0.001), (
        "summing the raw contributions is the wrong rounding order"
    )
    assert b01["projected_students"] == 201
    assert b01["projected_students"] != 200, (
        "a round-once-at-the-end order would lose a whole student here"
    )


def test_projection_total_sums_the_rounded_area_projections():
    """The study total is the plain sum 201 + 90 + 90 == 381, never re-rounded.

    B-02 and B-03 carry no housing at all, so each bases and projects at
    round_half_up(100 * 0.98**5) == 90 with development_students 0.00, and the
    total turns entirely on B-01's per-development rounding.

    PRD: "The area's `projected_students` is `base_students` plus
    `development_students`, rounded half up to a whole student."

    PRD: "The run computes two outputs: `area_projections`, an array with one
    entry per planning area of the study ordered by area creation time, each
    entry carrying `area_id`, `base_students`, `development_students` and
    `projected_students`; and `projected_total_students`, the plain sum of every
    area's `projected_students`, which is never re-rounded."

    Design: Difficulty/combinatorial_formula/projection_rounds_each_development_before_summing
    """
    ctx = _brookfield_locked()

    run = create_projection_run(ctx["study_id"], variant="DEVELOPMENT_WEIGHTED")

    b02 = _projection_row(run, ctx["area_ids"]["B-02"])
    assert b02["development_students"] == pytest.approx(0.00, abs=0.005)
    assert b02["projected_students"] == 90

    b03 = _projection_row(run, ctx["area_ids"]["B-03"])
    assert b03["projected_students"] == 90

    assert run["projected_total_students"] == 381
    assert run["projected_total_students"] != 380, (
        "the total inherits B-01's per-development rounding"
    )


# ---------------------------------------------------------------------------
# combinatorial_formula / transfer_seat_pool_recomputed_between_batch_promotions
# ---------------------------------------------------------------------------
def test_activation_promotes_the_first_waitlisted_request_into_the_single_free_seat():
    """STU-003 takes the one seat Cedar's outbound approval handed back.

    Cedar's pool at activation is floor(540 * 84.10 / 100) - (452 + 2 - 1) == 1,
    so the earliest waitlisted request is promoted as a system act rather than an
    officer decision.

    PRD: "Link four revisits the waitlist, because the new head counts changed
    every seat pool: every `WAITLISTED` transfer request of this adoption is
    reconsidered in request creation order, and each one whose requested school
    now has at least one free transfer seat moves `WAITLISTED → APPROVED` with
    `promotion_source` set to `WAITLIST_AUTO` and `decided_by_user_id` left null,
    the pool being recomputed after each promotion before the next candidate is
    considered."

    Design: Difficulty/combinatorial_formula/transfer_seat_pool_recomputed_between_batch_promotions
    """
    ctx = _seat_pool_ladder()
    stu_003 = ctx["requests"][2]

    set_clock("2027-07-01T00:00:00Z", headers=OFFICER)
    adoption = validate_success(
        api_client.activate_adoption(ctx["adoption_id"], OFFICER)
    )

    assert adoption["implementation_status"] == "IN_EFFECT"

    promoted = validate_success(
        api_client.get_transfer_request(stu_003["id"], OFFICER)
    )
    assert promoted["status"] == "APPROVED"
    assert promoted["promotion_source"] == "WAITLIST_AUTO"
    assert promoted["decided_by_user_id"] is None, (
        "an activation promotion is a system act, not an officer decision"
    )


def test_activation_recomputes_the_seat_pool_between_promotions():
    """STU-004 stays waitlisted because STU-003 consumed the last seat.

    After the first promotion Cedar's pool is 454 - (452 + 3 - 1) == 0, so a
    batch that snapshotted the pool once would wrongly promote both, leaving the
    adoption with five approvals instead of four.

    PRD: "Because of that recomputation, an earlier candidate can consume the
    last seat and leave a later one waitlisted, which is why the creation-order
    walk is normative rather than incidental."

    PRD: "The pool itself is the school's effective capacity multiplied by the
    adoption's `transfer_cap_pct`, divided by 100, rounded **down** to a whole
    seat — a fractional seat is not a seat — minus that current head count."

    Design: Difficulty/combinatorial_formula/transfer_seat_pool_recomputed_between_batch_promotions
    """
    ctx = _seat_pool_ladder()
    stu_004 = ctx["requests"][3]

    set_clock("2027-07-01T00:00:00Z", headers=OFFICER)
    validate_success(api_client.activate_adoption(ctx["adoption_id"], OFFICER))

    held = validate_success(api_client.get_transfer_request(stu_004["id"], OFFICER))
    assert held["status"] == "WAITLISTED", (
        "the recomputed pool is 0 by the time the second candidate is considered"
    )
    assert held["promotion_source"] is None

    _, approved_meta = validate_paginated(
        api_client.list_transfer_requests(
            OFFICER, params={"adoption_id": ctx["adoption_id"], "status": "APPROVED"}
        )
    )
    assert approved_meta["total_count"] == 4, (
        "three officer approvals plus exactly one auto-promotion"
    )

    _, waitlisted_meta = validate_paginated(
        api_client.list_transfer_requests(
            OFFICER, params={"adoption_id": ctx["adoption_id"], "status": "WAITLISTED"}
        )
    )
    assert waitlisted_meta["total_count"] == 1
