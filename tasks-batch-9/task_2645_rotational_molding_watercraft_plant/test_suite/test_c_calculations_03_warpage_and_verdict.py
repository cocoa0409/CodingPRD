"""Warpage index and the verdict ladder: rounded terms, two lookups, a clamp.

PRD.md section 3.6 builds one warpage figure out of four separately rounded terms,
a weighted sum that is itself rounded, two multiplicative lookup factors, and a
ceiling that is applied *before* the final rounding. The same section runs the
figure twice — a provisional score on the cycle at demould and a final score on
the hull at inspection — and then feeds only the final score into an eight-clause
verdict ladder whose comparison operators are deliberately mixed. Each test here
pins one link of that chain with values that no other rounding order reproduces.
"""

from test_helpers import (
    advance_unit_to_outfitted,
    advance_unit_to_sellable,
    assert_at_most_scale,
    create_plant_baseline,
    create_production_order,
    create_resin_lot,
    dec,
    get_success_data,
    inspect_payload,
    outfit_payload,
    reserve_charge,
    run_cycle_to_demold,
    schedule_cycle,
    trim_payload,
)

# Six readings whose mean is exactly 10.000, whose population standard deviation
# about that mean is 1.209 and whose coefficient of variation is therefore 12.09 —
# nine hundredths above the default model's wall_cv_max_pct of 12.00, which is the
# smallest step that makes the distribution term of PRD.md section 3.6 non-zero.
_P5_HIGH_CV_POINTS = [8.65, 11.35, 8.75, 11.25, 9.0, 11.0]

# The factory default readings: mean 6.000, sd 0.065, cv 1.08, minimum 5.90.
_P5_TIGHT_POINTS = [5.9, 6.0, 6.1, 5.95, 6.05, 6.0]


def _p5_exact(actual, expected, places, label):
    """Assert a derived decimal is stored at its declared scale and exact value."""
    assert_at_most_scale(actual, places, label)
    assert dec(actual) == dec(expected), f"{label}: expected {expected}, got {actual!r}"


def _p5_value_only(actual, expected, label):
    """Assert a derived decimal's value without pinning its printed scale.

    PRD.md section 3.6 rounds ``min_wall_thickness_mm`` to three decimals while the
    field catalogue of PRD.md section 2.8 lists it at two, so the scale of this one
    field is not uniquely derivable from the PRD and only the value is asserted.
    """
    assert dec(actual) == dec(expected), f"{label}: expected {expected}, got {actual!r}"


def _p5_warpage_plant(*, size_class, airflow_mode, nominal_charge_kg, hull_type="KAYAK"):
    """A plant whose size class and airflow mode drive the two warpage lookups.

    The mould is single-cavity at the model's own nominal charge, so PRD.md
    section 3.5 — where the tolerance test compares ``charged_mass_kg`` against
    "the model's `nominal_charge_kg` multiplied by the tool's `cavity_count`" —
    is cleared by one charge of exactly that mass.
    """
    return create_plant_baseline(
        model_overrides={
            "hull_type": hull_type,
            "size_class": size_class,
            "nominal_charge_kg": nominal_charge_kg,
        },
        mold_overrides={
            "size_class": size_class,
            "cavity_count": 1,
            "nominal_charge_kg": nominal_charge_kg,
        },
        bay_overrides={"airflow_mode": airflow_mode},
    )


def _p5_demold_cycle(ctx, cycle, *, oven_start, oven_end, cooling_end):
    """Drive one already-charged cycle from SCHEDULED to DEMOLDED on explicit stamps."""
    ctx["molding_cycle"] = cycle
    ctx["molding_cycle_id"] = cycle["id"]
    run_cycle_to_demold(
        ctx,
        actual_oven_start_at=oven_start,
        actual_oven_end_at=oven_end,
        actual_cooling_end_at=cooling_end,
    )
    return ctx["molding_cycle"]


def test_warpage_multiplies_the_size_class_and_cooling_mode_lookups(api, admin_headers):
    """A TANDEM hull on WATER_MIST stores 0.288 where MID on AMBIENT would store 0.200.

    PRD.md section 3.6 names both tables and the order they are applied in: "Two
    multiplicative lookups follow: a size factor from the model's `size_class`
    (`COMPACT` 0.850, `MID` 1.000, `TANDEM` 1.150, `OVERSIZE` 1.400) and a mode
    factor from the cycle's `cooling_mode` (`AMBIENT` 1.000, `FORCED_AIR` 0.900,
    `WATER_MIST` 1.250). The product of base, size factor and mode factor is clamped
    to the range 0.000 through 5.000 **before** rounding and the clamped value is
    then rounded once to three decimals".  The base itself comes from the same
    section: "Term 1, thermal shoot: the absolute difference between the cycle's
    `oven_temp_c` and the reference 288, divided by the span 40, rounded to three
    decimals", and "The base is then the weighted sum over the **already-rounded**
    terms — 0.40 times the thermal term plus 0.35 times the cooling term plus 0.25
    times the rotation term plus 0.50 times the distribution term — rounded to three
    decimals".  The two variants are separated there too: "The **provisional**
    variant runs at demould, writes `provisional_warpage_index` on the cycle, uses
    `scheduled_cooling_minutes` for term 2, and forces the distribution term to 0.000
    because no hull has been measured yet. The **final** variant runs at inspection,
    writes `final_warpage_index` on the hull, uses the cycle's
    `actual_cooling_minutes` for term 2, and takes a live distribution term from the
    inspected `wall_cv_pct`."

    Design: Corner/calculations/calc_constants_applied_warpage_size_class_and_cooling_mode_factors
    """
    ctx = _p5_warpage_plant(
        size_class="TANDEM",
        airflow_mode="WATER_MIST",
        nominal_charge_kg=30.0,
        hull_type="CANOE",
    )
    lot = create_resin_lot(received_kg=200.0)
    order = create_production_order(ctx, ordered_qty=1)
    cycle = schedule_cycle(
        ctx, order, oven_temp_c=308.0, cooling_mode="WATER_MIST"
    )
    reserve_charge(ctx, cycle, lot, charge_kg=30.0, regrind_kg=3.0)

    demolded = _p5_demold_cycle(
        ctx,
        cycle,
        oven_start="2026-08-01T09:00:00Z",
        oven_end="2026-08-01T10:00:00Z",
        cooling_end="2026-08-01T10:35:00Z",
    )
    assert demolded["status"] == "DEMOLDED", f"expected DEMOLDED, got {demolded['status']}"
    # Cooling is 35 minutes against min_cooling_minutes 30, so term 2 is 0.000 on
    # both variants; the rotation ratio 8.00 / 2.00 is exactly the ideal 4.000, so
    # term 3 is 0.000 too. Thermal is abs(308.0 - 288) / 40 = 0.500, base is
    # round(0.40 * 0.500, 3) = 0.200, and 0.200 * 1.150 * 1.250 = 0.287500 quantises
    # half-up to 0.288. Reading MID / AMBIENT instead would store 0.200.
    assert demolded["actual_cooling_minutes"] == 35, "floored cooling minutes"
    _p5_exact(demolded["provisional_warpage_index"], "0.288", 3, "provisional_warpage_index")

    unit = advance_unit_to_sellable(
        ctx,
        ctx["finished_units"][0],
        wall_thickness_points=list(_P5_TIGHT_POINTS),
        impact_test_joules=120.0,
        cosmetic_defect_grade="A",
    )

    _p5_exact(unit["mean_wall_thickness_mm"], "6.000", 3, "mean_wall_thickness_mm")
    _p5_exact(unit["wall_sd_mm"], "0.065", 3, "wall_sd_mm")
    _p5_exact(unit["wall_cv_pct"], "1.08", 2, "wall_cv_pct")
    _p5_value_only(unit["min_wall_thickness_mm"], "5.90", "min_wall_thickness_mm")
    # The final variant adds 0.50 * max(0, 1.08 - 12.00) / 10 = 0.000, so the same
    # two factors reproduce 0.288 on the hull.
    _p5_exact(unit["final_warpage_index"], "0.288", 3, "final_warpage_index")
    assert unit["inspection_verdict"] == "PASS", (
        f"0.288 is far below the 1.200 rework threshold, got {unit['inspection_verdict']}"
    )
    assert unit["build_status"] == "SELLABLE", f"expected SELLABLE, got {unit['build_status']}"

    stored_cycle = api.read_entity("get_molding_cycle", cycle["id"], admin_headers)
    _p5_exact(
        stored_cycle["provisional_warpage_index"], "0.288", 3, "stored provisional_warpage_index"
    )
    stored_unit = api.read_entity("get_finished_unit", unit["id"], admin_headers)
    _p5_exact(stored_unit["final_warpage_index"], "0.288", 3, "stored final_warpage_index")


def test_warpage_terms_are_rounded_then_weighted_then_clamped(api, admin_headers):
    """Three non-zero terms weight to 1.691, and a 5.0025 product clamps to 5.000.

    PRD.md section 3.6 rounds each term before the weighting: "Term 2, cooling
    deficit: the model's `min_cooling_minutes` minus the applicable cooling minutes,
    floored at zero, divided by `min_cooling_minutes`, rounded to three decimals.
    Term 3, rotation departure: the rotation ratio `arm_rpm_major` divided by
    `arm_rpm_minor` rounded to three decimals, then the absolute difference between
    that ratio and the ideal 4.000 divided by 4.000, rounded to three decimals. Term
    4, distribution penalty: `wall_cv_pct` minus the model's `wall_cv_max_pct`,
    floored at zero, divided by 10, rounded to three decimals."  It then fixes the
    order of the clamp against the rounding: "The product of base, size factor and
    mode factor is clamped to the range 0.000 through 5.000 **before** rounding and
    the clamped value is then rounded once to three decimals; rounding before clamping
    would let a value such as 5.0004 escape the ceiling."  The clause that fires on
    each hull is named in the same section: "(4) `final_warpage_index` strictly
    greater than 2.500 gives `SCRAP`" and "(5) `wall_cv_pct` strictly greater than the
    model's `wall_cv_max_pct` gives `REWORK`", with "a `REWORK` moves `OUTFITTED` to
    `REWORK` and increments `rework_count`".

    Design: Corner/calculations/calc_weighted_scoring_warpage_terms_rounded_then_weighted_then_clamped
    """
    ctx = _p5_warpage_plant(
        size_class="TANDEM",
        airflow_mode="WATER_MIST",
        nominal_charge_kg=30.0,
        hull_type="CANOE",
    )
    lot = create_resin_lot(received_kg=200.0)
    order = create_production_order(ctx, ordered_qty=2)

    # Cycle A schedules only ten cooling minutes, which PRD.md section 2.8 permits
    # ("`scheduled_cooling_minutes` (required integer, 1 to 600 inclusive)") and which
    # is the only way to make the provisional cooling term non-zero, because PRD.md
    # section 3.5 refuses a demould whose *actual* cooling falls short of the model's
    # minimum.
    first = schedule_cycle(
        ctx,
        order,
        scheduled_cooling_minutes=10,
        oven_temp_c=200.0,
        arm_rpm_major=6.0,
        arm_rpm_minor=2.0,
        cooling_mode="WATER_MIST",
    )
    reserve_charge(ctx, first, lot, charge_kg=30.0, regrind_kg=3.0)
    demolded_first = _p5_demold_cycle(
        ctx,
        first,
        oven_start="2026-08-01T09:00:00Z",
        oven_end="2026-08-01T10:00:00Z",
        cooling_end="2026-08-01T10:35:00Z",
    )
    # thermal round(88 / 40, 3) = 2.200, cooling round(max(0, 30 - 10) / 30, 3) = 0.667,
    # rotation round(abs(3.000 - 4.000) / 4.000, 3) = 0.250, so the base is
    # round(0.40 * 2.200 + 0.35 * 0.667 + 0.25 * 0.250, 3) = round(1.17595, 3) = 1.176
    # and 1.176 * 1.150 * 1.250 = 1.690500 rounds half-up to 1.691.
    _p5_exact(demolded_first["provisional_warpage_index"], "1.691", 3, "provisional A")
    assert demolded_first["actual_cooling_minutes"] == 35, "floored cooling minutes"

    hull_a = ctx["finished_units"][0]
    advance_unit_to_outfitted(ctx, hull_a, hardware_kit_serial="HK-CVD2-A")
    unit_a = get_success_data(
        api.inspect_finished_unit(
            hull_a["id"],
            inspect_payload(
                wall_thickness_points=list(_P5_HIGH_CV_POINTS),
                impact_test_joules=120.0,
                cosmetic_defect_grade="A",
            ),
            ctx["inspector_headers"],
        )
    )
    _p5_exact(unit_a["mean_wall_thickness_mm"], "10.000", 3, "mean A")
    _p5_exact(unit_a["wall_sd_mm"], "1.209", 3, "sd A")
    _p5_exact(unit_a["wall_cv_pct"], "12.09", 2, "cv A")
    # The final variant drops the cooling term (35 actual minutes clear the minimum)
    # and gains round((12.09 - 12.00) / 10, 3) = 0.009, so the base is
    # round(0.880 + 0.0625 + 0.0045, 3) = 0.947 and 0.947 * 1.4375 = 1.36131250
    # rounds to 1.361.
    _p5_exact(unit_a["final_warpage_index"], "1.361", 3, "final A")
    assert unit_a["inspection_verdict"] == "REWORK", (
        f"cv 12.09 exceeds 12.00 at clause 5, got {unit_a['inspection_verdict']}"
    )
    assert unit_a["build_status"] == "REWORK", f"expected REWORK, got {unit_a['build_status']}"
    assert unit_a["rework_count"] == 1, f"expected rework_count 1, got {unit_a['rework_count']}"

    second = schedule_cycle(
        ctx,
        order,
        oven_start_at="2026-08-01T11:00:00Z",
        oven_temp_c=200.0,
        arm_rpm_major=45.6,
        arm_rpm_minor=1.0,
        cooling_mode="WATER_MIST",
    )
    reserve_charge(ctx, second, lot, charge_kg=30.0, regrind_kg=3.0)
    demolded_second = _p5_demold_cycle(
        ctx,
        second,
        oven_start="2026-08-01T11:00:00Z",
        oven_end="2026-08-01T12:00:00Z",
        cooling_end="2026-08-01T12:35:00Z",
    )
    # rotation round(45.60 / 1.00, 3) = 45.600 gives round(41.600 / 4.000, 3) = 10.400,
    # so the base is round(0.880 + 2.600, 3) = 3.480 and the unrounded product
    # 3.480 * 1.150 * 1.250 = 5.00250000 is clamped to the 5.000 ceiling and only then
    # rounded; rounding first would report 5.003.
    _p5_exact(demolded_second["provisional_warpage_index"], "5.000", 3, "provisional B")

    hull_b = ctx["finished_units"][0]
    unit_b = advance_unit_to_sellable(
        ctx,
        hull_b,
        hardware_kit_serial="HK-CVD2-B",
        wall_thickness_points=list(_P5_TIGHT_POINTS),
        impact_test_joules=120.0,
        cosmetic_defect_grade="A",
    )
    _p5_exact(unit_b["wall_cv_pct"], "1.08", 2, "cv B")
    _p5_exact(unit_b["final_warpage_index"], "5.000", 3, "final B")
    assert unit_b["inspection_verdict"] == "SCRAP", (
        "5.000 exceeds the 2.500 scrap threshold at clause 4 even with perfect walls, "
        f"got {unit_b['inspection_verdict']}"
    )
    assert unit_b["build_status"] == "SCRAPPED", f"expected SCRAPPED, got {unit_b['build_status']}"

    stored_order = api.read_entity("get_production_order", order["id"], admin_headers)
    assert stored_order["status"] == "IN_PRODUCTION", (
        f"neither hull completes the order, got {stored_order['status']}"
    )
    assert stored_order["completed_qty"] == 0, "a REWORK hull counts as neither"
    assert stored_order["scrapped_qty"] == 1, "only the scrapped hull is counted"


def test_verdict_ladder_at_and_above_the_scrap_threshold(api, admin_headers):
    """The same hull reworks at exactly 2.500 and scraps at 2.505.

    PRD.md section 3.6 makes the operators of the ladder load-bearing: "(4)
    `final_warpage_index` strictly greater than 2.500 gives `SCRAP`; exactly 2.500
    does not scrap. (5) `wall_cv_pct` strictly greater than the model's
    `wall_cv_max_pct` gives `REWORK`; exactly equal passes. (6)
    `final_warpage_index` strictly greater than 1.200 gives `REWORK`."  It also fixes
    the two clauses this hull deliberately sits on: "(2) `impact_test_joules` strictly
    less than the model's `impact_test_min_joules` gives `SCRAP`; exactly equal
    passes" and "Grade `B` never reworks on its own; it matters only through the
    absence of clause 7."  The short circuit is stated outright — "the first matching
    clause wins; the remaining clauses are not evaluated" — and so is the budget
    override that does *not* apply here: "a `REWORK` verdict on a hull whose
    `rework_count` already equals 2 is converted to `SCRAP`".  The rework loop's own
    side effect is from the same section: "On the `REWORK` entry the previously
    recorded `hardware_kit_serial` is cleared to null, so outfitting must be redone
    from scratch."

    Design: Corner/calculations/calc_threshold_inspection_verdict_at_and_above_the_scrap_threshold
    """
    ctx = _p5_warpage_plant(
        size_class="MID", airflow_mode="AMBIENT", nominal_charge_kg=20.0
    )
    lot = create_resin_lot(received_kg=200.0)
    order = create_production_order(ctx, ordered_qty=1)
    cycle = schedule_cycle(
        ctx,
        order,
        oven_temp_c=200.0,
        arm_rpm_major=29.92,
        arm_rpm_minor=1.0,
        cooling_mode="AMBIENT",
    )
    reserve_charge(ctx, cycle, lot, charge_kg=20.0, regrind_kg=2.0)
    _p5_demold_cycle(
        ctx,
        cycle,
        oven_start="2026-08-01T09:00:00Z",
        oven_end="2026-08-01T10:00:00Z",
        cooling_end="2026-08-01T10:35:00Z",
    )

    hull = ctx["finished_units"][0]
    advance_unit_to_outfitted(ctx, hull, trim_waste_kg=0.3, hardware_kit_serial="HK-CVE-1")
    first_verdict = get_success_data(
        api.inspect_finished_unit(
            hull["id"],
            inspect_payload(
                wall_thickness_points=list(_P5_TIGHT_POINTS),
                impact_test_joules=90.0,
                cosmetic_defect_grade="B",
            ),
            ctx["inspector_headers"],
        )
    )
    # MID and AMBIENT both look up 1.000, so the index is its own base: thermal
    # round(88 / 40, 3) = 2.200, rotation round(abs(29.920 - 4.000) / 4.000, 3) = 6.480,
    # distribution 0.000 for cv 1.08, base round(0.880 + 1.620, 3) = 2.500.
    _p5_exact(first_verdict["final_warpage_index"], "2.500", 3, "final index at the boundary")
    _p5_exact(first_verdict["wall_cv_pct"], "1.08", 2, "cv on the first inspection")
    assert first_verdict["inspection_verdict"] == "REWORK", (
        "2.500 is not strictly greater than 2.500, so clause 4 does not fire and "
        f"clause 6 reworks, got {first_verdict['inspection_verdict']}"
    )
    assert first_verdict["build_status"] == "REWORK", (
        f"expected REWORK, got {first_verdict['build_status']}"
    )
    assert first_verdict["rework_count"] == 1, (
        f"expected rework_count 1, got {first_verdict['rework_count']}"
    )

    retrimmed = get_success_data(
        api.trim_finished_unit(hull["id"], trim_payload(0.15), ctx["assembly_headers"])
    )
    assert retrimmed["build_status"] == "TRIMMED", (
        f"a REWORK hull re-enters TRIMMED, got {retrimmed['build_status']}"
    )
    assert retrimmed["hardware_kit_serial"] is None, (
        "the rework loop clears the kit serial so outfitting is redone from scratch, "
        f"got {retrimmed['hardware_kit_serial']!r}"
    )
    get_success_data(
        api.outfit_finished_unit(
            hull["id"], outfit_payload("HK-CVE-2"), ctx["assembly_headers"]
        )
    )
    second_verdict = get_success_data(
        api.inspect_finished_unit(
            hull["id"],
            inspect_payload(
                wall_thickness_points=list(_P5_HIGH_CV_POINTS),
                impact_test_joules=90.0,
                cosmetic_defect_grade="B",
            ),
            ctx["inspector_headers"],
        )
    )
    _p5_exact(second_verdict["wall_cv_pct"], "12.09", 2, "cv on the second inspection")
    # The distribution term round((12.09 - 12.00) / 10, 3) = 0.009 adds 0.50 * 0.009 =
    # 0.0045, so the base is round(0.880 + 1.620 + 0.0045, 3) = round(2.5045, 3) = 2.505
    # by half-up — five thousandths past the ceiling of clause 4.
    _p5_exact(second_verdict["final_warpage_index"], "2.505", 3, "final index past the boundary")
    assert second_verdict["inspection_verdict"] == "SCRAP", (
        "clause 4 fires on 2.505 before clause 5 can look at the coefficient of "
        f"variation, got {second_verdict['inspection_verdict']}"
    )
    assert second_verdict["build_status"] == "SCRAPPED", (
        f"expected SCRAPPED, got {second_verdict['build_status']}"
    )
    assert second_verdict["rework_count"] == 1, (
        "the scrap comes from the ladder, not from the exhausted-budget override, so "
        f"rework_count stays 1, got {second_verdict['rework_count']}"
    )

    stored_order = api.read_entity("get_production_order", order["id"], admin_headers)
    assert stored_order["scrapped_qty"] == 1, "the scrapped hull is counted"
    assert stored_order["completed_qty"] == 0, "no hull completed"
    assert stored_order["status"] == "IN_PRODUCTION", (
        f"a scrap does not complete the order, got {stored_order['status']}"
    )
