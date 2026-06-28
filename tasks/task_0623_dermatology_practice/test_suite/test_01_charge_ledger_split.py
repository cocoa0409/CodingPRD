"""Charge ledger: insurance-vs-cash split, deductible waterfall, biologic pricing,
and deductible boundary precision."""
import pytest
from test_helpers import (
    validate_success, get_success_data, api_client,
    setup_provider_patient_encounter, setup_active_membership, setup_approved_pa_round,
    create_patient, create_provider, create_encounter, redeem_treatment,
    setup_cosmetic_encounter_with_membership,
    TEST_USERS,
)

BILLING = TEST_USERS["billing_specialist_headers"]


def test_insurance_vs_cash_charge_diverge(api):
    """PRD §3.7: "The patient's coinsurance portion is that remainder multiplied by the
    patient's `insurance_coinsurance_rate`, rounded half-up to whole cents. The
    `patient_responsibility_cents` is the deductible applied plus the coinsurance portion,
    and the `insurer_responsibility_cents` is the allowed amount minus the patient
    responsibility."
    PRD §3.7: "On the `CASH` path the insurer-allowed amount and the deductible are ignored
    entirely: the `patient_responsibility_cents` is the `billed_amount_cents` multiplied by
    one minus a ten-percent prompt-pay discount, rounded half-up to whole cents; the
    `insurer_responsibility_cents` is 0; and the `deductible_applied_cents` is 0."

    Design: Difficulty/dual_variant_calc/charge_split_insurance_vs_cash_diverge
    """
    # Insured patient, coinsurance 0.2, deductible 0.
    _, p_ins, enc_ins = setup_provider_patient_encounter(
        patient_overrides={"has_active_insurance": True,
                           "insurance_coinsurance_rate": 0.2,
                           "insurance_deductible_remaining_cents": 0},
        encounter_overrides={"scheduled_at": "2026-01-02T09:00:00Z"},
    )
    # Cash patient (no insurance).
    p_cash = create_patient(full_name="Cash Pat", date_of_birth="1980-02-02",
                            has_active_insurance=False)
    prov2 = create_provider(full_name="Dr Two")
    enc_cash = create_encounter(p_cash["id"], prov2["id"], visit_type="MEDICAL",
                                scheduled_at="2026-01-02T10:00:00Z")

    ch_ins = validate_success(api.create_charge({
        "patient_id": p_ins["id"], "encounter_id": enc_ins["id"],
        "source_kind": "ENCOUNTER", "charge_kind": "OFFICE_VISIT",
        "billed_amount_cents": 10000, "insurer_allowed_cents": 10000,
    }, BILLING), 201)
    ch_cash = validate_success(api.create_charge({
        "patient_id": p_cash["id"], "encounter_id": enc_cash["id"],
        "source_kind": "ENCOUNTER", "charge_kind": "OFFICE_VISIT",
        "billed_amount_cents": 15000,
    }, BILLING), 201)

    assert ch_ins["patient_responsibility_cents"] == 2000
    assert ch_ins["insurer_responsibility_cents"] == 8000
    assert ch_cash["patient_responsibility_cents"] == 13500
    assert ch_cash["insurer_responsibility_cents"] == 0


def test_membership_redemption_silver_vs_gold_diverge(api):
    """PRD §3.6: "The list price is first discounted by the tier discount — 5 percent for
    `SILVER` and 15 percent for `GOLD` — giving a discounted price equal to the list price
    multiplied by one minus the tier discount, rounded half-up to whole cents. The amount
    drawn from the wallet, recorded as `redeemed_cents`, is the smaller of that rounded
    discounted price and the membership's currently available `unit_balance_cents`."

    Design: Difficulty/dual_variant_calc/membership_redemption_silver_vs_gold_diverge
    """
    provider, patient, enc, mem_s = setup_cosmetic_encounter_with_membership(
        tier="SILVER", purchased_unit_cents=100000
    )
    _, mem_g = setup_active_membership(tier="GOLD", purchased_unit_cents=100000, patient=patient)

    t_s = redeem_treatment(enc["id"], mem_s["id"], mem_s["version"],
                           service_name="filler", list_price_cents=20000)
    t_g = redeem_treatment(enc["id"], mem_g["id"], mem_g["version"],
                           service_name="filler", list_price_cents=20000)

    assert t_s["redeemed_cents"] == 19000
    assert t_s["out_of_pocket_cents"] == 0
    assert t_g["redeemed_cents"] == 17000
    assert t_g["out_of_pocket_cents"] == 0


def test_biologic_charge_tiered_with_resubmission_stepdown(api):
    """PRD §3.7: "A multi-round resubmission step-down is applied: the round factor is one
    minus five percent for each resubmission round beyond the first — that is, one minus 0.05
    multiplied by the prior authorization's `submission_round` minus one — but never below a
    floor of 0.80. The allowed-after-rounds amount is the base multiplied by that round
    factor, rounded half-up to whole cents. An in-office administration uplift is then added:
    the uplift is four percent of the allowed-after-rounds amount, rounded half-up to whole
    cents, but capped at 25000 cents (that is, $250.00). The final billed amount is the
    allowed-after-rounds amount plus the uplift."

    Design: Difficulty/combinatorial_formula/biologic_charge_tiered_with_resubmission_stepdown
    """
    # Insured patient with 0 coinsurance, 0 deductible; biologic charge self-prices.
    _, patient, enc = setup_provider_patient_encounter(
        patient_overrides={"has_active_insurance": True,
                           "insurance_coinsurance_rate": 0.0,
                           "insurance_deductible_remaining_cents": 0},
        encounter_overrides={"scheduled_at": "2026-01-04T09:00:00Z"},
    )
    pa = setup_approved_pa_round(patient, list_price_cents=100000, target_round=2)
    assert pa["submission_round"] == 2
    assert pa["status"] == "APPROVED"

    ch = validate_success(api.create_charge({
        "patient_id": patient["id"], "encounter_id": enc["id"],
        "source_kind": "ENCOUNTER", "charge_kind": "BIOLOGIC",
        "billed_amount_cents": 98800, "insurer_allowed_cents": 98800,
        "prior_auth_id": pa["id"],
    }, BILLING), 201)

    # base 100000 * (1 - 0.05*(2-1)) = 95000; uplift min(25000, round(95000*0.04)=3800) = 3800
    assert ch["billed_amount_cents"] == 98800
    assert ch["status"] == "POSTED"


def test_deductible_waterfall_round_per_charge_not_sum_then_round(api):
    """PRD §3.7: "the rounding order is pinned: each charge's coinsurance is rounded per
    charge — applied after that charge's deductible draw — and only then are the
    already-rounded per-charge responsibilities summed. This round-per-charge-then-sum order
    is deliberate and can differ by a cent from a sum-then-round implementation, so it must
    be preserved."

    Design: Difficulty/combinatorial_formula/deductible_waterfall_round_per_charge_not_sum_then_round
    """
    _, patient, enc = setup_provider_patient_encounter(
        patient_overrides={"has_active_insurance": True,
                           "insurance_coinsurance_rate": 0.25,
                           "insurance_deductible_remaining_cents": 0},
        encounter_overrides={"scheduled_at": "2026-01-05T09:00:00Z"},
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

    # each: round(502 * 0.25) = round(125.5) = 126; sum = 252 (vs sum-then-round 251)
    assert ch1["patient_responsibility_cents"] == 126
    assert ch2["patient_responsibility_cents"] == 126
    assert ch1["patient_responsibility_cents"] + ch2["patient_responsibility_cents"] == 252


def test_deductible_exact_equality_consumes_full_no_coinsurance(api):
    """PRD §3.7: "The deductible applied, recorded as `deductible_applied_cents`, is the
    smaller of the allowed amount and the patient's `insurance_deductible_remaining_cents`.
    The remainder is the allowed amount minus the deductible applied."
    PRD §3.7: "As a write-back side effect, the patient's `insurance_deductible_remaining_cents`
    is reduced by the deductible applied."

    Design: Difficulty/boundary_precision_check/deductible_exact_equality_consumes_full_no_coinsurance
    """
    _, patient, enc = setup_provider_patient_encounter(
        patient_overrides={"has_active_insurance": True,
                           "insurance_coinsurance_rate": 0.2,
                           "insurance_deductible_remaining_cents": 8000},
        encounter_overrides={"scheduled_at": "2026-01-10T09:00:00Z"},
    )
    ch = validate_success(api.create_charge({
        "patient_id": patient["id"], "encounter_id": enc["id"],
        "source_kind": "ENCOUNTER", "charge_kind": "OFFICE_VISIT",
        "billed_amount_cents": 8000, "insurer_allowed_cents": 8000,
    }, BILLING), 201)

    assert ch["deductible_applied_cents"] == 8000
    assert ch["patient_responsibility_cents"] == 8000
    assert ch["insurer_responsibility_cents"] == 0

    patient_after = validate_success(api.get_patient(patient["id"], BILLING), 200)
    assert patient_after["insurance_deductible_remaining_cents"] == 0
