"""Claim revision cycles, the adjudication and write-off cascade chains, and the
cross-entity preconditions that gate claim submission and eligibility.

Queue A (difficulty) instances:
  non_linear_state_machine / claim_denied_corrected_readjudicated_cycle
  transitive_cascade / adjudication_cascade_depth3_accumulator_balance
  transitive_cascade / writeoff_cascade_depth2_balance_and_close
  cross_entity_state_dependency / claim_submit_requires_encounter_coded_via_coding_cleared
  cross_entity_state_dependency / eligibility_requires_policy_active
"""
from test_helpers import (
    validate_success, validate_error,
    TEST_USERS, ApiErrorId, make_finance_headers,
    create_active_policy, create_policy, create_payer, create_patient,
    create_encounter, add_charge, run_eligibility,
    setup_submitted_claim, setup_charges_captured_encounter,
    setup_in_collections_statement,
    submit_claim, adjudicate, deny, get_statement_for_encounter,
    get_benefit_accumulator_for_policy, submit_claim_payload,
    write_off_payload,
)
from test_helpers import api_client as _api

REGISTRAR = TEST_USERS["registrar_headers"]
CODER = TEST_USERS["coder_headers"]
BILLING = TEST_USERS["billing_headers"]
FINANCE = TEST_USERS["finance_headers"]


# ===========================================================================
# non_linear_state_machine / claim_denied_corrected_readjudicated_cycle
# ===========================================================================
def test_coding_error_denial_corrected_then_readjudicated(api):
    """PRD §3.9: "A denial whose reason is CODING_ERROR may be corrected by a
    BillingSpecialist: correction is defined only from DENIED status with reason CODING_ERROR".
    PRD §3.9: "A CORRECTED claim rejoins the adjudicable set, so it can be re-adjudicated cleanly."
    PRD §3.8: "Adjudication may act on a claim in SUBMITTED, CORRECTED, or APPEALED status".

    SUBMITTED -> DENIED(CODING_ERROR) -> CORRECTED -> adjudicate(allowed 200000) -> PARTIALLY_PAID.

    Design: Difficulty/non_linear_state_machine/claim_denied_corrected_readjudicated_cycle
    """
    payer, patient, policy, encounter, coding, claim = setup_submitted_claim(
        charge_cents=300000, deductible_cents=100000, coinsurance_pct=0.20, oop_max_cents=500000,
    )
    deny(claim["id"], "CODING_ERROR")
    validate_success(api.correct_claim(claim["id"], BILLING))
    data = validate_success(
        _api.adjudicate_claim(
            claim["id"],
            {"allowed_amount_cents": 200000,
             "claim_lines": [{"cpt_code": "99285", "line_allowed_cents": 200000}]},
            BILLING,
        )
    )
    assert data["status"] == "PARTIALLY_PAID", f"expected PARTIALLY_PAID, got {data['status']}"


def test_corrected_claim_readjudication_computes_responsibility(api):
    """PRD §3.8: "the final patient_responsibility_cents is the smaller of that raw patient
    figure and the remaining out-of-pocket room - the out-of-pocket cap is applied only after
    the deductible and coinsurance are summed."

    After the correction reversal cascade resets the accumulator path, re-adjudicating allowed
    200000 yields 100000 deductible + round(100000*0.20)=20000 => 120000.

    Design: Difficulty/non_linear_state_machine/claim_denied_corrected_readjudicated_cycle
    """
    payer, patient, policy, encounter, coding, claim = setup_submitted_claim(
        charge_cents=300000, deductible_cents=100000, coinsurance_pct=0.20, oop_max_cents=500000,
    )
    deny(claim["id"], "CODING_ERROR")
    validate_success(api.correct_claim(claim["id"], BILLING))
    data = validate_success(
        _api.adjudicate_claim(
            claim["id"],
            {"allowed_amount_cents": 200000,
             "claim_lines": [{"cpt_code": "99285", "line_allowed_cents": 200000}]},
            BILLING,
        )
    )
    assert data["patient_responsibility_cents"] == 120000, (
        f"re-adjudicated responsibility should be 120000, got {data['patient_responsibility_cents']}"
    )


# ===========================================================================
# transitive_cascade / adjudication_cascade_depth3_accumulator_balance
# ===========================================================================
def test_adjudication_cascade_advances_encounter_and_accumulator(api):
    """PRD §3.8: "the cascade advances the encounter CODED -> BILLED with the encounter's
    patient_responsibility_cents set to the claim's patient_responsibility_cents, the
    encounter's account_balance_cents is reconciled".
    PRD §3.8: "its oop_met_cents increases by the final patient responsibility".

    Adjudicate allowed 200000 => responsibility 120000: accumulator oop_met 120000, encounter
    BILLED with patient_responsibility 120000 and account_balance 120000.

    Design: Difficulty/transitive_cascade/adjudication_cascade_depth3_accumulator_balance
    """
    payer, patient, policy, encounter, coding, claim = setup_submitted_claim(
        charge_cents=300000, deductible_cents=100000, coinsurance_pct=0.20, oop_max_cents=500000,
    )
    adjudicate(claim["id"], 200000)
    accum = get_benefit_accumulator_for_policy(policy["id"])
    assert accum["oop_met_cents"] == 120000, f"oop_met should be 120000, got {accum['oop_met_cents']}"
    enc = validate_success(api.get_encounter(encounter["id"], REGISTRAR))
    assert enc["status"] == "BILLED", f"encounter should be BILLED, got {enc['status']}"
    assert enc["patient_responsibility_cents"] == 120000
    assert enc["account_balance_cents"] == 120000, (
        f"account_balance should be 120000, got {enc['account_balance_cents']}"
    )


def test_partial_pay_adjudication_issues_one_statement(api):
    """PRD §3.8: "a PatientStatement is created for the encounter in ISSUED status."
    PRD §3.10: "the statement references the encounter by encounter_id, snapshots
    amount_due_cents from the encounter's patient_responsibility_cents at issue time".

    Exactly one ISSUED statement with amount_due 120000.

    Design: Difficulty/transitive_cascade/adjudication_cascade_depth3_accumulator_balance
    """
    payer, patient, policy, encounter, coding, claim = setup_submitted_claim(
        charge_cents=300000, deductible_cents=100000, coinsurance_pct=0.20, oop_max_cents=500000,
    )
    adjudicate(claim["id"], 200000)
    data, meta = _list_statements(api, encounter["id"])
    assert len(data) == 1, f"expected exactly one statement, got {len(data)}"
    assert data[0]["amount_due_cents"] == 120000
    assert data[0]["status"] == "ISSUED"


def _list_statements(api, encounter_id):
    body = api.list_statements_for_encounter(encounter_id, BILLING).json()
    return body.get("data", []), body.get("meta", {})


# ===========================================================================
# transitive_cascade / writeoff_cascade_depth2_balance_and_close
# ===========================================================================
def test_writeoff_recomputes_balance_and_closes_encounter(api):
    """PRD §3.11: "The statement's written_off_cents is set to the write-off amount, the
    statement moves to WRITTEN_OFF, the encounter's account_balance_cents is recomputed to 0,
    and the encounter bubbles up from BILLED to CLOSED."

    A 120000 statement with no payments written off in full: written_off 120000, encounter
    account_balance 0 and CLOSED.

    Design: Difficulty/transitive_cascade/writeoff_cascade_depth2_balance_and_close
    """
    payer, patient, policy, encounter, statement = setup_in_collections_statement(
        issued_clock="2026-03-01T00:00:00Z", aged_clock="2026-08-01T00:00:00Z",
        partial_payment_cents=None, denial=False, allowed_amount_cents=200000,
    )
    stmt = validate_success(api.get_statement(statement["id"], FINANCE))
    validate_success(
        api.write_off_statement(stmt["id"], write_off_payload(stmt["version"]),
                                make_finance_headers("finance-mgr-1")),
        expected_status=201,
    )
    stmt_after = validate_success(api.get_statement(statement["id"], FINANCE))
    assert stmt_after["status"] == "WRITTEN_OFF"
    assert stmt_after["written_off_cents"] == 120000
    enc = validate_success(api.get_encounter(encounter["id"], REGISTRAR))
    assert enc["account_balance_cents"] == 0, (
        f"account_balance should be 0, got {enc['account_balance_cents']}"
    )
    assert enc["status"] == "CLOSED", f"encounter should be CLOSED, got {enc['status']}"


def test_writeoff_closes_encounter_from_billed(api):
    """PRD §3.11: "the encounter bubbles up from BILLED to CLOSED."

    Design: Difficulty/transitive_cascade/writeoff_cascade_depth2_balance_and_close
    """
    payer, patient, policy, encounter, statement = setup_in_collections_statement(
        issued_clock="2026-03-01T00:00:00Z", aged_clock="2026-08-01T00:00:00Z",
        partial_payment_cents=None, denial=False, allowed_amount_cents=200000,
    )
    enc_before = validate_success(api.get_encounter(encounter["id"], REGISTRAR))
    assert enc_before["status"] == "BILLED"
    stmt = validate_success(api.get_statement(statement["id"], FINANCE))
    validate_success(
        api.write_off_statement(stmt["id"], write_off_payload(stmt["version"]),
                                make_finance_headers("finance-mgr-1")),
        expected_status=201,
    )
    enc = validate_success(api.get_encounter(encounter["id"], REGISTRAR))
    assert enc["status"] == "CLOSED"


# ===========================================================================
# cross_entity_state_dependency / claim_submit_requires_encounter_coded_via_coding_cleared
# ===========================================================================
def test_claim_submit_before_coding_cleared_rejected(api):
    """PRD §3.6: "Because a claim may only be submitted once the encounter is CODED, an
    attempt to submit a claim before clearance - while the encounter is still short of CODED -
    is rejected with ERR_CODING_NOT_CLEARED."

    Coding is FINALIZED but not yet CLEARED, so the encounter is still CHARGES_CAPTURED.

    Design: Difficulty/cross_entity_state_dependency/claim_submit_requires_encounter_coded_via_coding_cleared
    """
    payer, patient, policy, encounter, coding = setup_charges_captured_encounter(
        principal_icd10="E11.65", secondary_icd10=["I10"],
    )
    validate_success(api.finalize_coding(coding["id"], CODER))
    enc = validate_success(api.get_encounter(encounter["id"], REGISTRAR))
    resp = _api.submit_claim(
        encounter["id"], submit_claim_payload(payer["id"], enc["version"]), BILLING
    )
    validate_error(resp, ApiErrorId.ERR_CODING_NOT_CLEARED.value, expected_status=409)


def test_claim_submit_after_coding_cleared_succeeds(api):
    """PRD §3.6: "As a bubble-up side effect, clearing the coding advances the owning encounter
    from CHARGES_CAPTURED to CODED: the encounter only makes this CHARGES_CAPTURED -> CODED
    transition as a consequence of its coding assignment reaching CLEARED."
    PRD §3.7: "With the encounter CODED, a BillingSpecialist submits a claim to a payer."

    Once coding is FINALIZED and CLEARED, the encounter is CODED and claim submission succeeds.

    Design: Difficulty/cross_entity_state_dependency/claim_submit_requires_encounter_coded_via_coding_cleared
    """
    payer, patient, policy, encounter, coding = setup_charges_captured_encounter(
        principal_icd10="E11.65", secondary_icd10=["I10"],
    )
    validate_success(api.finalize_coding(coding["id"], CODER))
    validate_success(api.clear_coding(coding["id"], BILLING))
    enc = validate_success(api.get_encounter(encounter["id"], REGISTRAR))
    assert enc["status"] == "CODED"
    data = validate_success(
        _api.submit_claim(encounter["id"], submit_claim_payload(payer["id"], enc["version"]), BILLING),
        expected_status=201,
    )
    assert data["status"] == "SUBMITTED"


# ===========================================================================
# cross_entity_state_dependency / eligibility_requires_policy_active
# ===========================================================================
def test_eligibility_on_unverified_policy_rejected(api):
    """PRD §3.4: "If instead the referenced policy is not ACTIVE, the operation does not
    advance the encounter: it is rejected with ERR_POLICY_NOT_ACTIVE, the encounter remains in
    REGISTERED, and the recorded eligibility result for such a case is INELIGIBLE rather than
    ELIGIBLE."

    Policy is never verified (UNVERIFIED), so eligibility is rejected.

    Design: Difficulty/cross_entity_state_dependency/eligibility_requires_policy_active
    """
    payer = create_payer(active=True)
    patient = create_patient()
    policy = create_policy(patient["id"], payer["id"], member_number="M-013")
    encounter = create_encounter(patient["id"], policy["id"])
    resp = api.create_eligibility_check(encounter["id"], REGISTRAR)
    validate_error(resp, ApiErrorId.ERR_POLICY_NOT_ACTIVE.value, expected_status=409)


def test_eligibility_rejection_leaves_encounter_registered(api):
    """PRD §3.4: "it is rejected with ERR_POLICY_NOT_ACTIVE, the encounter remains in
    REGISTERED".

    Design: Difficulty/cross_entity_state_dependency/eligibility_requires_policy_active
    """
    payer = create_payer(active=True)
    patient = create_patient()
    policy = create_policy(patient["id"], payer["id"], member_number="M-013b")
    encounter = create_encounter(patient["id"], policy["id"])
    api.create_eligibility_check(encounter["id"], REGISTRAR)
    enc = validate_success(api.get_encounter(encounter["id"], REGISTRAR))
    assert enc["status"] == "REGISTERED", (
        f"encounter must remain REGISTERED, got {enc['status']}"
    )
