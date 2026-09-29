"""Derived-figure arithmetic across the plant.

These tests pin the computed outputs the PRD specifies: the recipe blend
figures and their rounding order (PRD 2.6, 3.1), the SKU warranty-term ladder
and its caps (PRD 3.3), the required-coverage list and the graded spec limits of
the laboratory (PRD 3.4), the changeover-gap input set on a press line (PRD
3.6), the licensed-volume and royalty ledger read back as a utilization summary
(PRD 3.2, 3.6), the allocation fill waterfall (PRD 3.8) and the warranty
settlement decay with its manufacturing-defect override (PRD 3.9).
"""

from test_helpers import (
    F_MIN_COMPONENTS,
    F_STD_COMPONENTS,
    PLANT_ADMIN,
    PRODUCTION_PLANNER,
    QA_TECHNICIAN,
    TECHNICAL_DIRECTOR,
    abort_run,
    adjudicate_claim,
    assert_blend_metrics,
    assert_warranty_terms,
    batch_of_run,
    begin_testing,
    build_approved_formulation,
    build_draft_formulation,
    build_passed_panel,
    build_released_sku,
    build_stock_batch,
    complete_run,
    create_allocation,
    create_click_lock_sku,
    create_claim,
    create_distributor,
    create_license,
    create_panel,
    create_press_line,
    create_print_film,
    create_run,
    create_sku,
    fill_allocation,
    get_success_data,
    record_result,
    record_review,
    run_to_completion,
    set_clock,
    set_qc_disposition,
    start_panel,
    triage_claim,
    validate_paginated,
    validate_success,
)


def test_blend_metrics_on_a_three_category_recipe(api):
    """A resin/plasticizer/filler recipe reports all eight blend figures, with both
    penalties at zero because the plasticizer ratio lands exactly on 0.25.

    "The four category subtotals — `resin_phr`, `plasticizer_phr`, `filler_phr` and
    `stabilizer_phr` — are the sums of the `phr` of the components whose material sits
    in the corresponding category, each rounded half up to two decimal places, and
    `total_phr` is the sum of `phr` across all components, likewise at two decimal
    places."
    "For each component, multiply its `phr` by the per-kilogram cost that the recipe's
    cost basis dictates: while `cost_basis` is `LIVE`, that is the material's current
    `cost_per_kg_cents`; once `cost_basis` is `PINNED`, it is the component's own
    `material_cost_snapshot_cents`."
    "Add those products together, divide the total by `total_phr`, and round half up to
    a whole cent."
    "The `performance_score` is built from three dosage-weighted blend indices, each
    carried to six decimal places and each computed as the sum over components of `phr`
    multiplied by the relevant material property, divided by `total_phr`: the blended
    indentation index uses `indentation_index` directly; the blended thermal index uses
    `thermal_stability_index` directly; and the blended migration-resistance index uses
    100 minus the material's `plasticizer_migration_index`, so that a migration-prone
    plasticizer drags the blend down."
    "Those three indices are weighted at forty percent, thirty-five percent and twenty-five
    percent respectively and added together."
    "The softness penalty reads the plasticizer ratio — `plasticizer_phr` divided by
    `resin_phr`, rounded half up to four decimal places — and is 12 points when that
    ratio is greater than 0.35, 5 points when it is greater than 0.25 but not greater
    than 0.35, and zero otherwise."
    "The brittleness penalty reads the filler ratio — `filler_phr` divided by
    `resin_phr`, also at four decimal places — and is 8 points when that ratio is at
    least 3.00, 3 points when it is at least 2.00 but below 3.00, and zero otherwise."
    "The `indentation_resistance_class` is derived from the blended indentation index
    **alone**, never from `performance_score`: the class is `CLASS_34_43` when that index
    is at least 88.00, `CLASS_33_42` when it is at least 70.00 but below 88.00, and
    `CLASS_23_31` otherwise."

    Design: Corner/calculations/blend_metrics_correct_result_on_three_category_recipe
    """
    set_clock(api, "2026-08-01T00:00:00Z")

    built = build_draft_formulation(api, "F-STD", F_STD_COMPONENTS)
    recipe = built["formulation"]

    assert recipe["resin_phr"] == 100.00
    assert recipe["plasticizer_phr"] == 25.00
    assert recipe["filler_phr"] == 40.00
    assert recipe["stabilizer_phr"] == 0.00
    assert_blend_metrics(
        recipe,
        total_phr=165.00,
        blended_cost_per_kg_cents=165,
        performance_score=80.39,
        indentation_resistance_class="CLASS_33_42",
    )


def test_blend_indices_are_not_rounded_before_the_single_final_rounding(api):
    """The two-component recipe scores 89.28, the value produced by carrying the three
    blend indices at six decimals into one final rounding.

    "The `performance_score` is built from three dosage-weighted blend indices, each
    carried to six decimal places and each computed as the sum over components of `phr`
    multiplied by the relevant material property, divided by `total_phr`: the blended
    indentation index uses `indentation_index` directly; the blended thermal index uses
    `thermal_stability_index` directly; and the blended migration-resistance index uses
    100 minus the material's `plasticizer_migration_index`, so that a migration-prone
    plasticizer drags the blend down."
    "The result is clamped to the range 0 through 100, taking whichever of the clamp
    bounds applies, and only then rounded half up to two decimal places."
    "That single final rounding is the contract; the six-decimal indices must not be
    rounded to two decimals on the way."
    "The three blend indices behind a recipe's performance score are each carried to six
    decimal places, and the score is rounded to two decimal places exactly once, after
    clamping."
    "Rounding the indices to two decimals first is a different, incorrect result."
    "Add those products together, divide the total by `total_phr`, and round half up to
    a whole cent."
    "The `indentation_resistance_class` is derived from the blended indentation index
    **alone**, never from `performance_score`: the class is `CLASS_34_43` when that index
    is at least 88.00, `CLASS_33_42` when it is at least 70.00 but below 88.00, and
    `CLASS_23_31` otherwise."

    Design: Corner/calculations/blend_indices_carried_at_six_decimals_before_the_single_rounding
    """
    set_clock(api, "2026-08-01T00:00:00Z")

    built = build_draft_formulation(api, "F-MIN", F_MIN_COMPONENTS)
    recipe = built["formulation"]

    assert_blend_metrics(
        recipe,
        total_phr=103.00,
        blended_cost_per_kg_cents=201,
        performance_score=89.28,
        indentation_resistance_class="CLASS_34_43",
    )
    assert recipe["performance_score"] != 89.29, (
        "89.29 is the result of pre-rounding the three indices to two decimals"
    )


def test_changeover_gap_measured_against_the_run_before_the_aborted_one(api):
    """Setup charges 30 minutes, computed against the earlier same-recipe run, because
    the chronologically nearest predecessor was aborted and leaves the input set.

    "The relevant predecessor is the run on the same line with the greatest
    `planned_end_utc` that is no later than the new run's `planned_start_utc` and whose
    `run_status` is not `ABORTED`, with ties broken by the earlier `created_at`; an
    aborted predecessor is skipped entirely, so the gap is measured against whatever ran
    before it."
    "Otherwise, take the line's `changeover_minutes` and apply a relatedness multiplier:
    0.50 when the predecessor's SKU shares this SKU's `formulation_id`, 0.75 when it
    instead shares this SKU's `print_film_id`, and 1.00 when it shares neither."
    "Round the multiplied base **up** to a whole minute, and only then add a thickness
    surcharge: 30 minutes when the absolute difference between the two SKUs'
    `overall_thickness_mm` values is at least 2.0 millimetres, 10 minutes when that
    difference is at least 0.5 but below 2.0, and nothing below 0.5."
    "Setup takes the run `PLANNED → SETUP` and is where the changeover allowance is
    persisted."
    "The gap computation above is re-evaluated against the current predecessor and stored
    in `changeover_minutes_applied`."
    "Aborting is available from `PLANNED`, `SETUP` or `RUNNING` with an `abort_reason`,
    and it is an exact compensation: the run's `planned_quantity_sqm` is subtracted from
    the grant's `reserved_volume_sqm`, restoring that figure to its pre-scheduling value
    bit for bit."

    Design: Corner/calculations/changeover_gap_skips_aborted_predecessor_run
    """
    set_clock(api, "2026-08-01T00:00:00Z")

    f_min = build_approved_formulation(api, "F-MIN", F_MIN_COMPONENTS)
    f_std = build_approved_formulation(
        api, "F-STD", F_STD_COMPONENTS, materials=f_min["materials"]
    )

    license_row = create_license(api)
    film_oak = create_print_film(api, license_row["id"])
    film_slate = create_print_film(
        api,
        license_row["id"],
        design_code="PF-SLATE-900",
        pattern_repeat_mm_length=900,
        pattern_repeat_mm_width=150,
        registration_tolerance_mm=0.30,
        emboss_plate_code="EP-SLATE-A",
        emboss_alignment_offset_mm=0.05,
        master_roll_sets=1,
    )

    # SKU-A: F-MIN, PF-OAK-1200, 2.50 mm. SKU-D: F-STD, PF-SLATE-900, 5.00 mm,
    # so SKU-D shares neither key with SKU-A and sits a 2.50 mm step away.
    sku_a = create_sku(api, f_min["formulation"]["id"], film_oak["id"])
    sku_d = create_sku(
        api,
        f_std["formulation"]["id"],
        film_slate["id"],
        sku_code="SKU-D",
        overall_thickness_mm=5.00,
        royalty_basis_price_cents_per_sqm=2000,
    )

    begin_testing(api, sku_a["id"])
    build_passed_panel(api, sku_a["id"])
    begin_testing(api, sku_d["id"])

    press_line = create_press_line(api)

    create_run(
        api,
        sku_a["id"],
        press_line["id"],
        run_code="RUN-B1",
        planned_start_utc="2026-08-01T01:00:00Z",
        planned_end_utc="2026-08-01T02:00:00Z",
        planned_quantity_sqm=100.00,
    )
    run_b2 = create_run(
        api,
        sku_d["id"],
        press_line["id"],
        run_code="RUN-B2",
        planned_start_utc="2026-08-01T04:00:00Z",
        planned_end_utc="2026-08-01T05:00:00Z",
        planned_quantity_sqm=100.00,
    )
    aborted = abort_run(
        api, run_b2["id"], abort_reason="SKU-D trial pulled from the schedule"
    )
    assert aborted["run_status"] == "ABORTED"

    grant = get_success_data(api.get_design_license(license_row["id"], PLANT_ADMIN))
    assert grant["reserved_volume_sqm"] == 100.00, (
        "the aborted run's reservation is released exactly"
    )

    run_b3 = create_run(
        api,
        sku_a["id"],
        press_line["id"],
        run_code="RUN-B3",
        planned_start_utc="2026-08-01T07:00:00Z",
        planned_end_utc="2026-08-01T08:00:00Z",
        planned_quantity_sqm=100.00,
    )
    set_clock(api, "2026-08-01T05:00:00Z")

    setup = validate_success(api.setup_production_run(run_b3["id"], PRODUCTION_PLANNER))

    assert setup["run_status"] == "SETUP"
    assert setup["changeover_minutes_applied"] == 30
    assert setup["changeover_minutes_applied"] != 90, (
        "90 is the gap the nearer but ABORTED RUN-B2 would have demanded"
    )


def test_dimensional_stability_spec_limit_switches_on_construction_type(api):
    """One reading of 0.2000 PCT passes on a glue-down plank against the 0.25 limit and
    fails on a click-lock plank against the 0.15 limit.

    "`DIMENSIONAL_STABILITY_HEAT` is measured in `PCT` and lower is better, with a limit
    of 0.15 for `CLICK_LOCK_SPC` and `CLICK_LOCK_WPC` constructions and 0.25 for every
    other construction."
    "For a lower-is-better test the marginal edge is the limit multiplied by 1.05,
    rounded half up to four decimal places; a `measured_value` no greater than the limit
    is `PASS`, a value above the limit but no greater than the marginal edge is
    `MARGINAL`, and anything larger is `FAIL`."
    "The instant coverage completes, the panel resolves in one of three ways, and a
    `FAIL` short-circuits the other two: any measurement graded `FAIL` takes the panel
    `IN_TEST → FAILED` immediately, without waiting for coverage."
    "Otherwise, if coverage is complete and every outcome at that attempt is `PASS`, the
    panel moves `IN_TEST → PASSED`."
    "A panel that reaches `PASSED` whose coverage includes both `RESIDUAL_INDENTATION`
    and `DIMENSIONAL_STABILITY_HEAT` moves the SKU's certification `TESTING →
    PROVISIONAL`."
    "A panel that reaches `FAILED` collapses the SKU's certification: `TESTING →
    UNCERTIFIED`, or `PROVISIONAL → SUSPENDED`, or `CERTIFIED → SUSPENDED`."

    Design: Corner/calculations/dim_stability_spec_limit_constant_switches_on_construction_type
    """
    set_clock(api, "2026-08-01T00:00:00Z")

    f_min = build_approved_formulation(api, "F-MIN", F_MIN_COMPONENTS)
    license_row = create_license(api)
    film_oak = create_print_film(api, license_row["id"])
    license_wp = create_license(
        api,
        license_code="LIC-WP",
        valid_until="2029-01-01T00:00:00Z",
        term_volume_cap_sqm=5000.00,
    )
    film_wp = create_print_film(
        api,
        license_wp["id"],
        design_code="PF-WP-1800",
        pattern_repeat_mm_length=1800,
        pattern_repeat_mm_width=200,
        emboss_plate_code="EP-WP-A",
    )

    sku_a = create_sku(api, f_min["formulation"]["id"], film_oak["id"])
    sku_w = create_click_lock_sku(api, f_min["formulation"]["id"], film_wp["id"])

    begin_testing(api, sku_a["id"])
    panel_a = create_panel(api, sku_a["id"], "TP-A1")
    start_panel(api, panel_a["id"])
    record_result(api, panel_a["id"], "RESIDUAL_INDENTATION", 0.0800)

    begin_testing(api, sku_w["id"])
    panel_w = create_panel(api, sku_w["id"], "TP-W1")
    start_panel(api, panel_w["id"])

    glue_result = validate_success(
        api.record_test_result(
            panel_a["id"],
            {"test_type": "DIMENSIONAL_STABILITY_HEAT", "measured_value": 0.2000},
            QA_TECHNICIAN,
        ),
        201,
    )
    click_result = validate_success(
        api.record_test_result(
            panel_w["id"],
            {"test_type": "DIMENSIONAL_STABILITY_HEAT", "measured_value": 0.2000},
            QA_TECHNICIAN,
        ),
        201,
    )

    assert glue_result["unit"] == "PCT"
    assert glue_result["spec_limit"] == 0.25
    assert glue_result["outcome"] == "PASS"

    assert click_result["spec_limit"] == 0.15
    assert click_result["outcome"] == "FAIL"

    assert get_success_data(api.get_test_panel(panel_a["id"], QA_TECHNICIAN))[
        "status"
    ] == "PASSED"
    assert get_success_data(api.get_product_sku(sku_a["id"], PLANT_ADMIN))[
        "certification_status"
    ] == "PROVISIONAL"
    assert get_success_data(api.get_test_panel(panel_w["id"], QA_TECHNICIAN))[
        "status"
    ] == "FAILED"
    assert get_success_data(api.get_product_sku(sku_w["id"], PLANT_ADMIN))[
        "certification_status"
    ] == "UNCERTIFIED"


def test_warranty_terms_across_the_wear_layer_rungs_and_both_caps(api):
    """Four SKUs walk the wear-layer ladder: 11.9 mil, exactly 12 mil, a waterproof
    click-lock at 20 mil that hits both caps, and a waterproof glue-down that earns no
    bonus.

    "The residential term is 25 years when `wear_layer_mil` is at least 20, 20 years
    when it is at least 12 but below 20, 15 years when it is at least 6 but below 12, and
    10 years otherwise."
    "The light-commercial term over the same tiers is 15, 10, 5 and 0 years."
    "A bonus of 5 years is added to both terms when — and only when — the SKU is both
    `waterproof_rated` and built on a `CLICK_LOCK_SPC` or `CLICK_LOCK_WPC` construction;
    a waterproof `GLUE_DOWN` plank earns nothing."
    "The residential result is then capped at 30 years and stored as `warranty_years`,
    and the light-commercial result is capped at 20 years and stored as
    `light_commercial_warranty_years`."
    "All tier thresholds are inclusive, so a wear layer of exactly 20 mil takes the top
    tier and exactly 12 mil gives 20 residential and 10 light-commercial years."

    Design: Corner/calculations/warranty_term_tiers_at_wear_layer_rung_boundaries_and_caps
    """
    set_clock(api, "2026-08-01T00:00:00Z")

    built = build_draft_formulation(api, "F-MIN", F_MIN_COMPONENTS)
    formulation_id = built["formulation"]["id"]
    license_row = create_license(api)
    film = create_print_film(api, license_row["id"])

    sku_t1 = create_sku(
        api,
        formulation_id,
        film["id"],
        sku_code="SKU-T1",
        wear_layer_mil=11.9,
        royalty_basis_price_cents_per_sqm=2000,
    )
    sku_t2 = create_sku(
        api,
        formulation_id,
        film["id"],
        sku_code="SKU-T2",
        wear_layer_mil=12,
        royalty_basis_price_cents_per_sqm=2000,
    )
    sku_t3 = create_sku(
        api,
        formulation_id,
        film["id"],
        sku_code="SKU-T3",
        construction_type="CLICK_LOCK_SPC",
        wear_layer_mil=20,
        overall_thickness_mm=5.00,
        royalty_basis_price_cents_per_sqm=2600,
        waterproof_rated=True,
        profile_family="UNILIN_5G",
        tongue_thickness_target_mm=1.80,
        tolerance_plus_mm=0.15,
        tolerance_minus_mm=0.15,
        target_lock_shear_n_per_mm=8.00,
    )
    sku_t4 = create_sku(
        api,
        formulation_id,
        film["id"],
        sku_code="SKU-T4",
        wear_layer_mil=20,
        royalty_basis_price_cents_per_sqm=2600,
        waterproof_rated=True,
    )

    assert_warranty_terms(sku_t1, residential=15, light_commercial=5)
    assert_warranty_terms(sku_t2, residential=20, light_commercial=10)
    assert_warranty_terms(sku_t3, residential=30, light_commercial=20)
    assert_warranty_terms(sku_t4, residential=25, light_commercial=15)


def test_stepped_settlement_steps_down_between_year_three_and_year_four(api):
    """Two claims on one batch differing only in `reported_on` settle at 42840 and 32130
    cents as the whole-year staircase drops from 80 percent to 60 percent.

    "Coverage is measured in whole calendar months. `elapsed_months` is the number of
    whole calendar months from `installed_on` to `reported_on`, floored, so a partial
    month does not count."
    "The `replacement_value_cents` is the `claimed_area_sqm` multiplied by the SKU's
    `royalty_basis_price_cents_per_sqm`, rounded half up to a whole cent."
    "The `labor_allowance_cents` is the `claimed_area_sqm` multiplied by 350 cents per
    square metre, rounded half up to a whole cent, when `installed_by_certified_installer`
    is true, and 0 otherwise."
    "A `DELAMINATION` or `LOCK_FAILURE` claim uses `STEPPED_SCHEDULE`: take the elapsed
    whole years as `elapsed_months` divided by twelve rounded down, then apply 100 percent
    when that figure is 1 or less, 80 percent when it is 2 or 3, 60 percent when it is 4
    through 7, 40 percent when it is 8 through 12, and 20 percent beyond that, rounding
    the result half up to a whole cent."
    "The `settlement_amount_cents` is the covered value plus the `labor_allowance_cents`,
    added as two already-rounded integers."
    "A **manufacturing defect** is confirmed when the batch's `wear_layer_measured_mil`
    is strictly less than the SKU's specified `wear_layer_mil` minus 0.5 mil — the
    tolerance the plant accepts on wear-layer thickness."

    Design: Corner/calculations/stepped_settlement_decays_across_the_year_three_and_four_steps
    """
    set_clock(api, "2026-08-01T00:00:00Z")

    built = build_stock_batch(api)
    distributor = create_distributor(api)
    batch_id = built["batch"]["id"]

    set_clock(api, "2030-08-05T00:00:00Z")

    claim_3y = create_claim(
        api,
        batch_id,
        distributor["id"],
        claim_code="WC-STEP-3Y",
        claim_type="LOCK_FAILURE",
        claimed_area_sqm=25.50,
        installed_on="2026-08-05T00:00:00Z",
        reported_on="2029-08-05T00:00:00Z",
    )
    triage_claim(api, claim_3y["id"])
    record_review(api, claim_3y["id"], "MATERIALS", "DEFECT_CONFIRMED")
    record_review(api, claim_3y["id"], "FIELD", "DEFECT_CONFIRMED")

    claim_4y = create_claim(
        api,
        batch_id,
        distributor["id"],
        claim_code="WC-STEP-4Y",
        claim_type="LOCK_FAILURE",
        claimed_area_sqm=25.50,
        installed_on="2026-08-05T00:00:00Z",
        reported_on="2030-08-05T00:00:00Z",
    )
    triage_claim(api, claim_4y["id"])
    record_review(api, claim_4y["id"], "MATERIALS", "DEFECT_CONFIRMED")
    record_review(api, claim_4y["id"], "FIELD", "DEFECT_CONFIRMED")

    settled_3y = adjudicate_claim(api, claim_3y["id"], "APPROVE")
    settled_4y = adjudicate_claim(api, claim_4y["id"], "APPROVE")

    assert settled_3y["settlement_variant"] == "STEPPED_SCHEDULE"
    assert settled_3y["elapsed_months"] == 36
    assert settled_4y["elapsed_months"] == 48
    assert settled_3y["replacement_value_cents"] == 53550
    assert settled_4y["replacement_value_cents"] == 53550
    assert settled_3y["labor_allowance_cents"] == 0
    assert settled_4y["labor_allowance_cents"] == 0
    assert settled_3y["settlement_amount_cents"] == 42840
    assert settled_4y["settlement_amount_cents"] == 32130


def test_manufacturing_defect_override_pays_full_value_despite_the_stepped_variant(api):
    """A batch measured 11.0 mil against a 12 mil spec settles at the full replacement
    value plus labour, 98000 cents, while `STEPPED_SCHEDULE` is still recorded.

    "A **manufacturing defect** is confirmed when the batch's `wear_layer_measured_mil`
    is strictly less than the SKU's specified `wear_layer_mil` minus 0.5 mil — the
    tolerance the plant accepts on wear-layer thickness."
    "When a defect is confirmed, the covered value is the full `replacement_value_cents`
    with no decay at all under either variant, so the variant becomes unobservable in the
    amount even though it is still recorded in `settlement_variant`."
    "The `settlement_amount_cents` is the covered value plus the `labor_allowance_cents`,
    added as two already-rounded integers."
    "The `replacement_value_cents` is the `claimed_area_sqm` multiplied by the SKU's
    `royalty_basis_price_cents_per_sqm`, rounded half up to a whole cent."
    "The `labor_allowance_cents` is the `claimed_area_sqm` multiplied by 350 cents per
    square metre, rounded half up to a whole cent, when `installed_by_certified_installer`
    is true, and 0 otherwise."
    "A `DELAMINATION` or `LOCK_FAILURE` claim uses `STEPPED_SCHEDULE`: take the elapsed
    whole years as `elapsed_months` divided by twelve rounded down, then apply 100 percent
    when that figure is 1 or less, 80 percent when it is 2 or 3, 60 percent when it is 4
    through 7, 40 percent when it is 8 through 12, and 20 percent beyond that, rounding
    the result half up to a whole cent."
    "a `wear_layer_measured_mil` copied from the run's measurement — the reading that
    will later serve as warranty defect evidence."

    Design: Corner/calculations/manufacturing_defect_override_selects_full_value_over_the_decay
    """
    set_clock(api, "2026-08-01T00:00:00Z")

    distributor = create_distributor(
        api,
        account_code="D-200",
        name="Certified Install Partners",
        certified_installer_program=True,
    )
    built = build_released_sku(api)
    press_line = create_press_line(api)
    run = run_to_completion(
        api,
        built["sku"]["id"],
        press_line["id"],
        1200.00,
        completion_overrides={"wear_layer_measured_mil": 11.0},
    )
    set_qc_disposition(api, run["id"], "RELEASED")
    batch = batch_of_run(api, run["id"])

    assert batch["wear_layer_measured_mil"] == 11.0
    assert built["sku"]["wear_layer_mil"] == 12

    set_clock(api, "2030-08-05T00:00:00Z")

    claim = create_claim(
        api,
        batch["id"],
        distributor["id"],
        claim_code="WC-DEFECT-1",
        claim_type="LOCK_FAILURE",
        claimed_area_sqm=40.00,
        installed_on="2026-08-05T00:00:00Z",
        reported_on="2030-08-05T00:00:00Z",
        installed_by_certified_installer=True,
    )
    triage_claim(api, claim["id"])
    record_review(api, claim["id"], "MATERIALS", "DEFECT_CONFIRMED")
    record_review(api, claim["id"], "FIELD", "DEFECT_CONFIRMED")

    settled = adjudicate_claim(api, claim["id"], "APPROVE")

    assert settled["settlement_variant"] == "STEPPED_SCHEDULE"
    assert settled["elapsed_months"] == 48
    assert settled["replacement_value_cents"] == 84000
    assert settled["labor_allowance_cents"] == 14000
    assert settled["settlement_amount_cents"] == 98000
    assert settled["settlement_amount_cents"] != 64400, (
        "64400 is the 60 percent step the recorded variant would otherwise have produced"
    )


def test_license_utilization_aggregates_reserved_consumed_and_projection(api):
    """The utilization read reports a 700.00 reservation from a planned run alongside
    1200.00 consumed and 126000 cents accrued from the one completed run.

    "A grant's utilization is readable as a computed summary carrying
    `term_volume_cap_sqm`, `reserved_volume_sqm`, `consumed_volume_sqm`, the
    forward-looking `projected_volume_sqm` (consumed plus reserved), the
    `remaining_volume_sqm` left under the cap (the cap less the projection), the
    `accrued_royalty_cents` ledger, and `contributing_run_count`, the number of completed
    runs that have contributed royalty to it."
    "On success, the run's `planned_quantity_sqm` is added to the grant's
    `reserved_volume_sqm` and the grant's `version` is advanced."
    "Second, the licensed-volume ledger settles on an actual basis: the run's
    `planned_quantity_sqm` is subtracted from the grant's `reserved_volume_sqm` and the
    measured `actual_quantity_sqm` is added to its `consumed_volume_sqm`."
    "The run's `actual_quantity_sqm` is multiplied by the SKU's
    `royalty_basis_price_cents_per_sqm` and by the grant's `royalty_rate_bps` divided by
    10000, and the product is rounded half up to a whole cent."
    "**Round per run, then accumulate.** A production run's royalty contribution is
    rounded to a whole cent on its own and only that rounded integer is added to the
    grant's royalty ledger."
    "The grant's projected volume is its `consumed_volume_sqm` plus its
    `reserved_volume_sqm` plus the new run's `planned_quantity_sqm`, and that projection
    may not exceed `term_volume_cap_sqm`; equality is admitted, and an excess is
    `ERR_LICENSE_VOLUME_CAP_EXCEEDED` (HTTP 422)."

    Design: Corner/calculations/license_utilization_aggregates_reserved_consumed_and_projection
    """
    set_clock(api, "2026-08-01T00:00:00Z")

    f_min = build_approved_formulation(api, "F-MIN", F_MIN_COMPONENTS)
    license_row = create_license(api)
    film = create_print_film(api, license_row["id"])
    sku = create_sku(api, f_min["formulation"]["id"], film["id"])
    begin_testing(api, sku["id"])
    build_passed_panel(api, sku["id"])

    press_line = create_press_line(api)
    run_to_completion(api, sku["id"], press_line["id"], 1200.00)

    create_run(
        api,
        sku["id"],
        press_line["id"],
        run_code="RUN-A2",
        planned_start_utc="2026-08-01T09:30:00Z",
        planned_end_utc="2026-08-01T12:00:00Z",
        planned_quantity_sqm=700.00,
    )

    utilization = validate_success(
        api.get_license_utilization(license_row["id"], TECHNICAL_DIRECTOR)
    )

    assert utilization["term_volume_cap_sqm"] == 2000.00
    assert utilization["reserved_volume_sqm"] == 700.00
    assert utilization["consumed_volume_sqm"] == 1200.00
    assert utilization["projected_volume_sqm"] == 1900.00
    assert utilization["remaining_volume_sqm"] == 100.00
    assert utilization["accrued_royalty_cents"] == 126000
    assert utilization["contributing_run_count"] == 1


def test_fill_waterfall_drains_the_older_batch_before_touching_the_second(api):
    """A 1500.00 request against a 1200.00 and a 300.00 batch emits two lines, the older
    batch drained in full first, and leaves both batches at 0.00 available.

    "Candidates are ordered by substitution kind first — exact matches ahead of
    underlayment upgrades, which are ahead of wear-layer upgrades — then by the batch's
    `created_at` ascending, then by `batch_code` ascending."
    "The remaining requirement is the allocation's `requested_quantity_sqm` less its
    current `allocated_quantity_sqm`, rounded half up to two decimal places."
    "Walking the candidates in rank order while the remaining requirement is strictly
    positive, each candidate contributes the smaller of the remaining requirement and its
    own `available_quantity_sqm`."
    "One allocation line is created per drawn batch, carrying the `allocation_id` it
    fills, the `batch_id` drawn on, the `quantity_sqm` drawn, and its `substitution_kind`;
    the batch's `available_quantity_sqm` is decremented by that quantity and its `version`
    advanced, and the remaining requirement falls by the same amount."
    "The first candidate is drained completely before the second is touched, even when the
    second alone would have covered the whole request."
    "Each line's `upgrade_cost_delta_cents` is 0 when its `substitution_kind` is
    `EXACT`."
    "The allocation's `allocated_quantity_sqm` is then the sum of its `ACTIVE` lines'
    quantities at two decimal places, and its `upgrade_cost_total_cents` is the exact sum
    of those already-rounded per-line integers."
    "The allocation's resulting `status` follows from the arithmetic: `FILLED` when
    `allocated_quantity_sqm` has reached `requested_quantity_sqm`, `PARTIALLY_FILLED` when
    it is above zero but short of the request, and `OPEN` when it is zero."
    "Round the multiplied base **up** to a whole minute, and only then add a thickness
    surcharge: 30 minutes when the absolute difference between the two SKUs'
    `overall_thickness_mm` values is at least 2.0 millimetres, 10 minutes when that
    difference is at least 0.5 but below 2.0, and nothing below 0.5."

    Design: Corner/calculations/fill_waterfall_drains_first_batch_before_touching_second
    """
    set_clock(api, "2026-08-01T00:00:00Z")

    built = build_stock_batch(api)
    distributor = create_distributor(api)
    batch_first = built["batch"]

    run_a3 = create_run(
        api,
        built["sku"]["id"],
        built["press_line"]["id"],
        run_code="RUN-A3",
        planned_start_utc="2026-08-01T09:30:00Z",
        planned_end_utc="2026-08-01T12:00:00Z",
        planned_quantity_sqm=300.00,
    )
    set_clock(api, "2026-08-01T07:30:00Z")
    setup = validate_success(api.setup_production_run(run_a3["id"], PRODUCTION_PLANNER))
    assert setup["changeover_minutes_applied"] == 30

    validate_success(api.start_production_run(run_a3["id"], PRODUCTION_PLANNER))
    complete_run(
        api,
        run_a3["id"],
        300.00,
        registration_drift_mm=0.10,
        curl_deviation_mm=0.05,
        emboss_alignment_offset_mm=0.10,
        wear_layer_measured_mil=12.0,
    )
    set_qc_disposition(api, run_a3["id"], "RELEASED")
    batch_second = batch_of_run(api, run_a3["id"])

    allocation = create_allocation(
        api,
        distributor["id"],
        built["sku"]["id"],
        headers=PLANT_ADMIN,
        allocation_code="ALLOC-W",
        requested_quantity_sqm=1500.00,
    )

    filled = fill_allocation(
        api, allocation["id"], distributor["id"], allocation["version"]
    )

    assert filled["status"] == "FILLED"
    assert filled["allocated_quantity_sqm"] == 1500.00
    assert filled["upgrade_cost_total_cents"] == 0

    lines, meta = validate_paginated(
        api.list_allocation_lines(allocation["id"], PLANT_ADMIN)
    )
    assert meta["total_count"] == 2
    assert lines[0]["batch_id"] == batch_first["id"]
    assert lines[0]["quantity_sqm"] == 1200.00
    assert lines[0]["substitution_kind"] == "EXACT"
    assert lines[1]["batch_id"] == batch_second["id"]
    assert lines[1]["quantity_sqm"] == 300.00

    assert get_success_data(api.get_batch(batch_first["id"], QA_TECHNICIAN))[
        "available_quantity_sqm"
    ] == 0.00
    assert get_success_data(api.get_batch(batch_second["id"], QA_TECHNICIAN))[
        "available_quantity_sqm"
    ] == 0.00


def test_required_test_types_derive_from_the_sku_configuration_flags(api):
    """A glue-down SKU requires exactly two test types while a waterproof click-lock SKU
    with attached underlayment requires all five, in canonical order.

    "Every panel requires `RESIDUAL_INDENTATION` and `DIMENSIONAL_STABILITY_HEAT`. A
    `waterproof_rated` SKU additionally requires `SLIP_RESISTANCE`. A SKU whose
    `attached_underlayment_type` is anything other than `NONE` additionally requires
    `PEEL_ADHESION_DELAMINATION`. A SKU whose `construction_type` is `CLICK_LOCK_SPC` or
    `CLICK_LOCK_WPC` additionally requires `LOCK_SHEAR`."
    "The resulting list is stored in the canonical order `RESIDUAL_INDENTATION`,
    `DIMENSIONAL_STABILITY_HEAT`, `SLIP_RESISTANCE`, `PEEL_ADHESION_DELAMINATION`,
    `LOCK_SHEAR`, regardless of the order in which the conditions fired."
    "A glue-down, non-waterproof SKU with no attached underlayment therefore requires
    exactly two types, while a waterproof `CLICK_LOCK_WPC` SKU with `CORK_2MM`
    underlayment requires all five."
    "A new panel is `SCHEDULED` with `attempt_no` 1, `retest_count` 0, `void_reason` and
    `started_by_user_id` null, and `required_test_types` derived from the SKU."

    Design: Corner/calculations/required_test_types_propagate_from_five_sku_configuration_flags
    """
    set_clock(api, "2026-08-01T00:00:00Z")

    f_min = build_approved_formulation(api, "F-MIN", F_MIN_COMPONENTS)
    license_row = create_license(api)
    film_oak = create_print_film(api, license_row["id"])
    license_wp = create_license(
        api,
        license_code="LIC-WP",
        valid_until="2029-01-01T00:00:00Z",
        term_volume_cap_sqm=5000.00,
    )
    film_wp = create_print_film(
        api,
        license_wp["id"],
        design_code="PF-WP-1800",
        pattern_repeat_mm_length=1800,
        pattern_repeat_mm_width=200,
        emboss_plate_code="EP-WP-A",
    )

    sku_a = create_sku(api, f_min["formulation"]["id"], film_oak["id"])
    sku_w = create_click_lock_sku(api, f_min["formulation"]["id"], film_wp["id"])
    begin_testing(api, sku_a["id"])
    begin_testing(api, sku_w["id"])

    panel_a = validate_success(
        api.create_test_panel({"panel_code": "TP-A1", "sku_id": sku_a["id"]}, QA_TECHNICIAN),
        201,
    )
    panel_w = validate_success(
        api.create_test_panel({"panel_code": "TP-W1", "sku_id": sku_w["id"]}, QA_TECHNICIAN),
        201,
    )

    assert panel_a["required_test_types"] == [
        "RESIDUAL_INDENTATION",
        "DIMENSIONAL_STABILITY_HEAT",
    ]
    assert panel_w["required_test_types"] == [
        "RESIDUAL_INDENTATION",
        "DIMENSIONAL_STABILITY_HEAT",
        "SLIP_RESISTANCE",
        "PEEL_ADHESION_DELAMINATION",
        "LOCK_SHEAR",
    ]
    for panel in (panel_a, panel_w):
        assert panel["status"] == "SCHEDULED"
        assert panel["attempt_no"] == 1
        assert panel["retest_count"] == 0
