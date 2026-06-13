"""Pricing-engine tests: the condition-grading formula, the promotion bonus, and
the inspection-outcome tolerance band, with their boundary cases.

Every test reaches the exact pricing state via test_helpers fixtures and copies
the literal expected cents pre-computed in the design index.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success,
    get_success_data,
    find_quote,
    setup_catalog_model_customer,
    create_quoted_trade_in,
    create_received_trade_in,
    create_promotion,
    set_clock,
    inspect,
    get_quotes,
    get_inspections,
    make_customer_headers,
    TEST_USERS,
)

ADMIN = TEST_USERS["catalog_admin_headers"]


# ─────────────────────────────────────────────────────────────────────────────
# dual_variant_calc / graded_value_quoted_vs_inspected_diverge
# ─────────────────────────────────────────────────────────────────────────────

def test_quoted_value_is_self_graded_48000(api):
    """PRD §3.4: "the model's `base_value_cents` is multiplied by the multiplier
    for the declared grade taken from `condition_multipliers`, and that product is
    rounded to whole cents using round half up to give the conditioned value."
    PRD §3.4: "The quote's `amount_cents` is then simply the graded subtotal plus
    the promotion bonus; since both are already whole cents, no further rounding is applied."

    A self-graded GOOD/no-defect quote on a 60000 model yields amount 48000.

    Design: Difficulty/dual_variant_calc/graded_value_quoted_vs_inspected_diverge
    """
    _cat, model, customer = setup_catalog_model_customer()
    ti = create_quoted_trade_in(customer, model, declared_grade="GOOD", declared_defects=[], declared_powers_on=True)

    quotes = get_quotes(ti["id"])
    initial = find_quote(quotes, kind="INITIAL")
    assert initial["amount_cents"] == 48000, f"INITIAL quote amount should be 48000, got {initial['amount_cents']}"


def test_inspected_value_diverges_from_quoted(api):
    """PRD §3.6: "The inspection computes an `inspected_value_cents` by re-running the
    very same condition-grading formula described in Section 3.4 ... but with one
    critical difference: **no promotion bonus is ever applied to an inspected value**."

    Same device: self-graded GOOD/no-defect quote is 48000, but a verified
    FAIR+WATER_DAMAGE inspection yields inspected_value 16000 — the two diverge.

    Design: Difficulty/dual_variant_calc/graded_value_quoted_vs_inspected_diverge
    """
    _cat, model, customer = setup_catalog_model_customer()
    ti = create_received_trade_in(customer, model, declared_grade="GOOD", declared_defects=[], declared_powers_on=True)

    quotes = get_quotes(ti["id"])
    initial = find_quote(quotes, kind="INITIAL")
    assert initial["amount_cents"] == 48000

    inspect(ti["id"], "FAIR", verified_defects=["WATER_DAMAGE"])
    inspections = get_inspections(ti["id"])
    assert len(inspections) == 1
    assert inspections[0]["inspected_value_cents"] == 16000, "verified FAIR+WATER_DAMAGE should grade to 16000"
    assert inspections[0]["inspected_value_cents"] != initial["amount_cents"]


# ─────────────────────────────────────────────────────────────────────────────
# combinatorial_formula / graded_value_three_input_nonlinear_poweroff_floor
# ─────────────────────────────────────────────────────────────────────────────

def test_poweroff_override_forces_poor_floor_and_wont_power_on(api):
    """PRD §3.4: "if `declared_powers_on` is false, the conditioned value is instead
    computed using the `POOR` multiplier regardless of the declared grade, and
    additionally the `WONT_POWER_ON` deduction is added to the deduction total even
    if `WONT_POWER_ON` was not among the declared defects (if it was already listed,
    it is not counted twice)."

    GOOD declared but powers_on=false: POOR floor 21000 minus WONT_POWER_ON 15000 = 6000.

    Design: Difficulty/combinatorial_formula/graded_value_three_input_nonlinear_poweroff_floor
    """
    _cat, model, customer = setup_catalog_model_customer()
    ti = create_quoted_trade_in(customer, model, declared_grade="GOOD", declared_defects=[], declared_powers_on=False)

    quotes = get_quotes(ti["id"])
    initial = find_quote(quotes, kind="INITIAL")
    assert initial["graded_subtotal_cents"] == 6000, f"expected 6000, got {initial['graded_subtotal_cents']}"
    assert initial["amount_cents"] == 6000


def test_poweroff_override_amount_equals_subtotal_no_promo(api):
    """PRD §3.4: "The graded subtotal, stored on the quote as `graded_subtotal_cents`,
    is the conditioned value minus the total deductions, floored at 0 so it can never
    go negative."
    PRD §3.4: "When no promotion was resolved, `promo_bonus_cents` is 0."

    With no promo, the GOOD/powers_off quote's amount equals its 6000 subtotal and
    promo_bonus is 0.

    Design: Difficulty/combinatorial_formula/graded_value_three_input_nonlinear_poweroff_floor
    """
    _cat, model, customer = setup_catalog_model_customer()
    ti = create_quoted_trade_in(customer, model, declared_grade="GOOD", declared_defects=[], declared_powers_on=False)

    initial = find_quote(get_quotes(ti["id"]), kind="INITIAL")
    assert initial["graded_subtotal_cents"] == 6000
    assert initial["promo_bonus_cents"] == 0
    assert initial["amount_cents"] == 6000


# ─────────────────────────────────────────────────────────────────────────────
# combinatorial_formula / promo_bonus_nested_rounding_then_cap_order
# ─────────────────────────────────────────────────────────────────────────────

def test_promo_bonus_round_pct_add_flat_then_cap(api):
    """PRD §3.4: "first taking the percentage part — the graded subtotal multiplied by
    the campaign's `bonus_pct`, rounded to whole cents using round half up — then
    adding the campaign's `bonus_flat_cents` flat part, and finally clamping the sum
    down to `bonus_cap_cents` if it would exceed the cap. The ordering is pinned and
    observable when the cap straddles the raw bonus: round the percentage part first,
    add the flat part second, then apply the cap to the combined total."

    pct rhu(36000*0.10)=3600, +flat 4000 = 7600, capped to 5000.

    Design: Difficulty/combinatorial_formula/promo_bonus_nested_rounding_then_cap_order
    """
    cat, model, customer = setup_catalog_model_customer()
    create_promotion(
        cat["id"], code="CAP5", category_scope="ALL",
        effective_from="2026-01-01T00:00:00Z", effective_to="2027-01-01T00:00:00Z",
        bonus_pct=0.10, bonus_flat_cents=4000, bonus_cap_cents=5000,
    )
    set_clock("2026-06-01T00:00:00Z")
    ti = create_quoted_trade_in(
        customer, model, declared_grade="GOOD", declared_defects=["CRACKED_SCREEN"],
        declared_powers_on=True, promo_code="CAP5",
    )

    initial = find_quote(get_quotes(ti["id"]), kind="INITIAL")
    assert initial["graded_subtotal_cents"] == 36000
    assert initial["promo_bonus_cents"] == 5000, f"capped bonus should be 5000, got {initial['promo_bonus_cents']}"


def test_promo_capped_amount_is_subtotal_plus_capped_bonus(api):
    """PRD §3.4: "The quote's `amount_cents` is then simply the graded subtotal plus
    the promotion bonus; since both are already whole cents, no further rounding is applied."

    36000 subtotal + 5000 capped bonus = 41000.

    Design: Difficulty/combinatorial_formula/promo_bonus_nested_rounding_then_cap_order
    """
    cat, model, customer = setup_catalog_model_customer()
    create_promotion(
        cat["id"], code="CAP5", category_scope="ALL",
        effective_from="2026-01-01T00:00:00Z", effective_to="2027-01-01T00:00:00Z",
        bonus_pct=0.10, bonus_flat_cents=4000, bonus_cap_cents=5000,
    )
    set_clock("2026-06-01T00:00:00Z")
    ti = create_quoted_trade_in(
        customer, model, declared_grade="GOOD", declared_defects=["CRACKED_SCREEN"],
        declared_powers_on=True, promo_code="CAP5",
    )

    initial = find_quote(get_quotes(ti["id"]), kind="INITIAL")
    assert initial["amount_cents"] == 41000, f"expected 41000, got {initial['amount_cents']}"


# ─────────────────────────────────────────────────────────────────────────────
# boundary_precision_check / graded_value_zero_floor_empty_deduction_edge
# ─────────────────────────────────────────────────────────────────────────────

def test_graded_subtotal_floored_at_zero(api):
    """PRD §3.4: "The graded subtotal, stored on the quote as `graded_subtotal_cents`,
    is the conditioned value minus the total deductions, floored at 0 so it can never
    go negative."

    POOR + WATER_DAMAGE + powers_off: conditioned 21000, deductions 20000+15000=35000,
    so max(0, -14000) = 0.

    Design: Difficulty/boundary_precision_check/graded_value_zero_floor_empty_deduction_edge
    """
    _cat, model, customer = setup_catalog_model_customer()
    ti = create_quoted_trade_in(
        customer, model, declared_grade="POOR", declared_defects=["WATER_DAMAGE"], declared_powers_on=False
    )

    initial = find_quote(get_quotes(ti["id"]), kind="INITIAL")
    assert initial["graded_subtotal_cents"] == 0, f"expected floored 0, got {initial['graded_subtotal_cents']}"


def test_zero_floor_amount_is_zero(api):
    """PRD §3.4: "The quote's `amount_cents` is then simply the graded subtotal plus
    the promotion bonus; since both are already whole cents, no further rounding is applied."

    With a 0 graded subtotal and no promo, the offered amount is 0.

    Design: Difficulty/boundary_precision_check/graded_value_zero_floor_empty_deduction_edge
    """
    _cat, model, customer = setup_catalog_model_customer()
    ti = create_quoted_trade_in(
        customer, model, declared_grade="POOR", declared_defects=["WATER_DAMAGE"], declared_powers_on=False
    )

    initial = find_quote(get_quotes(ti["id"]), kind="INITIAL")
    assert initial["amount_cents"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# boundary_precision_check / inspection_tolerance_inclusive_boundary
# ─────────────────────────────────────────────────────────────────────────────

def test_inspection_tolerance_inclusive_boundary_matches(api):
    """PRD §3.6: "if the inspected value is greater than or equal to that minimum
    acceptable value, the outcome is `MATCH`."
    PRD §3.6: "the system computes the minimum acceptable value as the locked quote
    amount minus the tolerance band, where the band is the locked amount multiplied by
    the catalog's `requote_tolerance_pct` and rounded to whole cents using round half up".

    Locked 60000, tol 0.15 -> band 9000 -> min_acceptable 51000. An inspected value
    of exactly 51000 is MATCH (inclusive), auto-accepting the trade-in.

    Design: Difficulty/boundary_precision_check/inspection_tolerance_inclusive_boundary
    """
    _cat, model, customer = setup_catalog_model_customer()
    ti = create_received_trade_in(customer, model, declared_grade="FLAWLESS")
    inspect(ti["id"], "FLAWLESS", verified_defects=["BATTERY_DEGRADED", "MISSING_PARTS"])

    inspections = get_inspections(ti["id"])
    assert inspections[0]["inspected_value_cents"] == 51000
    assert inspections[0]["outcome"] == "MATCH"
    refreshed = validate_success(api.get_trade_in(ti["id"], ADMIN))
    assert refreshed["status"] == "ACCEPTED"


def test_inspection_below_tolerance_boundary_requotes(api):
    """PRD §3.6: "when the inspected value falls below the minimum acceptable value but
    stays above the recycle floor, the outcome is `REQUOTE`."

    One deduction-step below the 51000 boundary (inspected 48000) flips to REQUOTE.

    Design: Difficulty/boundary_precision_check/inspection_tolerance_inclusive_boundary
    """
    _cat, model, customer = setup_catalog_model_customer()
    ti = create_received_trade_in(customer, model, declared_grade="FLAWLESS")
    inspect(ti["id"], "FLAWLESS", verified_defects=["BATTERY_DEGRADED", "MISSING_PARTS", "DENTED_BODY"])

    inspections = get_inspections(ti["id"])
    assert inspections[0]["inspected_value_cents"] == 48000
    assert inspections[0]["outcome"] == "REQUOTE"
    refreshed = validate_success(api.get_trade_in(ti["id"], ADMIN))
    assert refreshed["status"] == "REQUOTED"


# ─────────────────────────────────────────────────────────────────────────────
# Corner / calculations
# ─────────────────────────────────────────────────────────────────────────────

def test_promo_bonus_within_cap_full_grant(api):
    """PRD §3.4: "first taking the percentage part — the graded subtotal multiplied by
    the campaign's `bonus_pct`, rounded to whole cents using round half up — then
    adding the campaign's `bonus_flat_cents` flat part, and finally clamping the sum
    down to `bonus_cap_cents` if it would exceed the cap."

    SAVE10 (pct 0.10, flat 2000, cap 6000) on graded 36000: 3600+2000=5600 (<=6000),
    fully granted; amount 41600.

    Design: Corner/calculations/promo_bonus_within_cap_full_grant
    """
    cat, model, customer = setup_catalog_model_customer()
    create_promotion(
        cat["id"], code="SAVE10", category_scope="ALL",
        effective_from="2026-01-01T00:00:00Z", effective_to="2027-01-01T00:00:00Z",
        bonus_pct=0.10, bonus_flat_cents=2000, bonus_cap_cents=6000,
    )
    set_clock("2026-06-01T00:00:00Z")
    ti = create_quoted_trade_in(
        customer, model, declared_grade="GOOD", declared_defects=["CRACKED_SCREEN"],
        declared_powers_on=True, promo_code="SAVE10",
    )

    initial = find_quote(get_quotes(ti["id"]), kind="INITIAL")
    assert initial["promo_bonus_cents"] == 5600
    assert initial["amount_cents"] == 41600


def test_requote_quote_carries_no_promo_bonus(api):
    """PRD §3.6: "a fresh `Quote` of `kind` `REQUOTE` is minted in `LOCKED` status with
    its `amount_cents` equal to the inspected value, its `promo_bonus_cents` fixed at 0".

    Even though the INITIAL quote carried a promo bonus, the REQUOTE quote minted at
    inspection has promo_bonus_cents 0 and amount equal to the 16000 inspected value.

    Design: Corner/calculations/requote_quote_carries_no_promo_bonus
    """
    cat, model, customer = setup_catalog_model_customer()
    create_promotion(
        cat["id"], code="SAVE10", category_scope="ALL",
        effective_from="2026-01-01T00:00:00Z", effective_to="2027-01-01T00:00:00Z",
        bonus_pct=0.10, bonus_flat_cents=2000, bonus_cap_cents=6000,
    )
    set_clock("2026-06-01T00:00:00Z")
    ti = create_received_trade_in(
        customer, model, declared_grade="GOOD", declared_defects=["CRACKED_SCREEN"],
        declared_powers_on=True, promo_code="SAVE10",
    )
    inspect(ti["id"], "FAIR", verified_defects=["WATER_DAMAGE"])

    requote = find_quote(get_quotes(ti["id"]), kind="REQUOTE")
    assert requote["promo_bonus_cents"] == 0
    assert requote["amount_cents"] == 16000


def test_recycle_floor_inclusive_boundary(api):
    """PRD §3.6: "if the inspected value is at or below the catalog's
    `recycle_floor_value_cents`, the outcome is `RECYCLE` — the floor check is
    evaluated before anything else and wins outright."

    With recycle_floor 16000, an inspected value of exactly 16000 is RECYCLE (inclusive).

    Design: Corner/calculations/recycle_floor_inclusive_boundary
    """
    _cat, model, customer = setup_catalog_model_customer(catalog_overrides={"recycle_floor_value_cents": 16000})
    ti = create_received_trade_in(
        customer, model, declared_grade="GOOD", declared_defects=["CRACKED_SCREEN"], declared_powers_on=True
    )
    inspect(ti["id"], "FAIR", verified_defects=["WATER_DAMAGE"])

    inspections = get_inspections(ti["id"])
    assert inspections[0]["inspected_value_cents"] == 16000
    assert inspections[0]["outcome"] == "RECYCLE"
    refreshed = validate_success(api.get_trade_in(ti["id"], ADMIN))
    assert refreshed["status"] == "RECYCLED"
