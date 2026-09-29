"""Formulas assembled from several independent lookups and a pinned step order.

The fabrication cost model rounds each of its three line items separately and
indexes three different constant maps, one of them off a second entity; the
closeout waterfall consumes each step's output in a fixed order. Every test here
pins the exact cent figures that order produces.
"""

from test_helpers import (
    CONSERVATOR,
    FABRICATION,
    PM,
    ComplexityTier,
    FinishGrade,
    MaterialClass,
    MountStatus,
    PackageStage,
    Phase,
    PrototypeDecision,
    SecurityTier,
    UsedIn,
    assert_ledger,
    assert_money_identity,
    factories as f,
    fixtures as fx,
    is_iso8601_timestamp,
    validate_success,
)
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


def _cleared_material(api, project_id, name, used_in, voc, formaldehyde, cure_days):
    material = fx.create_material(
        api,
        project_id,
        material_name=name,
        used_in=used_in,
        voc_mg_per_m2_day=voc,
        formaldehyde_ppm=formaldehyde,
        cure_days=cure_days,
    )
    fx.approve_material(api, material["id"])
    return material["id"]


def _fabrication_world(api):
    """A commission in FABRICATION with a cleared prototype and two cleared materials.

    One material is INTERACTIVE_HOUSING stock at 47500 cents the square metre and
    one is GRAPHIC stock at 12500, so a sheet can be re-priced by changing nothing
    but the material it references.
    """
    ctx = fx.project_in_phase(api, Phase.FABRICATION)
    _cleared_prototype(api, ctx["interactive_id"])
    ctx["housing_material_id"] = _cleared_material(
        api,
        ctx["project_id"],
        "Powder-coated aluminium housing",
        UsedIn.INTERACTIVE_HOUSING,
        0.12,
        0.02,
        14,
    )
    ctx["graphic_material_id"] = _cleared_material(
        api,
        ctx["project_id"],
        "Direct-print interpretive graphic",
        UsedIn.GRAPHIC,
        0.30,
        0.05,
        10,
    )
    return ctx


def _issue_sheet(api, ctx, drawing_number, material_id, complexity_tier, finish_grade):
    """Issue one sheet of 12.5 shop hours over 3.7 square metres."""
    return fx.create_drawing(
        api,
        ctx["project_id"],
        material_id,
        drawing_number=drawing_number,
        complexity_tier=complexity_tier,
        shop_hours=12.5,
        material_area_m2=3.7,
        finish_grade=finish_grade,
        subject_interactive_id=ctx["interactive_id"],
    )


def _project_at_closeout(api):
    """Drive a commission to CLOSEOUT carrying 4837500 cents of committed fabrication.

    Sheet SD-201 details the interactive on INTERACTIVE_HOUSING stock at
    CONSERVATION_GRADE for 100 hours over 60 square metres, settling at 4700000
    cents; sheet SD-202 details the case on CASE_INTERIOR stock at STANDARD for 10
    hours over 1 square metre, settling at 137500. The single commissioned station
    carries three years of parts availability.
    """
    fx.set_clock(api)
    project = fx.create_project(api, contract_value_cents=CONTRACT_VALUE_CENTS)
    project_id = project["id"]
    fx.advance(api, project_id, Phase.SCHEMATIC)
    fx.approve_package(api, project_id, PackageStage.SCHEMATIC)
    fx.advance(api, project_id, Phase.DESIGN_DEV)
    zone = fx.create_zone(api, project_id, closure_allowed=True)
    artifact = fx.create_artifact(
        api,
        project_id,
        material_class=MaterialClass.PAPER,
        security_class=SecurityTier.ENHANCED,
    )
    case = fx.create_case(
        api,
        project_id,
        zone["id"],
        rh_tolerance_pct=2.0,
        uv_microwatt_per_lumen=20.0,
    )
    interactive = fx.create_interactive(
        api,
        project_id,
        expected_daily_uses=150,
        mtbf_cycles=1200000,
        parts_availability_years=3,
        warranty_months=36,
    )
    fx.place_artifact(api, case["id"], artifact["id"])
    fx.approve_case(api, case["id"])
    fx.approve_package(api, project_id, PackageStage.DESIGN_DEV)
    fx.advance(api, project_id, Phase.FABRICATION)
    housing_id = _cleared_material(
        api,
        project_id,
        "Powder-coated aluminium housing",
        UsedIn.INTERACTIVE_HOUSING,
        0.12,
        0.02,
        14,
    )
    interior_id = _cleared_material(
        api,
        project_id,
        "Buffered museum board",
        UsedIn.CASE_INTERIOR,
        0.04,
        0.015,
        25,
    )
    _cleared_prototype(api, interactive["id"])
    sheet_a = fx.create_drawing(
        api,
        project_id,
        housing_id,
        drawing_number="SD-201",
        complexity_tier=ComplexityTier.CONSERVATION_GRADE,
        shop_hours=100.0,
        material_area_m2=60.0,
        finish_grade=FinishGrade.MILL,
        subject_interactive_id=interactive["id"],
    )
    decided_a = fx.approve_drawing(
        api, sheet_a["id"], actual_shop_hours=100.0, actual_waste_factor=1.0
    )
    sheet_b = fx.create_drawing(
        api,
        project_id,
        interior_id,
        drawing_number="SD-202",
        complexity_tier=ComplexityTier.STANDARD,
        shop_hours=10.0,
        material_area_m2=1.0,
        finish_grade=FinishGrade.MILL,
        subject_case_id=case["id"],
    )
    decided_b = fx.approve_drawing(
        api, sheet_b["id"], actual_shop_hours=10.0, actual_waste_factor=1.0
    )
    fx.advance_mount(api, case["id"], MountStatus.MOUNT_DESIGN)
    fx.advance_mount(api, case["id"], MountStatus.MOUNT_FABRICATED)
    validate_success(api.mark_fabricated(interactive["id"], FABRICATION))
    fx.advance(api, project_id, Phase.INSTALLATION)
    window = fx.create_window(
        api,
        project_id,
        zone["id"],
        starts_at=LATE_CLOCK,
        ends_at="2026-09-10T10:00:00Z",
    )
    fx.decide_window(api, window["id"])
    fx.set_clock(api, LATE_CLOCK)
    fx.start_window(api, window["id"])
    fx.advance_mount(api, case["id"], MountStatus.MOUNT_INSTALLED)
    fx.complete_window(api, window["id"])
    fx.advance(api, project_id, Phase.COMMISSIONING)
    validate_success(
        api.commission_interactive(interactive["id"], f.commission_payload(), PM)
    )
    fx.advance(api, project_id, Phase.CLOSEOUT)
    return {
        "project_id": project_id,
        "sheet_a_actual": decided_a["actual_cost_cents"],
        "sheet_b_actual": decided_b["actual_cost_cents"],
    }


def test_the_labour_line_is_rounded_before_it_joins_the_sheet_total(api):
    """A sheet of 12.5 precision hours rounds its half-cent labour line up first.

    12.5 hours at 14500 cents the hour with the 1.15 schematic contingency is
    exactly 208437.5 cents, so the labour line alone decides whether the sheet
    total ends in a nine or a zero. Rounded first it is 208438; with material at
    3.7 * 47500 * 1.20 = 210900 and finishing at 13.5 percent of that
    already-rounded material line (28471.5 -> 28472) the sheet totals 447810.

    "The cost model has three line items, and **each is rounded to whole cents before the three are summed**."

    Design: Difficulty/combinatorial_formula/per_line_item_rounding_order_changes_the_drawing_total
    """
    ctx = _fabrication_world(api)

    sheet = _issue_sheet(
        api,
        ctx,
        "SD-101",
        ctx["housing_material_id"],
        ComplexityTier.PRECISION,
        FinishGrade.MUSEUM_GLOSS,
    )

    assert sheet["estimate_labor_cents"] == 208438
    assert sheet["estimate_material_cents"] == 210900
    assert sheet["estimate_finishing_cents"] == 28472
    assert sheet["estimate_total_cents"] == 447810


def test_the_finishing_line_is_rounded_before_it_joins_the_sheet_total(api):
    """The same sheet's half-cent finishing line rounds up on its own too.

    13.5 percent of the 210900-cent material line is exactly 28471.5 cents.
    Rounding it before the sum gives 28472 and a sheet total of 447810, which is
    the plain addition of the three rounded lines; adding the three unrounded
    figures (208437.5 + 210900 + 28471.5 = 447809.0) and rounding once at the
    end would report 447809, one cent short.

    "Summing the three unrounded figures and rounding once at the end is a different and incorrect answer, and each line item participates in the rounding independently."

    Design: Difficulty/combinatorial_formula/per_line_item_rounding_order_changes_the_drawing_total
    """
    ctx = _fabrication_world(api)

    sheet = _issue_sheet(
        api,
        ctx,
        "SD-101",
        ctx["housing_material_id"],
        ComplexityTier.PRECISION,
        FinishGrade.MUSEUM_GLOSS,
    )

    assert sheet["estimate_finishing_cents"] == 28472
    assert sheet["estimate_total_cents"] == (
        sheet["estimate_labor_cents"]
        + sheet["estimate_material_cents"]
        + sheet["estimate_finishing_cents"]
    )
    assert sheet["estimate_total_cents"] == 447810
    assert sheet["estimate_total_cents"] != 447809


def test_only_the_complexity_tier_moves_and_only_the_labour_line_follows(api):
    """Re-tiering the same sheet from PRECISION to CONSERVATION_GRADE moves labour alone.

    Hours, area, material and finish grade are all held fixed, so the only
    difference between the two sheets is the shop rate the tier selects: 14500
    cents the hour gives labour 208438 and a total of 447810, while 18500 cents
    the hour gives 12.5 * 18500 * 1.15 = 265937.5 -> 265938 and a total of
    505310. The gap is exactly 57500 cents and neither the material line nor the
    finishing line budges.

    "Labour is the hours multiplied by the shop rate for the sheet's complexity tier multiplied by a labour multiplier: the shop charges 95 dollars per hour at `STANDARD`, 145 dollars per hour at `PRECISION` and 185 dollars per hour at `CONSERVATION_GRADE`, recorded as 9,500, 14,500 and 18,500 cents per hour respectively."

    Design: Difficulty/combinatorial_formula/three_enum_cross_product_selects_three_independent_constant_maps
    """
    ctx = _fabrication_world(api)

    baseline = _issue_sheet(
        api,
        ctx,
        "SD-A",
        ctx["housing_material_id"],
        ComplexityTier.PRECISION,
        FinishGrade.MUSEUM_GLOSS,
    )
    re_tiered = _issue_sheet(
        api,
        ctx,
        "SD-B",
        ctx["housing_material_id"],
        ComplexityTier.CONSERVATION_GRADE,
        FinishGrade.MUSEUM_GLOSS,
    )

    assert baseline["estimate_total_cents"] == 447810
    assert re_tiered["estimate_labor_cents"] == 265938
    assert re_tiered["estimate_material_cents"] == 210900
    assert re_tiered["estimate_finishing_cents"] == 28472
    assert re_tiered["estimate_total_cents"] == 505310
    assert re_tiered["estimate_total_cents"] - baseline["estimate_total_cents"] == 57500


def test_only_the_finish_grade_moves_and_only_the_finishing_line_follows(api):
    """Dropping the same sheet from MUSEUM_GLOSS to SATIN moves finishing alone.

    Finishing is a percentage of the already-rounded material line, so with
    material fixed at 210900 the glossed sheet takes 13.5 percent (28471.5 ->
    28472) for a total of 447810 and the satin sheet takes 7.5 percent (15817.5
    -> 15818) for a total of 435156. Labour stays at 208438 in both and the gap
    is exactly 12654 cents.

    "Finishing is a percentage of the **already-rounded** material line item — 0 percent for `MILL`, 7.5 percent for `SATIN` and 13.5 percent for `MUSEUM_GLOSS` — and it too is rounded to whole cents."

    Design: Difficulty/combinatorial_formula/three_enum_cross_product_selects_three_independent_constant_maps
    """
    ctx = _fabrication_world(api)

    baseline = _issue_sheet(
        api,
        ctx,
        "SD-A",
        ctx["housing_material_id"],
        ComplexityTier.PRECISION,
        FinishGrade.MUSEUM_GLOSS,
    )
    satin = _issue_sheet(
        api,
        ctx,
        "SD-C",
        ctx["housing_material_id"],
        ComplexityTier.PRECISION,
        FinishGrade.SATIN,
    )

    assert baseline["estimate_total_cents"] == 447810
    assert satin["estimate_labor_cents"] == 208438
    assert satin["estimate_material_cents"] == 210900
    assert satin["estimate_finishing_cents"] == 15818
    assert satin["estimate_total_cents"] == 435156
    assert baseline["estimate_total_cents"] - satin["estimate_total_cents"] == 12654


def test_only_the_referenced_material_moves_and_the_material_line_follows_its_assembly(api):
    """Pointing the same sheet at GRAPHIC stock re-prices material off the other row.

    The material rate is read from the referenced material's own `used_in`, not
    from anything on the sheet: at 47500 cents the square metre the housing sheet
    prices material at 3.7 * 47500 * 1.20 = 210900 and totals 447810, while the
    graphic sheet at 12500 prices material at 55500 and, with finishing at 13.5
    percent of that (7492.5 -> 7493), totals 271431. Labour is 208438 on both
    sheets and the gap is exactly 176379 cents.

    "Material is the `material_area_m2` multiplied by the rate for the **material's** `used_in` assembly multiplied by a waste factor, where the rates per square metre are 42,500 cents for `CASE_INTERIOR`, 31,000 for `CASE_EXTERIOR`, 58,000 for `MOUNT`, 12,500 for `GRAPHIC` and 47,500 for `INTERACTIVE_HOUSING`."

    Design: Difficulty/combinatorial_formula/three_enum_cross_product_selects_three_independent_constant_maps
    """
    ctx = _fabrication_world(api)

    baseline = _issue_sheet(
        api,
        ctx,
        "SD-A",
        ctx["housing_material_id"],
        ComplexityTier.PRECISION,
        FinishGrade.MUSEUM_GLOSS,
    )
    on_graphic_stock = _issue_sheet(
        api,
        ctx,
        "SD-D",
        ctx["graphic_material_id"],
        ComplexityTier.PRECISION,
        FinishGrade.MUSEUM_GLOSS,
    )

    assert baseline["estimate_total_cents"] == 447810
    assert on_graphic_stock["estimate_labor_cents"] == 208438
    assert on_graphic_stock["estimate_material_cents"] == 55500
    assert on_graphic_stock["estimate_finishing_cents"] == 7493
    assert on_graphic_stock["estimate_total_cents"] == 271431
    assert (
        baseline["estimate_total_cents"] - on_graphic_stock["estimate_total_cents"]
        == 176379
    )


def test_the_retainage_tier_is_chosen_from_the_total_the_parts_premium_already_lifted(api):
    """A fabrication total below the 5,000,000-cent breakpoint is lifted over it first.

    The two cleared sheets commit 4700000 + 137500 = 4837500 cents, which sits
    below 5,000,000. The weakest commissioned station carries three years of
    parts availability, so the premium band is 4.5 percent and the premium is
    round half up of 217687.5 = 217688; that puts the pre-retainage total at
    5055188, at or above 5,000,000, so the retainage rate is 7.5 percent and the
    hold-back is 379139 cents — not the 505519 a rate picked from the fabrication
    total alone would withhold.

    "Step two prices the parts commitment as a percentage of that fabrication total, and the percentage is chosen from the project's `COMMISSIONED` interactives: if the project has none, the percentage is zero; otherwise take the **smallest** `parts_availability_years` among them — the weakest station governs the whole commission — and select the first band it satisfies, reading the bands in descending order of their threshold, where at least 15 years gives 0.5 percent, at least 10 years gives 1.2 percent, at least 5 years gives 2.8 percent and anything from 0 years up gives 4.5 percent."

    "Step three adds steps one and two into a pre-retainage total."

    "Step four picks the retainage percentage from that pre-retainage total on the same first-band-satisfied basis: a total of at least 20,000,000 cents retains 5 percent, at least 5,000,000 cents retains 7.5 percent, and anything from zero up retains 10 percent, so a larger job is trusted with a thinner hold-back and a total sitting exactly on a boundary takes the lower rate."

    Design: Difficulty/combinatorial_formula/closeout_waterfall_step_order_crosses_a_retainage_tier_boundary
    """
    world = _project_at_closeout(api)
    project_id = world["project_id"]
    assert world["sheet_a_actual"] == 4700000
    assert world["sheet_b_actual"] == 137500
    assert_ledger(
        fx.read_project(api, project_id), 4837500, CONTRACT_VALUE_CENTS - 4837500
    )

    settled = validate_success(api.closeout(project_id, f.closeout_payload(), PM))

    assert settled["retainage_held_cents"] == 379139
    assert settled["retainage_held_cents"] != 505519


def test_the_warranty_reserve_and_the_release_come_off_the_net_of_the_retainage(api):
    """The reserve is two percent of what is left after the hold-back, not of the gross.

    On a pre-retainage total of 5055188 with 379139 withheld, two percent of the
    4676049-cent remainder is 93520.98, rounded half up to 93521 — two percent of
    the gross would have reserved 101104. The release is then the plain integer
    subtraction 5055188 - 379139 - 93521 = 4582528, so the three settlement
    figures add straight back to the pre-retainage total.

    "Step six is the warranty reserve: two percent of the pre-retainage total **less the retainage already withheld**, rounded half up to whole cents — the reserve is deliberately computed on the net figure, not on the gross, so the retainage band choice also moves the reserve."

    "Step seven is the release: the pre-retainage total less the retainage less the warranty reserve, by exact integer subtraction with no rounding of its own, which is what guarantees the three settlement figures reconstruct the pre-retainage total to the cent."

    Design: Difficulty/combinatorial_formula/closeout_waterfall_step_order_crosses_a_retainage_tier_boundary
    """
    world = _project_at_closeout(api)
    project_id = world["project_id"]

    settled = validate_success(api.closeout(project_id, f.closeout_payload(), PM))

    assert settled["warranty_reserve_cents"] == 93521
    assert settled["warranty_reserve_cents"] != 101104
    assert settled["released_cents"] == 4582528
    assert (
        settled["retainage_held_cents"]
        + settled["warranty_reserve_cents"]
        + settled["released_cents"]
        == 5055188
    )


def test_settlement_zeroes_the_committed_bucket_and_stamps_the_warranty_registration(api):
    """The three settlement figures replace the commitment and close the commission.

    With 379139 withheld, 93521 reserved and 4582528 released, the committed
    bucket falls to 0 and the uncommitted bucket becomes 9000000 - 5055188 =
    3944812, so the five buckets still add to the contract value. The handover
    fields land, `warranty_registered_at` is stamped from the logical clock the
    install work moved to 2026-09-10T08:00:00Z, and the phase leaves CLOSEOUT for
    the terminal WARRANTY_CLOSED.

    "The `committed_fabrication_cents` bucket is zeroed, and `uncommitted_cents` is recomputed as the `contract_value_cents` less the sum of the three settlement figures, so the five-bucket ledger still reconciles exactly after settlement."

    "The handover fields `docent_kit_url`, `maintenance_manual_url` and `parts_commitment_years` are stored, `warranty_registered_at` is stamped with the current logical clock instant, and every punch item standing at `VERIFIED` or `WAIVED` is transitioned to `CLOSED` — items still `OPEN` are left alone, which is why a project carrying a blocking defect cannot have reached this phase in the first place."

    "Finally the phase advances from `CLOSEOUT` to `WARRANTY_CLOSED` and the project's `version` is incremented by one."

    Design: Difficulty/combinatorial_formula/closeout_waterfall_step_order_crosses_a_retainage_tier_boundary
    """
    world = _project_at_closeout(api)
    project_id = world["project_id"]

    settled = validate_success(api.closeout(project_id, f.closeout_payload(), PM))

    assert settled["committed_fabrication_cents"] == 0
    assert settled["uncommitted_cents"] == 3944812
    assert settled["contract_value_cents"] == CONTRACT_VALUE_CENTS
    assert_money_identity(settled)
    assert settled["phase"] == Phase.WARRANTY_CLOSED
    assert settled["parts_commitment_years"] == 10
    assert is_iso8601_timestamp(settled["warranty_registered_at"])
    assert settled["warranty_registered_at"].startswith("2026-09-10T08:00:00")
