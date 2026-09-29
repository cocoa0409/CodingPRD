"""Dual-basis and multi-step arithmetic of the plant-operations contract.

These tests exercise the two-variant and ordered-step calculations of the PRD:
the pinned-versus-live SKU standard cost and its cost summary (PRD §3.1, §3.3),
the prorated-versus-stepped warranty settlement (PRD §3.9), the licensed-volume
ledger read on a reserved basis at admission and an actual basis at completion
(PRD §3.2, §3.6), the nested penalty ladders and single final clamp behind a
recipe's performance score (PRD §2.6, §3.1), the round-per-run-then-accumulate
royalty ledger (PRD §2.6, §3.6), and the rank-before-cost step order of the
allocation fill selector (PRD §3.8).
"""

from test_helpers import (
    ApiErrorId,
    CLOCK_BOOT_UTC,
    PLANT_ADMIN,
    PRODUCTION_PLANNER,
    QA_TECHNICIAN,
    TECHNICAL_DIRECTOR,
    WARRANTY_ADJUSTER,
    WARRANTY_ADJUSTER_B,
    add_component,
    assert_blend_metrics,
    batch_of_run,
    begin_testing,
    build_certified_sku,
    build_stock_batch,
    certify_sku,
    complete_run,
    create_allocation,
    create_distributor,
    create_formulation,
    create_panel,
    create_press_line,
    create_raw_material,
    create_run,
    create_sku,
    distributor_headers,
    fill_allocation,
    get_success_data,
    production_run_payload,
    record_result,
    revalue_material,
    set_clock,
    set_commercial_status,
    set_qc_disposition,
    setup_run,
    start_panel,
    start_run,
    validate_error,
    validate_paginated,
    validate_success,
)

# ---------------------------------------------------------------------------
# Local setup fragments. Each test calls these itself, because the harness
# wipes the database before every individual test.
# ---------------------------------------------------------------------------

RUN_QC_CLEAN = {
    "registration_drift_mm": 0.10,
    "curl_deviation_mm": 0.05,
    "emboss_alignment_offset_mm": 0.15,
    "wear_layer_measured_mil": 12.0,
}


def _certified_sku_a_then_revalue_resin(api):
    """Certified glue-down SKU-A on the pinned F-MIN recipe, then RM-RESIN at 260.

    F-MIN doses RM-RESIN at 100 phr and RM-STAB at 3 phr; on approval the recipe
    pins at a blended cost of 201 cents per kilogram and SKU-A is certified with
    a stamped standard cost of 1157 cents per square metre. Revaluing RM-RESIN
    from 180 to 260 cents per kilogram afterwards leaves those pinned figures
    alone.
    """
    set_clock(api, CLOCK_BOOT_UTC)
    built = build_certified_sku(api)
    revalue_material(api, built["materials"]["RM-RESIN"]["id"], 260)
    return built


def _two_blends_in_draft(api):
    """Draft recipes F-STD and F-LOW over the four reference materials."""
    set_clock(api, CLOCK_BOOT_UTC)
    resin = create_raw_material(api, "RM-RESIN")
    stab = create_raw_material(api, "RM-STAB")
    plast = create_raw_material(
        api,
        "RM-PLAST",
        name="DINP plasticiser",
        category="PLASTICIZER",
        cost_per_kg_cents=240,
        indentation_index=35,
        thermal_stability_index=40,
        plasticizer_migration_index=62,
        max_phr=60,
    )
    filler = create_raw_material(api, "RM-FILLER")

    f_std = create_formulation(api, "F-STD")
    add_component(api, f_std["id"], resin["id"], 100)
    add_component(api, f_std["id"], plast["id"], 22)
    add_component(api, f_std["id"], filler["id"], 240)
    add_component(api, f_std["id"], stab["id"], 3)

    f_low = create_formulation(api, "F-LOW")
    add_component(api, f_low["id"], resin["id"], 100)
    add_component(api, f_low["id"], plast["id"], 44)
    add_component(api, f_low["id"], filler["id"], 330)
    add_component(api, f_low["id"], stab["id"], 1)

    return {"f_std_id": f_std["id"], "f_low_id": f_low["id"]}


def _two_runs_of_ten_point_one(api):
    """Certified SKU-A plus two disjoint runs on PL-1, each completed at 10.10 sqm."""
    set_clock(api, CLOCK_BOOT_UTC)
    built = build_certified_sku(api)
    press_line = create_press_line(api)

    run_r1 = create_run(
        api,
        built["sku"]["id"],
        press_line["id"],
        run_code="RUN-R1",
        planned_start_utc="2026-08-01T01:00:00Z",
        planned_end_utc="2026-08-01T03:00:00Z",
        planned_quantity_sqm=12.00,
    )
    setup_run(api, run_r1["id"])
    start_run(api, run_r1["id"])

    set_clock(api, "2026-08-01T03:30:00Z")
    run_r2 = create_run(
        api,
        built["sku"]["id"],
        press_line["id"],
        run_code="RUN-R2",
        planned_start_utc="2026-08-01T05:00:00Z",
        planned_end_utc="2026-08-01T07:00:00Z",
        planned_quantity_sqm=12.00,
    )
    setup_run(api, run_r2["id"])
    start_run(api, run_r2["id"])

    completed_r1 = complete_run(api, run_r1["id"], 10.10, **RUN_QC_CLEAN)
    completed_r2 = complete_run(api, run_r2["id"], 10.10, **RUN_QC_CLEAN)
    return {
        "license_id": built["license"]["id"],
        "run_r1": completed_r1,
        "run_r2": completed_r2,
    }


def _wear_layer_upgrade_stock(api):
    """Three released batches: an older 20-mil upgrade batch and two 12-mil exacts.

    B1 is minted first from RUN-U1 of SKU-A20 (300.00 sqm), B2 second from
    RUN-U2 of SKU-A (100.00 sqm) and B3 third from RUN-U3 of SKU-A (300.00 sqm),
    with the logical clock advanced between the runs so the three batches carry
    strictly increasing ``created_at`` stamps.
    """
    set_clock(api, CLOCK_BOOT_UTC)
    built = build_certified_sku(api)
    sku_a = set_commercial_status(api, built["sku"]["id"], "RELEASED")

    sku_a20 = create_sku(
        api,
        built["formulation"]["id"],
        built["film"]["id"],
        sku_code="SKU-A20",
        wear_layer_mil=20,
    )
    begin_testing(api, sku_a20["id"])
    panel = create_panel(api, sku_a20["id"], "TP-A20")
    start_panel(api, panel["id"])
    record_result(api, panel["id"], "RESIDUAL_INDENTATION", 0.08)
    record_result(api, panel["id"], "DIMENSIONAL_STABILITY_HEAT", 0.12)
    sku_a20 = certify_sku(api, sku_a20["id"])

    press_line = create_press_line(api)

    run_u1 = create_run(
        api,
        sku_a20["id"],
        press_line["id"],
        run_code="RUN-U1",
        planned_start_utc="2026-08-01T01:00:00Z",
        planned_end_utc="2026-08-01T03:00:00Z",
        planned_quantity_sqm=300.00,
    )
    setup_run(api, run_u1["id"])
    start_run(api, run_u1["id"])
    complete_run(
        api,
        run_u1["id"],
        300.00,
        registration_drift_mm=0.10,
        curl_deviation_mm=0.05,
        emboss_alignment_offset_mm=0.15,
        wear_layer_measured_mil=20.0,
    )
    set_qc_disposition(api, run_u1["id"], "RELEASED")
    b1 = batch_of_run(api, run_u1["id"])

    set_clock(api, "2026-08-01T03:30:00Z")
    run_u2 = create_run(
        api,
        sku_a["id"],
        press_line["id"],
        run_code="RUN-U2",
        planned_start_utc="2026-08-01T05:00:00Z",
        planned_end_utc="2026-08-01T07:00:00Z",
        planned_quantity_sqm=100.00,
    )
    setup_run(api, run_u2["id"])
    start_run(api, run_u2["id"])
    complete_run(api, run_u2["id"], 100.00, **RUN_QC_CLEAN)
    set_qc_disposition(api, run_u2["id"], "RELEASED")
    b2 = batch_of_run(api, run_u2["id"])

    set_clock(api, "2026-08-01T07:30:00Z")
    run_u3 = create_run(
        api,
        sku_a["id"],
        press_line["id"],
        run_code="RUN-U3",
        planned_start_utc="2026-08-01T09:00:00Z",
        planned_end_utc="2026-08-01T11:00:00Z",
        planned_quantity_sqm=300.00,
    )
    setup_run(api, run_u3["id"])
    start_run(api, run_u3["id"])
    complete_run(api, run_u3["id"], 300.00, **RUN_QC_CLEAN)
    set_qc_disposition(api, run_u3["id"], "RELEASED")
    b3 = batch_of_run(api, run_u3["id"])

    distributor = create_distributor(api)
    return {
        "sku_a": sku_a,
        "sku_a20": sku_a20,
        "b1_id": b1["id"],
        "b2_id": b2["id"],
        "b3_id": b3["id"],
        "distributor_id": distributor["id"],
    }


# ---------------------------------------------------------------------------
# SKU standard cost on the pinned basis versus the live basis.
# ---------------------------------------------------------------------------


def test_cost_summary_pinned_basis_holds_the_snapshot_blend_after_revaluation(api):
    """The pinned basis prices the core compound from the approval-time snapshots.

    "The **pinned basis** takes the core-compound component from the per-component
    `material_cost_snapshot_cents` captured when the recipe was approved —
    equivalently, from a pinned recipe's `blended_cost_per_kg_cents`, which is
    what the SKU's `pinned_formulation_version` refers to."
    "Add those products together, divide the total by `total_phr`, and round half
    up to a whole cent."
    "The core-compound component is the compound's blended cost per kilogram
    multiplied by 1.90 — the specific gravity in kilograms per square metre per
    millimetre — multiplied by the SKU's `overall_thickness_mm`."
    "`standard_cost_cents_per_sqm` is the exact integer sum of those seven rounded
    integers, and `list_price_cents_per_sqm` is that standard cost multiplied by
    the quantity 10000 plus `target_margin_bps`, divided by 10000, rounded half up
    to a whole cent."
    "Recipes whose `cost_basis` is `PINNED` are untouched, which means their
    `blended_cost_per_kg_cents` and every SKU standard cost stamped from them stay
    exactly as they were."

    Design: Difficulty/dual_variant_calc/sku_standard_cost_live_versus_pinned_material_basis
    """
    built = _certified_sku_a_then_revalue_resin(api)
    sku_id = built["sku"]["id"]

    summary = validate_success(api.get_sku_cost_summary(sku_id, TECHNICAL_DIRECTOR))
    assert summary["pinned_basis_blended_cost_per_kg_cents"] == 201
    assert summary["pinned_basis_core_cost_cents"] == 955
    assert summary["pinned_basis_standard_cost_cents_per_sqm"] == 1157
    assert summary["pinned_basis_list_price_cents_per_sqm"] == 1562

    formulation = validate_success(
        api.get_formulation(built["formulation"]["id"], TECHNICAL_DIRECTOR)
    )
    assert formulation["blended_cost_per_kg_cents"] == 201
    assert formulation["cost_basis"] == "PINNED"

    sku = validate_success(api.get_product_sku(sku_id, PLANT_ADMIN))
    assert sku["standard_cost_cents_per_sqm"] == 1157
    assert sku["list_price_cents_per_sqm"] == 1562


def test_cost_summary_live_basis_reblends_from_the_current_material_cost(api):
    """The live basis re-blends the core compound from the revalued material cost.

    "The **live basis** re-blends the core compound from the *current*
    `cost_per_kg_cents` of every component material, ignoring the snapshots
    entirely: it sums each component's `phr` multiplied by its material's current
    cost, divides by `total_phr`, and rounds half up to a whole cent before the
    thickness and specific-gravity multiplication."
    "A material revaluation moves the live basis immediately, even for an approved
    recipe, and leaves the pinned basis bit-identical; the gap between the two is
    the plant's replacement-cost exposure."
    "`standard_cost_cents_per_sqm` is the exact integer sum of those seven rounded
    integers, and `list_price_cents_per_sqm` is that standard cost multiplied by
    the quantity 10000 plus `target_margin_bps`, divided by 10000, rounded half up
    to a whole cent."

    Design: Difficulty/dual_variant_calc/sku_standard_cost_live_versus_pinned_material_basis
    """
    built = _certified_sku_a_then_revalue_resin(api)

    material = validate_success(
        api.get_raw_material(built["materials"]["RM-RESIN"]["id"], PLANT_ADMIN)
    )
    assert material["cost_per_kg_cents"] == 260

    summary = validate_success(
        api.get_sku_cost_summary(built["sku"]["id"], TECHNICAL_DIRECTOR)
    )
    assert summary["live_basis_blended_cost_per_kg_cents"] == 279
    assert summary["live_basis_core_cost_cents"] == 1325
    assert summary["live_basis_standard_cost_cents_per_sqm"] == 1527
    assert summary["live_basis_list_price_cents_per_sqm"] == 2061


def test_cost_summary_reports_the_five_shared_components_and_the_basis_delta(api):
    """The five basis-independent components and the royalty are shared; the gap is 370.

    "The cost of a square metre is assembled from seven named components, each
    rounded half up to a whole cent on its own before any addition happens."
    "The wear-layer component is `wear_layer_mil` multiplied by 3.5 cents per mil
    per square metre."
    "The print-film component is a base of 18 cents plus a repeat surcharge
    determined by the larger of the design's two pattern repeats: 6 cents when that
    larger repeat is at least 1800 millimetres, 2 cents when it is at least 1200 but
    below 1800, and nothing below 1200."
    "The underlayment component is 0 cents for `NONE`, 22 for `IXPE_1MM`, 17 for
    `EVA_1_5MM` and 41 for `CORK_2MM`."
    "The waterproofing component is 9 cents when the SKU is `waterproof_rated` and
    zero otherwise."
    "The conversion component is a base of 35 cents plus 12 cents of click-lock
    milling when `construction_type` is `CLICK_LOCK_SPC` or `CLICK_LOCK_WPC`."
    "The seventh component is the royalty: the SKU's
    `royalty_basis_price_cents_per_sqm` multiplied by the governing grant's
    `royalty_rate_bps` divided by 10000, rounded half up to a whole cent."
    "A material revaluation moves the live basis immediately, even for an approved
    recipe, and leaves the pinned basis bit-identical; the gap between the two is
    the plant's replacement-cost exposure."

    Design: Difficulty/dual_variant_calc/sku_standard_cost_live_versus_pinned_material_basis
    """
    built = _certified_sku_a_then_revalue_resin(api)

    summary = validate_success(
        api.get_sku_cost_summary(built["sku"]["id"], TECHNICAL_DIRECTOR)
    )
    assert summary["wear_layer_cost_cents"] == 42
    assert summary["print_film_cost_cents"] == 20
    assert summary["underlayment_cost_cents"] == 0
    assert summary["waterproof_cost_cents"] == 0
    assert summary["conversion_cost_cents"] == 35
    assert summary["royalty_cost_cents"] == 105
    assert summary["pinned_basis_standard_cost_cents_per_sqm"] == 1157
    assert summary["live_basis_standard_cost_cents_per_sqm"] == 1527
    assert summary["basis_delta_cents_per_sqm"] == 370


# ---------------------------------------------------------------------------
# Warranty settlement: prorated straight line versus stepped schedule.
# ---------------------------------------------------------------------------


def test_wear_through_claim_settles_on_the_prorated_straight_line_variant(api):
    """A wear-through claim decays straight-line by month to 112875 cents.

    "The residential term is 25 years when `wear_layer_mil` is at least 20, 20 years
    when it is at least 12 but below 20, 15 years when it is at least 6 but below
    12, and 10 years otherwise."
    "The light-commercial term over the same tiers is 15, 10, 5 and 0 years."
    "Triage stamps `assigned_adjuster_user_id` with the acting adjuster and
    **forks** the investigation by setting `required_reviews`: a `DELAMINATION` or
    `LOCK_FAILURE` claim requires both a materials review and a field review, while
    a `WEAR_LAYER_WEARTHROUGH` or `DIMENSIONAL_MOVEMENT` claim requires the field
    review only."
    "`elapsed_months` is the number of whole calendar months from `installed_on` to
    `reported_on`, floored, so a partial month does not count."
    "The `replacement_value_cents` is the `claimed_area_sqm` multiplied by the SKU's
    `royalty_basis_price_cents_per_sqm`, rounded half up to a whole cent."
    "The `labor_allowance_cents` is the `claimed_area_sqm` multiplied by 350 cents
    per square metre, rounded half up to a whole cent, when
    `installed_by_certified_installer` is true, and 0 otherwise."
    "A `WEAR_LAYER_WEARTHROUGH` or `DIMENSIONAL_MOVEMENT` claim uses
    `PRORATED_STRAIGHT_LINE`: the remaining months — the coverage term less
    `elapsed_months`, floored at zero — divided by the coverage term, applied to the
    replacement value and rounded half up to a whole cent."
    "A measurement exactly equal to the specified thickness less 0.5 is *not* a
    defect, because the comparison is strict."
    "The `settlement_amount_cents` is the covered value plus the
    `labor_allowance_cents`, added as two already-rounded integers."

    Design: Difficulty/dual_variant_calc/warranty_settlement_prorated_versus_stepped_variant_divergence
    """
    built = build_stock_batch(api)
    sku = validate_success(api.get_product_sku(built["sku"]["id"], PLANT_ADMIN))
    assert sku["warranty_years"] == 20
    assert sku["light_commercial_warranty_years"] == 10

    distributor = create_distributor(api, certified_installer_program=True)
    set_clock(api, "2026-08-25T00:00:00Z")

    claim = get_success_data(
        api.create_warranty_claim(
            {
                "claim_code": "WC-WEAR",
                "batch_id": built["batch"]["id"],
                "distributor_id": distributor["id"],
                "claim_type": "WEAR_LAYER_WEARTHROUGH",
                "claimed_area_sqm": 60.00,
                "installed_on": "2021-03-10T00:00:00Z",
                "reported_on": "2026-08-20T00:00:00Z",
                "installed_by_certified_installer": True,
            },
            distributor_headers(distributor["id"]),
        )
    )
    triaged = get_success_data(
        api.triage_warranty_claim(claim["id"], WARRANTY_ADJUSTER)
    )
    assert triaged["required_reviews"] == ["FIELD"]
    get_success_data(
        api.record_claim_review(
            claim["id"],
            {
                "review_kind": "FIELD",
                "outcome": "DEFECT_CONFIRMED",
                "note": "wear-through to print film",
            },
            WARRANTY_ADJUSTER,
        )
    )
    settled = validate_success(
        api.adjudicate_warranty_claim(
            claim["id"], {"decision": "APPROVE"}, WARRANTY_ADJUSTER_B
        )
    )

    assert settled["status"] == "APPROVED"
    assert settled["elapsed_months"] == 65
    assert settled["settlement_variant"] == "PRORATED_STRAIGHT_LINE"
    assert settled["replacement_value_cents"] == 126000
    assert settled["labor_allowance_cents"] == 21000
    assert settled["settlement_amount_cents"] == 112875


def test_delamination_claim_settles_on_the_stepped_schedule_variant(api):
    """A delamination claim decays in whole-year steps to 96600 cents.

    "Triage stamps `assigned_adjuster_user_id` with the acting adjuster and
    **forks** the investigation by setting `required_reviews`: a `DELAMINATION` or
    `LOCK_FAILURE` claim requires both a materials review and a field review, while
    a `WEAR_LAYER_WEARTHROUGH` or `DIMENSIONAL_MOVEMENT` claim requires the field
    review only."
    "`elapsed_months` is the number of whole calendar months from `installed_on` to
    `reported_on`, floored, so a partial month does not count."
    "The `replacement_value_cents` is the `claimed_area_sqm` multiplied by the SKU's
    `royalty_basis_price_cents_per_sqm`, rounded half up to a whole cent."
    "The `labor_allowance_cents` is the `claimed_area_sqm` multiplied by 350 cents
    per square metre, rounded half up to a whole cent, when
    `installed_by_certified_installer` is true, and 0 otherwise."
    "A `DELAMINATION` or `LOCK_FAILURE` claim uses `STEPPED_SCHEDULE`: take the
    elapsed whole years as `elapsed_months` divided by twelve rounded down, then
    apply 100 percent when that figure is 1 or less, 80 percent when it is 2 or 3,
    60 percent when it is 4 through 7, 40 percent when it is 8 through 12, and 20
    percent beyond that, rounding the result half up to a whole cent."
    "A measurement exactly equal to the specified thickness less 0.5 is *not* a
    defect, because the comparison is strict."
    "The `settlement_amount_cents` is the covered value plus the
    `labor_allowance_cents`, added as two already-rounded integers."

    Design: Difficulty/dual_variant_calc/warranty_settlement_prorated_versus_stepped_variant_divergence
    """
    built = build_stock_batch(api)
    distributor = create_distributor(api, certified_installer_program=True)
    set_clock(api, "2026-08-25T00:00:00Z")

    claim = get_success_data(
        api.create_warranty_claim(
            {
                "claim_code": "WC-DELAM",
                "batch_id": built["batch"]["id"],
                "distributor_id": distributor["id"],
                "claim_type": "DELAMINATION",
                "claimed_area_sqm": 60.00,
                "installed_on": "2021-03-10T00:00:00Z",
                "reported_on": "2026-08-20T00:00:00Z",
                "installed_by_certified_installer": True,
            },
            distributor_headers(distributor["id"]),
        )
    )
    triaged = get_success_data(api.triage_warranty_claim(claim["id"], WARRANTY_ADJUSTER))
    assert triaged["required_reviews"] == ["MATERIALS", "FIELD"]
    get_success_data(
        api.record_claim_review(
            claim["id"],
            {
                "review_kind": "MATERIALS",
                "outcome": "DEFECT_CONFIRMED",
                "note": "adhesive failure at core interface",
            },
            WARRANTY_ADJUSTER,
        )
    )
    get_success_data(
        api.record_claim_review(
            claim["id"],
            {
                "review_kind": "FIELD",
                "outcome": "DEFECT_CONFIRMED",
                "note": "visible layer separation",
            },
            WARRANTY_ADJUSTER,
        )
    )
    settled = validate_success(
        api.adjudicate_warranty_claim(
            claim["id"], {"decision": "APPROVE"}, WARRANTY_ADJUSTER_B
        )
    )

    assert settled["status"] == "APPROVED"
    assert settled["elapsed_months"] == 65
    assert settled["settlement_variant"] == "STEPPED_SCHEDULE"
    assert settled["replacement_value_cents"] == 126000
    assert settled["labor_allowance_cents"] == 21000
    assert settled["settlement_amount_cents"] == 96600


def test_two_settlement_variants_diverge_by_16275_cents_on_identical_inputs(api):
    """Identical claims on one batch diverge by exactly 16275 cents on claim_type.

    "A `WEAR_LAYER_WEARTHROUGH` or `DIMENSIONAL_MOVEMENT` claim uses
    `PRORATED_STRAIGHT_LINE`: the remaining months — the coverage term less
    `elapsed_months`, floored at zero — divided by the coverage term, applied to the
    replacement value and rounded half up to a whole cent."
    "A `DELAMINATION` or `LOCK_FAILURE` claim uses `STEPPED_SCHEDULE`: take the
    elapsed whole years as `elapsed_months` divided by twelve rounded down, then
    apply 100 percent when that figure is 1 or less, 80 percent when it is 2 or 3,
    60 percent when it is 4 through 7, 40 percent when it is 8 through 12, and 20
    percent beyond that, rounding the result half up to a whole cent."
    "Identical inputs therefore settle differently under the two variants everywhere
    except inside the first step."
    "The `settlement_amount_cents` is the covered value plus the
    `labor_allowance_cents`, added as two already-rounded integers."

    Design: Difficulty/dual_variant_calc/warranty_settlement_prorated_versus_stepped_variant_divergence
    """
    built = build_stock_batch(api)
    distributor = create_distributor(api, certified_installer_program=True)
    set_clock(api, "2026-08-25T00:00:00Z")

    shared = {
        "batch_id": built["batch"]["id"],
        "distributor_id": distributor["id"],
        "claimed_area_sqm": 60.00,
        "installed_on": "2021-03-10T00:00:00Z",
        "reported_on": "2026-08-20T00:00:00Z",
        "installed_by_certified_installer": True,
    }
    headers = distributor_headers(distributor["id"])

    wear = get_success_data(
        api.create_warranty_claim(
            dict(shared, claim_code="WC-WEAR", claim_type="WEAR_LAYER_WEARTHROUGH"),
            headers,
        )
    )
    get_success_data(api.triage_warranty_claim(wear["id"], WARRANTY_ADJUSTER))
    get_success_data(
        api.record_claim_review(
            wear["id"],
            {"review_kind": "FIELD", "outcome": "DEFECT_CONFIRMED"},
            WARRANTY_ADJUSTER,
        )
    )
    wear_settled = validate_success(
        api.adjudicate_warranty_claim(
            wear["id"], {"decision": "APPROVE"}, WARRANTY_ADJUSTER_B
        )
    )

    delam = get_success_data(
        api.create_warranty_claim(
            dict(shared, claim_code="WC-DELAM", claim_type="DELAMINATION"), headers
        )
    )
    get_success_data(api.triage_warranty_claim(delam["id"], WARRANTY_ADJUSTER))
    for review_kind in ("MATERIALS", "FIELD"):
        get_success_data(
            api.record_claim_review(
                delam["id"],
                {"review_kind": review_kind, "outcome": "DEFECT_CONFIRMED"},
                WARRANTY_ADJUSTER,
            )
        )
    delam_settled = validate_success(
        api.adjudicate_warranty_claim(
            delam["id"], {"decision": "APPROVE"}, WARRANTY_ADJUSTER_B
        )
    )

    assert wear_settled["replacement_value_cents"] == 126000
    assert delam_settled["replacement_value_cents"] == 126000
    assert wear_settled["settlement_amount_cents"] == 112875
    assert delam_settled["settlement_amount_cents"] == 96600
    assert (
        wear_settled["settlement_amount_cents"]
        - delam_settled["settlement_amount_cents"]
        == 16275
    )


# ---------------------------------------------------------------------------
# Licensed-volume ledger: reserved basis at admission, actual basis at settlement.
# ---------------------------------------------------------------------------


def test_scheduling_admission_reads_the_reserved_volume_basis(api):
    """A planned run reserves its full quantity and a 900.00 sqm sibling is refused.

    "On success, the run's `planned_quantity_sqm` is added to the grant's
    `reserved_volume_sqm` and the grant's `version` is advanced."
    "The grant's projected volume is its `consumed_volume_sqm` plus its
    `reserved_volume_sqm` plus the new run's `planned_quantity_sqm`, and that
    projection may not exceed `term_volume_cap_sqm`; equality is admitted, and an
    excess is `ERR_LICENSE_VOLUME_CAP_EXCEEDED` (HTTP 422)."
    "This is a forward-looking projection: volume merely reserved by runs in
    `PLANNED`, `SETUP` or `RUNNING` counts against the cap even though nothing has
    physically been produced, which is exactly what makes an admission fail on a
    grant that has produced nothing at all."
    "A grant's utilization is readable as a computed summary carrying
    `term_volume_cap_sqm`, `reserved_volume_sqm`, `consumed_volume_sqm`, the
    forward-looking `projected_volume_sqm` (consumed plus reserved), the
    `remaining_volume_sqm` left under the cap (the cap less the projection), the
    `accrued_royalty_cents` ledger, and `contributing_run_count`, the number of
    completed runs that have contributed royalty to it."

    Design: Difficulty/dual_variant_calc/license_volume_ledger_reserved_versus_actual_basis
    """
    set_clock(api, CLOCK_BOOT_UTC)
    built = build_certified_sku(api)
    press_line = create_press_line(api)
    create_run(
        api,
        built["sku"]["id"],
        press_line["id"],
        run_code="RUN-A1",
        planned_start_utc="2026-08-01T01:00:00Z",
        planned_end_utc="2026-08-01T09:00:00Z",
        planned_quantity_sqm=1200.00,
    )

    utilization = validate_success(
        api.get_license_utilization(built["license"]["id"], TECHNICAL_DIRECTOR)
    )
    assert utilization["term_volume_cap_sqm"] == 2000.00
    assert utilization["reserved_volume_sqm"] == 1200.00
    assert utilization["consumed_volume_sqm"] == 0.00
    assert utilization["projected_volume_sqm"] == 1200.00
    assert utilization["contributing_run_count"] == 0

    refused = api.create_production_run(
        production_run_payload(
            built["sku"]["id"],
            press_line["id"],
            run_code="RUN-A2-REJECT",
            planned_start_utc="2026-08-01T12:00:00Z",
            planned_end_utc="2026-08-01T16:00:00Z",
            planned_quantity_sqm=900.00,
        ),
        PRODUCTION_PLANNER,
    )
    validate_error(refused, ApiErrorId.LICENSE_VOLUME_CAP_EXCEEDED.value)


def test_run_completion_settles_the_ledger_on_the_actual_volume_basis(api):
    """Completion releases the planned 1200.00 and consumes the measured 1300.00.

    "Second, the licensed-volume ledger settles on an actual basis: the run's
    `planned_quantity_sqm` is subtracted from the grant's `reserved_volume_sqm` and
    the measured `actual_quantity_sqm` is added to its `consumed_volume_sqm`."
    "The reservation is released at its *planned* size while the *measured* quantity
    is consumed, so when actual output differs from plan the two figures diverge —
    and the cap is deliberately not re-checked at completion, which means
    `consumed_volume_sqm` may end up above what the admission projection assumed."
    "The run's `actual_quantity_sqm` is multiplied by the SKU's
    `royalty_basis_price_cents_per_sqm` and by the grant's `royalty_rate_bps`
    divided by 10000, and the product is rounded half up to a whole cent."
    "`pattern_waste_sqm` is the run's `actual_quantity_sqm` multiplied by the larger
    of the film's two pattern repeats, divided by 60000, multiplied by 0.35, rounded
    half up to two decimal places."

    Design: Difficulty/dual_variant_calc/license_volume_ledger_reserved_versus_actual_basis
    """
    set_clock(api, CLOCK_BOOT_UTC)
    built = build_certified_sku(api)
    press_line = create_press_line(api)
    run = create_run(
        api,
        built["sku"]["id"],
        press_line["id"],
        run_code="RUN-A1",
        planned_start_utc="2026-08-01T01:00:00Z",
        planned_end_utc="2026-08-01T09:00:00Z",
        planned_quantity_sqm=1200.00,
    )
    setup_run(api, run["id"])
    start_run(api, run["id"])
    completed = complete_run(api, run["id"], 1300.00, **RUN_QC_CLEAN)

    assert completed["actual_quantity_sqm"] == 1300.00
    assert completed["royalty_accrued_cents"] == 136500
    assert completed["pattern_waste_sqm"] == 9.10

    license_row = validate_success(
        api.get_design_license(built["license"]["id"], TECHNICAL_DIRECTOR)
    )
    assert license_row["reserved_volume_sqm"] == 0.00
    assert license_row["consumed_volume_sqm"] == 1300.00
    assert license_row["accrued_royalty_cents"] == 136500


def test_post_completion_admission_allows_a_run_landing_exactly_on_the_cap(api):
    """After 1300.00 is consumed a 700.00 run reaches the 2000.00 cap exactly.

    "The grant's projected volume is its `consumed_volume_sqm` plus its
    `reserved_volume_sqm` plus the new run's `planned_quantity_sqm`, and that
    projection may not exceed `term_volume_cap_sqm`; equality is admitted, and an
    excess is `ERR_LICENSE_VOLUME_CAP_EXCEEDED` (HTTP 422)."
    "On success, the run's `planned_quantity_sqm` is added to the grant's
    `reserved_volume_sqm` and the grant's `version` is advanced."
    "A grant's utilization is readable as a computed summary carrying
    `term_volume_cap_sqm`, `reserved_volume_sqm`, `consumed_volume_sqm`, the
    forward-looking `projected_volume_sqm` (consumed plus reserved), the
    `remaining_volume_sqm` left under the cap (the cap less the projection), the
    `accrued_royalty_cents` ledger, and `contributing_run_count`, the number of
    completed runs that have contributed royalty to it."

    Design: Difficulty/dual_variant_calc/license_volume_ledger_reserved_versus_actual_basis
    """
    set_clock(api, CLOCK_BOOT_UTC)
    built = build_certified_sku(api)
    press_line = create_press_line(api)
    run_a1 = create_run(
        api,
        built["sku"]["id"],
        press_line["id"],
        run_code="RUN-A1",
        planned_start_utc="2026-08-01T01:00:00Z",
        planned_end_utc="2026-08-01T09:00:00Z",
        planned_quantity_sqm=1200.00,
    )
    setup_run(api, run_a1["id"])
    start_run(api, run_a1["id"])
    complete_run(api, run_a1["id"], 1300.00, **RUN_QC_CLEAN)

    admitted = api.create_production_run(
        production_run_payload(
            built["sku"]["id"],
            press_line["id"],
            run_code="RUN-A3",
            planned_start_utc="2026-08-01T12:00:00Z",
            planned_end_utc="2026-08-01T16:00:00Z",
            planned_quantity_sqm=700.00,
        ),
        PRODUCTION_PLANNER,
    )
    validate_success(admitted, 201)

    license_row = validate_success(
        api.get_design_license(built["license"]["id"], TECHNICAL_DIRECTOR)
    )
    assert license_row["reserved_volume_sqm"] == 700.00
    assert license_row["consumed_volume_sqm"] == 1300.00
    assert license_row["accrued_royalty_cents"] == 136500

    utilization = validate_success(
        api.get_license_utilization(built["license"]["id"], TECHNICAL_DIRECTOR)
    )
    assert utilization["projected_volume_sqm"] == 2000.00
    assert utilization["remaining_volume_sqm"] == 0.00
    assert utilization["contributing_run_count"] == 1


# ---------------------------------------------------------------------------
# Blend metrics: two independent penalty ladders and one final clamp-and-round.
# ---------------------------------------------------------------------------


def test_blend_score_of_f_std_subtracts_only_the_brittleness_penalty(api):
    """F-STD lands on brittleness tier 3 with zero softness, scoring 87.15.

    "The four category subtotals — `resin_phr`, `plasticizer_phr`, `filler_phr` and
    `stabilizer_phr` — are the sums of the `phr` of the components whose material
    sits in the corresponding category, each rounded half up to two decimal places,
    and `total_phr` is the sum of `phr` across all components, likewise at two
    decimal places."
    "For each component, multiply its `phr` by the per-kilogram cost that the
    recipe's cost basis dictates: while `cost_basis` is `LIVE`, that is the
    material's current `cost_per_kg_cents`; once `cost_basis` is `PINNED`, it is the
    component's own `material_cost_snapshot_cents`."
    "The `performance_score` is built from three dosage-weighted blend indices, each
    carried to six decimal places and each computed as the sum over components of
    `phr` multiplied by the relevant material property, divided by `total_phr`: the
    blended indentation index uses `indentation_index` directly; the blended thermal
    index uses `thermal_stability_index` directly; and the blended
    migration-resistance index uses 100 minus the material's
    `plasticizer_migration_index`, so that a migration-prone plasticizer drags the
    blend down."
    "Those three indices are weighted at forty percent, thirty-five percent and
    twenty-five percent respectively and added together."
    "The softness penalty reads the plasticizer ratio — `plasticizer_phr` divided by
    `resin_phr`, rounded half up to four decimal places — and is 12 points when that
    ratio is greater than 0.35, 5 points when it is greater than 0.25 but not greater
    than 0.35, and zero otherwise."
    "The brittleness penalty reads the filler ratio — `filler_phr` divided by
    `resin_phr`, also at four decimal places — and is 8 points when that ratio is at
    least 3.00, 3 points when it is at least 2.00 but below 3.00, and zero
    otherwise."
    "The result is clamped to the range 0 through 100, taking whichever of the clamp
    bounds applies, and only then rounded half up to two decimal places."
    "The three blend indices behind a recipe's performance score are each carried to
    six decimal places, and the score is rounded to two decimal places exactly once,
    after clamping."

    Design: Difficulty/combinatorial_formula/formulation_blend_metrics_nested_penalty_ladders_mode_a
    """
    ids = _two_blends_in_draft(api)
    f_std = validate_success(api.get_formulation(ids["f_std_id"], TECHNICAL_DIRECTOR))

    assert f_std["resin_phr"] == 100.00
    assert f_std["plasticizer_phr"] == 22.00
    assert f_std["filler_phr"] == 240.00
    assert f_std["stabilizer_phr"] == 3.00
    assert_blend_metrics(
        f_std,
        total_phr=365.00,
        blended_cost_per_kg_cents=101,
        performance_score=87.15,
        indentation_resistance_class="CLASS_34_43",
    )
    assert f_std["status"] == "DRAFT"
    assert f_std["cost_basis"] == "LIVE"


def test_blend_score_of_f_low_subtracts_both_top_penalty_tiers(api):
    """F-LOW lands on both top tiers, losing 12 plus 8 points to score 68.73.

    "The `performance_score` is built from three dosage-weighted blend indices, each
    carried to six decimal places and each computed as the sum over components of
    `phr` multiplied by the relevant material property, divided by `total_phr`: the
    blended indentation index uses `indentation_index` directly; the blended thermal
    index uses `thermal_stability_index` directly; and the blended
    migration-resistance index uses 100 minus the material's
    `plasticizer_migration_index`, so that a migration-prone plasticizer drags the
    blend down."
    "Those three indices are weighted at forty percent, thirty-five percent and
    twenty-five percent respectively and added together."
    "The softness penalty reads the plasticizer ratio — `plasticizer_phr` divided by
    `resin_phr`, rounded half up to four decimal places — and is 12 points when that
    ratio is greater than 0.35, 5 points when it is greater than 0.25 but not greater
    than 0.35, and zero otherwise."
    "The brittleness penalty reads the filler ratio — `filler_phr` divided by
    `resin_phr`, also at four decimal places — and is 8 points when that ratio is at
    least 3.00, 3 points when it is at least 2.00 but below 3.00, and zero
    otherwise."
    "The result is clamped to the range 0 through 100, taking whichever of the clamp
    bounds applies, and only then rounded half up to two decimal places."
    "Add those products together, divide the total by `total_phr`, and round half up
    to a whole cent."
    "A newly created recipe is `DRAFT` with `revision` 1, `cost_basis` `LIVE`,
    `rejection_count` and `open_revision_count` both 0, and `authored_by_user_id` set
    to the acting `X-User-ID`."

    Design: Difficulty/combinatorial_formula/formulation_blend_metrics_nested_penalty_ladders_mode_a
    """
    ids = _two_blends_in_draft(api)
    f_low = validate_success(api.get_formulation(ids["f_low_id"], TECHNICAL_DIRECTOR))

    assert_blend_metrics(
        f_low,
        total_phr=475.00,
        blended_cost_per_kg_cents=93,
        performance_score=68.73,
        indentation_resistance_class="CLASS_34_43",
    )
    assert f_low["status"] == "DRAFT"
    assert f_low["cost_basis"] == "LIVE"


def test_indentation_class_is_read_off_the_blend_index_not_the_score(api):
    """Both recipes share CLASS_34_43 although their scores are 87.15 and 68.73.

    "The `indentation_resistance_class` is derived from the blended indentation
    index **alone**, never from `performance_score`: the class is `CLASS_34_43` when
    that index is at least 88.00, `CLASS_33_42` when it is at least 70.00 but below
    88.00, and `CLASS_23_31` otherwise."
    "Two recipes with an identical score can therefore land in different classes."
    "The result is clamped to the range 0 through 100, taking whichever of the clamp
    bounds applies, and only then rounded half up to two decimal places."

    Design: Difficulty/combinatorial_formula/formulation_blend_metrics_nested_penalty_ladders_mode_a
    """
    ids = _two_blends_in_draft(api)
    f_std = validate_success(api.get_formulation(ids["f_std_id"], TECHNICAL_DIRECTOR))
    f_low = validate_success(api.get_formulation(ids["f_low_id"], TECHNICAL_DIRECTOR))

    assert f_std["performance_score"] == 87.15
    assert f_low["performance_score"] == 68.73
    assert f_std["indentation_resistance_class"] == "CLASS_34_43"
    assert f_low["indentation_resistance_class"] == "CLASS_34_43"


# ---------------------------------------------------------------------------
# Royalty accrual: round per run, then accumulate.
# ---------------------------------------------------------------------------


def test_each_run_rounds_its_own_royalty_to_1061_cents(api):
    """Each 10.10 sqm run computes 1060.50 cents and stores 1061 on its own row.

    "The run's `actual_quantity_sqm` is multiplied by the SKU's
    `royalty_basis_price_cents_per_sqm` and by the grant's `royalty_rate_bps` divided
    by 10000, and the product is rounded half up to a whole cent."
    "A production run's royalty contribution is rounded to a whole cent on its own
    and only that rounded integer is added to the grant's royalty ledger."
    "`pattern_waste_sqm` is the run's `actual_quantity_sqm` multiplied by the larger
    of the film's two pattern repeats, divided by 60000, multiplied by 0.35, rounded
    half up to two decimal places."
    "`auto_disposition_recommendation` is set to `RELEASED` when all four gates hold
    and `QUARANTINED` otherwise; it is advisory only."

    Design: Difficulty/combinatorial_formula/license_royalty_accrual_round_per_run_then_sum_mode_b
    """
    built = _two_runs_of_ten_point_one(api)

    assert built["run_r1"]["royalty_accrued_cents"] == 1061
    assert built["run_r2"]["royalty_accrued_cents"] == 1061
    assert built["run_r1"]["pattern_waste_sqm"] == 0.07
    assert built["run_r1"]["auto_disposition_recommendation"] == "RELEASED"


def test_royalty_ledger_accumulates_rounded_run_integers_to_2122_cents(api):
    """The grant ledger holds 1061 + 1061 = 2122 cents, not the 2121 of a late round.

    "A production run's royalty contribution is rounded to a whole cent on its own
    and only that rounded integer is added to the grant's royalty ledger."
    "Two runs each computing 1060.50 cents contribute 1061 cents each, for a ledger
    total of 2122 cents — not the 2121 cents that accumulating first and rounding
    once would give."
    "That integer is stored in the run's `royalty_accrued_cents` and added to the
    grant's `accrued_royalty_cents`, one run at a time, per the rounding-order rule
    of §2.6."
    "Second, the licensed-volume ledger settles on an actual basis: the run's
    `planned_quantity_sqm` is subtracted from the grant's `reserved_volume_sqm` and
    the measured `actual_quantity_sqm` is added to its `consumed_volume_sqm`."

    Design: Difficulty/combinatorial_formula/license_royalty_accrual_round_per_run_then_sum_mode_b
    """
    built = _two_runs_of_ten_point_one(api)

    utilization = validate_success(
        api.get_license_utilization(built["license_id"], TECHNICAL_DIRECTOR)
    )
    assert utilization["accrued_royalty_cents"] == 2122
    assert utilization["consumed_volume_sqm"] == 20.20

    license_row = validate_success(
        api.get_design_license(built["license_id"], TECHNICAL_DIRECTOR)
    )
    assert license_row["accrued_royalty_cents"] == 2122
    assert license_row["reserved_volume_sqm"] == 0.00


# ---------------------------------------------------------------------------
# Allocation fill: rank before cost, waterfall before the per-line premium.
# ---------------------------------------------------------------------------


def test_upgrade_delta_between_the_two_wear_layers_is_28_cents_per_sqm(api):
    """SKU-A stamps 1157 and SKU-A20 stamps 1185, a per-sqm premium of exactly 28.

    "The cost of a square metre is assembled from seven named components, each
    rounded half up to a whole cent on its own before any addition happens."
    "The wear-layer component is `wear_layer_mil` multiplied by 3.5 cents per mil per
    square metre."
    "`standard_cost_cents_per_sqm` is computed on the pinned basis described in §3.3
    and stored, and `list_price_cents_per_sqm` is derived from it by the
    `target_margin_bps` gross-up."
    "Otherwise, take the per-square-metre premium as the candidate SKU's
    `standard_cost_cents_per_sqm` less the requested SKU's, floored at zero so that a
    cheaper substitute contributes nothing rather than a credit, and treated as zero
    outright if either SKU's standard cost is null."

    Design: Difficulty/combinatorial_formula/allocation_fill_plan_rank_before_cost_step_order_mode_c
    """
    built = _wear_layer_upgrade_stock(api)

    sku_a = validate_success(api.get_product_sku(built["sku_a"]["id"], PLANT_ADMIN))
    sku_a20 = validate_success(api.get_product_sku(built["sku_a20"]["id"], PLANT_ADMIN))
    assert sku_a["standard_cost_cents_per_sqm"] == 1157
    assert sku_a20["standard_cost_cents_per_sqm"] == 1185


def test_fill_drains_the_two_exact_batches_before_the_older_upgrade_batch(api):
    """The 300.00 sqm request is met by two EXACT lines, leaving B1 untouched.

    "Candidates are ordered by substitution kind first — exact matches ahead of
    underlayment upgrades, which are ahead of wear-layer upgrades — then by the
    batch's `created_at` ascending, then by `batch_code` ascending."
    "An exact match therefore always outranks any upgrade batch, however much older
    the upgrade batch is."
    "The ranking may **not** consult upgrade cost; the per-line premiums do not even
    exist until step four, and ranking cheapest-upgrade-first produces a different,
    incorrect line set."
    "Walking the candidates in rank order while the remaining requirement is strictly
    positive, each candidate contributes the smaller of the remaining requirement and
    its own `available_quantity_sqm`."
    "The first candidate is drained completely before the second is touched, even
    when the second alone would have covered the whole request."
    "Each line's `upgrade_cost_delta_cents` is 0 when its `substitution_kind` is
    `EXACT`."
    "The allocation's `allocated_quantity_sqm` is then the sum of its `ACTIVE` lines'
    quantities at two decimal places, and its `upgrade_cost_total_cents` is the exact
    sum of those already-rounded per-line integers."
    "The allocation's resulting `status` follows from the arithmetic: `FILLED` when
    `allocated_quantity_sqm` has reached `requested_quantity_sqm`,
    `PARTIALLY_FILLED` when it is above zero but short of the request, and `OPEN`
    when it is zero."

    Design: Difficulty/combinatorial_formula/allocation_fill_plan_rank_before_cost_step_order_mode_c
    """
    built = _wear_layer_upgrade_stock(api)
    distributor_id = built["distributor_id"]
    allocation = create_allocation(
        api,
        distributor_id,
        built["sku_a"]["id"],
        allocation_code="AL-M1",
        requested_quantity_sqm=300.00,
        substitution_policy="ALLOW_WEAR_LAYER_UPGRADE",
    )
    filled = fill_allocation(
        api, allocation["id"], distributor_id, allocation["version"]
    )

    assert filled["allocated_quantity_sqm"] == 300.00
    assert filled["upgrade_cost_total_cents"] == 0
    assert filled["status"] == "FILLED"

    lines, meta = validate_paginated(
        api.list_allocation_lines(
            allocation["id"], distributor_headers(distributor_id)
        )
    )
    assert meta["total_count"] == 2
    assert lines[0]["batch_id"] == built["b2_id"]
    assert lines[0]["quantity_sqm"] == 100.00
    assert lines[0]["substitution_kind"] == "EXACT"
    assert lines[0]["upgrade_cost_delta_cents"] == 0
    assert lines[1]["batch_id"] == built["b3_id"]
    assert lines[1]["quantity_sqm"] == 200.00
    assert lines[1]["substitution_kind"] == "EXACT"
    assert lines[1]["upgrade_cost_delta_cents"] == 0

    b1 = validate_success(api.get_batch(built["b1_id"], QA_TECHNICIAN))
    b2 = validate_success(api.get_batch(built["b2_id"], QA_TECHNICIAN))
    b3 = validate_success(api.get_batch(built["b3_id"], QA_TECHNICIAN))
    assert b1["available_quantity_sqm"] == 300.00
    assert b2["available_quantity_sqm"] == 0.00
    assert b3["available_quantity_sqm"] == 100.00


def test_second_fill_prices_the_wear_layer_upgrade_line_at_2800_cents(api):
    """Once the exacts run short the upgrade batch is drawn and priced at 2800 cents.

    "A `WEAR_LAYER_UPGRADE` candidate is admissible only under the
    `ALLOW_WEAR_LAYER_UPGRADE` policy, and only when the candidate SKU's
    `wear_layer_mil` is strictly greater than the requested SKU's and the two agree
    exactly on `formulation_id`, `print_film_id`, `construction_type`,
    `attached_underlayment_type` and `waterproof_rated`."
    "Candidates are ordered by substitution kind first — exact matches ahead of
    underlayment upgrades, which are ahead of wear-layer upgrades — then by the
    batch's `created_at` ascending, then by `batch_code` ascending."
    "The remaining requirement is the allocation's `requested_quantity_sqm` less its
    current `allocated_quantity_sqm`, rounded half up to two decimal places."
    "Otherwise, take the per-square-metre premium as the candidate SKU's
    `standard_cost_cents_per_sqm` less the requested SKU's, floored at zero so that a
    cheaper substitute contributes nothing rather than a credit, and treated as zero
    outright if either SKU's standard cost is null."
    "Multiply that premium by the line's `quantity_sqm` and round half up to a whole
    cent."
    "The allocation's `allocated_quantity_sqm` is then the sum of its `ACTIVE` lines'
    quantities at two decimal places, and its `upgrade_cost_total_cents` is the exact
    sum of those already-rounded per-line integers."

    Design: Difficulty/combinatorial_formula/allocation_fill_plan_rank_before_cost_step_order_mode_c
    """
    built = _wear_layer_upgrade_stock(api)
    distributor_id = built["distributor_id"]
    headers = distributor_headers(distributor_id)

    first = create_allocation(
        api,
        distributor_id,
        built["sku_a"]["id"],
        allocation_code="AL-M1",
        requested_quantity_sqm=300.00,
        substitution_policy="ALLOW_WEAR_LAYER_UPGRADE",
    )
    fill_allocation(api, first["id"], distributor_id, first["version"])

    second = create_allocation(
        api,
        distributor_id,
        built["sku_a"]["id"],
        allocation_code="AL-M2",
        requested_quantity_sqm=200.00,
        substitution_policy="ALLOW_WEAR_LAYER_UPGRADE",
    )
    filled = fill_allocation(api, second["id"], distributor_id, second["version"])

    assert filled["allocated_quantity_sqm"] == 200.00
    assert filled["upgrade_cost_total_cents"] == 2800
    assert filled["status"] == "FILLED"

    lines, meta = validate_paginated(api.list_allocation_lines(second["id"], headers))
    assert meta["total_count"] == 2
    assert lines[0]["batch_id"] == built["b3_id"]
    assert lines[0]["quantity_sqm"] == 100.00
    assert lines[0]["substitution_kind"] == "EXACT"
    assert lines[0]["upgrade_cost_delta_cents"] == 0
    assert lines[1]["batch_id"] == built["b1_id"]
    assert lines[1]["quantity_sqm"] == 100.00
    assert lines[1]["substitution_kind"] == "WEAR_LAYER_UPGRADE"
    assert lines[1]["upgrade_cost_delta_cents"] == 2800

    b1 = validate_success(api.get_batch(built["b1_id"], QA_TECHNICIAN))
    assert b1["available_quantity_sqm"] == 200.00
