"""Second-angle coverage of the charge ledger difficulty instances: alternate inputs
that still isolate the same insurance/cash, tier, biologic, waterfall, and boundary rules."""
import pytest
from test_helpers import (
    validate_success,
    setup_provider_patient_encounter, setup_active_membership, setup_approved_pa_round,
    create_patient, create_provider, create_encounter, redeem_treatment,
    setup_cosmetic_encounter_with_membership,
    TEST_USERS,
)

BILLING = TEST_USERS["billing_specialist_headers"]


def test_insurance_charge_with_deductible_then_coinsurance_split(api):
    """PRD §3.7: "The patient's coinsurance portion is that remainder multiplied by the
    patient's `insurance_coinsurance_rate`, rounded half-up to whole cents. The
    `patient_responsibility_cents` is the deductible applied plus the coinsurance portion,
    and the `insurer_responsibility_cents` is the allowed amount minus the patient
    responsibility."

    Design: Difficulty/dual_variant_calc/charge_split_insurance_vs_cash_diverge
    """
    # allowed 10000, deductible 2000, coinsurance 0.2:
    # ded=2000, remainder=8000, coins=round(8000*0.2)=1600, patient=3600, insurer=6400
    _, patient, enc = setup_provider_patient_encounter(
        patient_overrides={"has_active_insurance": True,
                           "insurance_coinsurance_rate": 0.2,
                           "insurance_deductible_remaining_cents": 2000},
        encounter_overrides={"scheduled_at": "2026-03-02T09:00:00Z"},
    )
    ch = validate_success(api.create_charge({
        "patient_id": patient["id"], "encounter_id": enc["id"],
        "source_kind": "ENCOUNTER", "charge_kind": "OFFICE_VISIT",
        "billed_amount_cents": 10000, "insurer_allowed_cents": 10000,
    }, BILLING), 201)
    assert ch["deductible_applied_cents"] == 2000
    assert ch["patient_responsibility_cents"] == 3600
    assert ch["insurer_responsibility_cents"] == 6400


def test_cash_charge_prompt_pay_discount_only(api):
    """PRD §3.7: "On the `CASH` path the insurer-allowed amount and the deductible are ignored
    entirely: the `patient_responsibility_cents` is the `billed_amount_cents` multiplied by
    one minus a ten-percent prompt-pay discount, rounded half-up to whole cents; the
    `insurer_responsibility_cents` is 0; and the `deductible_applied_cents` is 0."

    Design: Difficulty/dual_variant_calc/charge_split_insurance_vs_cash_diverge
    """
    p_cash = create_patient(full_name="Cash Only", date_of_birth="1981-01-01",
                            has_active_insurance=False)
    prov = create_provider(full_name="Dr Cash")
    enc = create_encounter(p_cash["id"], prov["id"], visit_type="MEDICAL",
                           scheduled_at="2026-03-03T09:00:00Z")
    ch = validate_success(api.create_charge({
        "patient_id": p_cash["id"], "encounter_id": enc["id"],
        "source_kind": "ENCOUNTER", "charge_kind": "OFFICE_VISIT",
        "billed_amount_cents": 20000,
    }, BILLING), 201)
    # round(20000 * 0.9) = 18000
    assert ch["patient_responsibility_cents"] == 18000
    assert ch["insurer_responsibility_cents"] == 0
    assert ch["deductible_applied_cents"] == 0


def test_membership_redemption_tier_spillover_to_out_of_pocket(api):
    """PRD §3.6: "The residual, recorded as `out_of_pocket_cents`, is the discounted price
    minus the redeemed amount, which the patient pays in cash. Note that the discount multiply
    is rounded **before** the wallet comparison, so the wallet draws against the
    already-rounded discounted price."

    Design: Difficulty/dual_variant_calc/membership_redemption_silver_vs_gold_diverge
    """
    # GOLD wallet only 10000; list 20000 -> discounted round(20000*0.85)=17000;
    # redeemed=min(17000,10000)=10000, out_of_pocket=7000
    provider, patient, enc, mem_g = setup_cosmetic_encounter_with_membership(
        tier="GOLD", purchased_unit_cents=10000
    )
    # GOLD purchased 10000 -> wallet 11000 (10% bonus). list 20000 -> disc 17000.
    # redeemed=min(17000,11000)=11000; out_of_pocket=6000.
    t = redeem_treatment(enc["id"], mem_g["id"], mem_g["version"],
                         service_name="filler", list_price_cents=20000)
    assert t["redeemed_cents"] == 11000
    assert t["out_of_pocket_cents"] == 6000


def test_biologic_charge_first_round_no_stepdown(api):
    """PRD §3.7: "the round factor is one minus five percent for each resubmission round
    beyond the first — that is, one minus 0.05 multiplied by the prior authorization's
    `submission_round` minus one — but never below a floor of 0.80. The allowed-after-rounds
    amount is the base multiplied by that round factor, rounded half-up to whole cents. An
    in-office administration uplift is then added: the uplift is four percent of the
    allowed-after-rounds amount, rounded half-up to whole cents, but capped at 25000 cents
    (that is, $250.00). The final billed amount is the allowed-after-rounds amount plus the
    uplift."

    Design: Difficulty/combinatorial_formula/biologic_charge_tiered_with_resubmission_stepdown
    """
    _, patient, enc = setup_provider_patient_encounter(
        patient_overrides={"has_active_insurance": True,
                           "insurance_coinsurance_rate": 0.0,
                           "insurance_deductible_remaining_cents": 0},
        encounter_overrides={"scheduled_at": "2026-03-04T09:00:00Z"},
    )
    pa = setup_approved_pa_round(patient, list_price_cents=100000, target_round=1)
    assert pa["submission_round"] == 1
    ch = validate_success(api.create_charge({
        "patient_id": patient["id"], "encounter_id": enc["id"],
        "source_kind": "ENCOUNTER", "charge_kind": "BIOLOGIC",
        "billed_amount_cents": 1, "insurer_allowed_cents": 1,
        "prior_auth_id": pa["id"],
    }, BILLING), 201)
    # round factor 1.0 -> allowed 100000; uplift min(25000, round(100000*0.04)=4000)=4000
    # billed = 104000 (client-supplied 1 ignored)
    assert ch["billed_amount_cents"] == 104000


def test_waterfall_single_charge_after_partial_deductible_draw(api):
    """PRD §3.7: "each charge draws the smaller of its allowed amount and the deductible
    remaining before it, reduces the running deductible remaining by that draw, computes its
    coinsurance as the post-draw remainder times the coinsurance rate rounded half-up, and
    sets that charge's patient portion to the draw plus the rounded coinsurance; the patient
    total is the sum of those already-rounded per-charge portions."

    Design: Difficulty/combinatorial_formula/deductible_waterfall_round_per_charge_not_sum_then_round
    """
    # deductible 300, coinsurance 0.25, two charges allowed 502 each:
    # charge1: ded=min(502,300)=300, remainder=202, coins=round(202*0.25)=round(50.5)=51,
    #          patient=351; deductible now 0
    # charge2: ded=0, remainder=502, coins=round(502*0.25)=round(125.5)=126, patient=126
    _, patient, enc = setup_provider_patient_encounter(
        patient_overrides={"has_active_insurance": True,
                           "insurance_coinsurance_rate": 0.25,
                           "insurance_deductible_remaining_cents": 300},
        encounter_overrides={"scheduled_at": "2026-03-05T09:00:00Z"},
    )
    ch1 = validate_success(api.create_charge({
        "patient_id": patient["id"], "encounter_id": enc["id"],
        "source_kind": "ENCOUNTER", "charge_kind": "OFFICE_VISIT",
        "billed_amount_cents": 502, "insurer_allowed_cents": 502,
    }, BILLING), 201)
    ch2 = validate_success(api.create_charge({
        "patient_id": patient["id"], "encounter_id": enc["id"],
        "source_kind": "ENCOUNTER", "charge_kind": "PROCEDURE",
        "billed_amount_cents": 502, "insurer_allowed_cents": 502,
    }, BILLING), 201)
    assert ch1["deductible_applied_cents"] == 300
    assert ch1["patient_responsibility_cents"] == 351
    assert ch2["deductible_applied_cents"] == 0
    assert ch2["patient_responsibility_cents"] == 126


def test_deductible_partial_draw_leaves_remainder(api):
    """PRD §3.7: "The deductible applied, recorded as `deductible_applied_cents`, is the
    smaller of the allowed amount and the patient's `insurance_deductible_remaining_cents`."
    PRD §3.7: "As a write-back side effect, the patient's
    `insurance_deductible_remaining_cents` is reduced by the deductible applied."

    Design: Difficulty/boundary_precision_check/deductible_exact_equality_consumes_full_no_coinsurance
    """
    # allowed 5000 < deductible 8000: ded=5000, deductible remaining -> 3000,
    # remainder 0, coins 0, patient 5000, insurer 0
    _, patient, enc = setup_provider_patient_encounter(
        patient_overrides={"has_active_insurance": True,
                           "insurance_coinsurance_rate": 0.2,
                           "insurance_deductible_remaining_cents": 8000},
        encounter_overrides={"scheduled_at": "2026-03-06T09:00:00Z"},
    )
    ch = validate_success(api.create_charge({
        "patient_id": patient["id"], "encounter_id": enc["id"],
        "source_kind": "ENCOUNTER", "charge_kind": "OFFICE_VISIT",
        "billed_amount_cents": 5000, "insurer_allowed_cents": 5000,
    }, BILLING), 201)
    assert ch["deductible_applied_cents"] == 5000
    assert ch["patient_responsibility_cents"] == 5000
    assert ch["insurer_responsibility_cents"] == 0
    patient_after = validate_success(api.get_patient(patient["id"], BILLING), 200)
    assert patient_after["insurance_deductible_remaining_cents"] == 3000
