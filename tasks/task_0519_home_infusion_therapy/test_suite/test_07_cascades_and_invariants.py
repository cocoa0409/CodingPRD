"""Cascades and conserved-quantity invariants: discontinuation chains, auth-denied
chains, vial conservation, payer-accumulator post/void symmetry, and the future-visit
miss cascade.

Translates Queue A (Difficulty) rules: transitive_cascade, compensating_invariant; and
Queue B (Corner) sections: consistency_model, cross_cutting_complexity_layers.
"""
from test_helpers import (
    validate_success,
    TEST_USERS,
    make_visiting_nurse_headers,
    fixtures,
    factories as F,
    assert_inventory_conserved,
)

PHARM = TEST_USERS["pharmacist_headers"]
AUTH = TEST_USERS["auth_specialist_headers"]
MD = TEST_USERS["medical_director_headers"]
WAREHOUSE = TEST_USERS["warehouse_clerk_headers"]
BILLER = TEST_USERS["biller_headers"]

VANCO_NONSPEC = {
    "therapy_category": "AMINOGLYCOSIDE_OR_VANCO",
    "vial_size_mg": 1000,
    "awp_per_vial_cents": 4250,
    "is_specialty": False,
    "lot_total_vials": 100,
}
PA_PLAN = {
    "per_diem_rate_cents": {"AMINOGLYCOSIDE_OR_VANCO": 12500},
    "awp_discount_pct": 0.18,
    "coinsurance_pct": 0.20,
    "deductible_remaining_cents": 30000,
    "oop_max_remaining_cents": 50000,
}


# === transitive_cascade / discontinue_cascade_order_to_visits_to_compounds_to_inventory ===
def test_discontinue_cascade_wastes_compound_and_returns_vials(api):
    """PRD 3.11: "Every compound for that order in `ORDERED` or `COMPOUNDED` is moved to `WASTED`; and for each compound that was `COMPOUNDED` — meaning its vials had been reserved — the `vials_reserved` are returned to the drug's `on_hand_vials`, restoring the inventory conservation equality."

    Design: Difficulty/transitive_cascade/discontinue_cascade_order_to_visits_to_compounds_to_inventory
    """
    # COMPOUNDED compound reserving 14 vials (on_hand 86); one future SCHEDULED visit.
    ctx = fixtures.setup_compounded_order(
        daily_dose_mg=2000, scheduled_days=7, lot_total_vials=100,
        drug_overrides={**VANCO_NONSPEC}, plan_overrides=PA_PLAN, activate=True,
    )
    nurse = ctx["nurse"]
    future_visit = fixtures.schedule_visit(
        ctx["order"]["id"], nurse["id"], start_at="2026-06-20T10:00:00Z", duration_min=120
    )
    drug_before = validate_success(api.get_drug(ctx["drug"]["id"], PHARM))
    assert drug_before["on_hand_vials"] == 86
    assert ctx["compound"]["status"] == "COMPOUNDED"

    validate_success(api.discontinue_order(ctx["order"]["id"], MD))

    order = validate_success(api.get_order(ctx["order"]["id"], PHARM))
    assert order["status"] == "DISCONTINUED"
    visit = validate_success(api.get_visit(future_visit["id"], make_visiting_nurse_headers(nurse["id"])))
    assert visit["status"] == "CANCELLED"
    compound = validate_success(api.get_compound(ctx["compound"]["id"], PHARM))
    assert compound["status"] == "WASTED"
    drug_after = validate_success(api.get_drug(ctx["drug"]["id"], PHARM))
    assert drug_after["on_hand_vials"] == 100, "14 vials credited back by the WASTED hop"


def test_discontinue_cascade_cancels_scheduled_visits(api):
    """PRD 3.11: "Every nursing visit still in `SCHEDULED` for that order is moved to `CANCELLED`."

    Design: Difficulty/transitive_cascade/discontinue_cascade_order_to_visits_to_compounds_to_inventory
    """
    ctx = fixtures.setup_compounded_order(
        daily_dose_mg=2000, scheduled_days=7, lot_total_vials=100,
        drug_overrides={**VANCO_NONSPEC}, plan_overrides=PA_PLAN, activate=True,
    )
    nurse = ctx["nurse"]
    v_future = fixtures.schedule_visit(
        ctx["order"]["id"], nurse["id"], start_at="2026-06-21T10:00:00Z", duration_min=120
    )
    validate_success(api.discontinue_order(ctx["order"]["id"], MD))
    visit = validate_success(api.get_visit(v_future["id"], make_visiting_nurse_headers(nurse["id"])))
    assert visit["status"] == "CANCELLED"


# === transitive_cascade / auth_deny_cascade_pa_to_order_to_kit ===
def test_auth_deny_cascade_discontinues_order(api):
    """PRD 3.3: "Denial moves `SUBMITTED` to `DENIED` and cascades in the opposite direction: the order is driven from `PENDING_AUTH` to `DISCONTINUED`"

    Design: Difficulty/transitive_cascade/auth_deny_cascade_pa_to_order_to_kit
    """
    ctx = fixtures.setup_pending_auth_order(
        drug_overrides={
            "therapy_category": "IMMUNE_GLOBULIN", "vial_size_mg": 5000,
            "awp_per_vial_cents": 90000, "is_specialty": True, "lot_total_vials": 50,
        },
        plan_overrides={
            "per_diem_rate_cents": {"IMMUNE_GLOBULIN": 30000},
            "awp_discount_pct": 0.10, "coinsurance_pct": 0.20,
            "deductible_remaining_cents": 10000, "oop_max_remaining_cents": 500000,
        },
        order_overrides={"daily_dose_mg": 10000, "scheduled_days": 3},
    )
    validate_success(api.deny_prior_auth(ctx["auth"]["id"], AUTH))
    order = validate_success(api.get_order(ctx["order"]["id"], PHARM))
    assert order["status"] == "DISCONTINUED"


def test_auth_deny_cascade_cancels_picking_kit(api):
    """PRD 3.3: "as part of that same cascade every supply kit for that order still in `PICKING` is moved to `CANCELLED`."

    Design: Difficulty/transitive_cascade/auth_deny_cascade_pa_to_order_to_kit
    """
    ctx = fixtures.setup_pending_auth_order(
        drug_overrides={
            "therapy_category": "IMMUNE_GLOBULIN", "vial_size_mg": 5000,
            "awp_per_vial_cents": 90000, "is_specialty": True, "lot_total_vials": 50,
        },
        plan_overrides={
            "per_diem_rate_cents": {"IMMUNE_GLOBULIN": 30000},
            "awp_discount_pct": 0.10, "coinsurance_pct": 0.20,
            "deductible_remaining_cents": 10000, "oop_max_remaining_cents": 500000,
        },
        order_overrides={"daily_dose_mg": 10000, "scheduled_days": 3},
    )
    kit = validate_success(
        api.create_supply_kit(
            F.create_supply_kit_payload(
                order_id=ctx["order"]["id"], kit_type="START_OF_CARE", line_count=4
            ),
            WAREHOUSE,
        ),
        expected_status=201,
    )
    validate_success(api.deny_prior_auth(ctx["auth"]["id"], AUTH))
    kit = validate_success(api.get_supply_kit(kit["id"], WAREHOUSE))
    assert kit["status"] == "CANCELLED"


# === compensating_invariant / inventory_conserved_on_compound_then_discontinue ===
def test_inventory_conserved_compound_then_discontinue(api):
    """PRD 2.9: "the sum of `on_hand_vials` (unreserved vials available to draw) plus the vials currently committed to live compounds (those reserved by compounds in `COMPOUNDED` or `DELIVERED` status) always equals `lot_total_vials`."

    Design: Difficulty/compensating_invariant/inventory_conserved_on_compound_then_discontinue
    """
    ctx = fixtures.setup_compounded_order(
        daily_dose_mg=2000, scheduled_days=7, lot_total_vials=100,
        drug_overrides={**VANCO_NONSPEC}, plan_overrides=PA_PLAN, activate=True,
    )
    drug_before = validate_success(api.get_drug(ctx["drug"]["id"], PHARM))
    compound_before = validate_success(api.get_compound(ctx["compound"]["id"], PHARM))
    assert drug_before["on_hand_vials"] == 86
    assert compound_before["vials_reserved"] == 14
    assert_inventory_conserved(drug_before, committed_vials=14)

    validate_success(api.discontinue_order(ctx["order"]["id"], MD))

    drug_after = validate_success(api.get_drug(ctx["drug"]["id"], PHARM))
    compound_after = validate_success(api.get_compound(ctx["compound"]["id"], PHARM))
    assert compound_after["status"] == "WASTED"
    assert drug_after["on_hand_vials"] == 100, "lot total 100 conserved after WASTED return"
    assert_inventory_conserved(drug_after, committed_vials=0)


def test_compound_draw_debits_on_hand_vials(api):
    """PRD 2.9: "Reserving vials for a compound debits `on_hand_vials`"
    PRD 3.4: "the server sets the compound's `vials_reserved` to that computed whole-vial count, debits the drug's `on_hand_vials` by the same amount"

    Design: Difficulty/compensating_invariant/inventory_conserved_on_compound_then_discontinue
    """
    ctx = fixtures.setup_compounded_order(
        daily_dose_mg=2000, scheduled_days=7, lot_total_vials=100,
        drug_overrides={**VANCO_NONSPEC}, plan_overrides=PA_PLAN, activate=False,
    )
    compound = validate_success(api.get_compound(ctx["compound"]["id"], PHARM))
    drug = validate_success(api.get_drug(ctx["drug"]["id"], PHARM))
    assert compound["vials_reserved"] == 14, "ceil(2000*7/1000)==14"
    assert drug["on_hand_vials"] == 86, "100 lot minus 14 reserved"
    assert_inventory_conserved(drug, committed_vials=14)


# === compensating_invariant / payer_accumulator_conserved_on_post_then_void ===
def test_post_then_void_restores_payer_accumulators(api):
    """PRD 2.10: "They move only when a claim is posted, and they move back, by exactly
    the same amounts, if that claim is later voided — so that a post followed by a void
    returns the plan to its pre-post accumulator values."

    Design: Difficulty/compensating_invariant/payer_accumulator_conserved_on_post_then_void
    """
    ctx = fixtures.setup_active_order_with_completed_visits(
        num_completed=1, scheduled_days=1,
        drug_overrides={**VANCO_NONSPEC}, plan_overrides=PA_PLAN,
        order_overrides={"daily_dose_mg": 2000},
    )
    claim = fixtures.create_estimate_claim(ctx["order"]["id"])
    posted = validate_success(api.post_claim(claim["id"], BILLER))
    assert posted["allowed_total_cents"] == 19470, f"got {posted['allowed_total_cents']}"
    plan_after_post = validate_success(api.get_payer_plan(ctx["plan"]["id"], BILLER))
    assert plan_after_post["deductible_remaining_cents"] == 10530, "30000 - 19470"
    assert plan_after_post["oop_max_remaining_cents"] == 30530, "50000 - 19470"

    voided = validate_success(api.void_claim(claim["id"], BILLER))
    assert voided["status"] == "VOID"
    plan_after_void = validate_success(api.get_payer_plan(ctx["plan"]["id"], BILLER))
    assert plan_after_void["deductible_remaining_cents"] == 30000, "deductible restored"
    assert plan_after_void["oop_max_remaining_cents"] == 50000, "OOP restored"


def test_post_claim_debits_accumulators(api):
    """PRD 3.12: "When the claim is posted under `FINAL`, the post additionally debits the plan: the `deductible_remaining_cents` is reduced by the deductible portion actually applied, and the `oop_max_remaining_cents` is reduced by the final `patient_responsibility_cents`."

    Design: Difficulty/compensating_invariant/payer_accumulator_conserved_on_post_then_void
    """
    ctx = fixtures.setup_active_order_with_completed_visits(
        num_completed=1, scheduled_days=1,
        drug_overrides={**VANCO_NONSPEC}, plan_overrides=PA_PLAN,
        order_overrides={"daily_dose_mg": 2000},
    )
    claim = fixtures.create_estimate_claim(ctx["order"]["id"])
    plan_before = validate_success(api.get_payer_plan(ctx["plan"]["id"], BILLER))
    assert plan_before["deductible_remaining_cents"] == 30000, "ESTIMATE did not debit"
    validate_success(api.post_claim(claim["id"], BILLER))
    plan_after = validate_success(api.get_payer_plan(ctx["plan"]["id"], BILLER))
    assert plan_after["deductible_remaining_cents"] == 10530
    assert plan_after["oop_max_remaining_cents"] == 30530


# === Queue B: cross_cutting_complexity_layers / ae_hold_misses_future_scheduled_visits_cascade ===
def test_ae_hold_misses_future_scheduled_visits(api):
    """PRD 3.9: "When the held order had been `ACTIVE`, the hold cascade also sweeps every `SCHEDULED` visit for that order whose `start_at` is in the future into `MISSED`."

    Design: Corner/cross_cutting_complexity_layers/ae_hold_misses_future_scheduled_visits_cascade
    """
    # clock at 2026-06-10T12:00Z; first visit completed (order ACTIVE), one future
    # SCHEDULED visit at 2026-06-15.
    ctx = fixtures.setup_released_nonspecialty_order(
        drug_overrides={**VANCO_NONSPEC}, plan_overrides=PA_PLAN,
        order_overrides={"daily_dose_mg": 2000, "scheduled_days": 5},
        clock="2026-06-10T12:00:00Z",
    )
    nurse = fixtures.add_nurse(ctx)
    nid = nurse["id"]
    v1 = fixtures.schedule_visit(
        ctx["order"]["id"], nid, start_at="2026-06-10T09:00:00Z", duration_min=120
    )
    fixtures.complete_visit(v1["id"], nid)
    v2 = fixtures.schedule_visit(
        ctx["order"]["id"], nid, start_at="2026-06-15T09:00:00Z", duration_min=120
    )
    ae = fixtures.report_adverse_event(
        ctx["order"]["id"], nurse_id=nid,
        severity_grade=3, reaction_count=2, vital_instability=1,
    )
    assert ae["severity_score"] == 11
    order = validate_success(api.get_order(ctx["order"]["id"], PHARM))
    assert order["status"] == "ON_HOLD"
    v2_now = validate_success(api.get_visit(v2["id"], make_visiting_nurse_headers(nid)))
    assert v2_now["status"] == "MISSED", "future SCHEDULED visit auto-missed by the hold cascade"


# === Queue B: consistency_model / discontinue_cascade_visible_in_same_request ===
def test_discontinue_cascade_immediately_visible(api):
    """PRD 1 (introduction): "a single discontinuation can ripple through visits, compounds, inventory, and billing in one atomic request"
    PRD 3.11: "In both cases discontinuation runs one atomic cascade."

    Design: Corner/consistency_model/discontinue_cascade_visible_in_same_request
    """
    ctx = fixtures.setup_compounded_order(
        daily_dose_mg=2000, scheduled_days=7, lot_total_vials=100,
        drug_overrides={**VANCO_NONSPEC}, plan_overrides=PA_PLAN, activate=True,
    )
    validate_success(api.discontinue_order(ctx["order"]["id"], MD))
    # immediate reads with no settling delay
    compound = validate_success(api.get_compound(ctx["compound"]["id"], PHARM))
    assert compound["status"] == "WASTED"
    drug = validate_success(api.get_drug(ctx["drug"]["id"], PHARM))
    assert drug["on_hand_vials"] == 100
