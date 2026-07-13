"""Depth probes: dual-variant calculations and combinatorial formulas.

Covers Difficulty rules dual_variant_calc and combinatorial_formula — PEP dose
cost (provisional vs final), quarantine boarding (estimated vs actual),
risk_level branching, and per-line citation-fine rounding.
"""
import pytest

from test_helpers import (
    validate_success,
    setup_pep_initiated,
    setup_active_facility_order,
    create_animal,
    create_bite_case,
    setup_citation_issued,
    set_clock,
)


# ---------------------------------------------------------------------------
# dual_variant_calc / pep_cost_provisional_vs_final_on_victim
# ---------------------------------------------------------------------------
def test_pep_projected_cost_assumes_full_regimen(api):
    """PRD §3.6: "The `projected_doses` is four when the `indication` is
    `INITIATE` and zero otherwise. The `projected_cost_cents` is the
    `projected_doses` multiplied by the per-dose cost of 30,000 cents, plus a
    one-time rabies immune globulin cost of 120,000 cents when `rig_indicated`
    is true."

    Design: Difficulty/dual_variant_calc/pep_cost_provisional_vs_final_on_victim
    """
    pep = setup_pep_initiated(wound_category="CATEGORY_II", doses=0)["pep"]
    assert pep["indication"] == "INITIATE"
    assert pep["projected_doses"] == 4
    assert pep["projected_cost_cents"] == 120000


def test_pep_final_cost_counts_only_administered_doses(api, epidemiologist_headers):
    """PRD §3.6: "The `final_cost_cents` is the `doses_administered` multiplied
    by the per-dose cost of 30,000 cents, plus the 120,000-cent immune-globulin
    cost when `rig_indicated` is true and at least one dose has been
    administered. Because it counts only actual doses, `final_cost_cents`
    diverges from `projected_cost_cents` whenever prophylaxis stops early."

    Design: Difficulty/dual_variant_calc/pep_cost_provisional_vs_final_on_victim
    """
    state = setup_pep_initiated(wound_category="CATEGORY_II", doses=1)
    pep = validate_success(
        api.administer_dose(state["pep"]["id"], {}, epidemiologist_headers), 200)
    assert pep["status"] == "INITIATED"
    assert pep["doses_administered"] == 2
    assert pep["projected_cost_cents"] == 120000
    assert pep["final_cost_cents"] == 60000


# ---------------------------------------------------------------------------
# dual_variant_calc / quarantine_boarding_estimated_vs_actual_on_owner
# ---------------------------------------------------------------------------
def test_boarding_estimated_full_ten_days_while_active(api):
    """PRD §3.3: "While the order is `ACTIVE` the estimated variant applies and
    `billable_days` is fixed at the full ten-day window."

    Design: Difficulty/dual_variant_calc/quarantine_boarding_estimated_vs_actual_on_owner
    """
    order = setup_active_facility_order(daily_boarding_cents=4000)["order"]
    assert order["status"] == "ACTIVE"
    assert order["boarding_cost_cents"] == 40000


def test_boarding_actual_whole_days_after_early_breach(api, animal_control_officer_headers):
    """PRD §3.3: "Once the order is terminal the actual variant applies:
    `billable_days` is the number of whole 24-hour days from `start_date` to
    `actual_release_date`, taken as a floor, but never fewer than one day."
    PRD §3.4: "A breach moves the order from `ACTIVE` to `BREACHED`, sets
    `actual_release_date` to the clock's current value, recomputes
    `boarding_cost_cents` to the actual variant, and, for a facility order,
    decreases the facility's `current_occupancy` by one."

    Design: Difficulty/dual_variant_calc/quarantine_boarding_estimated_vs_actual_on_owner
    """
    state = setup_active_facility_order(daily_boarding_cents=4000,
                                        clock="2026-03-01T00:00:00Z",
                                        start_date="2026-03-01T00:00:00Z")
    set_clock("2026-03-05T00:00:00Z")
    order = validate_success(
        api.breach_quarantine_order(state["order"]["id"], animal_control_officer_headers), 200)
    assert order["status"] == "BREACHED"
    assert order["boarding_cost_cents"] == 16000


# ---------------------------------------------------------------------------
# combinatorial_formula / risk_level_nonlinear_branch_mode_a
# ---------------------------------------------------------------------------
def test_current_vaccinated_dog_category_iii_yields_low_defer(api, intake_officer_headers):
    """PRD §3.1: "Otherwise, if the animal's `species` is one of the observable
    domestic species — `DOG`, `CAT`, or `FERRET` — then a `vaccination_status`
    of `CURRENT` yields `risk_level` `LOW` while any other vaccination status
    yields `MODERATE`."
    PRD §3.1: "`NONE` maps to `NOT_INDICATED`, `LOW` maps to `DEFER`, `MODERATE`
    maps to `INITIATE`, and `HIGH` maps to `INITIATE`."

    Design: Difficulty/combinatorial_formula/risk_level_nonlinear_branch_mode_a
    """
    animal = create_animal(species="DOG", animal_class="DOMESTIC",
                           identified=True, vaccination_status="CURRENT")
    case = create_bite_case(region_code="RB-CF1", wound_category="CATEGORY_III",
                            body_site="ARM", animal_id=animal["id"])
    assert case["risk_level"] == "LOW"
    assert case["pep_indication"] == "DEFER"


def test_expired_vaccinated_dog_yields_moderate_initiate(api):
    """PRD §3.1: "Otherwise, if the animal's `species` is one of the observable
    domestic species — `DOG`, `CAT`, or `FERRET` — then a `vaccination_status`
    of `CURRENT` yields `risk_level` `LOW` while any other vaccination status
    yields `MODERATE`."
    PRD §3.1: "`NONE` maps to `NOT_INDICATED`, `LOW` maps to `DEFER`, `MODERATE`
    maps to `INITIATE`, and `HIGH` maps to `INITIATE`."

    Design: Difficulty/combinatorial_formula/risk_level_nonlinear_branch_mode_a
    """
    animal = create_animal(species="DOG", animal_class="DOMESTIC",
                           identified=True, vaccination_status="EXPIRED")
    case = create_bite_case(region_code="RB-CF1b", wound_category="CATEGORY_II",
                            body_site="ARM", animal_id=animal["id"])
    assert case["risk_level"] == "MODERATE"
    assert case["pep_indication"] == "INITIATE"


# ---------------------------------------------------------------------------
# combinatorial_formula / citation_fine_per_line_rounding_mode_b
# ---------------------------------------------------------------------------
def test_two_violation_fine_rounds_per_line_then_sums(api):
    """PRD §3.7: "The `total_fine_cents` — the amount actually owed — applies an
    8.5 percent surcharge: for each violation line the base fine is multiplied
    by 1.085 and that product is rounded to a whole cent with round half up, and
    only then are the rounded lines summed. Rounding per line before summing is
    required; summing first and rounding once is incorrect."

    Design: Difficulty/combinatorial_formula/citation_fine_per_line_rounding_mode_b
    """
    citation = setup_citation_issued(
        violations=("NO_CURRENT_VACCINATION", "UNLICENSED_ANIMAL"))["citation"]
    assert citation["base_fine_cents"] == 40100
    assert citation["total_fine_cents"] == 43508


def test_single_violation_fine_applies_surcharge(api):
    """PRD §3.7: "Each violation contributes a base fine drawn from a fixed
    schedule: `QUARANTINE_BREACH` is 50,000 cents, `FAILURE_TO_SURRENDER` is
    75,000 cents, `NO_CURRENT_VACCINATION` is 25,025 cents, and
    `UNLICENSED_ANIMAL` is 15,075 cents."
    PRD §3.7: "for each violation line the base fine is multiplied by 1.085 and
    that product is rounded to a whole cent with round half up, and only then
    are the rounded lines summed."

    Design: Difficulty/combinatorial_formula/citation_fine_per_line_rounding_mode_b
    """
    citation = setup_citation_issued(violations=("QUARANTINE_BREACH",))["citation"]
    assert citation["base_fine_cents"] == 50000
    assert citation["total_fine_cents"] == 54250
