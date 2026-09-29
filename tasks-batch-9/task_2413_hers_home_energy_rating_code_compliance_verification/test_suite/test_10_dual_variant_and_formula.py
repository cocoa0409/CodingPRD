"""Depth tests for the `dual_variant_calc` and `combinatorial_formula` rules.

Every test below translates exactly one non-stub instance of
`SCAFFOLD_DIFFICULTY_DESIGN.yaml`; the trailing `Design:` line of each docstring
names the instance it came from.
"""

from typing import Any, Dict

from test_helpers.api_client import ApiClient
from test_helpers.assertions import (
    assert_builder_ledger,
    assert_cents,
    assert_home_sampling_state,
    assert_index,
    assert_line_items,
    assert_normalized_value,
    assert_package_state,
    assert_rating_dimensions,
    assert_sample_set_counters,
)
from test_helpers.fixtures import (
    build_confirmed_world,
    build_sample_world,
    close_sample_set,
    complete_inspection,
    confirm_rating,
    create_builder,
    create_plan_model,
    create_rater,
    create_subdivision,
    draft_package,
    get_builder,
    get_home,
    get_rating,
    get_sample_set,
    issue_package,
    record_test,
    schedule_inspection,
    select_sample_set,
)

# --- plan catalogues used by the instances below -----------------------------
SOLAR_2400 = {
    "plan_code": "SOLAR-2400",
    "envelope_ua_btu_per_hr_f": 340,
    "hvac_efficiency_index": 16,
    "pv_capacity_kw_dc": 3.0,
}

ODD_2135 = {
    "plan_code": "ODD-2135",
    "conditioned_floor_area_sqft": 2135,
    "conditioned_volume_cuft": 19215,
    "bedrooms": 3,
    "envelope_ua_btu_per_hr_f": 300,
    "design_ach50": 3.00,
    "design_duct_leakage_cfm25_per_100sqft": 3.00,
    "hvac_efficiency_index": 9,
    "pv_capacity_kw_dc": 0,
}

BIG_3000 = {
    "plan_code": "BIG-3000",
    "conditioned_floor_area_sqft": 3000,
    "conditioned_volume_cuft": 27000,
    "bedrooms": 5,
    "envelope_ua_btu_per_hr_f": 520,
    "design_ach50": 4.00,
    "design_duct_leakage_cfm25_per_100sqft": 4.00,
    "hvac_efficiency_index": 8,
    "pv_capacity_kw_dc": 0,
}

PERF_2400 = {
    "plan_code": "PERF-2400",
    "conditioned_floor_area_sqft": 2400,
    "conditioned_volume_cuft": 21600,
    "bedrooms": 3,
    "envelope_ua_btu_per_hr_f": 336,
    "design_ach50": 3.00,
    "design_duct_leakage_cfm25_per_100sqft": 3.00,
    "hvac_efficiency_index": 5,
    "pv_capacity_kw_dc": 0,
}

LOW_2200 = {
    "plan_code": "LOW-2200",
    "conditioned_floor_area_sqft": 2200,
    "conditioned_volume_cuft": 19800,
    "bedrooms": 3,
    "envelope_ua_btu_per_hr_f": 290,
    "design_ach50": 2.50,
    "design_duct_leakage_cfm25_per_100sqft": 2.50,
    "hvac_efficiency_index": 10,
    "pv_capacity_kw_dc": 0,
}


def _final_checkpoint(
    api: ApiClient,
    rating_id: str,
    inspector_id: str,
    blower_door: float,
    duct_leakage: float,
    *,
    scheduled_start_utc: str = "2026-08-20T09:00:00Z",
    scheduled_end_utc: str = "2026-08-20T11:00:00Z",
) -> Dict[str, Any]:
    """Schedule a FINAL checkpoint, record both governing tests and close it."""
    inspection = schedule_inspection(
        api,
        rating_id,
        inspector_id,
        checkpoint="FINAL",
        scheduled_start_utc=scheduled_start_utc,
        scheduled_end_utc=scheduled_end_utc,
        air_handler_installed=True,
    )
    record_test(api, inspection["id"], inspector_id, "BLOWER_DOOR", blower_door)
    record_test(api, inspection["id"], inspector_id, "DUCT_LEAKAGE_TOTAL", duct_leakage)
    return complete_inspection(api, inspection["id"], inspector_id)


def _cedar_run_confirmed(api: ApiClient, *, blower_door: float, duct_leakage: float):
    """Meridian Homes / Cedar Run: three plans, three lots, one selected and
    confirmed tested home, leaving the set at `TESTED`."""
    world = build_sample_world(
        api,
        member_count=3,
        builder_name="Meridian Homes",
        subdivision_name="Cedar Run",
        utility_program_budget_cents=500000,
        lot_numbers=["L-1", "L-2", "L-3"],
        permit_dates=["2026-08-05", "2026-08-06", "2026-08-07"],
        plan_overrides_per_home=[BIG_3000, PERF_2400, LOW_2200],
        window_start_date="2026-08-01",
        window_end_date="2026-08-31",
    )
    select_sample_set(api, world.sample_set_id)
    _final_checkpoint(
        api, world.ratings[0]["id"], world.base.inspector_id, blower_door, duct_leakage
    )
    confirm_rating(api, world.ratings[0]["id"], world.rater_id)
    # §3.4 advances the set from SELECTED to TESTED as a side effect of the
    # confirmation, so the set is re-read after it rather than before.
    world.sample_set = get_sample_set(api, world.sample_set_id)
    return world


# ============================================================ dual_variant_calc
def test_projected_index_survives_confirmation_on_the_same_home(api: ApiClient) -> None:
    """Plan STD-2400 projects 43 and the as-built confirmation writes 46 beside it.

    PRD §3.4: "Because the same home routinely lands on a different index as built than it did on paper, the confirmed and projected numbers coexist on the rating permanently and neither overwrites the other."

    Design: Difficulty/dual_variant_calc/projected_vs_confirmed_hers_index_diverge_on_same_home
    """
    world = build_confirmed_world(
        api,
        builder_name="Cardinal Homes",
        subdivision_name="Larkspur Phase 1",
        utility_program_budget_cents=500000,
        lot_number="L-101",
        permit_date="2026-08-03",
        blower_door=1080,
        duct_leakage=96,
    )
    assert_index(world.plan_model["projected_index"], 43)
    rating = get_rating(api, world.rating_id)
    assert_index(rating["projected_index"], 43)
    assert_index(rating["confirmed_index"], 46)


def test_confirmed_variant_reads_the_measured_normalized_values(api: ApiClient) -> None:
    """1080 CFM50 normalizes to 3.00 and 96 CFM25 to 4.00, and those two figures —
    not the plan's 3.00 / 3.00 design pair — drive `confirmed_index` 46.

    PRD §3.4: "It re-runs the HERS index routine of §3.1 in its **confirmed variant** — identical arithmetic, but with the measured, normalized `confirmed_ach50` standing in for the plan's `design_ach50` and the measured `confirmed_duct_leakage_cfm25_per_100sqft` standing in for the plan's `design_duct_leakage_cfm25_per_100sqft` — and writes the result into `confirmed_index`."

    Design: Difficulty/dual_variant_calc/projected_vs_confirmed_hers_index_diverge_on_same_home
    """
    world = build_confirmed_world(
        api,
        builder_name="Cardinal Homes",
        subdivision_name="Larkspur Phase 1",
        lot_number="L-101",
        blower_door=1080,
        duct_leakage=96,
    )
    rating = get_rating(api, world.rating_id)
    assert_normalized_value(rating["confirmed_ach50"], 3.00)
    assert_normalized_value(rating["confirmed_duct_leakage_cfm25_per_100sqft"], 4.00)
    assert_index(rating["confirmed_index"], 46)


def test_confirmation_snapshots_the_eri_target_and_passes_on_the_eri_path(
    api: ApiClient,
) -> None:
    """`IECC_2021` / `CZ4` snapshots an ERI target of 55, and confirmed index 46
    clears it with both instrument tests passing.

    PRD §3.4: "If `confirmed_index` is less than or equal to the ERI target, and the airtightness test passes, and the duct test passes, then `compliance_path` becomes `ERI` and `compliance_status` becomes `PASSING`."

    Design: Difficulty/dual_variant_calc/projected_vs_confirmed_hers_index_diverge_on_same_home
    """
    world = build_confirmed_world(
        api,
        builder_name="Cardinal Homes",
        subdivision_name="Larkspur Phase 1",
        lot_number="L-101",
        blower_door=1080,
        duct_leakage=96,
    )
    rating = get_rating(api, world.rating_id)
    assert_index(rating["eri_target"], 55)
    assert rating["compliance_path"] == "ERI", rating
    assert_rating_dimensions(rating, stage="CONFIRMED", compliance_status="PASSING")


def test_provisional_tax_credit_amount_reads_the_projected_index_tier(
    api: ApiClient,
) -> None:
    """Drafting reads projected index 43 and lands in the 250,000-cent tier while
    `certified_amount_cents` is still null.

    PRD §3.9: "An index of 45 or lower earns 250,000 cents — two thousand five hundred dollars."

    Design: Difficulty/dual_variant_calc/provisional_vs_certified_tax_credit_amount_diverge
    """
    world = build_confirmed_world(
        api,
        builder_name="Cardinal Homes",
        subdivision_name="Larkspur Phase 1",
        utility_program_budget_cents=500000,
        lot_number="L-101",
        blower_door=1080,
        duct_leakage=96,
    )
    package = draft_package(api, world.rating_id, world.builder_id, "TAX_CREDIT_45L")
    assert_package_state(
        package,
        status="DRAFT",
        provisional_amount_cents=250000,
        certified_amount_cents=None,
    )
    assert package["line_items"] == [], package


def test_certified_tax_credit_amount_reads_the_confirmed_index_tier(
    api: ApiClient,
) -> None:
    """Issuance recomputes on confirmed index 46, which falls in the second tier at
    100,000 cents, and only that certified figure moves the builder's ledger.

    PRD §3.9: "Only the certified figure ever moves `certified_incentive_cents`."

    Design: Difficulty/dual_variant_calc/provisional_vs_certified_tax_credit_amount_diverge
    """
    world = build_confirmed_world(
        api,
        builder_name="Cardinal Homes",
        subdivision_name="Larkspur Phase 1",
        utility_program_budget_cents=500000,
        lot_number="L-101",
        blower_door=1080,
        duct_leakage=96,
    )
    package = draft_package(api, world.rating_id, world.builder_id, "TAX_CREDIT_45L")
    issued = issue_package(api, package["id"])
    assert_package_state(
        issued,
        status="ISSUED",
        provisional_amount_cents=250000,
        certified_amount_cents=100000,
    )
    assert issued["line_items"] == [], issued
    assert_builder_ledger(get_builder(api, world.builder_id), certified_incentive_cents=100000)


# ========================================================= combinatorial_formula
def test_equipment_multiplier_floor_and_capped_pv_credit_under_iecc_2021(
    api: ApiClient,
) -> None:
    """`hvac_efficiency_index` 16 would drive the multiplier to 0.55 but is held at
    the 0.62 floor, and a 3.0 kW array's 12 points are clipped to 5.0, giving 26.

    PRD §3.1: "Second, an **equipment multiplier** is derived from the plan's `hvac_efficiency_index`: take 1.35, subtract 0.05 multiplied by the efficiency index, then clamp the result into the closed range from 0.62 to 1.05 — that is, any value above 1.05 becomes exactly 1.05 and any value below 0.62 becomes exactly 0.62."

    Design: Difficulty/combinatorial_formula/hers_index_nonlinear_clamp_and_pv_cap
    """
    builder = create_builder(
        api,
        name="Solstice Builders",
        builder_type="PRODUCTION",
        utility_program_budget_cents=500000,
    )
    rater = create_rater(api)
    subdivision = create_subdivision(
        api,
        builder["id"],
        name="Sunfield 2021",
        code_edition="IECC_2021",
        climate_zone="CZ4",
        sampling_enabled=False,
        compliance_path_preference="ERI_PATH",
    )
    plan = create_plan_model(api, subdivision["id"], rater["id"], **SOLAR_2400)
    assert_index(plan["projected_index"], 26)
    assert plan["status"] == "ACTIVE", plan


def test_same_plan_earns_the_uncapped_pv_credit_under_iecc_2015(api: ApiClient) -> None:
    """The identical plan inputs land on 19 under `IECC_2015`, seven points below
    the `IECC_2021` result, because the photovoltaic cap is the only difference.

    PRD §2.7: "Under `IECC_2015` the cap is 100.0 points, which in practice means the credit is uncapped for any realistic array."

    Design: Difficulty/combinatorial_formula/hers_index_nonlinear_clamp_and_pv_cap
    """
    builder = create_builder(
        api,
        name="Solstice Builders",
        builder_type="PRODUCTION",
        utility_program_budget_cents=500000,
    )
    rater = create_rater(api)
    sd_2021 = create_subdivision(
        api,
        builder["id"],
        name="Sunfield 2021",
        code_edition="IECC_2021",
        climate_zone="CZ4",
        sampling_enabled=False,
        compliance_path_preference="ERI_PATH",
    )
    sd_2015 = create_subdivision(
        api,
        builder["id"],
        name="Sunfield 2015",
        code_edition="IECC_2015",
        climate_zone="CZ4",
        sampling_enabled=False,
        compliance_path_preference="ERI_PATH",
    )
    plan_2021 = create_plan_model(api, sd_2021["id"], rater["id"], **SOLAR_2400)
    plan_2015 = create_plan_model(api, sd_2015["id"], rater["id"], **SOLAR_2400)
    assert_index(plan_2015["projected_index"], 19)
    assert plan_2021["projected_index"] - plan_2015["projected_index"] == 7, (
        plan_2021["projected_index"],
        plan_2015["projected_index"],
    )


def test_utility_line_items_are_rounded_before_they_are_summed(api: ApiClient) -> None:
    """On CFA 2135 the ENVELOPE line rounds 80062.5 up to 80063 and the DUCTS line
    rounds 837.5 up to 838; the pinned order therefore totals 113481 rather than
    the 113480 a sum-then-round implementation reports.

    PRD §3.9: "For a **`UTILITY_PROGRAM`** package the amount is the sum of four per-measure line items, computed in a pinned rounding order that must not be rearranged: **each line item is rounded to whole cents first, the rounded line items are then summed, and the cap is applied last.**"

    Design: Difficulty/combinatorial_formula/utility_package_line_item_rounding_order
    """
    world = build_confirmed_world(
        api,
        builder_name="Halcyon Homes",
        subdivision_name="Odd Acres",
        utility_program_budget_cents=500000,
        plan_overrides=ODD_2135,
        lot_number="L-207",
        permit_date="2026-08-03",
        blower_door=890,
        duct_leakage=71,
    )
    package = draft_package(api, world.rating_id, world.builder_id, "UTILITY_PROGRAM")
    issued = issue_package(api, package["id"])
    assert_line_items(
        issued,
        [("ENVELOPE", 80063), ("DUCTS", 838), ("AIR", 3330), ("INDEX", 29250)],
    )
    assert_cents(issued["certified_amount_cents"], 113481)


def test_utility_provisional_amount_reads_the_plan_design_figures(api: ApiClient) -> None:
    """The provisional figure uses projected index 46 with design duct 3.00 and
    design air 3.00, totalling 115813 cents before anyone has been on site.

    PRD §3.9: "The two variants read different inputs and that is the entire point: the provisional figure uses the rating's `projected_index` together with the pinned plan's `design_ach50` and `design_duct_leakage_cfm25_per_100sqft`, all paper values available before anyone has been on site, while the certified figure uses the rating's `confirmed_index` together with the measured `confirmed_ach50` and `confirmed_duct_leakage_cfm25_per_100sqft`."

    Design: Difficulty/combinatorial_formula/utility_package_line_item_rounding_order
    """
    world = build_confirmed_world(
        api,
        builder_name="Halcyon Homes",
        subdivision_name="Odd Acres",
        utility_program_budget_cents=500000,
        plan_overrides=ODD_2135,
        lot_number="L-207",
        blower_door=890,
        duct_leakage=71,
    )
    assert_index(get_rating(api, world.rating_id)["projected_index"], 46)
    package = draft_package(api, world.rating_id, world.builder_id, "UTILITY_PROGRAM")
    assert_package_state(package, status="DRAFT", provisional_amount_cents=115813)


def test_certified_utility_amount_moves_the_ledger_by_the_rounded_total(
    api: ApiClient,
) -> None:
    """Measured 2.78 ACH50 and 3.33 CFM25 per 100 sqft produce confirmed index 47,
    and the resulting 113481 cents is exactly what lands on the builder's ledger.

    PRD §3.9: "A successful issuance recomputes the certified variant into `certified_amount_cents` and rewrites `line_items` from the measured values, sets `status` to `ISSUED`, stamps `issued_at` from the logical clock, and raises the builder's `certified_incentive_cents` by the certified amount."

    Design: Difficulty/combinatorial_formula/utility_package_line_item_rounding_order
    """
    world = build_confirmed_world(
        api,
        builder_name="Halcyon Homes",
        subdivision_name="Odd Acres",
        utility_program_budget_cents=500000,
        plan_overrides=ODD_2135,
        lot_number="L-207",
        blower_door=890,
        duct_leakage=71,
    )
    rating = get_rating(api, world.rating_id)
    assert_index(rating["confirmed_index"], 47)
    assert_normalized_value(rating["confirmed_ach50"], 2.78)
    assert_normalized_value(rating["confirmed_duct_leakage_cfm25_per_100sqft"], 3.33)
    package = draft_package(api, world.rating_id, world.builder_id, "UTILITY_PROGRAM")
    issue_package(api, package["id"])
    assert_builder_ledger(get_builder(api, world.builder_id), certified_incentive_cents=113481)


def test_representative_index_is_the_maximum_over_tested_members_only(
    api: ApiClient,
) -> None:
    """The tested home L-1 confirms at 54, and closure writes 54 — not the 55 that
    folding sibling L-2's projected index into the maximum would produce.

    PRD §3.5: "Step two reduces that collection to its maximum — the worst-performing tested home — and writes it into the set's `representative_index`; because exactly one home per set is ever `TESTED`, that maximum is in practice that single home's confirmed index, and there is no rounding since the inputs are already whole numbers."

    Design: Difficulty/combinatorial_formula/sample_set_representative_index_evaluation_order
    """
    world = _cedar_run_confirmed(api, blower_door=810, duct_leakage=90)
    assert_sample_set_counters(
        world.sample_set, status="TESTED", tested_home_id=world.homes[0]["id"]
    )
    assert_index(get_rating(api, world.ratings[0]["id"])["confirmed_index"], 54)
    closed = close_sample_set(api, world.sample_set_id)
    assert_sample_set_counters(
        closed, status="CLOSED_PASS", representative_index=54, represented_member_count=2
    )


def test_represented_homes_inherit_the_index_without_feeding_it_back(
    api: ApiClient,
) -> None:
    """L-2 and L-3 become `REPRESENTED` and receive confirmed index 54 while their
    own projected indices of 55 and 40 stay untouched and outside the maximum.

    PRD §3.5: "The values written in step three are never fed back into steps one or two: a represented home's projected index and its newly assigned confirmed index lie outside the input set of the maximum."

    Design: Difficulty/combinatorial_formula/sample_set_representative_index_evaluation_order
    """
    world = _cedar_run_confirmed(api, blower_door=810, duct_leakage=90)
    close_sample_set(api, world.sample_set_id)
    for home in (world.homes[1], world.homes[2]):
        assert_home_sampling_state(get_home(api, home["id"]), sampling_role="REPRESENTED")
    perf = get_rating(api, world.ratings[1]["id"])
    low = get_rating(api, world.ratings[2]["id"])
    assert_index(perf["confirmed_index"], 54)
    assert_index(low["confirmed_index"], 54)
    assert_index(perf["projected_index"], 55)
    assert_index(low["projected_index"], 40)
