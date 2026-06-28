"""Herbal dispensing: fill cascade, inventory conservation, and dispense gating.

Covers the fill-to-LOW_STOCK transitive-cascade difficulty instance, the
inventory-mass conservation compensating-invariant difficulty instance, the
safety-beats-referential priority-pair difficulty instance, the dispense-requires-
plan-active cross-entity difficulty instance, and the corner instances for
insufficient stock and reverse-not-filled.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, make_practitioner_headers,
    assert_herb_item, assert_dispense,
    create_herb_item, create_formula, create_practitioner, create_patient,
    setup_finalized_intake, setup_active_plan, setup_dispense_scenario, get_plan_version,
    create_dispense_payload,
)

ADMIN = TEST_USERS["clinic_admin_headers"]
PHARM = TEST_USERS["pharmacist_headers"]


# ─── Fill -> inventory debit -> LOW_STOCK (queue A, depth 3) ───────────────
def test_dispense_fill_debits_inventory_and_flags_low_stock(api):
    """PRD 3.9: "The second hop, caused by the first, decreases each referenced herb
    item's on_hand_grams by its deducted grams and increments that herb item's version.
    The third hop, caused by the second, auto-transitions any herb item whose
    on_hand_grams has fallen to or below its reorder_threshold_grams from IN_STOCK to
    LOW_STOCK, incurring a further version bump on that herb item."
    PRD 3.9: "The stock_status is LOW_STOCK when on_hand_grams is at or below
    reorder_threshold_grams and IN_STOCK otherwise — the boundary is inclusive, so an
    on-hand quantity exactly equal to the threshold is LOW_STOCK."

    Design: Difficulty/transitive_cascade/dispense_fill_inventory_lowstock_depth3
    """
    ctx = setup_dispense_scenario(initial_grams=500, reorder_threshold_grams=400,
                                  grams_per_dose=120, doses=1)
    filled = validate_success(api.fill_dispense(ctx["dispense"]["id"], PHARM), 200)
    assert filled["status"] == "FILLED"

    herb = get_success_data(api.get_herb_item(ctx["herb"]["id"], PHARM))
    assert_herb_item(herb)
    assert herb["on_hand_grams"] == 380  # 500 - 120
    assert herb["stock_status"] == "LOW_STOCK"  # 380 <= 400


def test_dispense_fill_moves_status_to_filled(api):
    """PRD 3.9: "The dispense itself moves from REQUESTED to FILLED and its version is
    incremented."

    Design: Difficulty/transitive_cascade/dispense_fill_inventory_lowstock_depth3
    """
    ctx = setup_dispense_scenario(initial_grams=1000, reorder_threshold_grams=50,
                                  grams_per_dose=100, doses=1)
    before_v = ctx["dispense"]["version"]
    filled = validate_success(api.fill_dispense(ctx["dispense"]["id"], PHARM), 200)
    assert filled["status"] == "FILLED"
    assert filled["version"] == before_v + 1


# ─── Inventory mass conserved across fill + reverse (queue A) ──────────────
def test_inventory_mass_conserved_fill_then_reverse(api):
    """PRD 3.9: "Reversal restores each referenced herb item's on_hand_grams by exactly
    the grams recorded for it in total_grams_by_herb, increments that herb item's version,
    and auto-transitions any herb item whose on_hand_grams thereby rises above its
    reorder_threshold_grams from LOW_STOCK back to IN_STOCK."
    PRD 3.9: "The dispense moves to the terminal REVERSED state and its version is
    incremented; across a fill and its reversal the total inventory mass is exactly
    conserved."

    Design: Difficulty/compensating_invariant/inventory_mass_conserved_fill_then_reverse
    """
    ctx = setup_dispense_scenario(initial_grams=500, reorder_threshold_grams=400,
                                  grams_per_dose=120, doses=1)
    filled = validate_success(api.fill_dispense(ctx["dispense"]["id"], PHARM), 200)
    herb_after_fill = get_success_data(api.get_herb_item(ctx["herb"]["id"], PHARM))
    assert herb_after_fill["on_hand_grams"] == 380
    assert herb_after_fill["stock_status"] == "LOW_STOCK"

    reversed_d = validate_success(
        api.reverse_dispense(ctx["dispense"]["id"],
                             {"expected_formula_dispense_version": filled["version"]}, PHARM), 200)
    assert reversed_d["status"] == "REVERSED"

    herb_after_reverse = get_success_data(api.get_herb_item(ctx["herb"]["id"], PHARM))
    assert herb_after_reverse["on_hand_grams"] == 500  # back to initial_grams, zero drift
    assert herb_after_reverse["stock_status"] == "IN_STOCK"


def test_reverse_returns_dispense_to_reversed_terminal(api):
    """PRD 3.9: "The dispense moves to the terminal REVERSED state and its version is
    incremented; across a fill and its reversal the total inventory mass is exactly
    conserved."

    Design: Difficulty/compensating_invariant/inventory_mass_conserved_fill_then_reverse
    """
    ctx = setup_dispense_scenario(initial_grams=500, reorder_threshold_grams=50,
                                  grams_per_dose=100, doses=1)
    filled = validate_success(api.fill_dispense(ctx["dispense"]["id"], PHARM), 200)
    reversed_d = validate_success(
        api.reverse_dispense(ctx["dispense"]["id"],
                             {"expected_formula_dispense_version": filled["version"]}, PHARM), 200)
    assert_dispense(reversed_d)
    assert reversed_d["status"] == "REVERSED"


# ─── Safety-beats-referential priority pair (queue A) ──────────────────────
def test_fill_checks_plan_active_before_stock(api):
    """PRD 3.9: "Filling requires the dispense status to be REQUESTED (otherwise
    ERR_DISPENSE_NOT_REQUESTED), requires the governing plan to be ACTIVE (otherwise
    ERR_PLAN_NOT_ACTIVE), and requires that for every recipe line the referenced herb
    item's on_hand_grams be at least grams_per_dose times doses (otherwise
    ERR_INSUFFICIENT_STOCK); this stock safety check precedes any financial bookkeeping."

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_referential_on_dispense_fill
    """
    # Herb 100g, recipe needs 120g (stock would fail), but plan is put ON_HOLD after
    # the dispense is requested. The fill must report the plan-active failure, not stock.
    herb = create_herb_item(herb_name="Dang Gui", initial_grams=100, reorder_threshold_grams=50)
    formula = create_formula(herb["id"], grams_per_dose=120)
    prac = create_practitioner()
    patient = create_patient(full_name="SR Pat")
    intake = setup_finalized_intake(patient["id"], prac["id"],
                                    tongue_finding="PALE", pulse_finding="DEEP",
                                    tcm_pattern="YANG_DEFICIENCY")
    plan = setup_active_plan(patient["id"], prac["id"], intake["id"], acupoints=["CV4"])
    plv = get_plan_version(plan["id"])
    dispense = get_success_data(api.create_dispense(
        create_dispense_payload(patient["id"], plan["id"], formula["id"], plv, doses=1), PHARM))
    # Put the plan ON_HOLD.
    get_success_data(api.hold_plan(plan["id"], make_practitioner_headers(prac["id"])))

    validate_error(api.fill_dispense(dispense["id"], PHARM),
                   ApiErrorId.ERR_PLAN_NOT_ACTIVE.value)
    # No inventory debit on rejection.
    herb_after = get_success_data(api.get_herb_item(herb["id"], PHARM))
    assert herb_after["on_hand_grams"] == 100


def test_fill_reports_insufficient_stock_when_plan_active(api):
    """PRD 3.9: "Filling requires the dispense status to be REQUESTED (otherwise
    ERR_DISPENSE_NOT_REQUESTED), requires the governing plan to be ACTIVE (otherwise
    ERR_PLAN_NOT_ACTIVE), and requires that for every recipe line the referenced herb
    item's on_hand_grams be at least grams_per_dose times doses (otherwise
    ERR_INSUFFICIENT_STOCK); this stock safety check precedes any financial bookkeeping."

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_referential_on_dispense_fill
    """
    # Same stock shortfall, but the plan stays ACTIVE — so the safety check (stock) is the
    # one that fires, isolating it from the referential (plan-active) check.
    ctx = setup_dispense_scenario(initial_grams=100, reorder_threshold_grams=50,
                                  grams_per_dose=120, doses=1)
    validate_error(api.fill_dispense(ctx["dispense"]["id"], PHARM),
                   ApiErrorId.ERR_INSUFFICIENT_STOCK.value)
    herb_after = get_success_data(api.get_herb_item(ctx["herb"]["id"], PHARM))
    assert herb_after["on_hand_grams"] == 100


# ─── Dispense create requires plan ACTIVE (queue A cross-entity) ───────────
def test_dispense_create_requires_plan_active(api):
    """PRD 3.9: "A Pharmacist or a Practitioner requests a dispense against an ACTIVE
    plan by supplying the patient_id, the treatment_plan_id, the herbal_formula_id, the
    number of doses (at least 1), and expected_treatment_plan_version for the OCC check;
    the referenced plan must be ACTIVE (otherwise ERR_PLAN_NOT_ACTIVE) and the plan's
    version must match the supplied expected value (otherwise ERR_STALE_VERSION)."

    Design: Difficulty/cross_entity_state_dependency/dispense_requires_plan_active
    """
    herb = create_herb_item(herb_name="Gan Cao", initial_grams=500, reorder_threshold_grams=50)
    formula = create_formula(herb["id"], grams_per_dose=10)
    prac = create_practitioner()
    patient = create_patient(full_name="Hold Pat")
    intake = setup_finalized_intake(patient["id"], prac["id"],
                                    tongue_finding="PALE", pulse_finding="DEEP",
                                    tcm_pattern="YANG_DEFICIENCY")
    plan = setup_active_plan(patient["id"], prac["id"], intake["id"], acupoints=["CV4"])
    held = get_success_data(api.hold_plan(plan["id"], make_practitioner_headers(prac["id"])))
    assert held["status"] == "ON_HOLD"

    validate_error(api.create_dispense(
        create_dispense_payload(patient["id"], plan["id"], formula["id"],
                                held["version"], doses=1), PHARM),
        ApiErrorId.ERR_PLAN_NOT_ACTIVE.value)


def test_dispense_create_succeeds_on_active_plan(api):
    """PRD 3.9: "A Pharmacist or a Practitioner requests a dispense against an ACTIVE
    plan by supplying the patient_id, the treatment_plan_id, the herbal_formula_id, the
    number of doses (at least 1), and expected_treatment_plan_version for the OCC check;
    the referenced plan must be ACTIVE (otherwise ERR_PLAN_NOT_ACTIVE) and the plan's
    version must match the supplied expected value (otherwise ERR_STALE_VERSION)."
    PRD 3.3: "While a plan is ON_HOLD no appointments and no dispenses may be created
    against it."

    Design: Difficulty/cross_entity_state_dependency/dispense_requires_plan_active
    """
    # Same setup but the plan stays ACTIVE: the dispense create succeeds, confirming the
    # ON_HOLD rejection above is driven by plan status, not some other failure.
    ctx = setup_dispense_scenario(initial_grams=500, reorder_threshold_grams=50,
                                  grams_per_dose=10, doses=1)
    assert ctx["plan"]["status"] == "ACTIVE"
    assert ctx["dispense"]["status"] == "REQUESTED"


# ─── Insufficient-stock boundary (corner) ──────────────────────────────────
def test_insufficient_stock_one_gram_short_rejected(api):
    """PRD 3.9: "Filling requires the dispense status to be REQUESTED (otherwise
    ERR_DISPENSE_NOT_REQUESTED), requires the governing plan to be ACTIVE (otherwise
    ERR_PLAN_NOT_ACTIVE), and requires that for every recipe line the referenced herb
    item's on_hand_grams be at least grams_per_dose times doses (otherwise
    ERR_INSUFFICIENT_STOCK); this stock safety check precedes any financial bookkeeping."

    Design: Corner/calculations/insufficient_stock_boundary_one_gram_short
    """
    ctx = setup_dispense_scenario(initial_grams=120, reorder_threshold_grams=50,
                                  grams_per_dose=121, doses=1)
    validate_error(api.fill_dispense(ctx["dispense"]["id"], PHARM),
                   ApiErrorId.ERR_INSUFFICIENT_STOCK.value)
    herb_after = get_success_data(api.get_herb_item(ctx["herb"]["id"], PHARM))
    assert herb_after["on_hand_grams"] == 120  # unchanged


# ─── Reverse a REQUESTED (never-filled) dispense (corner) ──────────────────
def test_reverse_requested_dispense_rejected_not_filled(api):
    """PRD 3.9: "A Pharmacist reverses a dispense whose status is FILLED (otherwise
    ERR_DISPENSE_NOT_FILLED), and because reversal is OCC-guarded the request must carry
    expected_formula_dispense_version matching the dispense's current version (otherwise
    ERR_STALE_VERSION)."

    Design: Corner/state_machines/reverse_requested_dispense_rejected_not_filled
    """
    ctx = setup_dispense_scenario(initial_grams=300, reorder_threshold_grams=50,
                                  grams_per_dose=10, doses=1)
    dispense = ctx["dispense"]  # still REQUESTED
    validate_error(api.reverse_dispense(
        dispense["id"], {"expected_formula_dispense_version": dispense["version"]}, PHARM),
        ApiErrorId.ERR_DISPENSE_NOT_FILLED.value)
    herb_after = get_success_data(api.get_herb_item(ctx["herb"]["id"], PHARM))
    assert herb_after["on_hand_grams"] == 300  # unchanged
