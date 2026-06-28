"""Calculation correctness: honey yield (provisional vs final), colony strength
(point-in-time vs forward-projected), pollination payout, and honey revenue.

Covers difficulty queue-A instances under rules dual_variant_calc and
combinatorial_formula, plus the corner-queue calculations instances. Each test's
Design tag names the exact source instance it translates.
"""
import pytest
from test_helpers import (
    api_client, validate_success, get_success_data,
    create_apiary_payload, create_hive_payload, create_inspection_payload,
    create_honey_lot_payload, create_harvest_payload, sell_payload,
    TEST_USERS, make_apiary_manager_headers,
    create_apiary, create_registered_apiary, create_hive, create_inspected_hive,
    setup_lot_with_harvests, setup_extracted_lot,
    create_signed_contract, propose_placement, confirm_placement_fresh,
    current_contract_version, set_clock,
)

ADMIN = TEST_USERS["platform_admin_headers"]
COORDINATOR = TEST_USERS["contract_coordinator_headers"]


# ─── dual_variant_calc / honey_yield_provisional_vs_final_diverge_on_lot ────
def test_honey_yield_provisional_and_final_diverge_on_same_lot(api):
    """PRD §3.7: "it is the sum of `frames_pulled` across the lot's `RECORDED`
    (non-void) harvests, multiplied by the per-frame estimate of 2.5 kilograms
    per frame, and rounded half-up to two decimal places."
    PRD §3.7: "Extraction computes the lot's `final_yield_kg` using the **final**
    variant of the yield calculation: the measured `gross_weight_kg` reduced by a
    4% extraction loss — that is, the gross weight multiplied by 0.96 — rounded
    half-up to two decimal places."

    Design: Difficulty/dual_variant_calc/honey_yield_provisional_vs_final_diverge_on_lot
    """
    set_clock("2026-05-10T00:00:00Z")
    apiary = create_apiary()
    hive = create_hive(apiary["id"], tag="H1", brood_frames=6)
    # Two harvests: frames 4(w12.0) + 6(w18.0) -> provisional 10*2.5=25.0, gross 30.0
    lot, _ = setup_lot_with_harvests(apiary["id"], hive["id"], [(4, 12.0), (6, 18.0)])
    headers = make_apiary_manager_headers(apiary["id"])

    extracted = validate_success(api.extract_honey_lot(lot["id"], headers), 200)
    assert extracted["provisional_yield_kg"] == 25.0
    assert extracted["final_yield_kg"] == 28.8  # 30.0 * 0.96
    assert extracted["provisional_yield_kg"] != extracted["final_yield_kg"]


def test_final_yield_applies_four_percent_extraction_loss(api):
    """PRD §3.7: "Extraction computes the lot's `final_yield_kg` using the **final**
    variant of the yield calculation: the measured `gross_weight_kg` reduced by a
    4% extraction loss — that is, the gross weight multiplied by 0.96 — rounded
    half-up to two decimal places."

    Design: Difficulty/dual_variant_calc/honey_yield_provisional_vs_final_diverge_on_lot
    """
    set_clock("2026-05-10T00:00:00Z")
    apiary = create_apiary()
    hive = create_hive(apiary["id"], tag="H1", brood_frames=6)
    lot, _ = setup_lot_with_harvests(apiary["id"], hive["id"], [(4, 12.0), (6, 18.0)])
    headers = make_apiary_manager_headers(apiary["id"])

    extracted = validate_success(api.extract_honey_lot(lot["id"], headers), 200)
    assert extracted["gross_weight_kg"] == 30.0
    assert extracted["final_yield_kg"] == 28.8


# ─── dual_variant_calc / colony_strength_point_in_time_vs_forward_projected ──
def test_point_in_time_vs_forward_projected_strength_diverge_on_hive(api):
    """PRD §3.3: "The raw result is the base minus the mite penalty plus the queen
    bonus, and the final score is that raw value clamped into the inclusive range
    from 0 to 100 — any value below 0 becomes 0 and any value above 100 becomes 100."
    PRD §3.5: "the colony's `brood_frames` is first projected forward to
    `bloom_start`, growing by 2 frames per whole week from the clock to
    `bloom_start` (using the floor of the number of whole weeks, so a partial week
    adds no growth) and capped at a maximum of 20 brood frames, and only then is
    the score computed."

    Design: Difficulty/dual_variant_calc/colony_strength_point_in_time_vs_forward_projected_diverge_on_hive
    """
    set_clock("2026-01-06T00:00:00Z")
    apiary, _ = create_registered_apiary()
    # brood=5, honey=3, mite 1.0, queenright -> point-in-time = 5*8+3*3+10 = 59
    hive = create_inspected_hive(apiary["id"], brood_frames=5,
                                 brood_frames_observed=5, honey_frames_observed=3,
                                 mites=1.0, queen_seen=True,
                                 inspected_at="2026-01-06T00:00:00Z", tag="H1")
    assert hive["inspection_strength"] == 59

    # bloom 2026-02-04 is 29 days ahead -> 4 whole weeks -> +8 brood -> 13 -> capped? 13<20
    # forward brood 13 -> 13*8 + 3*3 + 10 = 104 + 9 + 10 = 123 -> clamp 100
    contract = create_signed_contract(required_strong_hives=1, max_hives_on_site=4,
                                      base_rate_cents=20000)
    placement = propose_placement(contract["id"], hive["id"])
    confirmed = confirm_placement_fresh(contract["id"], placement["id"])
    assert confirmed["contract_rated_strength"] == 100
    assert confirmed["grade"] == "CONTRACT_GRADE"


def test_forward_projected_grade_contract_grade_above_minimum(api):
    """PRD §3.5: "The grade is `CONTRACT_GRADE` when the projected score is at or
    above the contract-grade minimum of 60, and `SUB_GRADE` otherwise."

    Design: Difficulty/dual_variant_calc/colony_strength_point_in_time_vs_forward_projected_diverge_on_hive
    """
    set_clock("2026-01-06T00:00:00Z")
    apiary, _ = create_registered_apiary()
    hive = create_inspected_hive(apiary["id"], brood_frames=5,
                                 brood_frames_observed=5, honey_frames_observed=3,
                                 mites=1.0, queen_seen=True, tag="H1")
    # Today's point-in-time strength is 59 (< 60), but forward-projected is 100.
    assert hive["inspection_strength"] == 59
    contract = create_signed_contract(required_strong_hives=1, max_hives_on_site=4,
                                      base_rate_cents=20000)
    placement = propose_placement(contract["id"], hive["id"])
    confirmed = confirm_placement_fresh(contract["id"], placement["id"])
    assert confirmed["grade"] == "CONTRACT_GRADE"


# ─── combinatorial_formula / pollination_payout_nested_min_max_tiered_mode_a ─
def test_pollination_payout_two_contract_grade_hives(api):
    """PRD §3.6: "a contract-grade hive earns the contract's `base_rate_cents`
    multiplied by a strong multiplier of 1.20 when its `contract_rated_strength` is
    at or above the strong-bonus minimum of 80, and by 1.00 otherwise"
    PRD §3.6: "A fulfillment bonus of 10000 cents is added when `placed_strong_hives`
    is at or above `required_strong_hives`, and zero otherwise."
    PRD §3.6: "The `projected_payout_cents` is the greater of zero and the subtotal
    plus the fulfillment bonus minus the penalty."

    Design: Difficulty/combinatorial_formula/pollination_payout_nested_min_max_tiered_mode_a
    """
    set_clock("2026-01-06T00:00:00Z")
    apiary, _ = create_registered_apiary()
    h1 = create_inspected_hive(apiary["id"], tag="H1", brood_frames=5,
                               brood_frames_observed=5)
    h2 = create_inspected_hive(apiary["id"], tag="H2", brood_frames=5,
                               brood_frames_observed=5)
    contract = create_signed_contract(required_strong_hives=2, max_hives_on_site=4,
                                      base_rate_cents=20000)
    p1 = propose_placement(contract["id"], h1["id"])
    confirm_placement_fresh(contract["id"], p1["id"])
    p2 = propose_placement(contract["id"], h2["id"])
    confirm_placement_fresh(contract["id"], p2["id"])

    placed = validate_success(api.finalize_placement(contract["id"], COORDINATOR), 200)
    assert placed["status"] == "PLACED"
    assert placed["placed_strong_hives"] == 2
    # 2 strong hives @ strength100 -> 20000*1.20=24000 each -> 48000 subtotal
    # + 10000 fulfillment bonus, shortfall 0 -> 58000
    assert placed["projected_payout_cents"] == 58000


def test_pollination_payout_strong_multiplier_at_strength_above_80(api):
    """PRD §3.6: "a contract-grade hive earns the contract's `base_rate_cents`
    multiplied by a strong multiplier of 1.20 when its `contract_rated_strength` is
    at or above the strong-bonus minimum of 80, and by 1.00 otherwise"
    PRD §3.6: "Each per-hive amount is rounded half-up to whole cents **before** any
    summation."

    Design: Difficulty/combinatorial_formula/pollination_payout_nested_min_max_tiered_mode_a
    """
    set_clock("2026-01-06T00:00:00Z")
    apiary, _ = create_registered_apiary()
    h1 = create_inspected_hive(apiary["id"], tag="H1", brood_frames=5,
                               brood_frames_observed=5)
    contract = create_signed_contract(required_strong_hives=1, max_hives_on_site=4,
                                      base_rate_cents=20000)
    p1 = propose_placement(contract["id"], h1["id"])
    confirmed = confirm_placement_fresh(contract["id"], p1["id"])
    assert confirmed["contract_rated_strength"] == 100  # >= 80 -> strong mult

    placed = validate_success(api.finalize_placement(contract["id"], COORDINATOR), 200)
    # 1 strong hive @100 -> 20000*1.20=24000 + 10000 bonus -> 34000
    assert placed["projected_payout_cents"] == 34000


# ─── combinatorial_formula / honey_revenue_discount_keyed_on_total_tier_mode_c ─
def test_honey_revenue_tier1_discount_keyed_on_gross(api):
    """PRD §3.7: "The `gross_revenue_cents` is the `final_yield_kg` multiplied by
    `price_per_kg_cents`, rounded half-up to whole cents."
    PRD §3.7: "If `gross_revenue_cents` is at or above 500000 cents the discount is
    10%; otherwise if it is at or above 100000 cents the discount is 5%; otherwise
    the discount is zero."
    PRD §3.7: "The `net_revenue_cents` is `gross_revenue_cents` minus the discount,
    where the discount is `gross_revenue_cents` multiplied by the discount
    percentage and rounded half-up to whole cents."

    Design: Difficulty/combinatorial_formula/honey_revenue_discount_keyed_on_total_tier_mode_c
    """
    set_clock("2026-05-10T00:00:00Z")
    apiary = create_apiary()
    hive = create_hive(apiary["id"], tag="H1", brood_frames=6)
    # gross 30.0 kg -> final 28.8 kg
    extracted = setup_extracted_lot(apiary["id"], hive["id"], [(5, 12.0), (5, 18.0)])
    assert extracted["final_yield_kg"] == 28.8
    headers = make_apiary_manager_headers(apiary["id"])

    sold = validate_success(
        api.sell_honey_lot(extracted["id"], sell_payload(price_per_kg_cents=4000),
                           headers), 200)
    assert sold["status"] == "SOLD"
    # gross = round(28.8 * 4000) = 115200 -> tier1 (>=100000) 5% -> discount 5760
    assert sold["gross_revenue_cents"] == 115200
    assert sold["net_revenue_cents"] == 109440


def test_honey_revenue_gross_rounded_before_tier_selection(api):
    """PRD §3.7: "A volume discount is then keyed on that gross figure with a pinned
    evaluation order: compute the gross first, select the tier from the gross, then
    apply."
    PRD §3.7: "If `gross_revenue_cents` is at or above 500000 cents the discount is
    10%; otherwise if it is at or above 100000 cents the discount is 5%; otherwise
    the discount is zero."

    Design: Difficulty/combinatorial_formula/honey_revenue_discount_keyed_on_total_tier_mode_c
    """
    set_clock("2026-05-10T00:00:00Z")
    apiary = create_apiary()
    hive = create_hive(apiary["id"], tag="H1", brood_frames=6)
    extracted = setup_extracted_lot(apiary["id"], hive["id"], [(5, 12.0), (5, 18.0)])
    headers = make_apiary_manager_headers(apiary["id"])
    sold = validate_success(
        api.sell_honey_lot(extracted["id"], sell_payload(price_per_kg_cents=4000),
                           headers), 200)
    # gross 115200 sits in tier1 [100000,500000): 5% applied, not 10%
    assert sold["gross_revenue_cents"] == 115200
    assert sold["net_revenue_cents"] == 109440


# ─── Corner / calculations ──────────────────────────────────────────────────
def test_mite_threshold_just_below_three_no_recommendation(api):
    """PRD §3.3: "The inspection also computes a boolean `treatment_recommended`,
    which is true exactly when `mites_per_100_bees` is at or above the
    mite-treatment threshold of 3.0 mites per 100 bees, and false otherwise — this
    is a precise boundary, so a reading of exactly 3.0 recommends treatment."

    Design: Corner/calculations/mite_threshold_just_below_three_no_recommendation
    """
    set_clock("2026-01-06T00:00:00Z")
    apiary = create_apiary()
    headers = make_apiary_manager_headers(apiary["id"])
    hive = create_hive(apiary["id"], tag="H1", brood_frames=5)

    insp = validate_success(api.create_inspection(
        hive["id"],
        create_inspection_payload(mites_per_100_bees=2.9, brood_frames_observed=5,
                                  honey_frames_observed=3, queen_seen=True), headers), 201)
    assert insp["treatment_recommended"] is False
    refreshed = validate_success(api.get_hive(hive["id"], headers), 200)
    # 2.9 < 3.0 -> no mite penalty: 5*8 + 3*3 + 10 = 59
    assert refreshed["inspection_strength"] == 59


def test_inspection_strength_mite_penalty_applied_above_threshold(api):
    """PRD §3.3: "From this base a mite penalty of 25 points is subtracted when the
    colony's most recent mite reading (`last_mite_count`) is at or above the 3.0
    threshold, and zero is subtracted otherwise. A queen bonus of 10 points is
    added when the colony is `QUEENRIGHT`, and zero is added otherwise."

    Design: Corner/calculations/inspection_strength_mite_penalty_applied_above_threshold
    """
    set_clock("2026-01-06T00:00:00Z")
    apiary = create_apiary()
    headers = make_apiary_manager_headers(apiary["id"])
    hive = create_hive(apiary["id"], tag="H1", brood_frames=5)
    validate_success(api.create_inspection(
        hive["id"],
        create_inspection_payload(mites_per_100_bees=4.0, brood_frames_observed=5,
                                  honey_frames_observed=3, queen_seen=True), headers), 201)
    refreshed = validate_success(api.get_hive(hive["id"], headers), 200)
    # 5*8 + 3*3 - 25 + 10 = 34
    assert refreshed["inspection_strength"] == 34


def test_provisional_yield_recomputed_after_each_harvest(api):
    """PRD §3.7: "it is the sum of `frames_pulled` across the lot's `RECORDED`
    (non-void) harvests, multiplied by the per-frame estimate of 2.5 kilograms per
    frame, and rounded half-up to two decimal places."
    PRD §2.9: "The second conserved quantity is a honey lot's `gross_weight_kg`:
    the running sum of the `weight_kg` of every non-voided harvest contribution
    rolled into the lot."

    Design: Corner/calculations/provisional_yield_recomputed_after_each_harvest
    """
    set_clock("2026-05-10T00:00:00Z")
    apiary = create_apiary()
    hive = create_hive(apiary["id"], tag="H1", brood_frames=6)
    lot, _ = setup_lot_with_harvests(apiary["id"], hive["id"], [(4, 12.0), (6, 18.0)])
    headers = make_apiary_manager_headers(apiary["id"])
    refreshed = validate_success(api.get_honey_lot(lot["id"], headers), 200)
    # (4+6)*2.5 = 25.0; gross 30.0
    assert refreshed["provisional_yield_kg"] == 25.0
    assert refreshed["gross_weight_kg"] == 30.0


def test_final_yield_null_while_draft(api):
    """PRD §3.7: "The `final_yield_kg` is null until the lot is extracted, and it
    diverges from the frame-based provisional estimate for the same lot."

    Design: Corner/calculations/variant_selection_provisional_at_draft_final_only_after_extract
    """
    set_clock("2026-05-10T00:00:00Z")
    apiary = create_apiary()
    hive = create_hive(apiary["id"], tag="H1", brood_frames=6)
    lot, _ = setup_lot_with_harvests(apiary["id"], hive["id"], [(4, 12.0)])
    headers = make_apiary_manager_headers(apiary["id"])
    refreshed = validate_success(api.get_honey_lot(lot["id"], headers), 200)
    assert refreshed["status"] == "DRAFT"
    assert refreshed["final_yield_kg"] is None
