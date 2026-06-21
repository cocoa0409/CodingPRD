"""Financial calculation tests: allowance waterfall, coinsurance/patient_due,
warranty settlement, return refunds, and the conserved-quantity invariants.

Each test builds its own state from scratch (the server DB is reset per test).
"""
from test_helpers import (
    validate_success,
    api_client,
    TEST_USERS,
    fixtures,
    factories,
    assert_warranty_split_conserved,
    assert_net_charge_equals_restock,
)

ADMIN = TEST_USERS["clinic_admin_headers"]
AUD = TEST_USERS["audiologist_headers"]
CLERK = TEST_USERS["billing_clerk_headers"]


# ==========================================================================
# Allowance waterfall: cap-binds vs pool-binds (dual variant + combinatorial)
# ==========================================================================

def test_waterfall_cap_binds_first_on_fresh_pool(api):
    """PRD §3.4: "the system first computes the per-device-eligible amount as the
    smaller of the order's gross price and the pool's per_device_cap_cents; it
    then computes the pool's remaining headroom as the pool's total_allowance_cents
    minus its current consumed_allowance_cents, floored at 0 so it never goes
    negative; and finally sets allowance_applied_cents to the smaller of the
    per-device-eligible amount and the remaining headroom."
    PRD §3.4: "In the case where the gross exceeds the per-device cap and the pool
    still has more headroom than the cap, the applied amount equals the per-device
    cap (the cap binds first)"

    Design: Difficulty/dual_variant_calc/benefit_waterfall_cap_binds_vs_pool_binds
    """
    ctx = fixtures.setup_order_in_trial(
        ptag=60,
        model_overrides={"list_price_cents": 300_000, "min_severity": "MODERATE",
                         "restock_fee_cents": 20_000, "warranty_months": 24,
                         "firmware_version": "4.2.0"},
        use_benefit=True,
        benefit_overrides={"total_allowance_cents": 500_000, "per_device_cap_cents": 250_000,
                           "coinsurance_pct": 0.20, "period_end": "2026-12-31"},
        order_overrides={"ear_count": 2},
    )
    data = validate_success(api.purchase_order(ctx["order"]["id"], CLERK))
    assert data["gross_price_cents"] == 600_000
    assert data["allowance_applied_cents"] == 250_000
    # post-allowance = 350000, coins = round_half_up(350000*0.20) = 70000, due = 420000
    assert data["patient_due_cents"] == 420_000


def _build_pool_depleted_to_400000(api):
    """Helper: patient with an ACTIVE benefit (total 500000, cap 250000, coins 0.20)
    whose consumed_allowance_cents has been driven to 400000 by two prior PURCHASED
    orders, leaving a binaural TRIAL order on a 300000 model ready to purchase.

    Drives consumption deterministically:
      - prior A on 400000 model (ear 1): applied min(min(400000,250000),500000-0)=250000.
      - prior B on 150000 model (ear 1): applied min(min(150000,250000),500000-250000)=150000.
      total consumed = 400000.
    Returns the final order's id.
    """
    fixtures.set_clock(fixtures.CLOCK_BASE)
    patient = fixtures.create_patient(date_of_birth="1958-02-02")
    model150 = fixtures.create_device_model(
        list_price_cents=150_000, min_severity="MODERATE", restock_fee_cents=20_000,
        firmware_version="4.2.0", warranty_months=24)
    model300 = fixtures.create_device_model(
        list_price_cents=300_000, min_severity="MODERATE", restock_fee_cents=20_000,
        firmware_version="4.2.0", warranty_months=24)
    model400 = fixtures.create_device_model(
        list_price_cents=400_000, min_severity="MODERATE", restock_fee_cents=20_000,
        firmware_version="4.2.0", warranty_months=24)
    benefit = fixtures.create_allowance_benefit(
        patient["id"], total_allowance_cents=500_000, per_device_cap_cents=250_000,
        coinsurance_pct=0.20, period_end="2026-12-31")
    evaluation = fixtures.create_finalized_evaluation(patient["id"], pure_tone_avg_db=60)
    p_a = fixtures.create_draft_order(patient["id"], evaluation["id"], model400["id"],
                                      ear_count=1, allowance_benefit_id=benefit["id"])
    validate_success(api.start_trial(p_a["id"], AUD))
    pa_data = validate_success(api.purchase_order(p_a["id"], CLERK), 200)
    assert pa_data["allowance_applied_cents"] == 250_000
    p_b = fixtures.create_draft_order(patient["id"], evaluation["id"], model150["id"],
                                      ear_count=1, allowance_benefit_id=benefit["id"])
    validate_success(api.start_trial(p_b["id"], AUD))
    pb_data = validate_success(api.purchase_order(p_b["id"], CLERK), 200)
    assert pb_data["allowance_applied_cents"] == 150_000  # consumed now 400000
    final = fixtures.create_draft_order(patient["id"], evaluation["id"], model300["id"],
                                        ear_count=2, allowance_benefit_id=benefit["id"])
    validate_success(api.start_trial(final["id"], AUD))
    return final["id"]


def test_waterfall_pool_binds_first_on_depleted_pool(api):
    """PRD §3.4: "and finally sets allowance_applied_cents to the smaller of the
    per-device-eligible amount and the remaining headroom."
    PRD §3.4: "in the case where the remaining headroom is smaller than the
    per-device-eligible amount, the applied amount equals the remaining headroom
    (the pool is exhausted before the cap)."

    Design: Difficulty/dual_variant_calc/benefit_waterfall_cap_binds_vs_pool_binds
    """
    final_order_id = _build_pool_depleted_to_400000(api)
    data = validate_success(api.purchase_order(final_order_id, CLERK))
    # gross 600000, cap-eligible 250000, headroom 500000-400000=100000 -> applied 100000.
    assert data["gross_price_cents"] == 600_000
    assert data["allowance_applied_cents"] == 100_000


def test_waterfall_mode_a_nested_min_pool_binds(api):
    """PRD §3.4: "it then computes the pool's remaining headroom as the pool's
    total_allowance_cents minus its current consumed_allowance_cents, floored at 0
    so it never goes negative; and finally sets allowance_applied_cents to the
    smaller of the per-device-eligible amount and the remaining headroom."

    Design: Difficulty/combinatorial_formula/benefit_waterfall_mode_a_nested_min
    """
    final_order_id = _build_pool_depleted_to_400000(api)
    data = validate_success(api.purchase_order(final_order_id, CLERK))
    # Nested min: min(min(600000, 250000), 500000-400000) = min(250000, 100000) = 100000.
    assert data["gross_price_cents"] == 600_000
    assert data["allowance_applied_cents"] == 100_000


def test_patient_due_single_rounding_on_post_allowance_remainder(api):
    """PRD §3.4: "The coinsurance amount is that remainder multiplied by the pool's
    coinsurance_pct, rounded half up to whole cents in a single rounding step; for
    a self-pay order the coinsurance fraction is treated as 0. The patient_due_cents
    is the post-allowance remainder plus the coinsurance amount."

    Design: Difficulty/combinatorial_formula/patient_due_mode_b_single_rounding_on_post_allowance
    """
    ctx = fixtures.setup_order_in_trial(
        ptag=35,
        model_overrides={"list_price_cents": 200_000, "min_severity": "MILD",
                         "restock_fee_cents": 10_000, "firmware_version": "2.0.0",
                         "warranty_months": 24},
        use_benefit=True,
        benefit_overrides={"total_allowance_cents": 500_000, "per_device_cap_cents": 166_667,
                           "coinsurance_pct": 0.15, "period_end": "2026-12-31"},
        order_overrides={"ear_count": 1},
    )
    data = validate_success(api.purchase_order(ctx["order"]["id"], CLERK))
    # gross 200000, applied min(min(200000,166667),500000)=166667, post=33333,
    # coins=round_half_up(33333*0.15)=round_half_up(4999.95)=5000, due=38333.
    assert data["allowance_applied_cents"] == 166_667
    assert data["patient_due_cents"] == 38_333


def test_self_pay_purchase_due_equals_gross(api):
    """PRD §3.4: "For a self-pay order this reduces to patient_due_cents equal to
    gross_price_cents, since the allowance is 0 and the coinsurance is 0."

    Design: Corner/calculations/self_pay_purchase_due_equals_gross
    """
    ctx = fixtures.setup_order_in_trial(
        ptag=50,
        model_overrides={"list_price_cents": 200_000, "min_severity": "MILD",
                         "restock_fee_cents": 10_000, "warranty_months": 24},
        order_overrides={"ear_count": 2},
    )
    data = validate_success(api.purchase_order(ctx["order"]["id"], CLERK))
    assert data["gross_price_cents"] == 400_000
    assert data["allowance_applied_cents"] == 0
    assert data["patient_due_cents"] == 400_000


# ==========================================================================
# Warranty settlement: DEFECT / DAMAGE / LOSS splits + cap + conservation
# ==========================================================================

def test_warranty_settlement_defect_vs_loss_split(api):
    """PRD §3.8: "For a DEFECT, the patient's deductible is 0 and the clinic absorbs
    the full assessed value as clinic_cost_cents."
    PRD §3.8: "For a LOSS, the deductible is the assessed value multiplied by 50
    percent, rounded half up to whole cents and then capped at the same 40000 cents,
    with clinic_cost_cents again equal to the assessed value minus the deductible."

    Design: Difficulty/dual_variant_calc/warranty_settlement_defect_vs_loss
    """
    ctx = fixtures.setup_order_warranty_active(
        ptag=45, model_overrides={"list_price_cents": 200_000, "min_severity": "MILD",
                                  "restock_fee_cents": 15_000, "warranty_months": 24})
    order_id = ctx["order"]["id"]
    defect = validate_success(api.create_warranty_claim(
        order_id, factories.create_warranty_claim_payload(
            claim_type="DEFECT", assessed_value_cents=150_000, incident_date="2026-04-15"), CLERK), 201)
    loss = validate_success(api.create_warranty_claim(
        order_id, factories.create_warranty_claim_payload(
            claim_type="LOSS", assessed_value_cents=100_000, incident_date="2026-04-20"), CLERK), 201)
    defect_approved = validate_success(api.approve_warranty_claim(defect["id"], CLERK))
    loss_approved = validate_success(api.approve_warranty_claim(loss["id"], CLERK))
    assert defect_approved["deductible_cents"] == 0
    assert defect_approved["clinic_cost_cents"] == 150_000
    # LOSS: 100000*0.50 = 50000, capped at 40000 -> deductible 40000, clinic 60000.
    assert loss_approved["deductible_cents"] == 40_000
    assert loss_approved["clinic_cost_cents"] == 60_000


def test_damage_deductible_cap_applies_after_rounding(api):
    """PRD §3.8: "For a DAMAGE, the deductible is the assessed value multiplied by
    25 percent, rounded half up to whole cents and then capped at 40000 cents (the
    cap is applied after rounding), with clinic_cost_cents equal to the assessed
    value minus that deductible."

    Design: Corner/calculations/damage_deductible_cap_applies_after_rounding
    """
    ctx = fixtures.setup_order_warranty_active(
        ptag=50, model_overrides={"list_price_cents": 300_000, "min_severity": "MILD",
                                  "restock_fee_cents": 15_000, "warranty_months": 24})
    claim = validate_success(api.create_warranty_claim(
        ctx["order"]["id"], factories.create_warranty_claim_payload(
            claim_type="DAMAGE", assessed_value_cents=200_000, incident_date="2026-04-15"), CLERK), 201)
    approved = validate_success(api.approve_warranty_claim(claim["id"], CLERK))
    # 200000*0.25 = 50000 > cap 40000 -> deductible 40000, clinic 160000.
    assert approved["deductible_cents"] == 40_000
    assert approved["clinic_cost_cents"] == 160_000


def test_warranty_settlement_conserves_assessed_value_split(api):
    """PRD §2.10: "a warranty settlement always splits the assessed value exactly
    into the patient's deductible and the clinic's absorbed cost, with no remainder:
    the deductible plus the clinic cost equals the assessed value."
    PRD §3.8: "For a DAMAGE, the deductible is the assessed value multiplied by 25
    percent, rounded half up to whole cents and then capped at 40000 cents (the cap
    is applied after rounding), with clinic_cost_cents equal to the assessed value
    minus that deductible."

    Design: Difficulty/compensating_invariant/warranty_settlement_conserves_assessed_value_split
    """
    ctx = fixtures.setup_order_warranty_active(
        ptag=50, model_overrides={"list_price_cents": 250_000, "min_severity": "MILD",
                                  "restock_fee_cents": 15_000, "warranty_months": 24})
    claim = validate_success(api.create_warranty_claim(
        ctx["order"]["id"], factories.create_warranty_claim_payload(
            claim_type="DAMAGE", assessed_value_cents=120_000, incident_date="2026-04-15"), CLERK), 201)
    approved = validate_success(api.approve_warranty_claim(claim["id"], CLERK))
    # 120000*0.25 = 30000 (< cap) -> deductible 30000, clinic 90000.
    assert approved["deductible_cents"] == 30_000
    assert approved["clinic_cost_cents"] == 90_000
    assert_warranty_split_conserved(approved)


# ==========================================================================
# Return refunds + conserved net-charge invariant
# ==========================================================================

def test_trial_return_no_purchase_charges_restock_only(api):
    """PRD §3.5: "When the order is returned out of TRIAL — that is, it was never
    purchased and the patient has paid nothing yet — refund_cents is set to the
    negative of the device model's restock_fee_cents; the negative refund expresses
    that the patient still owes the restocking fee even though no purchase occurred,
    and because no allowance was ever consumed none is released."

    Design: Corner/calculations/trial_return_no_purchase_charges_restock_only
    """
    ctx = fixtures.setup_order_in_trial(
        ptag=50, model_overrides={"list_price_cents": 200_000, "min_severity": "MILD",
                                  "restock_fee_cents": 10_000, "warranty_months": 24})
    data = validate_success(api.return_order(ctx["order"]["id"], CLERK))
    assert data["status"] == "RETURNED"
    assert data["refund_cents"] == -10_000


def test_purchased_return_conserves_net_charge_to_restock(api):
    """PRD §3.5: "When the order is returned out of PURCHASED within the open window,
    refund_cents is set to patient_due_cents minus the device model's
    restock_fee_cents; this is exactly the amount that leaves the patient's net
    charge for the order equal to the restocking fee"
    PRD §2.10: "a purchased order returned within its trial window must leave the
    patient's net charge for that order equal exactly to the device model's
    restocking fee"

    Design: Difficulty/compensating_invariant/purchase_then_return_conserves_net_patient_charge_to_restock
    """
    ctx = fixtures.setup_order_purchased(
        ptag=50, model_overrides={"list_price_cents": 300_000, "min_severity": "MILD",
                                  "restock_fee_cents": 15_000, "warranty_months": 24})
    purchased = ctx["order"]
    assert purchased["patient_due_cents"] == 300_000
    data = validate_success(api.return_order(purchased["id"], CLERK))
    assert data["status"] == "RETURNED"
    # refund = patient_due (300000) - restock (15000) = 285000.
    assert data["refund_cents"] == 285_000
    assert data["patient_due_cents"] == 300_000
    assert_net_charge_equals_restock(data, 15_000)


def test_fitting_order_trial_branch_purchase_vs_return(api):
    """PRD §3.4: "Converting a trial into a sale is a BillingClerk operation that
    advances the order TRIAL → PURCHASED"
    PRD §3.5: "When the order is returned out of TRIAL — that is, it was never
    purchased and the patient has paid nothing yet — refund_cents is set to the
    negative of the device model's restock_fee_cents"

    Design: Difficulty/non_linear_state_machine/fitting_order_trial_branch_purchase_vs_return
    """
    fixtures.set_clock(fixtures.CLOCK_BASE)
    patient = fixtures.create_patient(date_of_birth="1957-07-07")
    model = fixtures.create_device_model(
        list_price_cents=300_000, min_severity="MILD", restock_fee_cents=15_000,
        firmware_version="1.0.0", warranty_months=24)
    evaluation = fixtures.create_finalized_evaluation(patient["id"], pure_tone_avg_db=50)
    buy = fixtures.create_draft_order(patient["id"], evaluation["id"], model["id"], ear_count=1)
    validate_success(api.start_trial(buy["id"], AUD))
    ret = fixtures.create_draft_order(patient["id"], evaluation["id"], model["id"], ear_count=1)
    validate_success(api.start_trial(ret["id"], AUD))
    buy_data = validate_success(api.purchase_order(buy["id"], CLERK))
    ret_data = validate_success(api.return_order(ret["id"], CLERK))
    assert buy_data["status"] == "PURCHASED"
    assert buy_data["patient_due_cents"] == 300_000
    assert ret_data["status"] == "RETURNED"
    assert ret_data["refund_cents"] == -15_000


# ==========================================================================
# Second-coverage tests (each Difficulty instance needs >= 2 tests)
# ==========================================================================

def test_waterfall_mode_a_nested_min_cap_binds_branch(api):
    """PRD §3.4: "the system first computes the per-device-eligible amount as the
    smaller of the order's gross price and the pool's per_device_cap_cents"
    PRD §3.4: "In the case where the gross exceeds the per-device cap and the pool
    still has more headroom than the cap, the applied amount equals the per-device
    cap (the cap binds first)"

    Design: Difficulty/combinatorial_formula/benefit_waterfall_mode_a_nested_min
    """
    ctx = fixtures.setup_order_in_trial(
        ptag=60,
        model_overrides={"list_price_cents": 300_000, "min_severity": "MODERATE",
                         "restock_fee_cents": 20_000, "warranty_months": 24},
        use_benefit=True,
        benefit_overrides={"total_allowance_cents": 500_000, "per_device_cap_cents": 250_000,
                           "coinsurance_pct": 0.20, "period_end": "2026-12-31"},
        order_overrides={"ear_count": 2},
    )
    data = validate_success(api.purchase_order(ctx["order"]["id"], CLERK))
    # Nested min on fresh pool: min(min(600000, 250000), 500000-0) = 250000.
    assert data["gross_price_cents"] == 600_000
    assert data["allowance_applied_cents"] == 250_000


def test_patient_due_self_pay_no_coinsurance_rounding(api):
    """PRD §3.4: "for a self-pay order the coinsurance fraction is treated as 0. The
    patient_due_cents is the post-allowance remainder plus the coinsurance amount."
    PRD §3.4: "For a self-pay order this reduces to patient_due_cents equal to
    gross_price_cents, since the allowance is 0 and the coinsurance is 0."

    Design: Difficulty/combinatorial_formula/patient_due_mode_b_single_rounding_on_post_allowance
    """
    ctx = fixtures.setup_order_in_trial(
        ptag=35,
        model_overrides={"list_price_cents": 200_000, "min_severity": "MILD",
                         "restock_fee_cents": 10_000, "warranty_months": 24},
        order_overrides={"ear_count": 1},
    )
    data = validate_success(api.purchase_order(ctx["order"]["id"], CLERK))
    # self-pay: allowance 0, post=200000, coins 0, due=200000.
    assert data["allowance_applied_cents"] == 0
    assert data["patient_due_cents"] == 200_000


def test_warranty_settlement_defect_zero_deductible(api):
    """PRD §3.8: "For a DEFECT, the patient's deductible is 0 and the clinic absorbs
    the full assessed value as clinic_cost_cents."

    Design: Difficulty/dual_variant_calc/warranty_settlement_defect_vs_loss
    """
    ctx, claim = fixtures.setup_submitted_claim(
        claim_type="DEFECT", assessed_value_cents=80_000)
    approved = validate_success(api.approve_warranty_claim(claim["id"], CLERK))
    assert approved["deductible_cents"] == 0
    assert approved["clinic_cost_cents"] == 80_000


def test_warranty_settlement_loss_conserves_split(api):
    """PRD §2.10: "a warranty settlement always splits the assessed value exactly
    into the patient's deductible and the clinic's absorbed cost, with no remainder:
    the deductible plus the clinic cost equals the assessed value."
    PRD §3.8: "For a LOSS, the deductible is the assessed value multiplied by 50
    percent, rounded half up to whole cents and then capped at the same 40000 cents,
    with clinic_cost_cents again equal to the assessed value minus the deductible."

    Design: Difficulty/compensating_invariant/warranty_settlement_conserves_assessed_value_split
    """
    # assessed 60000, LOSS: 60000*0.50 = 30000 (< cap) -> deductible 30000, clinic 30000.
    ctx, claim = fixtures.setup_submitted_claim(
        claim_type="LOSS", assessed_value_cents=60_000)
    approved = validate_success(api.approve_warranty_claim(claim["id"], CLERK))
    assert approved["deductible_cents"] == 30_000
    assert approved["clinic_cost_cents"] == 30_000
    assert_warranty_split_conserved(approved)


def test_trial_return_branch_conserves_restock_charge(api):
    """PRD §3.5: "When the order is returned out of TRIAL — that is, it was never
    purchased and the patient has paid nothing yet — refund_cents is set to the
    negative of the device model's restock_fee_cents"

    Design: Difficulty/non_linear_state_machine/fitting_order_trial_branch_purchase_vs_return
    """
    ctx = fixtures.setup_order_in_trial(
        ptag=50, model_overrides={"list_price_cents": 250_000, "min_severity": "MILD",
                                  "restock_fee_cents": 12_000, "warranty_months": 24})
    data = validate_success(api.return_order(ctx["order"]["id"], CLERK))
    assert data["status"] == "RETURNED"
    assert data["refund_cents"] == -12_000


def test_purchased_return_refund_value_in_window(api):
    """PRD §3.5: "When the order is returned out of PURCHASED within the open window,
    refund_cents is set to patient_due_cents minus the device model's
    restock_fee_cents"

    Design: Difficulty/compensating_invariant/purchase_then_return_conserves_net_patient_charge_to_restock
    """
    ctx = fixtures.setup_order_purchased(
        ptag=50, model_overrides={"list_price_cents": 200_000, "min_severity": "MILD",
                                  "restock_fee_cents": 8_000, "warranty_months": 24})
    data = validate_success(api.return_order(ctx["order"]["id"], CLERK))
    # patient_due 200000 - restock 8000 = 192000.
    assert data["refund_cents"] == 192_000
    assert_net_charge_equals_restock(data, 8_000)
