"""State-machine transitions: invalid/terminal rejections, initial state, precondition
enforcement, and valid forks.

Queue B (corner) — section state_machines.
"""
from test_helpers import (
    validate_success, validate_error,
    TEST_USERS, ApiErrorId,
    create_active_policy, create_encounter, add_charge, run_eligibility,
    create_patient,
    setup_eligibility_verified_encounter, setup_submitted_claim,
    setup_denied_statement,
    adjudicate, deny,
)
from test_helpers import api_client as _api

REGISTRAR = TEST_USERS["registrar_headers"]
CODER = TEST_USERS["coder_headers"]
BILLING = TEST_USERS["billing_headers"]


# ---------------------------------------------------------------------------
# cancel_eligibility_from_already_verified_returns_invalid_state
# ---------------------------------------------------------------------------
def test_second_eligibility_check_on_verified_encounter_rejected(api):
    """PRD §3.4: "This operation is defined only from REGISTERED status."
    PRD §2.7: "the target resource's state is checked: if the requested transition is not
    defined from the resource's current state, the request yields ERR_INVALID_STATE (409)."

    A second eligibility check on an ELIGIBILITY_VERIFIED encounter is rejected.

    Design: Corner/state_machines/cancel_eligibility_from_already_verified_returns_invalid_state
    """
    payer, patient, policy, encounter = setup_eligibility_verified_encounter()
    resp = api.create_eligibility_check(encounter["id"], REGISTRAR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)


# ---------------------------------------------------------------------------
# terminal_paid_claim_rejects_further_transition
# ---------------------------------------------------------------------------
def test_deny_on_paid_claim_rejected(api):
    """PRD §2.7: "the target resource's state is checked: if the requested transition is not
    defined from the resource's current state, the request yields ERR_INVALID_STATE (409)."
    PRD §3.8: "If the computed patient responsibility is 0 - the payer covers the allowed
    amount in full - the claim transitions to PAID".

    A PAID claim (policy deductible 0, oop_max 0 => PR 0) rejects a subsequent deny.

    Design: Corner/state_machines/terminal_paid_claim_rejects_further_transition
    """
    payer, patient, policy, encounter, coding, claim = setup_submitted_claim(
        charge_cents=300000, deductible_cents=0, coinsurance_pct=0.0, oop_max_cents=0,
    )
    paid = adjudicate(claim["id"], 200000)
    assert paid["status"] == "PAID"
    resp = _api.deny_claim(claim["id"], {"denial_reason": "NOT_COVERED"}, BILLING)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)


# ---------------------------------------------------------------------------
# initial_state_encounter_registered
# ---------------------------------------------------------------------------
def test_new_encounter_starts_registered(api):
    """PRD §3.3: "A new encounter begins in REGISTERED status with a discharge_at of null
    while it remains open."
    PRD §2.5: "Several fields are derived rather than supplied: total_charges_cents,
    patient_responsibility_cents, and account_balance_cents on an encounter ... are all
    computed and reconciled by the server".

    A newly created encounter is REGISTERED with total_charges_cents 0.

    Design: Corner/state_machines/initial_state_encounter_registered
    """
    patient = create_patient()
    data = validate_success(api.create_encounter(
        {"patient_id": patient["id"], "admission_at": "2026-03-01T09:00:00Z"}, REGISTRAR
    ), expected_status=201)
    assert data["status"] == "REGISTERED"
    assert data["total_charges_cents"] == 0


# ---------------------------------------------------------------------------
# policy_terminate_blocked_while_open_encounter
# ---------------------------------------------------------------------------
def test_terminate_policy_with_open_encounter_rejected(api):
    """PRD §3.2: "Termination is defined only from ACTIVE status and is permitted only when no
    encounter referencing this policy is still open - that is, every encounter that references
    the policy must be in CLOSED status. If any referencing encounter is in any status other
    than CLOSED, termination is rejected with ERR_POLICY_IN_USE."

    Design: Corner/state_machines/policy_terminate_blocked_while_open_encounter
    """
    payer, patient, policy = create_active_policy()
    create_encounter(patient["id"], policy["id"])  # open REGISTERED encounter
    resp = api.terminate_policy(policy["id"], REGISTRAR)
    validate_error(resp, ApiErrorId.ERR_POLICY_IN_USE.value, expected_status=409)


# ---------------------------------------------------------------------------
# charge_blocked_after_discharge_charges_closed
# ---------------------------------------------------------------------------
def test_charge_after_discharge_rejected(api):
    """PRD §3.3: "A charge may be posted only while the encounter is in REGISTERED or
    ELIGIBILITY_VERIFIED status; charge capture closes at discharge, so an attempt to post a
    charge to an encounter in any later status is rejected with ERR_CHARGES_CLOSED."

    Design: Corner/state_machines/charge_blocked_after_discharge_charges_closed
    """
    payer, patient, policy = create_active_policy()
    encounter = create_encounter(patient["id"], policy["id"])
    add_charge(encounter["id"], unit_price_cents=300000)
    run_eligibility(encounter["id"])
    validate_success(api.discharge_encounter(encounter["id"], REGISTRAR))
    resp = api.create_charge(
        encounter["id"], {"cpt_code": "70450", "units": 1, "unit_price_cents": 5000}, REGISTRAR
    )
    validate_error(resp, ApiErrorId.ERR_CHARGES_CLOSED.value, expected_status=409)


# ---------------------------------------------------------------------------
# claim_void_from_duplicate_denial
# ---------------------------------------------------------------------------
def test_duplicate_denial_can_be_voided(api):
    """PRD §3.9: "a duplicate claim is voided rather than reworked. Voiding is performed by a
    BillingSpecialist and is defined from a claim in SUBMITTED status, or from a DENIED claim
    whose denial_reason is DUPLICATE. Voiding transitions the claim to VOID, which is terminal."

    Design: Corner/state_machines/claim_void_from_duplicate_denial
    """
    payer, patient, policy, encounter, coding, claim = setup_submitted_claim(
        charge_cents=300000, deductible_cents=100000, coinsurance_pct=0.20, oop_max_cents=500000,
    )
    deny(claim["id"], "DUPLICATE")
    data = validate_success(api.void_claim(claim["id"], BILLING))
    assert data["status"] == "VOID", f"expected VOID, got {data['status']}"


# ---------------------------------------------------------------------------
# correct_non_coding_error_denial_returns_not_correctable
# ---------------------------------------------------------------------------
def test_correct_non_coding_error_denial_rejected(api):
    """PRD §3.9: "correction is defined only from DENIED status with reason CODING_ERROR, and
    a correction attempt on a denial with any other reason is rejected with ERR_NOT_CORRECTABLE."

    Design: Corner/state_machines/correct_non_coding_error_denial_returns_not_correctable
    """
    payer, patient, policy, encounter, coding, claim = setup_submitted_claim(
        charge_cents=300000, deductible_cents=100000, coinsurance_pct=0.20, oop_max_cents=500000,
    )
    deny(claim["id"], "NOT_COVERED")
    resp = api.correct_claim(claim["id"], BILLING)
    validate_error(resp, ApiErrorId.ERR_NOT_CORRECTABLE.value, expected_status=409)


# ---------------------------------------------------------------------------
# paid_branch_when_oop_already_met
# ---------------------------------------------------------------------------
def test_paid_branch_issues_no_statement(api):
    """PRD §3.8: "If the computed patient responsibility is 0 - the payer covers the allowed
    amount in full - the claim transitions to PAID, and the cascade advances the encounter
    CODED -> BILLED with the encounter's patient_responsibility_cents set to 0; no patient
    statement is issued in this case."

    Policy deductible 0, oop_max 0 => responsibility 0 => PAID, no statement.

    Design: Corner/state_machines/paid_branch_when_oop_already_met
    """
    payer, patient, policy, encounter, coding, claim = setup_submitted_claim(
        charge_cents=300000, deductible_cents=0, coinsurance_pct=0.0, oop_max_cents=0,
    )
    data = adjudicate(claim["id"], 200000)
    assert data["status"] == "PAID"
    assert data["patient_responsibility_cents"] == 0
    enc = validate_success(api.get_encounter(encounter["id"], REGISTRAR))
    assert enc["patient_responsibility_cents"] == 0
    body = api.list_statements_for_encounter(encounter["id"], BILLING).json()
    assert body["data"] == [], f"PAID branch must issue no statement, got {body['data']}"
