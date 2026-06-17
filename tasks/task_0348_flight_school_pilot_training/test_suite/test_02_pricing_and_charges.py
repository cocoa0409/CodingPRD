"""Pricing claims: the booking cost estimate (tiered complexity surcharge,
server-computed) and the flight charge (HOBBS vs TACH dual variant, pinned
round-hours-then-cents order, SOLO excludes the instructor portion).

All expected cent values are copied verbatim from the design indices; they are
re-derivable from the PRD §3.7 formulas (rates, hours, tiers) and §2.8 rounding.
"""
from test_helpers import (
    get_success_data,
    setup_active_enrollment, create_aircraft, create_booking,
    setup_drafted_flight_log,
    make_instructor_headers,
)


# ──────────────────────────────────────────────────────────────────────────
# booking cost estimate — combinatorial / tiered surcharge
# ──────────────────────────────────────────────────────────────────────────
def test_booking_estimate_complex_tier1_surcharge_at_2h(api):
    """PRD §3.7: "if it is true and the planned hours are at most the complex
    tier-one threshold of 2.0 hours the surcharge percentage is 10 percent..."
    PRD §3.7: "The booking's `estimated_cost_cents` is then the aircraft portion
    plus the surcharge plus the instructor portion — each product rounded to cents
    before this final sum."

    Design: Difficulty/combinatorial_formula/booking_cost_estimate_tiered_surcharge_branches
    """
    base = setup_active_enrollment(deposit_cents=200000, instructor_overrides={"cfi_rate_cents_per_hour": 7000})
    aircraft = create_aircraft(rental_rate_cents_per_hour=18000, is_complex=True, initial_hobbs=50.0, initial_tach=40.0)
    booking = create_booking(
        base["enrollment"]["id"], aircraft["id"], "DUAL", 2.0,
        instructor_id=base["instructor"]["id"],
    )
    # 18000*2.0=36000 aircraft; surcharge 10% -> 3600; instructor 7000*2.0=14000; sum 53600.
    assert booking["estimated_cost_cents"] == 53600


def test_booking_estimate_complex_tier2_surcharge_above_2h(api):
    """PRD §3.7: "if it is true and the planned hours exceed 2.0 hours the surcharge
    percentage is 15 percent. The surcharge in cents is the aircraft portion
    multiplied by that percentage, rounded half up to whole cents."
    PRD §3.7: "The booking's `estimated_cost_cents` is then the aircraft portion
    plus the surcharge plus the instructor portion — each product rounded to cents
    before this final sum."

    Design: Difficulty/combinatorial_formula/booking_cost_estimate_tiered_surcharge_branches
    """
    base = setup_active_enrollment(deposit_cents=200000, instructor_overrides={"cfi_rate_cents_per_hour": 7000})
    aircraft = create_aircraft(rental_rate_cents_per_hour=18000, is_complex=True, initial_hobbs=50.0, initial_tach=40.0)
    booking = create_booking(
        base["enrollment"]["id"], aircraft["id"], "DUAL", 2.5,
        window=("2026-07-02T14:00:00.000Z", "2026-07-02T17:00:00.000Z"),
        instructor_id=base["instructor"]["id"],
    )
    # 18000*2.5=45000 aircraft; surcharge 15% -> 6750; instructor 7000*2.5=17500; sum 69250.
    assert booking["estimated_cost_cents"] == 69250


def test_booking_estimate_is_server_computed_not_client_supplied(api):
    """PRD §3.3: "computes its `estimated_cost_cents` via the booking cost estimate
    (see §3.7), and increments the aircraft's `version` by one to record that this
    create has claimed a slice of the aircraft's schedule. The new booking's
    `estimated_cost_cents` is computed once at creation and never recomputed
    afterward."

    Design: Corner/entities/computed_estimated_cost_input_ignored
    """
    base = setup_active_enrollment(deposit_cents=100000)
    aircraft = create_aircraft(rental_rate_cents_per_hour=15000)
    booking = create_booking(
        base["enrollment"]["id"], aircraft["id"], "DUAL", 2.0,
        instructor_id=base["instructor"]["id"],
    )
    # Noncomplex 15000*2.0=30000 aircraft; DUAL 6000*2.0=12000 instructor; sum 42000.
    assert booking["estimated_cost_cents"] == 42000


# ──────────────────────────────────────────────────────────────────────────
# flight charge — HOBBS vs TACH dual variant
# ──────────────────────────────────────────────────────────────────────────
def test_flight_charge_hobbs_basis_uses_hobbs_delta(api):
    """PRD §3.7: "When the basis is `HOBBS`, the raw meter delta is `hobbs_end`
    minus `hobbs_start` (the engine-running clock, which yields the larger delta)..."
    PRD §3.7: "The `total_charge_cents` is `aircraft_charge_cents` plus
    `instructor_charge_cents`."

    Design: Difficulty/dual_variant_calc/flight_charge_hobbs_vs_tach_diverge
    """
    base = setup_drafted_flight_log(
        deposit_cents=100000, lesson_type="DUAL",
        aircraft_overrides={"rental_rate_cents_per_hour": 15000, "billing_basis": "HOBBS"},
        hobbs_start=100.0, hobbs_end=101.7, tach_start=200.0, tach_end=201.4,
    )
    instr_id = base["instructor"]["id"]
    posted = get_success_data(api.post_flight_log(base["flight_log"]["id"], make_instructor_headers(instr_id)))
    # HOBBS delta 1.7; aircraft 15000*1.7=25500; instructor 6000*1.7=10200; total 35700.
    assert posted["billed_hours"] == 1.7
    assert posted["total_charge_cents"] == 35700


def test_flight_charge_tach_basis_uses_tach_delta(api):
    """PRD §3.7: "when the basis is `TACH`, the raw delta is `tach_end` minus
    `tach_start` (the rpm-scaled clock, which yields a smaller delta and so a
    different charge for the identical flight)."
    PRD §3.7: "The `aircraft_charge_cents` is the aircraft's
    `rental_rate_cents_per_hour` multiplied by `billed_hours`, with that product
    rounded half up to whole cents."

    Design: Difficulty/dual_variant_calc/flight_charge_hobbs_vs_tach_diverge
    """
    base = setup_drafted_flight_log(
        deposit_cents=100000, lesson_type="DUAL",
        aircraft_overrides={"rental_rate_cents_per_hour": 15000, "billing_basis": "TACH"},
        hobbs_start=100.0, hobbs_end=101.7, tach_start=200.0, tach_end=201.4,
    )
    instr_id = base["instructor"]["id"]
    posted = get_success_data(api.post_flight_log(base["flight_log"]["id"], make_instructor_headers(instr_id)))
    # TACH delta 1.4; aircraft 15000*1.4=21000; instructor 6000*1.4=8400; total 29400.
    assert posted["billed_hours"] == 1.4
    assert posted["total_charge_cents"] == 29400


# ──────────────────────────────────────────────────────────────────────────
# flight charge — pinned rounding order (round hours, then cents)
# ──────────────────────────────────────────────────────────────────────────
def test_flight_charge_rounds_hours_to_tenths_before_cents(api):
    """PRD §2.8: "For the flight charge, the meter delta is first rounded half up to
    one decimal place (tenths of an hour), then multiplied by the rate, then that
    product is rounded half up to whole cents; the raw product is never rounded
    directly at the cent level."

    Design: Difficulty/combinatorial_formula/flight_charge_round_hours_then_cents_order
    """
    # SOLO so the aircraft portion is isolated; raw HOBBS delta 1.25 -> tenths 1.3.
    base = setup_drafted_flight_log(
        deposit_cents=100000, lesson_type="SOLO", with_solo_endorsement=True,
        aircraft_overrides={"rental_rate_cents_per_hour": 15000, "billing_basis": "HOBBS",
                            "initial_hobbs": 300.0, "initial_tach": 250.0},
        hobbs_start=300.0, hobbs_end=301.25, tach_start=250.0, tach_end=251.0, landings=2,
    )
    instr_id = base["instructor"]["id"]
    posted = get_success_data(api.post_flight_log(base["flight_log"]["id"], make_instructor_headers(instr_id)))
    # delta 1.25 -> 1.3; 15000*1.3=19500 (not 18750 from rounding the raw product).
    assert posted["billed_hours"] == 1.3
    assert posted["aircraft_charge_cents"] == 19500
    assert posted["instructor_charge_cents"] == 0
    assert posted["total_charge_cents"] == 19500


def test_flight_charge_dual_rounds_hours_then_multiplies_both_portions(api):
    """PRD §2.8: "For the flight charge, the meter delta is first rounded half up to
    one decimal place (tenths of an hour), then multiplied by the rate, then that
    product is rounded half up to whole cents; the raw product is never rounded
    directly at the cent level."
    PRD §3.7: "The `billed_hours` is that raw delta rounded half up to one decimal
    place — the tenths rounding happens first, before any multiplication."

    Design: Difficulty/combinatorial_formula/flight_charge_round_hours_then_cents_order
    """
    # Raw HOBBS delta 1.25 -> tenths 1.3, applied to BOTH aircraft and instructor.
    base = setup_drafted_flight_log(
        deposit_cents=100000, lesson_type="DUAL",
        aircraft_overrides={"rental_rate_cents_per_hour": 15000, "billing_basis": "HOBBS",
                            "initial_hobbs": 300.0, "initial_tach": 250.0},
        hobbs_start=300.0, hobbs_end=301.25, tach_start=250.0, tach_end=251.0, landings=2,
    )
    instr_id = base["instructor"]["id"]
    posted = get_success_data(api.post_flight_log(base["flight_log"]["id"], make_instructor_headers(instr_id)))
    # delta 1.25 -> 1.3; aircraft 15000*1.3=19500; instructor 6000*1.3=7800; total 27300.
    assert posted["billed_hours"] == 1.3
    assert posted["aircraft_charge_cents"] == 19500
    assert posted["instructor_charge_cents"] == 7800
    assert posted["total_charge_cents"] == 27300


def test_solo_flight_charge_excludes_instructor_portion(api):
    """PRD §3.7: "for a `SOLO` booking it is zero. The `total_charge_cents` is
    `aircraft_charge_cents` plus `instructor_charge_cents`."

    Design: Corner/calculations/solo_flight_charge_excludes_instructor
    """
    base = setup_drafted_flight_log(
        deposit_cents=100000, lesson_type="SOLO", with_solo_endorsement=True,
        aircraft_overrides={"rental_rate_cents_per_hour": 15000, "billing_basis": "TACH"},
        hobbs_start=100.0, hobbs_end=101.3, tach_start=200.0, tach_end=201.0, landings=1,
    )
    instr_id = base["instructor"]["id"]
    posted = get_success_data(api.post_flight_log(base["flight_log"]["id"], make_instructor_headers(instr_id)))
    # TACH delta 1.0; aircraft 15000*1.0=15000; instructor 0; total 15000.
    assert posted["billed_hours"] == 1.0
    assert posted["aircraft_charge_cents"] == 15000
    assert posted["instructor_charge_cents"] == 0
    assert posted["total_charge_cents"] == 15000
