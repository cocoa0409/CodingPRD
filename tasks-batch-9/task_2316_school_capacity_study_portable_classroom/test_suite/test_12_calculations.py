"""Arithmetic: seat loading constants, utilization rounding and the cost model."""

from prd_bench_local_runner.testing import validate_success

from test_helpers import PLANNER_HEADERS
from test_helpers.assertions import assert_capacity_fields, assert_cost_breakdown
from test_helpers.fixtures import (
    build_campus,
    build_request_context,
    create_projection,
    create_room,
    create_school,
    create_set_aside,
    create_study,
    submit_study,
)

CLOCK = "2027-03-01T00:00:00Z"
MIXED_AREAS = (900, 900, 720, 1000, 650, 840, 5000)
MIXED_TYPES = ("STANDARD_CLASSROOM", "STANDARD_CLASSROOM", "STANDARD_CLASSROOM",
               "SCIENCE_LAB", "SPED_RESOURCE", "ART_MUSIC", "GYM")


def test_every_component_of_the_relocation_estimate_is_separately_visible(api):
    """PRD §3.6: "**Mobilisation** starts from the chassis move base — 4,500,000 cents
    for a `SINGLE_24x40` ... and adds 38,000 cents for each of the request's
    `haul_miles`." "**Rehab** is keyed on the unit's `condition_grade`: nothing for grade
    `A`, 1,250,000 cents for grade `B`, and 4,600,000 cents for grade `C`." "**Permit
    fees** are 210,000 cents for each discipline in the required permit set, and the set
    is sized as three baseline disciplines plus one more when the chassis needs a sewer
    connection and the pad has none, plus one more when either the unit lacks a compliant
    ramp or the pad path is non-compliant." "**Contingency** is 12 percent of that direct
    cost, rounded half up, then capped at 1,500,000 cents from above and lifted to
    700,000 cents from below". "The requested window counts as inside the summer
    construction window when `requested_window_start` falls on or after June 15 of its
    own calendar year, `requested_window_end` falls on or before August 15 of its own
    calendar year, and both dates fall in the same calendar year."

    Design: Corner/calculations/relocation_cost_estimate_component_breakdown
    """
    ctx = build_request_context(
        api, stage="draft", clock=CLOCK,
        school_overrides={"name": "Northside Middle"},
        unit_overrides={"asset_tag": "PU-H101"},
    )

    model = validate_success(api.get_cost_model(ctx["request_id"], PLANNER_HEADERS))
    assert_cost_breakdown(model, {
        "mobilisation_cents": 5_032_000,
        "off_summer_applied": False,
        "site_work_cents": 0,
        "rehab_cents": 1_250_000,
        "permit_fee_cents": 630_000,
        "direct_cost_cents": 6_912_000,
        "contingency_cents": 829_440,
        "estimated_relocation_cost_cents": 7_741_440,
    })

    request = validate_success(api.get_placement_request(ctx["request_id"],
                                                        PLANNER_HEADERS))
    assert request["estimated_relocation_cost_cents"] == 7_741_440
    assert request["encumbered_cost_cents"] == 0


def test_projection_selection_ignores_other_years_other_campuses_and_older_rows(api):
    """PRD §3.3: "For each grade in that set, the server gathers the projection rows for
    the study's campus and `school_year` at that `grade_level`. Under the
    `DISTRICT_POLICY` variant both methodologies compete, so a later `DEVELOPER_YIELD`
    row can displace an earlier `COHORT_SURVIVAL` row for that grade; under the
    `STATE_LOADING_STANDARD` variant `DEVELOPER_YIELD` rows are dropped before selection,
    so the grade falls back to the newest `COHORT_SURVIVAL` row. Among the surviving
    candidates for a grade, exactly one row is selected: order the candidates by
    `created_at` descending, break ties on `projected_students` descending, and take the
    first." PRD §3.2: "summing the per-room seat counts over every `IN_SERVICE` room of
    the campus gives `gross_room_seats`", and the breakdown reports "the same total
    computed under each variant's source filter as `state_projected_total` and
    `district_projected_total`".

    Design: Corner/calculations/utilization_input_set_excludes_other_years_and_campuses
    """
    ctx = build_campus(api, clock=CLOCK,
                       school_overrides={"name": "Northside Middle"},
                       projections=())
    other_school = create_school(api, name="Southside Middle")
    create_room(api, other_school["id"], room_number="R901", area_sqft=900)

    create_projection(api, ctx["school_id"], 6, 20, source="COHORT_SURVIVAL")
    create_projection(api, ctx["school_id"], 6, 26, source="DEVELOPER_YIELD",
                      confidence_tier="MEDIUM")
    create_projection(api, ctx["school_id"], 7, 20)
    create_projection(api, ctx["school_id"], 8, 20)
    create_projection(api, ctx["school_id"], 6, 99, school_year="2028-29")
    create_projection(api, other_school["id"], 6, 40)

    study = create_study(api, ctx["school_id"], ctx["policy_id"])
    submitted = submit_study(api, study["id"])

    assert_capacity_fields(
        submitted,
        program_capacity_seats=56,
        projected_enrollment_total=66,
        utilization_pct=117.9,
        seat_deficit=13,
        required_portable_count=1,
    )

    breakdown = validate_success(
        api.get_capacity_breakdown(study["id"], PLANNER_HEADERS)
    )
    assert breakdown["district_projected_total"] == 66
    assert breakdown["state_projected_total"] == 60


def test_each_room_type_and_each_set_aside_carries_its_own_constant(api):
    """PRD §3.2: "take the room's `area_sqft`, divide it by the policy's
    `min_area_sqft_per_seat`, take the quotient downward to a whole number, and then take
    the smaller of that figure and the policy's `max_class_size` — that is the seat count
    for a `STANDARD_CLASSROOM`. A `SCIENCE_LAB` is treated identically except that the
    divisor is the policy's `min_area_sqft_per_seat` increased by its
    `lab_area_premium_sqft` ... A `SPED_RESOURCE` room contributes a fixed 12 seats,
    regardless of area. An `ART_MUSIC` room loads at half strength: compute the
    standard-classroom figure for that room exactly as described above, multiply it by
    0.50, and take the product downward to a whole number. A `GYM`, a `LIBRARY` and an
    `ADMIN` room each contribute 0 seats." "For each participating set-aside, count how
    many `IN_SERVICE` rooms of the campus have the set-aside's `reserved_room_type`, take
    the smaller of that count and the set-aside's `reserved_room_count`, and multiply by
    `seats_excluded_per_room`." Under `STATE_LOADING_STANDARD` each room instead takes
    "25 seats for a `STANDARD_CLASSROOM`, 24 for a `SCIENCE_LAB`, 12 for a
    `SPED_RESOURCE`, 25 for an `ART_MUSIC` room, and 0 each for `GYM`, `LIBRARY` and
    `ADMIN`", and "only set-asides whose `program_type` is `SPED_SELF_CONTAINED`
    participate".

    Design: Corner/calculations/program_capacity_constants_by_room_type_and_set_aside
    """
    ctx = build_campus(api, clock=CLOCK,
                       school_overrides={"name": "Riverbend Middle"},
                       room_areas=MIXED_AREAS, room_types=MIXED_TYPES,
                       projections=((6, 44), (7, 42), (8, 40)))
    create_set_aside(api, ctx["school_id"], program_type="SPED_SELF_CONTAINED",
                     reserved_room_type="SPED_RESOURCE", reserved_room_count=1,
                     seats_excluded_per_room=12)
    create_set_aside(api, ctx["school_id"], program_type="CTE_LAB",
                     reserved_room_type="SCIENCE_LAB", reserved_room_count=1,
                     seats_excluded_per_room=8)

    study = create_study(api, ctx["school_id"], ctx["policy_id"])
    submit_study(api, study["id"])

    breakdown = validate_success(
        api.get_capacity_breakdown(study["id"], PLANNER_HEADERS)
    )
    assert breakdown["method"] == "DISTRICT_POLICY"
    assert breakdown["gross_room_seats"] == 126
    assert breakdown["set_aside_deduction_seats"] == 20
    assert breakdown["program_capacity_seats"] == 106
    assert breakdown["district_policy_seats"] == 106
    assert breakdown["state_standard_seats"] == 124
    assert breakdown["projected_enrollment_total"] == 126
    assert breakdown["utilization_pct"] == 118.9
    assert breakdown["seat_deficit"] == 26
    assert breakdown["required_portable_count"] == 2


def test_a_utilization_tie_at_the_second_decimal_rounds_upward(api):
    """PRD §3.3: "`utilization_pct` is the projected enrolment total multiplied by 100,
    divided by `program_capacity_seats`, and rounded half up to one decimal place. The
    portable trigger fires when `utilization_pct` reaches 95.0 or more ... multiply
    `program_capacity_seats` by 95, divide by 100, and take the quotient downward to a
    whole number to obtain the campus's effective capacity at target loading. When the
    trigger has fired, `seat_deficit` is the projected enrolment total reduced by that
    effective capacity, clamped at 0 from below ... `required_portable_count` is the seat
    deficit divided by 24 — the seats a standard single-wide portable provides — with the
    quotient taken upward to the next whole number."

    Design: Corner/calculations/utilization_rounds_half_up_at_one_decimal
    """
    ctx = build_campus(api, clock=CLOCK,
                       school_overrides={"name": "Tinyfield Middle",
                                         "site_acreage": 4.0,
                                         "electrical_spare_capacity_kw": 20,
                                         "sewer_spare_connections": 1},
                       room_areas=(480, 480),
                       projections=((6, 14), (7, 14), (8, 14)))

    study = create_study(api, ctx["school_id"], ctx["policy_id"])
    submitted = submit_study(api, study["id"])

    assert_capacity_fields(
        submitted,
        program_capacity_seats=32,
        projected_enrollment_total=42,
        utilization_pct=131.3,
        portable_trigger_met=True,
        seat_deficit=12,
        required_portable_count=1,
    )
    assert submitted["utilization_pct"] != 131.2


def test_every_mitigation_flag_reappears_as_money_in_the_cost_model(api):
    """PRD §3.4: "The third step collects mitigations, appended in one fixed order. If
    the pad's `electrical_drop_available_kw` is less than the chassis's service draw,
    `ELECTRICAL_UPGRADE` is appended. If the chassis needs a sewer connection and
    `sewer_connection_available` is false, `SEWER_HOOKUP` is appended. If
    `ada_path_of_travel_compliant` is false, `ADA_PATH_UPGRADE` is appended. A pad that
    collects no flags is judged `FEASIBLE`; a pad that collects at least one is judged
    `FEASIBLE_WITH_MITIGATION`. In both cases `infeasible_reason` is set to null and
    `mitigation_flags` holds the collected list in that fixed order." "Assessment is
    re-enterable: a pad already carrying any verdict ... may be re-assessed against a
    different chassis at any time while it is unoccupied, and the new verdict wholly
    replaces the old one." PRD §3.6: "**Site work** is then added, conditional on the
    actual unit-and-pad pair: 1,850,000 cents when the pad's
    `electrical_drop_available_kw` is less than the chassis's service draw, 2,400,000
    cents when the chassis needs a sewer connection and the pad's
    `sewer_connection_available` is false, and 3,150,000 cents when either the unit's
    `ada_ramp_installed` is false or the pad's `ada_path_of_travel_compliant` is false."

    Design: Corner/calculations/site_feasibility_mitigations_propagate_to_cost_model
    """
    ctx = build_request_context(
        api, stage="draft", clock=CLOCK,
        school_overrides={"name": "Westgate Middle"},
        pad_overrides={"pad_code": "PAD-BIG", "pad_length_ft": 74, "pad_width_ft": 38,
                       "distance_to_fire_lane_ft": 60,
                       "electrical_drop_available_kw": 15,
                       "sewer_connection_available": False,
                       "ada_path_of_travel_compliant": False},
        assess_pad_for=None,
        unit_overrides={"asset_tag": "PU-J101", "size_class": "DOUBLE_28x64",
                        "condition_grade": "B", "ada_ramp_installed": False,
                        "acquisition_cost_cents": 15_000_000, "in_service_year": 2019},
        request_overrides={"haul_miles": 10},
    )

    assessed = validate_success(
        api.assess_placement_site(ctx["site_id"],
                                  {"candidate_size_class": "DOUBLE_28x64"},
                                  PLANNER_HEADERS)
    )
    assert assessed["feasibility_status"] == "FEASIBLE_WITH_MITIGATION"
    assert assessed["infeasible_reason"] is None
    assert assessed["mitigation_flags"] == ["ELECTRICAL_UPGRADE", "SEWER_HOOKUP",
                                            "ADA_PATH_UPGRADE"]
    assert assessed["assessed_for_size_class"] == "DOUBLE_28x64"

    model = validate_success(api.get_cost_model(ctx["request_id"], PLANNER_HEADERS))
    assert_cost_breakdown(model, {
        "mobilisation_cents": 7_580_000,
        "site_work_cents": 7_400_000,
        "rehab_cents": 1_250_000,
        "permit_fee_cents": 1_050_000,
        "direct_cost_cents": 17_280_000,
        "contingency_cents": 1_500_000,
        "estimated_relocation_cost_cents": 18_780_000,
    })

    single = validate_success(
        api.assess_placement_site(ctx["site_id"],
                                  {"candidate_size_class": "SINGLE_24x40"},
                                  PLANNER_HEADERS)
    )
    assert single["feasibility_status"] == "FEASIBLE_WITH_MITIGATION"
    assert single["mitigation_flags"] == ["ADA_PATH_UPGRADE"]
    assert single["assessed_for_size_class"] == "SINGLE_24x40"

    again = validate_success(
        api.assess_placement_site(ctx["site_id"],
                                  {"candidate_size_class": "DOUBLE_28x64"},
                                  PLANNER_HEADERS)
    )
    assert again["mitigation_flags"] == ["ELECTRICAL_UPGRADE", "SEWER_HOOKUP",
                                         "ADA_PATH_UPGRADE"]
    assert again["assessed_for_size_class"] == "DOUBLE_28x64"


def test_the_cost_model_defaults_to_the_lifecycle_basis_and_the_method_stays_pinned(api):
    """PRD §3.6: "Under the default 20-year lifecycle basis, the per-unit figure is this
    request's relocation estimate, plus 1,150,000 cents of annual operations and
    maintenance for each of 20 years, plus the size-class removal cost — 1,600,000 cents
    for a `SINGLE_24x40` ... **A boundary change** costs a fixed 4,200,000 cents of study
    work plus 96,000 cents of transport for each deficit seat for each of 5 years. **A
    permanent addition** costs 3,850,000 cents for each deficit seat." "a direct cost
    below 50,000,000 cents attracts 9 percent ... The soft cost is that percentage of the
    direct cost, rounded half up. The total program cost is the direct cost plus the soft
    cost". "The recommendation is the surviving option with the smallest total program
    cost." "The cost-model view accepts `basis` as a query parameter, defaults to the
    lifecycle basis when it is absent". PRD §3.2: the breakdown reports "the study's own
    `method` ... and the net program capacity under each variant separately as
    `state_standard_seats` and `district_policy_seats`".

    Design: Corner/calculations/cost_model_basis_defaults_to_lifecycle_and_method_is_frozen
    """
    ctx = build_request_context(
        api, stage="draft", clock=CLOCK,
        school_overrides={"name": "Northside Middle"},
        unit_overrides={"asset_tag": "PU-K101"},
    )

    model = validate_success(api.get_cost_model(ctx["request_id"], PLANNER_HEADERS))
    assert_cost_breakdown(model, {
        "relocation_direct_cents": 32_341_440,
        "relocation_soft_cost_cents": 2_910_730,
        "relocation_total_program_cost_cents": 35_252_170,
        "boundary_change_direct_cents": 7_560_000,
        "boundary_change_total_program_cost_cents": 8_240_400,
        "permanent_addition_direct_cents": 26_950_000,
        "permanent_addition_soft_cost_cents": 2_425_500,
        "permanent_addition_total_program_cost_cents": 29_375_500,
        "cost_recommendation": "BOUNDARY_CHANGE",
    })
    assert model["relocate_excluded_for_reliance"] is False

    request = validate_success(api.get_placement_request(ctx["request_id"],
                                                         PLANNER_HEADERS))
    assert request["cost_recommendation"] == "BOUNDARY_CHANGE"

    study = validate_success(api.get_capacity_study(ctx["study_id"], PLANNER_HEADERS))
    assert study["method"] == "DISTRICT_POLICY"

    breakdown = validate_success(
        api.get_capacity_breakdown(ctx["study_id"], PLANNER_HEADERS)
    )
    assert breakdown["method"] == "DISTRICT_POLICY"
    assert breakdown["program_capacity_seats"] == 56
    assert breakdown["state_standard_seats"] == 50
    assert breakdown["district_policy_seats"] == 56
