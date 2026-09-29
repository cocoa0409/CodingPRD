"""Two loading variants, two valuation bases and two cost bases on one dataset."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import ApiErrorId, ASSET_HEADERS, PLANNER_HEADERS
from test_helpers.assertions import assert_capacity_fields, assert_cost_breakdown
from test_helpers.factories import disposal_payload, unit_payload
from test_helpers.fixtures import (
    build_mixed_room_campus,
    create_request,
    create_site,
    create_study,
    create_unit,
    record_condition,
    set_clock,
    submit_study,
)


def _both_studies(api):
    """One campus carrying a district-policy study and a state-standard study."""
    ctx = build_mixed_room_campus(api)
    district = create_study(api, ctx["school_id"], ctx["policy_id"],
                            method="DISTRICT_POLICY")
    submit_study(api, district["id"])
    state = create_study(api, ctx["school_id"], ctx["policy_id"],
                         method="STATE_LOADING_STANDARD")
    submit_study(api, state["id"])
    ctx["district_study_id"] = district["id"]
    ctx["state_study_id"] = state["id"]
    return ctx


def test_capacity_breakdown_reports_both_loading_variants_side_by_side(api):
    """PRD §3.2: "Under the **`STATE_LOADING_STANDARD`** variant, area is ignored
    entirely and each room contributes a fixed statewide loading factor determined
    solely by its `room_type`: 25 seats for a `STANDARD_CLASSROOM`, 24 for a
    `SCIENCE_LAB`, 12 for a `SPED_RESOURCE`, 25 for an `ART_MUSIC` room, and 0 each
    for `GYM`, `LIBRARY` and `ADMIN`." and "under `STATE_LOADING_STANDARD` only
    set-asides whose `program_type` is `SPED_SELF_CONTAINED` participate", while it
    "recomputes both variants live against the campus's current rooms and set-asides
    and reports, side by side, the study's own `method`, the `gross_room_seats`,
    `set_aside_deduction_seats` and `program_capacity_seats` under that method, and
    the net program capacity under each variant separately as `state_standard_seats`
    and `district_policy_seats`."

    Design: Difficulty/dual_variant_calc/capacity_variant_state_loading_vs_district_policy
    """
    ctx = _both_studies(api)

    data = validate_success(
        api.get_capacity_breakdown(ctx["state_study_id"], PLANNER_HEADERS)
    )

    assert data["method"] == "STATE_LOADING_STANDARD"
    assert data["state_standard_seats"] == 124
    assert data["district_policy_seats"] == 106
    assert data["gross_room_seats"] == 136
    assert data["set_aside_deduction_seats"] == 12
    assert data["program_capacity_seats"] == 124
    assert data["state_projected_total"] == 126
    assert data["district_projected_total"] == 134
    assert data["projected_enrollment_total"] == 126
    assert data["utilization_pct"] == 101.6
    assert data["portable_trigger_met"] is True
    assert data["seat_deficit"] == 9
    assert data["required_portable_count"] == 1


def test_district_policy_study_freezes_area_driven_capacity_on_the_same_campus(api):
    """PRD §3.2: "For each `IN_SERVICE` room of the campus, take the room's
    `area_sqft`, divide it by the policy's `min_area_sqft_per_seat`, take the
    quotient downward to a whole number, and then take the smaller of that figure
    and the policy's `max_class_size`", where "A `SCIENCE_LAB` is treated
    identically except that the divisor is the policy's `min_area_sqft_per_seat`
    increased by its `lab_area_premium_sqft`", "A `SPED_RESOURCE` room contributes a
    fixed 12 seats, regardless of area" and "An `ART_MUSIC` room loads at half
    strength". PRD §3.3: "`utilization_pct` is the projected enrolment total
    multiplied by 100, divided by `program_capacity_seats`, and rounded half up to
    one decimal place."

    Design: Difficulty/dual_variant_calc/capacity_variant_state_loading_vs_district_policy
    """
    ctx = _both_studies(api)

    data = validate_success(
        api.get_capacity_study(ctx["district_study_id"], PLANNER_HEADERS)
    )

    assert_capacity_fields(
        data,
        gross_room_seats=126,
        set_aside_deduction_seats=20,
        program_capacity_seats=106,
        projected_enrollment_total=134,
        utilization_pct=126.4,
        portable_trigger_met=True,
        seat_deficit=34,
        required_portable_count=2,
    )


def _four_condemned_grade_c_units(api):
    """Four byte-identical grade C units, all condemned and still in storage."""
    set_clock(api, "2027-03-15T00:00:00Z")
    unit_ids = []
    for tag in ("PU-1001", "PU-1002", "PU-1003", "PU-1004"):
        unit = create_unit(api, asset_tag=tag, condition_grade="C",
                           ada_ramp_installed=False,
                           acquisition_cost_cents=9_600_000, in_service_year=2011)
        record_condition(api, unit["id"], "UNSAFE", "C")
        unit_ids.append(unit["id"])
    return unit_ids


def test_scrap_salvage_diverges_between_straight_line_and_condition_adjusted(api):
    """PRD §3.9: "Under the `STRAIGHT_LINE` basis, `salvage_value_cents` is exactly
    that straight-line figure — a pure age-based book value with a 5 percent floor,
    ignoring condition entirely. Under the `CONDITION_ADJUSTED` basis, the
    already-rounded straight-line figure is multiplied by the grade multiplier —
    1.00 for grade `A`, 0.80 for grade `B`, 0.55 for grade `C`, 0.25 for grade `D` —
    the product is rounded half up, and the result is then lifted to a floor equal
    to 5 percent of `acquisition_cost_cents` rounded half up."

    Design: Difficulty/dual_variant_calc/salvage_variant_straight_line_vs_condition_adjusted
    """
    straight_line_unit, condition_unit, _, _ = _four_condemned_grade_c_units(api)

    straight_line = validate_success(
        api.create_disposal_record(
            disposal_payload(straight_line_unit, valuation_basis="STRAIGHT_LINE"),
            ASSET_HEADERS,
        ),
        expected_status=201,
    )
    condition_adjusted = validate_success(
        api.create_disposal_record(
            disposal_payload(condition_unit, valuation_basis="CONDITION_ADJUSTED"),
            ASSET_HEADERS,
        ),
        expected_status=201,
    )

    assert straight_line["salvage_value_cents"] == 1_920_000
    assert straight_line["net_disposal_result_cents"] == -1_920_000
    assert condition_adjusted["salvage_value_cents"] == 1_056_000
    assert condition_adjusted["net_disposal_result_cents"] == -1_056_000


def test_sale_recovery_gate_verdict_flips_with_the_valuation_basis(api):
    """PRD §3.9: "A `SALE` requires `proceeds_cents` to be at least 70 percent of the
    computed `salvage_value_cents`, rounded half up" and "Because the two valuation
    bases can produce materially different salvage figures for the same unit, the
    same unit and the same proceeds may pass the recovery test on one basis and fail
    it on the other."

    Design: Difficulty/dual_variant_calc/salvage_variant_straight_line_vs_condition_adjusted
    """
    _, _, sale_straight_line_unit, sale_condition_unit = _four_condemned_grade_c_units(api)

    rejected = api.create_disposal_record(
        disposal_payload(sale_straight_line_unit, method="SALE",
                         valuation_basis="STRAIGHT_LINE", proceeds_cents=800_000),
        ASSET_HEADERS,
    )
    validate_error(rejected, ApiErrorId.DISPOSAL_UNDERVALUED)

    accepted = validate_success(
        api.create_disposal_record(
            disposal_payload(sale_condition_unit, method="SALE",
                             valuation_basis="CONDITION_ADJUSTED",
                             proceeds_cents=800_000),
            ASSET_HEADERS,
        ),
        expected_status=201,
    )
    assert accepted["salvage_value_cents"] == 1_056_000
    assert accepted["net_disposal_result_cents"] == -256_000


def _request_on_underserved_pad(api):
    """A request for one grade B single-wide onto a pad short of electrical service."""
    ctx = build_mixed_room_campus(api)
    ctx["site_id"] = create_site(api, ctx["school_id"], pad_code="PAD-A",
                                 electrical_drop_available_kw=8)["id"]
    unit = validate_success(
        api.create_portable_unit(
            unit_payload(asset_tag="PU-2001", condition_grade="B",
                         ada_ramp_installed=True,
                         acquisition_cost_cents=9_600_000, in_service_year=2019),
            ASSET_HEADERS,
        ),
        expected_status=201,
    )
    ctx["unit_id"] = unit["id"]
    study = create_study(api, ctx["school_id"], ctx["policy_id"],
                         method="DISTRICT_POLICY")
    submit_study(api, study["id"])
    ctx["study_id"] = study["id"]
    ctx["request_id"] = create_request(
        api, study["id"], ctx["site_id"], ctx["budget_id"],
        haul_miles=14, portable_unit_id=unit["id"],
    )["id"]
    return ctx


def test_cost_model_on_the_immediate_capital_basis_recommends_relocation(api):
    """PRD §3.6: "Under the immediate-capital basis the per-unit figure is the
    relocation estimate alone, with no operations, maintenance or removal carried."
    The estimate itself is built from "the chassis move base — 4,500,000 cents for a
    `SINGLE_24x40`" plus "38,000 cents for each of the request's `haul_miles`",
    "1,850,000 cents when the pad's `electrical_drop_available_kw` is less than the
    chassis's service draw", "1,250,000 cents for grade `B`", "210,000 cents for each
    discipline in the required permit set" and a contingency of "12 percent of that
    direct cost, rounded half up".

    Design: Difficulty/dual_variant_calc/cost_basis_variant_lifecycle_vs_immediate_capital
    """
    ctx = _request_on_underserved_pad(api)

    data = validate_success(
        api.get_cost_model(ctx["request_id"], PLANNER_HEADERS,
                           {"basis": "IMMEDIATE_CAPITAL"})
    )

    assert data["basis"] == "IMMEDIATE_CAPITAL"
    assert_cost_breakdown(data, {
        "mobilisation_cents": 5_032_000,
        "site_work_cents": 1_850_000,
        "rehab_cents": 1_250_000,
        "permit_fee_cents": 630_000,
        "direct_cost_cents": 8_762_000,
        "contingency_cents": 1_051_440,
        "estimated_relocation_cost_cents": 9_813_440,
        "relocation_direct_cents": 19_626_880,
        "relocation_soft_cost_cents": 1_766_419,
        "relocation_total_program_cost_cents": 21_393_299,
        "boundary_change_total_program_cost_cents": 22_366_800,
        "cost_recommendation": "RELOCATE",
    })


def test_cost_model_on_the_lifecycle_basis_recommends_a_boundary_change(api):
    """PRD §3.6: "Under the default 20-year lifecycle basis, the per-unit figure is
    this request's relocation estimate, plus 1,150,000 cents of annual operations and
    maintenance for each of 20 years, plus the size-class removal cost — 1,600,000
    cents for a `SINGLE_24x40`" and "the value stored on the request is always the one
    computed under the 20-year lifecycle basis — the basis that carries two decades of
    operations and the eventual removal, which frequently pushes relocation into a
    higher soft-cost tier and can flip the recommendation away from `RELOCATE`."

    Design: Difficulty/dual_variant_calc/cost_basis_variant_lifecycle_vs_immediate_capital
    """
    ctx = _request_on_underserved_pad(api)

    data = validate_success(
        api.get_cost_model(ctx["request_id"], PLANNER_HEADERS,
                           {"basis": "LIFECYCLE_20YR"})
    )
    assert_cost_breakdown(data, {
        "relocation_direct_cents": 68_826_880,
        "relocation_soft_cost_cents": 8_947_494,
        "relocation_total_program_cost_cents": 77_774_374,
        "cost_recommendation": "BOUNDARY_CHANGE",
    })

    stored = validate_success(
        api.get_placement_request(ctx["request_id"], PLANNER_HEADERS)
    )
    assert stored["cost_recommendation"] == "BOUNDARY_CHANGE"
