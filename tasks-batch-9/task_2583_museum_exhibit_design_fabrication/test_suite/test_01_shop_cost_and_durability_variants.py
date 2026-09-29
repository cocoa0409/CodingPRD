"""Two-variant calculations: the schematic estimate against the shop actual, and
the specification durability index against the bench-verified one.

Both calculations in this file run twice over the same stored row with different
inputs, so every test here pins the exact figures each variant produces and the
consequence the second variant has that the first does not.
"""

import pytest

from test_helpers import (
    CONSERVATOR,
    FABRICATION,
    PM,
    ComplexityTier,
    DrawingDecision,
    DrawingStatus,
    FinishGrade,
    InteractiveKind,
    InteractiveStatus,
    MaintenanceTier,
    MountStatus,
    PackageStage,
    Phase,
    PrototypeDecision,
    UsedIn,
    assert_counters,
    assert_index,
    assert_ledger,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_success,
)
from test_helpers import ERR_WARRANTY_TERM_TOO_SHORT
from test_helpers.fixtures import LATE_CLOCK

CONTRACT_VALUE_CENTS = 9000000


def _cleared_prototype(api, interactive_id, measured_daily_uses=60, measured_mtbf_cycles=1500000):
    """Run one interactive from SPECIFIED to PROTOTYPE_APPROVED on bench figures."""
    validate_success(
        api.submit_prototype(
            interactive_id,
            f.prototype_payload(measured_daily_uses, measured_mtbf_cycles),
            FABRICATION,
        )
    )
    return validate_success(
        api.prototype_decision(
            interactive_id,
            f.prototype_decision_payload(PrototypeDecision.APPROVE),
            CONSERVATOR,
        )
    )


def _fabrication_world(api):
    """A commission in FABRICATION with a cleared prototype and a cleared housing material.

    The ledger is still untouched: no shop drawing has been decided, so the whole
    contract value sits in uncommitted_cents.
    """
    ctx = fx.project_in_phase(api, Phase.FABRICATION)
    _cleared_prototype(api, ctx["interactive_id"])
    housing = fx.create_material(
        api,
        ctx["project_id"],
        material_name="Powder-coated aluminium housing",
        used_in=UsedIn.INTERACTIVE_HOUSING,
        voc_mg_per_m2_day=0.12,
        formaldehyde_ppm=0.02,
        cure_days=14,
    )
    fx.approve_material(api, housing["id"])
    ctx["housing_material_id"] = housing["id"]
    return ctx


def _issue_precision_gloss_sheet(api, ctx):
    """Issue SD-101: PRECISION, 12.5 shop hours, 3.7 m2, MUSEUM_GLOSS on housing stock."""
    return fx.create_drawing(
        api,
        ctx["project_id"],
        ctx["housing_material_id"],
        drawing_number="SD-101",
        complexity_tier=ComplexityTier.PRECISION,
        shop_hours=12.5,
        material_area_m2=3.7,
        finish_grade=FinishGrade.MUSEUM_GLOSS,
        subject_interactive_id=ctx["interactive_id"],
    )


def _project_in_design_dev(api):
    """A commission standing in DESIGN_DEV, the earliest phase that accepts a prototype."""
    fx.set_clock(api)
    project = fx.create_project(api)
    project_id = project["id"]
    fx.advance(api, project_id, Phase.SCHEMATIC)
    fx.approve_package(api, project_id, PackageStage.SCHEMATIC)
    fx.advance(api, project_id, Phase.DESIGN_DEV)
    return project_id


def _walk_to_commissioning(api, **interactive_overrides):
    """Drive a commission to COMMISSIONING carrying one interactive of our own spec.

    The interactive carries the second learning objective and the artifact case
    carries the first, so the advance out of DESIGN_DEV finds every objective code
    addressed.
    """
    fx.set_clock(api)
    project = fx.create_project(api)
    project_id = project["id"]
    fx.advance(api, project_id, Phase.SCHEMATIC)
    zone = fx.create_zone(api, project_id)
    artifact = fx.create_artifact(api, project_id)
    case = fx.create_case(api, project_id, zone["id"])
    interactive = fx.create_interactive(api, project_id, **interactive_overrides)
    fx.approve_package(api, project_id, PackageStage.SCHEMATIC)
    fx.advance(api, project_id, Phase.DESIGN_DEV)
    fx.approve_package(api, project_id, PackageStage.DESIGN_DEV)
    fx.advance(api, project_id, Phase.FABRICATION)
    material = fx.create_material(api, project_id)
    fx.approve_material(api, material["id"])
    _cleared_prototype(api, interactive["id"], 900, 300000)
    validate_success(api.mark_fabricated(interactive["id"], FABRICATION))
    fx.place_artifact(api, case["id"], artifact["id"])
    fx.approve_case(api, case["id"])
    drawing = fx.create_drawing(
        api, project_id, material["id"], subject_case_id=case["id"]
    )
    fx.approve_drawing(api, drawing["id"])
    fx.advance_mount(api, case["id"], MountStatus.MOUNT_DESIGN)
    fx.advance_mount(api, case["id"], MountStatus.MOUNT_FABRICATED)
    window = fx.create_window(
        api,
        project_id,
        zone["id"],
        starts_at="2026-09-09T09:00:00Z",
        ends_at="2026-09-09T12:00:00Z",
    )
    fx.decide_window(api, window["id"])
    fx.advance(api, project_id, Phase.INSTALLATION)
    fx.set_clock(api, LATE_CLOCK)
    fx.start_window(api, window["id"])
    fx.advance_mount(api, case["id"], MountStatus.MOUNT_INSTALLED)
    fx.complete_window(api, window["id"])
    fx.advance(api, project_id, Phase.COMMISSIONING)
    return project_id, interactive["id"]


# ---------------------------------------------------------------------------
# The estimate variant and the actual variant of the fabrication cost model
# ---------------------------------------------------------------------------
def test_the_schematic_estimate_prices_the_sheet_without_moving_the_ledger(api):
    """Issuing SD-101 prices it at the schematic contingency and allowance only.

    A PRECISION sheet of 12.5 shop hours on 3.7 square metres of
    INTERACTIVE_HOUSING stock finished MUSEUM_GLOSS estimates labour at
    12.5 * 14500 * 1.15 = 208437.5 -> 208438 cents, material at
    3.7 * 47500 * 1.20 = 210900 cents and finishing at 13.5 percent of that
    already-rounded material line, 28471.5 -> 28472 cents, for a total of
    447810 cents. None of it reaches the five-bucket ledger.

    "At issue it runs as a **schematic estimate**: the hours are the submitted `shop_hours`, the labour multiplier is the schematic contingency of 1.15, and the waste factor is the schematic allowance of 1.20."

    Design: Difficulty/dual_variant_calc/fabrication_estimate_versus_shop_actual_on_one_drawing
    """
    ctx = _fabrication_world(api)
    drawing = _issue_precision_gloss_sheet(api, ctx)

    assert drawing["status"] == DrawingStatus.SUBMITTED
    assert drawing["estimate_labor_cents"] == 208438
    assert drawing["estimate_material_cents"] == 210900
    assert drawing["estimate_finishing_cents"] == 28472
    assert drawing["estimate_total_cents"] == 447810
    assert drawing["actual_shop_hours"] is None
    assert drawing["actual_waste_factor"] is None
    assert drawing["actual_labor_cents"] is None
    assert drawing["actual_material_cents"] is None
    assert drawing["actual_finishing_cents"] is None
    assert drawing["actual_cost_cents"] is None

    project = fx.read_project(api, ctx["project_id"])
    assert_ledger(project, committed=0, uncommitted=CONTRACT_VALUE_CENTS)


def test_the_shop_actual_reprices_the_same_sheet_and_commits_the_divergent_total(api):
    """Approving SD-101 with the shop's real figures reprices and commits it.

    The same 12.5 hours and 3.7 square metres, now with the labour multiplier at
    exactly 1.00 and the waste factor at the shop's actual 1.00, give labour
    181250, material 175750 and finishing 23726.25 -> 23726 cents, an actual
    total of 380726 cents that sits 67084 cents below the 447810-cent estimate,
    and that actual total is the amount the ledger moves.

    "With them the cost model runs again as the **shop-drawing actual**: the hours are the supplied `actual_shop_hours`, the labour multiplier is exactly 1.00 because the schematic contingency is *dropped* rather than re-based, and the waste factor is the supplied `actual_waste_factor`."

    Design: Difficulty/dual_variant_calc/fabrication_estimate_versus_shop_actual_on_one_drawing
    """
    ctx = _fabrication_world(api)
    drawing = _issue_precision_gloss_sheet(api, ctx)
    estimate_total = drawing["estimate_total_cents"]

    decided = fx.approve_drawing(
        api,
        drawing["id"],
        DrawingDecision.APPROVE,
        actual_shop_hours=12.5,
        actual_waste_factor=1.0,
    )

    assert decided["status"] == DrawingStatus.APPROVED
    assert decided["actual_labor_cents"] == 181250
    assert decided["actual_material_cents"] == 175750
    assert decided["actual_finishing_cents"] == 23726
    assert decided["actual_cost_cents"] == 380726
    assert estimate_total - decided["actual_cost_cents"] == 67084
    assert decided["estimate_total_cents"] == 447810

    project = fx.read_project(api, ctx["project_id"])
    assert_ledger(project, committed=380726, uncommitted=8619274)
    assert project["retainage_held_cents"] == 0
    assert project["warranty_reserve_cents"] == 0
    assert project["released_cents"] == 0


# ---------------------------------------------------------------------------
# The specification variant and the verified variant of the durability index
# ---------------------------------------------------------------------------
def test_the_specification_variant_scores_the_station_from_catalogue_figures(api):
    """A touchscreen specified at 150 uses a day scores 70.60 and lands MEDIUM.

    The wear ratio is 150 * 6.0 * 320 / 1200000 = 0.24, so the wear penalty is
    0.55 * 24.0 = 13.20; the touchscreen fragility of 18 costs 0.9 * 18 = 16.20;
    ten years of parts supply costs nothing. With no prototype credit the index
    is 100 - 13.20 - 16.20 = 70.60, which is at least 60 and below 80.

    "The **specification** variant uses `expected_daily_uses` and the catalogue `mtbf_cycles` with a prototype credit of zero, and writes `durability_index_spec`."

    Design: Difficulty/dual_variant_calc/durability_index_spec_versus_prototype_verified_moves_maintenance_tier
    """
    project = fx.create_project(api)

    interactive = fx.create_interactive(
        api,
        project["id"],
        kind=InteractiveKind.TOUCHSCREEN,
        expected_daily_uses=150,
        duty_hours_per_day=6.0,
        mtbf_cycles=1200000,
        parts_availability_years=10,
        warranty_months=12,
    )

    assert interactive["status"] == InteractiveStatus.SPECIFIED
    assert interactive["prototype_iteration"] == 0
    assert_index(interactive["durability_index_spec"], 70.60)
    assert interactive["durability_index_verified"] is None
    assert interactive["measured_daily_uses"] is None
    assert interactive["measured_mtbf_cycles"] is None
    assert interactive["maintenance_tier"] == MaintenanceTier.MEDIUM


def test_the_verified_variant_adds_the_prototype_credit_and_relaxes_the_maintenance_tier(api):
    """Approving the bench prototype rewrites the index to 87.58 and the tier to LOW.

    The bench measured 60 uses a day against 1500000 cycles, a wear ratio of
    0.0768 and a wear penalty of 0.55 * 7.68 = 4.224; the kind penalty is
    unchanged at 16.20 and the parts penalty is still zero, and the 8-point
    prototype credit lifts the score to 87.576, rounded half up to 87.58. The
    specification figure is not overwritten by the verified one.

    "The **verified** variant uses the bench-measured `measured_daily_uses` and `measured_mtbf_cycles` with a prototype credit of 8 points — the reward for having actually built and tested the thing — and writes `durability_index_verified`; because the credit can push a strong station past a perfect score, this variant is where the cap at 100.0 bites."

    "The `maintenance_tier` is then derived from `durability_index_verified` when that field is non-null and from `durability_index_spec` otherwise, with inclusive lower boundaries: at least 80 is `LOW`, at least 60 is `MEDIUM`, at least 40 is `HIGH`, and anything below 40 is `CRITICAL`."

    Design: Difficulty/dual_variant_calc/durability_index_spec_versus_prototype_verified_moves_maintenance_tier
    """
    project_id = _project_in_design_dev(api)
    interactive = fx.create_interactive(
        api,
        project_id,
        kind=InteractiveKind.TOUCHSCREEN,
        expected_daily_uses=150,
        duty_hours_per_day=6.0,
        mtbf_cycles=1200000,
        parts_availability_years=10,
        warranty_months=12,
    )
    assert_index(interactive["durability_index_spec"], 70.60)

    ruled = _cleared_prototype(api, interactive["id"], 60, 1500000)

    assert ruled["status"] == InteractiveStatus.PROTOTYPE_APPROVED
    assert ruled["prototype_iteration"] == 1
    assert_index(ruled["durability_index_verified"], 87.58)
    assert_index(ruled["durability_index_spec"], 70.60)
    assert ruled["maintenance_tier"] == MaintenanceTier.LOW
    assert ruled["measured_daily_uses"] == 60
    assert ruled["measured_mtbf_cycles"] == 1500000

    read_back = validate_success(api.get_interactive(interactive["id"], PM))
    assert_index(read_back["durability_index_spec"], 70.60)
    assert_index(read_back["durability_index_verified"], 87.58)
    assert read_back["maintenance_tier"] == MaintenanceTier.LOW


# ---------------------------------------------------------------------------
# The verified variant running the other way: a bench result worse than spec
# ---------------------------------------------------------------------------
def test_the_specification_index_alone_puts_the_audio_station_in_the_low_tier(api):
    """An audio post specified at 40 uses a day scores 91.39 and lands LOW.

    The wear ratio is 40 * 4.0 * 320 / 2000000 = 0.0256, so the wear penalty is
    0.55 * 2.56 = 1.408; the audio fragility of 8 costs 0.9 * 8 = 7.20 and ten
    years of parts supply costs nothing, giving 100 - 1.408 - 7.20 = 91.392,
    rounded half up to 91.39. At least 80 is LOW, so a warranty of 12 months is
    all the tier demands while only the specification figure exists.

    "The **specification** variant uses `expected_daily_uses` and the catalogue `mtbf_cycles` with a prototype credit of zero, and writes `durability_index_spec`."

    Design: Difficulty/dual_variant_calc/verified_index_can_degrade_the_tier_and_raise_the_required_warranty
    """
    project = fx.create_project(api)

    interactive = fx.create_interactive(
        api,
        project["id"],
        code="INT-EXT",
        kind=InteractiveKind.AUDIO,
        expected_daily_uses=40,
        duty_hours_per_day=4.0,
        mtbf_cycles=2000000,
        parts_availability_years=10,
        warranty_months=12,
    )

    assert_index(interactive["durability_index_spec"], 91.39)
    assert interactive["durability_index_verified"] is None
    assert interactive["maintenance_tier"] == MaintenanceTier.LOW
    assert interactive["warranty_months"] == 12
    assert interactive["duty_hours_per_day"] == pytest.approx(4.0, abs=0.01)


def test_bench_figures_worse_than_specification_saturate_the_wear_penalty_and_degrade_the_tier(api):
    """A bench run of 900 uses a day against 300000 cycles drops the index to 67.80.

    The wear ratio is 900 * 4.0 * 320 / 300000 = 3.84, so the uncapped penalty
    would be 0.55 * 384 = 211.2 and would drive the score far below zero; the cap
    holds the wear penalty at 0.55 * 60.0 = 33.00, leaving
    100 - 33.00 - 7.20 - 0 + 8 = 67.80. That is below 80 and at least 60, so the
    tier degrades from LOW to MEDIUM while the stored warranty term stays at 12.

    "**The cap makes the penalty non-linear**: once the ratio passes 0.60 the wear penalty saturates at 33.0 and a station that is twice as hard-worn scores no worse than one merely at the cap."

    Design: Difficulty/dual_variant_calc/verified_index_can_degrade_the_tier_and_raise_the_required_warranty
    """
    project_id = _project_in_design_dev(api)
    interactive = fx.create_interactive(
        api,
        project_id,
        code="INT-EXT",
        kind=InteractiveKind.AUDIO,
        expected_daily_uses=40,
        duty_hours_per_day=4.0,
        mtbf_cycles=2000000,
        parts_availability_years=10,
        warranty_months=12,
    )
    assert_index(interactive["durability_index_spec"], 91.39)
    assert interactive["maintenance_tier"] == MaintenanceTier.LOW

    ruled = _cleared_prototype(api, interactive["id"], 900, 300000)

    assert ruled["status"] == InteractiveStatus.PROTOTYPE_APPROVED
    assert_index(ruled["durability_index_verified"], 67.80)
    assert_index(ruled["durability_index_spec"], 91.39)
    assert ruled["maintenance_tier"] == MaintenanceTier.MEDIUM
    assert ruled["warranty_months"] == 12


def test_the_degraded_tier_makes_the_specified_warranty_term_too_short_at_commissioning(api):
    """The MEDIUM tier the bench run produced demands 24 months, so 12 is refused.

    The station reaches COMMISSIONING at FABRICATED carrying the verified index of
    67.80 and therefore the MEDIUM tier, whose floor is 24 months. The stored term
    is 12, so commissioning is refused and the station stays FABRICATED.

    "Finally the term must meet the floor its derived `maintenance_tier` demands: 12 months at `LOW`, 24 at `MEDIUM`, 36 at `HIGH` and 60 at `CRITICAL`, with a term exactly equal to the floor accepted and anything shorter refused with `ERR_WARRANTY_TERM_TOO_SHORT` (HTTP 422)."

    Design: Difficulty/dual_variant_calc/verified_index_can_degrade_the_tier_and_raise_the_required_warranty
    """
    project_id, interactive_id = _walk_to_commissioning(
        api,
        code="INT-EXT",
        kind=InteractiveKind.AUDIO,
        expected_daily_uses=40,
        duty_hours_per_day=4.0,
        mtbf_cycles=2000000,
        parts_availability_years=10,
        warranty_months=12,
    )

    before = validate_success(api.get_interactive(interactive_id, PM))
    assert before["status"] == InteractiveStatus.FABRICATED
    assert_index(before["durability_index_verified"], 67.80)
    assert before["maintenance_tier"] == MaintenanceTier.MEDIUM
    assert before["warranty_months"] == 12

    response = api.commission_interactive(interactive_id, f.commission_payload(), PM)
    validate_error(response, ERR_WARRANTY_TERM_TOO_SHORT, 422)

    after = validate_success(api.get_interactive(interactive_id, PM))
    assert after["status"] == InteractiveStatus.FABRICATED
    assert after["warranty_months"] == 12
    assert after["maintenance_tier"] == MaintenanceTier.MEDIUM
    project = fx.read_project(api, project_id)
    assert_counters(project, phase=Phase.COMMISSIONING)
