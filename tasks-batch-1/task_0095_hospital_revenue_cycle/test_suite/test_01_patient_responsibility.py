"""Patient-responsibility math: forward-looking estimate vs chronological final,
OOP-cap clipping, and benefit-accumulator conservation across claims.

Queue A (difficulty) instances:
  dual_variant_calc / estimate_vs_final_patient_responsibility
  dual_variant_calc / denial_full_charges_vs_adjudication_billing
  combinatorial_formula / oop_cap_clips_summed_deductible_plus_coinsurance
  compensating_invariant / oop_met_never_exceeds_oop_max_across_two_claims
  compensating_invariant / statement_money_conservation_due_equals_paid_plus_written_plus_balance
"""
from test_helpers import (
    validate_success,
    get_success_data,
    api_client,
    TEST_USERS,
    make_finance_headers,
    # fixtures
    create_active_policy, create_encounter, add_charge, run_eligibility,
    setup_coded_encounter, setup_submitted_claim, submit_claim, adjudicate,
    deny, get_statement_for_encounter, get_benefit_accumulator_for_policy,
    setup_in_collections_statement, set_clock,
    # factories
    adjudicate_payload, single_line, payment_payload, write_off_payload,
    create_coding_payload,
)

REGISTRAR = TEST_USERS["registrar_headers"]
CODER = TEST_USERS["coder_headers"]
BILLING = TEST_USERS["billing_headers"]
FINANCE = TEST_USERS["finance_headers"]


# ===========================================================================
# dual_variant_calc / estimate_vs_final_patient_responsibility
# ===========================================================================
def test_eligibility_estimate_uses_billed_charges(api):
    """PRD §3.4: "The expected allowed amount is taken to be the encounter's current
    total_charges_cents over its posted charges - the estimate optimistically assumes
    the payer will allow the full billed charges, even though more charges may still be
    captured before discharge."

    Billed 300000, deductible 100000, coinsurance 0.20: deductible 100000 +
    coinsurance round(200000*0.20)=40000 => estimate 140000.

    Design: Difficulty/dual_variant_calc/estimate_vs_final_patient_responsibility
    """
    payer, patient, policy = create_active_policy(
        deductible_cents=100000, coinsurance_pct=0.20, oop_max_cents=500000,
    )
    encounter = create_encounter(patient["id"], policy["id"])
    add_charge(encounter["id"], unit_price_cents=300000)
    check = run_eligibility(encounter["id"])
    assert check["result"] == "ELIGIBLE"
    assert check["estimated_patient_responsibility_cents"] == 140000, (
        f"estimate should be 140000, got {check['estimated_patient_responsibility_cents']}"
    )


def test_final_responsibility_uses_payer_allowed_amount(api):
    """PRD §3.8: "Note that because this figure uses the payer-allowed amount rather than
    the billed charges, and uses accumulator state that may already reflect earlier claims
    adjudicated in the same plan year, an identical encounter can yield a different final
    number than the eligibility estimate of §3.4 whenever the allowed amount differs from
    the billed charges or the accumulator moved between verification and adjudication."

    Same encounter (billed 300000, estimate 140000) but allowed 200000:
    deductible 100000 + coinsurance round(100000*0.20)=20000 => 120000, distinct from the estimate.

    Design: Difficulty/dual_variant_calc/estimate_vs_final_patient_responsibility
    """
    payer, patient, policy = create_active_policy(
        deductible_cents=100000, coinsurance_pct=0.20, oop_max_cents=500000,
    )
    encounter = create_encounter(patient["id"], policy["id"])
    add_charge(encounter["id"], unit_price_cents=300000)
    check = run_eligibility(encounter["id"])
    estimate = check["estimated_patient_responsibility_cents"]
    # drive to CODED and submit a claim
    from test_helpers import api_client as _api
    get_success_data(_api.discharge_encounter(encounter["id"], REGISTRAR))
    coding = get_success_data(_api.create_coding_assignment(
        encounter["id"], create_coding_payload(principal_icd10="E11.65", secondary_icd10=["I10", "E78.5"]), CODER
    ))
    get_success_data(_api.finalize_coding(coding["id"], CODER))
    get_success_data(_api.clear_coding(coding["id"], BILLING))
    claim = submit_claim(encounter["id"], payer["id"])
    resp = _api.adjudicate_claim(
        claim["id"], adjudicate_payload(200000, single_line("99285", 200000)), BILLING
    )
    data = validate_success(resp)
    assert data["patient_responsibility_cents"] == 120000, (
        f"final responsibility should be 120000, got {data['patient_responsibility_cents']}"
    )
    assert data["patient_responsibility_cents"] != estimate, (
        "final responsibility must differ from the estimate for this encounter"
    )


# ===========================================================================
# dual_variant_calc / denial_full_charges_vs_adjudication_billing
# ===========================================================================
def test_denial_bills_patient_full_charges(api):
    """PRD §3.9: "On denial the server records the denial_reason, sets the claim to DENIED,
    and cascades: the encounter advances CODED -> BILLED with patient_responsibility_cents
    set to the encounter's full total_charges_cents - on a denial the whole balance is
    billed to the patient - and a PatientStatement in ISSUED status is created for the encounter."

    Design: Difficulty/dual_variant_calc/denial_full_charges_vs_adjudication_billing
    """
    payer, patient, policy, encounter, coding, claim = setup_submitted_claim(
        charge_cents=300000, deductible_cents=100000, coinsurance_pct=0.20, oop_max_cents=500000,
    )
    deny(claim["id"], "NOT_COVERED")
    enc = validate_success(api.get_encounter(encounter["id"], REGISTRAR))
    assert enc["patient_responsibility_cents"] == 300000, (
        f"denial should bill full charges 300000, got {enc['patient_responsibility_cents']}"
    )


def test_partial_payment_adjudication_bills_only_computed_responsibility(api):
    """PRD §3.8: "If instead the computed patient responsibility is greater than 0, the
    claim transitions to PARTIALLY_PAID, the cascade advances the encounter CODED -> BILLED
    with the encounter's patient_responsibility_cents set to the claim's
    patient_responsibility_cents, the encounter's account_balance_cents is reconciled, and
    a PatientStatement is created for the encounter in ISSUED status."

    Same coded encounter (billed 300000) but adjudicated allowed 200000 => 120000, not the full charges.

    Design: Difficulty/dual_variant_calc/denial_full_charges_vs_adjudication_billing
    """
    payer, patient, policy, encounter, coding, claim = setup_submitted_claim(
        charge_cents=300000, deductible_cents=100000, coinsurance_pct=0.20, oop_max_cents=500000,
    )
    adjudicate(claim["id"], 200000)
    enc = validate_success(api.get_encounter(encounter["id"], REGISTRAR))
    assert enc["patient_responsibility_cents"] == 120000, (
        f"partial-pay billing should be 120000, got {enc['patient_responsibility_cents']}"
    )
    assert enc["patient_responsibility_cents"] != 300000, (
        "partial-pay billing must differ from the full-charges denial billing"
    )


# ===========================================================================
# combinatorial_formula / oop_cap_clips_summed_deductible_plus_coinsurance
# ===========================================================================
def test_oop_cap_clips_summed_deductible_plus_coinsurance(api):
    """PRD §3.8: "The raw patient figure is the deductible applied plus the raw coinsurance,
    and the final patient_responsibility_cents is the smaller of that raw patient figure and
    the remaining out-of-pocket room - the out-of-pocket cap is applied only after the
    deductible and coinsurance are summed."

    allowed 200005, deductible 100000, coinsurance 0.20, oop_max 120000:
    deductible 100000 + round(100005*0.20)=20001 => raw 120001, clipped to oop room 120000.

    Design: Difficulty/combinatorial_formula/oop_cap_clips_summed_deductible_plus_coinsurance
    """
    payer, patient, policy, encounter, coding, claim = setup_submitted_claim(
        charge_cents=250000, deductible_cents=100000, coinsurance_pct=0.20, oop_max_cents=120000,
    )
    data = adjudicate(claim["id"], 200005)
    assert data["patient_responsibility_cents"] == 120000, (
        f"OOP cap should clip to 120000, got {data['patient_responsibility_cents']}"
    )


def test_oop_cap_advances_accumulator_to_caps(api):
    """PRD §3.8: "As a side effect of computing patient responsibility, the accumulator is
    advanced: its deductible_met_cents increases by the deductible applied, and its
    oop_met_cents increases by the final patient responsibility - and by construction neither
    is driven past its policy limit."

    deductible_met advances by deductible applied (100000); oop_met advances to the capped 120000.

    Design: Difficulty/combinatorial_formula/oop_cap_clips_summed_deductible_plus_coinsurance
    """
    payer, patient, policy, encounter, coding, claim = setup_submitted_claim(
        charge_cents=250000, deductible_cents=100000, coinsurance_pct=0.20, oop_max_cents=120000,
    )
    adjudicate(claim["id"], 200005)
    accum = get_benefit_accumulator_for_policy(policy["id"])
    assert accum["oop_met_cents"] == 120000, (
        f"oop_met should be 120000, got {accum['oop_met_cents']}"
    )
    assert accum["deductible_met_cents"] == 100000, (
        f"deductible_met should be 100000, got {accum['deductible_met_cents']}"
    )


# ===========================================================================
# compensating_invariant / oop_met_never_exceeds_oop_max_across_two_claims
# ===========================================================================
def _setup_two_coded_encounters_one_policy(api, oop_max_cents=120000):
    """Two coded encounters with SUBMITTED claims on one policy. Returns (policy, claim1, claim2)."""
    payer, patient, policy = create_active_policy(
        deductible_cents=100000, coinsurance_pct=0.20, oop_max_cents=oop_max_cents,
    )
    claims = []
    for i, (cpt, adm) in enumerate([("99285", "2026-03-01T09:00:00Z"), ("99284", "2026-03-05T09:00:00Z")]):
        encounter, coding, _payer, _pat, _pol, claim = _build_claim_on_policy(
            api, payer, patient, policy, cpt, adm
        )
        claims.append((encounter, claim))
    return policy, claims[0], claims[1]


def _build_claim_on_policy(api, payer, patient, policy, cpt, admission_at):
    from test_helpers import api_client as _api
    encounter = create_encounter(patient["id"], policy["id"], admission_at=admission_at)
    add_charge(encounter["id"], cpt_code=cpt, unit_price_cents=300000)
    run_eligibility(encounter["id"])
    get_success_data(_api.discharge_encounter(encounter["id"], REGISTRAR))
    coding = get_success_data(_api.create_coding_assignment(
        encounter["id"], create_coding_payload(principal_icd10="E11.65", secondary_icd10=["I10"]), CODER
    ))
    get_success_data(_api.finalize_coding(coding["id"], CODER))
    get_success_data(_api.clear_coding(coding["id"], BILLING))
    claim = submit_claim(encounter["id"], payer["id"])
    return encounter, coding, payer, patient, policy, claim


def test_oop_met_capped_across_two_claims(api):
    """PRD §3.2: "its oop_met_cents tracks the year-to-date patient out-of-pocket (deductible
    plus coinsurance) and never exceeds the policy's oop_max_cents."

    Claim1 allowed 100000 => deductible-only 100000; Claim2 allowed 200000 raw would add
    coinsurance, but oop_met is capped at oop_max 120000.

    Design: Difficulty/compensating_invariant/oop_met_never_exceeds_oop_max_across_two_claims
    """
    policy, (enc1, claim1), (enc2, claim2) = _setup_two_coded_encounters_one_policy(api, oop_max_cents=120000)
    d1 = adjudicate(claim1["id"], 100000, cpt_code="99285")
    assert d1["patient_responsibility_cents"] == 100000, (
        f"claim1 responsibility should be 100000, got {d1['patient_responsibility_cents']}"
    )
    d2 = adjudicate(claim2["id"], 200000, cpt_code="99284")
    accum = get_benefit_accumulator_for_policy(policy["id"])
    assert accum["oop_met_cents"] == 120000, (
        f"oop_met should be capped at oop_max 120000, got {accum['oop_met_cents']}"
    )


def test_second_claim_responsibility_clipped_by_remaining_oop(api):
    """PRD §3.8: "The remaining out-of-pocket room is the policy's oop_max_cents minus the
    accumulator's oop_met_cents, floored at 0. The raw patient figure is the deductible
    applied plus the raw coinsurance, and the final patient_responsibility_cents is the
    smaller of that raw patient figure and the remaining out-of-pocket room."

    After claim1 used 100000 of a 120000 OOP, claim2's responsibility is clipped to the
    remaining 20000.

    Design: Difficulty/compensating_invariant/oop_met_never_exceeds_oop_max_across_two_claims
    """
    policy, (enc1, claim1), (enc2, claim2) = _setup_two_coded_encounters_one_policy(api, oop_max_cents=120000)
    adjudicate(claim1["id"], 100000, cpt_code="99285")
    d2 = adjudicate(claim2["id"], 200000, cpt_code="99284")
    assert d2["patient_responsibility_cents"] == 20000, (
        f"claim2 responsibility should be clipped to 20000, got {d2['patient_responsibility_cents']}"
    )


# ===========================================================================
# compensating_invariant / statement_money_conservation_due_equals_paid_plus_written_plus_balance
# ===========================================================================
def test_partial_payment_then_writeoff_conserves_statement_dollars(api):
    """PRD §3.11: "the server creates a WriteOff ledger entry referencing the statement by
    statement_id, with its amount_cents set to the statement's amount_due_cents minus its
    amount_paid_cents at write-off time."

    amount_due 120000, partial payment 50000, write-off of the remaining 70000:
    amount_paid 50000 + written_off 70000 == amount_due 120000.

    Design: Difficulty/compensating_invariant/statement_money_conservation_due_equals_paid_plus_written_plus_balance
    """
    payer, patient, policy, encounter, statement = setup_in_collections_statement(
        issued_clock="2026-03-01T00:00:00Z", aged_clock="2026-08-01T00:00:00Z",
        partial_payment_cents=50000, denial=False, allowed_amount_cents=200000,
    )
    stmt = validate_success(api.get_statement(statement["id"], FINANCE))
    data = validate_success(
        api.write_off_statement(stmt["id"], write_off_payload(stmt["version"]),
                                make_finance_headers("finance-mgr-1")),
        expected_status=201,
    )
    stmt_after = validate_success(api.get_statement(statement["id"], FINANCE))
    assert stmt_after["amount_paid_cents"] == 50000
    assert stmt_after["written_off_cents"] == 70000
    assert stmt_after["amount_due_cents"] == 120000
    assert stmt_after["amount_paid_cents"] + stmt_after["written_off_cents"] == stmt_after["amount_due_cents"]


def test_writeoff_drives_encounter_balance_to_zero(api):
    """PRD §3.11: "The statement's written_off_cents is set to the write-off amount, the
    statement moves to WRITTEN_OFF, the encounter's account_balance_cents is recomputed to 0,
    and the encounter bubbles up from BILLED to CLOSED."

    Design: Difficulty/compensating_invariant/statement_money_conservation_due_equals_paid_plus_written_plus_balance
    """
    payer, patient, policy, encounter, statement = setup_in_collections_statement(
        issued_clock="2026-03-01T00:00:00Z", aged_clock="2026-08-01T00:00:00Z",
        partial_payment_cents=50000, denial=False, allowed_amount_cents=200000,
    )
    stmt = validate_success(api.get_statement(statement["id"], FINANCE))
    validate_success(
        api.write_off_statement(stmt["id"], write_off_payload(stmt["version"]),
                                make_finance_headers("finance-mgr-1")),
        expected_status=201,
    )
    enc = validate_success(api.get_encounter(encounter["id"], REGISTRAR))
    assert enc["account_balance_cents"] == 0, (
        f"account_balance should be 0 after write-off, got {enc['account_balance_cents']}"
    )
