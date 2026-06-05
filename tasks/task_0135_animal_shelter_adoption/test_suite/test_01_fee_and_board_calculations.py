"""Adoption-fee and board-cost calculations.

Covers the dual-variant and combinatorial-formula difficulty rules (queue A) plus
the projected-board computed read (queue B). Every monetary value is integer cents.
"""
from test_helpers import (
    api_client,
    validate_success,
    set_clock,
    bootstrap_shelter,
    register_animal,
    intake_animal,
    create_intaken_animal,
    create_available_animal,
    create_kennel,
    create_adopter,
    submit_application,
    approve_application,
    finalize_application,
    microchip_animal,
    clear_medical,
    make_animal_available,
    assign_kennel,
    TEST_USERS,
)

ADMIN = TEST_USERS["shelter_admin_headers"]
INTAKE = TEST_USERS["intake_officer_headers"]
COUNSELOR = TEST_USERS["adoption_counselor_headers"]


# ===================================================================
# Rule 1 — dual-variant calculation: adoption fee (estimated vs final)
# ===================================================================

def test_estimated_fee_adult_dog_no_microchip_is_17500(api):
    """PRD §3.7: "The base fee follows the band: 25000 cents for PUPPY_KITTEN,
    15000 cents for ADULT, and 5000 cents for SENIOR. A microchip surcharge of
    2500 cents is added when the animal's microchipped flag is false, and nothing
    is added when it is true; the gross amount is the base plus this surcharge."
    PRD §3.7: "The provisional computation at submission reads the animal's
    microchipped flag and the shelter's promo_active as they stand at submit time
    and stores the result in estimated_fee_cents."

    Design: Difficulty/dual_variant_calc/adoption_fee_estimated_vs_final_diverges_on_microchip
    """
    bootstrap_shelter(stray_hold_days=5, promo_active=False)
    animal = create_available_animal(species="DOG", age_months=36)  # ADULT, not chipped
    adopter = create_adopter(email="bob@x.com", full_name="Bob Adopter")
    app = submit_application(animal["id"], adopter["id"])
    assert app["estimated_fee_cents"] == 17500, (
        f"ADULT base 15000 + 2500 surcharge = 17500, got {app['estimated_fee_cents']}"
    )


def test_final_fee_diverges_from_estimated_when_microchipped_between(api):
    """PRD §3.7: "the final computation at finalization re-reads both inputs as they
    stand at finalize time and stores the result in final_fee_cents. If the animal
    was microchipped or the promotion was toggled in between, final_fee_cents will
    differ from estimated_fee_cents."
    PRD §3.7: "A microchip surcharge of 2500 cents is added when the animal's
    microchipped flag is false, and nothing is added when it is true."

    Design: Difficulty/dual_variant_calc/adoption_fee_estimated_vs_final_diverges_on_microchip
    """
    bootstrap_shelter(stray_hold_days=5, promo_active=False)
    animal = create_available_animal(species="DOG", age_months=36)  # ADULT, not chipped
    adopter = create_adopter(email="bob2@x.com", full_name="Bob Adopter")
    app = submit_application(animal["id"], adopter["id"])
    assert app["estimated_fee_cents"] == 17500

    # Microchip the animal AFTER submit, then approve and finalize.
    microchip_animal(animal["id"], chip_number="CHIP-1001")
    approve_application(app["id"])
    final = finalize_application(app["id"])

    assert final["final_fee_cents"] == 15000, (
        f"Chipped at finalize: ADULT base 15000, no surcharge = 15000, "
        f"got {final['final_fee_cents']}"
    )
    assert final["final_fee_cents"] != app["estimated_fee_cents"], (
        "final_fee_cents must diverge from estimated_fee_cents after microchipping"
    )


# ===================================================================
# Rule 1 — dual-variant calculation: board cost (projected vs actual)
# ===================================================================

def test_projected_board_dog_stray_full_hold_is_9945(api):
    """PRD §3.4: "The per-day charged amount is that base increased by a 7.5 percent
    care fee — that is, the base multiplied by 1.075 — and this per-day amount is
    rounded to the nearest whole cent, half-up, before anything else."
    PRD §3.4: "instead of the actual end_at it projects the occupied days from
    start_at forward to the animal's expected earliest release — its
    stray_hold_release_at. For a stray this assumes the full hold is served."

    Design: Difficulty/dual_variant_calc/board_cost_projected_vs_actual_diverges_on_early_release
    """
    bootstrap_shelter(stray_hold_days=5, dog_daily_board_cents=1850)
    kennel = create_kennel(capacity=1, label="A-1")
    animal = register_animal(name="Stray Rex", species="DOG", age_months=36)
    intake_animal(animal["id"], source="STRAY")
    ka = assign_kennel(kennel["id"], animal["id"], kennel["version"])

    proj = validate_success(api_client.get_projected_board(ka["id"], INTAKE))
    # round(1850 * 1.075) = round(1988.75) = 1989; 5-day hold -> 1989 * 5 = 9945
    assert proj["projected_board_cents"] == 9945, (
        f"5-day projection at 1989/day = 9945, got {proj['projected_board_cents']}"
    )


def test_actual_board_dog_released_after_two_days_is_3978_diverges_from_projection(api):
    """PRD §3.4: "Finally, actual_board_cents is that rounded per-day charged amount
    multiplied by the number of occupied days."
    PRD §3.4: "take the elapsed time from start_at to end_at, divide it by 24 hours,
    round that quotient up to the next whole number, and then take the larger of that
    figure and 1."

    Design: Difficulty/dual_variant_calc/board_cost_projected_vs_actual_diverges_on_early_release
    """
    bootstrap_shelter(stray_hold_days=5, dog_daily_board_cents=1850)
    kennel = create_kennel(capacity=1, label="A-1")
    animal = register_animal(name="Stray Rex", species="DOG", age_months=36)
    intake_animal(animal["id"], source="STRAY")
    ka = assign_kennel(kennel["id"], animal["id"], kennel["version"])

    proj = validate_success(api_client.get_projected_board(ka["id"], INTAKE))
    assert proj["projected_board_cents"] == 9945

    set_clock("2026-06-03T00:00:00Z")  # 2 days later
    released = validate_success(api_client.release_kennel_assignment(ka["id"], INTAKE))
    # 1989/day * 2 days = 3978
    assert released["actual_board_cents"] == 3978, (
        f"2-day actual at 1989/day = 3978, got {released['actual_board_cents']}"
    )
    assert released["actual_board_cents"] != 9945, (
        "actual must diverge from the full-hold projection after early release"
    )


# ===================================================================
# Rule 2 — combinatorial formula: nested-max promo discount
# ===================================================================

def test_promo_nested_max_pct_beats_flat_puppy_chipped_is_20000(api):
    """PRD §3.7: "If the shelter's promo_active is on, a discount applies: compute
    20 percent of the gross, rounded to the nearest cent half-up, and take the larger
    of that percentage amount and a flat 3000 cents — the discount is whichever of
    those two is greater."
    PRD §3.7: "The age band is PUPPY_KITTEN when the animal's age_months is under 6."

    Design: Difficulty/combinatorial_formula/adoption_fee_nested_max_promo_discount_mode_a
    """
    bootstrap_shelter(stray_hold_days=5, promo_active=True)
    # PUPPY (age 4), microchipped before submit so gross = base only.
    animal = create_available_animal(
        species="DOG", age_months=4, microchipped=True, chip_number="CHIP-2002"
    )
    adopter = create_adopter(email="cara@x.com", full_name="Cara")
    app = submit_application(animal["id"], adopter["id"])
    # gross=25000; pct_off=round(0.20*25000)=5000 > flat 3000 -> discount 5000; fee=20000
    assert app["estimated_fee_cents"] == 20000, (
        f"PUPPY 25000 chipped, promo pct_off 5000 -> 20000, got {app['estimated_fee_cents']}"
    )


def test_promo_discount_zero_when_promo_off_adult_chipped_is_15000(api):
    """PRD §3.7: "If promo_active is off, the discount is zero. The fee is then the
    gross minus the discount, but never below a floor of 0 cents."
    PRD §3.7: "nothing is added when it is true; the gross amount is the base plus
    this surcharge."

    Design: Difficulty/combinatorial_formula/adoption_fee_nested_max_promo_discount_mode_a
    """
    bootstrap_shelter(stray_hold_days=5, promo_active=False)
    # ADULT (age 36) chipped before submit -> gross 15000, no discount.
    animal = create_available_animal(
        species="DOG", age_months=36, microchipped=True, chip_number="CHIP-2003"
    )
    adopter = create_adopter(email="cara2@x.com", full_name="Cara Two")
    app = submit_application(animal["id"], adopter["id"])
    assert app["estimated_fee_cents"] == 15000, (
        f"ADULT 15000 chipped, no promo -> 15000, got {app['estimated_fee_cents']}"
    )


# ===================================================================
# Rule 2 — combinatorial formula: round-per-day-then-sum board cost
# ===================================================================

def test_board_cat_round_per_day_then_sum_three_days_is_4032(api):
    """PRD §3.4: "this per-day amount is rounded to the nearest whole cent, half-up,
    before anything else. Finally, actual_board_cents is that rounded per-day charged
    amount multiplied by the number of occupied days. The rounding order is pinned:
    the per-day amount is rounded first and then multiplied by the day count; the
    alternative of multiplying first and rounding once is not used and would yield a
    different total."

    Design: Difficulty/combinatorial_formula/board_cost_round_per_day_then_sum_mode_b
    """
    bootstrap_shelter(stray_hold_days=5, cat_daily_board_cents=1250)
    kennel = create_kennel(capacity=1, label="C-1")
    animal = register_animal(name="Tom", species="CAT", age_months=24)
    intake_animal(animal["id"], source="SURRENDER")
    ka = assign_kennel(kennel["id"], animal["id"], kennel["version"])

    set_clock("2026-06-04T00:00:00Z")  # 3 days
    released = validate_success(api_client.release_kennel_assignment(ka["id"], INTAKE))
    # round(1250*1.075)=round(1343.75)=1344; *3 = 4032 (NOT round(1250*3*1.075)=4031)
    assert released["actual_board_cents"] == 4032, (
        f"round-per-day 1344 * 3 days = 4032 (not 4031), got {released['actual_board_cents']}"
    )


def test_board_dog_round_per_day_single_day_minimum_is_1989(api):
    """PRD §3.4: "round that quotient up to the next whole number, and then take the
    larger of that figure and 1 — so any occupancy of even part of a 24-hour window
    counts as a full day, and the minimum chargeable stay is one day."
    PRD §3.4: "this per-day amount is rounded to the nearest whole cent, half-up,
    before anything else."

    Design: Difficulty/combinatorial_formula/board_cost_round_per_day_then_sum_mode_b
    """
    bootstrap_shelter(stray_hold_days=5, dog_daily_board_cents=1850)
    kennel = create_kennel(capacity=1, label="D-1")
    animal = register_animal(name="Spot", species="DOG", age_months=36)
    intake_animal(animal["id"], source="SURRENDER")
    ka = assign_kennel(kennel["id"], animal["id"], kennel["version"])

    # Release at the same clock instant -> zero elapsed, minimum 1 day.
    released = validate_success(api_client.release_kennel_assignment(ka["id"], INTAKE))
    # round(1850*1.075)=1989; minimum 1 day -> 1989
    assert released["actual_board_cents"] == 1989, (
        f"minimum 1 day at 1989/day = 1989, got {released['actual_board_cents']}"
    )


# ===================================================================
# Queue B — projected-board computed read
# ===================================================================

def test_projected_board_cat_stray_four_day_hold_is_5376(api):
    """PRD §3.4: "A forward-looking projection of board cost is available as a
    read-only capability on an assignment, returning projected_occupied_days and
    projected_board_cents. The projection uses the same per-day rounding-then-multiply
    rule, but instead of the actual end_at it projects the occupied days from start_at
    forward to the animal's expected earliest release — its stray_hold_release_at."

    Design: Corner/endpoints/projected_board_computed_read_matches_formula
    """
    bootstrap_shelter(stray_hold_days=4, cat_daily_board_cents=1250)
    kennel = create_kennel(capacity=1, label="P-1")
    animal = register_animal(name="Proj", species="CAT", age_months=24)
    intake_animal(animal["id"], source="STRAY")
    ka = assign_kennel(kennel["id"], animal["id"], kennel["version"])

    proj = validate_success(api_client.get_projected_board(ka["id"], INTAKE))
    assert proj["projected_occupied_days"] == 4, (
        f"4-day stray hold -> 4 projected days, got {proj['projected_occupied_days']}"
    )
    # round(1250*1.075)=1344; *4 = 5376
    assert proj["projected_board_cents"] == 5376, (
        f"1344/day * 4 days = 5376, got {proj['projected_board_cents']}"
    )
