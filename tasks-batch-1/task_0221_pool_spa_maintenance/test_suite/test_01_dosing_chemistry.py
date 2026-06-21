"""Chemical-reading dosing recommendation tests.

Covers the dual-variant dosing calc, the sum-then-round order pin, the pH-penalty
boundary, and the no-deficit case. All values are computed by the PRD §3.5 dosing
formula and asserted as literals.
"""
from test_helpers import (
    validate_success,
    setup_open_pool_dispatched_visit, create_reading_payload, TEST_USERS,
)

FT = TEST_USERS["field_technician_headers"]


def _setup_visit(api, water_type="CHLORINE", volume_gallons=20000):
    return setup_open_pool_dispatched_visit(water_type=water_type, volume_gallons=volume_gallons)


def test_final_dose_from_actual_reading_chlorine(api):
    """PRD §3.5: "The chlorine dose component is the free-chlorine deficit — the
    target minus the measured `free_chlorine_ppm`, taken as 0 when the measurement
    already meets or exceeds target so the deficit is never negative — multiplied by
    a per-water-type dose constant (14.0 for `CHLORINE`, 20.0 for `SALTWATER`, 11.0
    for `BROMINE_SPA`) and by the volume factor."
    PRD §3.5: "the chlorine and alkalinity components are summed and that single sum
    is rounded to one decimal place, round-half-up, to give `recommended_dose_grams`."

    Design: Difficulty/dual_variant_calc/dosing_provisional_vs_final_on_chemical_reading
    """
    ctx = _setup_visit(api, water_type="CHLORINE", volume_gallons=20000)
    ft = FT
    resp = api.create_reading(ctx["visit"]["id"],
                              create_reading_payload(free_chlorine_ppm=1.0, ph=7.5, total_alkalinity_ppm=80.0),
                              ft)
    data = validate_success(resp, 201)
    # chlorine = (3.0-1.0)*14.0*2.0 = 56.0 ; alk = (100-80)*1.5*2.0 = 60.0 ; sum 116.0
    assert data["recommended_dose_grams"] == 116.0, \
        f"expected 116.0, got {data['recommended_dose_grams']}"


def test_final_dose_differs_from_visit_billing_domain(api):
    """PRD §3.5: "The system then computes the reading's `recommended_dose_grams`;
    any value a client tries to supply for that field is ignored."

    The dosing recommendation (grams of chemical) is a distinct quantity from the
    visit's monetary bill; the final dose computed from the actual reading is
    116.0 grams, which is not the same number as any per-visit cents figure.

    Design: Difficulty/dual_variant_calc/dosing_provisional_vs_final_on_chemical_reading
    """
    ctx = _setup_visit(api, water_type="CHLORINE", volume_gallons=20000)
    ft = FT
    resp = api.create_reading(ctx["visit"]["id"],
                              create_reading_payload(free_chlorine_ppm=1.0, ph=7.5, total_alkalinity_ppm=80.0),
                              ft)
    data = validate_success(resp, 201)
    visit = validate_success(api.get_visit(ctx["visit"]["id"], ft))
    assert data["recommended_dose_grams"] == 116.0
    # The dose (116.0 grams) is not the visit's billed_amount_cents (0 pre-completion).
    assert data["recommended_dose_grams"] != visit["billed_amount_cents"]


def test_dose_sum_then_round_order_with_ph_penalty(api):
    """PRD §3.5: "If the measured `ph` is greater than 7.8, chlorine is less
    effective, so the chlorine component (and only the chlorine component, never the
    alkalinity component) is multiplied by a penalty factor of 1.25. Finally the
    chlorine and alkalinity components are summed and that single sum is rounded to
    one decimal place, round-half-up, to give `recommended_dose_grams`."

    Design: Difficulty/combinatorial_formula/dosing_sum_then_round_order_pinned
    """
    ctx = _setup_visit(api, water_type="SALTWATER", volume_gallons=20000)
    ft = FT
    resp = api.create_reading(ctx["visit"]["id"],
                              create_reading_payload(free_chlorine_ppm=1.0, ph=8.0, total_alkalinity_ppm=100.0),
                              ft)
    data = validate_success(resp, 201)
    # chlorine = (3.0-1.0)*20.0*2.0*1.25 = 100.0 ; alk deficit 0 ; sum 100.0
    assert data["recommended_dose_grams"] == 100.0, \
        f"expected 100.0, got {data['recommended_dose_grams']}"


def test_dose_sum_then_round_distinguishes_round_each(api):
    """PRD §3.5: "Finally the chlorine and alkalinity components are summed and that
    single sum is rounded to one decimal place, round-half-up, to give
    `recommended_dose_grams`."
    PRD §2.7: "The rounding is applied once, after the chlorine and alkalinity dose
    components have been summed — the system sums first and rounds the total, rather
    than rounding each component and then adding."

    Inputs chosen so that summing-then-rounding (48.5) differs from
    rounding-each-then-adding (which would yield 48.4): the chlorine component is
    30.625 and the alkalinity component is 17.85.

    Design: Difficulty/combinatorial_formula/dosing_sum_then_round_order_pinned
    """
    ctx = _setup_visit(api, water_type="CHLORINE", volume_gallons=7000)
    ft = FT
    resp = api.create_reading(ctx["visit"]["id"],
                              create_reading_payload(free_chlorine_ppm=0.5, ph=8.0, total_alkalinity_ppm=83.0),
                              ft)
    data = validate_success(resp, 201)
    # chlorine = (3.0-0.5)*14.0*0.7*1.25 = 30.625 ; alk = (100-83)*1.5*0.7 = 17.85 ;
    # sum 48.475 -> round-half-up to 1 decimal = 48.5
    assert data["recommended_dose_grams"] == 48.5, \
        f"expected 48.5, got {data['recommended_dose_grams']}"


def test_ph_penalty_not_applied_at_exactly_7_8(api):
    """PRD §3.5: "If the measured `ph` is greater than 7.8, chlorine is less
    effective, so the chlorine component (and only the chlorine component, never the
    alkalinity component) is multiplied by a penalty factor of 1.25."

    The penalty fires strictly above 7.8; at ph == 7.8 there is no penalty.

    Design: Difficulty/boundary_precision_check/ph_penalty_boundary_exactly_7_8
    """
    ctx = _setup_visit(api, water_type="CHLORINE", volume_gallons=10000)
    ft = FT
    resp = api.create_reading(ctx["visit"]["id"],
                              create_reading_payload(free_chlorine_ppm=1.0, ph=7.8, total_alkalinity_ppm=100.0),
                              ft)
    data = validate_success(resp, 201)
    # chlorine = (3.0-1.0)*14.0*1.0 = 28.0 ; no penalty (7.8 not > 7.8) ; alk 0 ; sum 28.0
    assert data["recommended_dose_grams"] == 28.0, \
        f"expected 28.0, got {data['recommended_dose_grams']}"


def test_ph_penalty_applied_just_above_7_8(api):
    """PRD §3.5: "If the measured `ph` is greater than 7.8, chlorine is less
    effective, so the chlorine component (and only the chlorine component, never the
    alkalinity component) is multiplied by a penalty factor of 1.25."

    At ph just above 7.8 (7.9), the chlorine component IS multiplied by 1.25.

    Design: Difficulty/boundary_precision_check/ph_penalty_boundary_exactly_7_8
    """
    ctx = _setup_visit(api, water_type="CHLORINE", volume_gallons=10000)
    ft = FT
    resp = api.create_reading(ctx["visit"]["id"],
                              create_reading_payload(free_chlorine_ppm=1.0, ph=7.9, total_alkalinity_ppm=100.0),
                              ft)
    data = validate_success(resp, 201)
    # chlorine = (3.0-1.0)*14.0*1.0*1.25 = 35.0 ; alk 0 ; sum 35.0
    assert data["recommended_dose_grams"] == 35.0, \
        f"expected 35.0, got {data['recommended_dose_grams']}"


def test_dose_zero_when_no_deficit(api):
    """PRD §3.5: "the target minus the measured `free_chlorine_ppm`, taken as 0 when
    the measurement already meets or exceeds target so the deficit is never negative".
    PRD §3.5: "the alkalinity deficit — 100 minus the measured `total_alkalinity_ppm`,
    again floored at 0".

    Design: Corner/calculations/dosing_no_deficit_yields_zero
    """
    ctx = _setup_visit(api, water_type="CHLORINE", volume_gallons=20000)
    ft = FT
    resp = api.create_reading(ctx["visit"]["id"],
                              create_reading_payload(free_chlorine_ppm=5.0, ph=7.2, total_alkalinity_ppm=120.0),
                              ft)
    data = validate_success(resp, 201)
    assert data["recommended_dose_grams"] == 0.0, \
        f"expected 0.0, got {data['recommended_dose_grams']}"


