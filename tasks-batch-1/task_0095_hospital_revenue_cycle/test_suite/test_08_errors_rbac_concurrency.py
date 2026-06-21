"""Business validations, error triggers, RBAC denials, optimistic concurrency,
and immediate-consistency reads.

Queue B (corner) — sections validations, errors, rbac, cross_cutting_complexity_layers,
consistency_model.
"""
from test_helpers import (
    validate_success, validate_error,
    TEST_USERS, ApiErrorId,
    make_coder_headers, make_finance_headers,
    create_active_policy, create_encounter, add_charge, run_eligibility,
    create_payer, create_patient, create_policy,
    setup_partially_paid_statement, setup_charges_captured_encounter,
    setup_coded_encounter, setup_in_collections_statement,
    submit_claim_payload, payment_payload, write_off_payload, set_clock,
)
from test_helpers import api_client as _api

REGISTRAR = TEST_USERS["registrar_headers"]
CODER = TEST_USERS["coder_headers"]
BILLING = TEST_USERS["billing_headers"]
FINANCE = TEST_USERS["finance_headers"]


# ===========================================================================
# validations
# ===========================================================================
# overpayment_rejected_on_issued_statement
def test_overpayment_on_issued_statement_rejected(api):
    """PRD §3.10: "A payment may not exceed the statement's outstanding balance - the
    statement's amount_due_cents minus its amount_paid_cents - and an overpayment is rejected
    with ERR_OVERPAYMENT."

    Payment 130000 against an ISSUED statement with outstanding 120000 => rejected.

    Design: Corner/validations/overpayment_rejected_on_issued_statement
    """
    payer, patient, policy, encounter, coding, claim, statement = setup_partially_paid_statement(
        allowed_amount_cents=200000, deductible_cents=100000, coinsurance_pct=0.20, oop_max_cents=500000,
    )
    resp = _api.post_payment(statement["id"], payment_payload(130000), BILLING)
    validate_error(resp, ApiErrorId.ERR_OVERPAYMENT.value, expected_status=422)


# eligibility_on_encounter_without_policy_returns_no_policy
def test_eligibility_on_self_pay_encounter_rejected(api):
    """PRD §3.4: "It first requires that the encounter actually has insurance attached: an
    eligibility check against an encounter whose policy_id is null is rejected with
    ERR_NO_POLICY_ON_ENCOUNTER."

    Design: Corner/validations/eligibility_on_encounter_without_policy_returns_no_policy
    """
    patient = create_patient(financial_class="SELF_PAY")
    encounter = create_encounter(patient["id"])  # no policy_id
    resp = api.create_eligibility_check(encounter["id"], REGISTRAR)
    validate_error(resp, ApiErrorId.ERR_NO_POLICY_ON_ENCOUNTER.value, expected_status=409)


# ===========================================================================
# errors
# ===========================================================================
# payer_inactive_blocks_policy_verify
def test_verify_policy_against_inactive_payer_rejected(api):
    """PRD §3.2: "Verification is defined only from UNVERIFIED status and additionally requires
    that the referenced payer's active flag is true - an attempt to verify against an inactive
    payer is rejected with ERR_PAYER_INACTIVE."

    Design: Corner/errors/payer_inactive_blocks_policy_verify
    """
    payer = create_payer(active=False, name="Inactive Health")
    patient = create_patient()
    policy = create_policy(patient["id"], payer["id"], member_number="M-117")
    resp = api.verify_policy(policy["id"], REGISTRAR)
    validate_error(resp, ApiErrorId.ERR_PAYER_INACTIVE.value, expected_status=409)


# ===========================================================================
# rbac
# ===========================================================================
# registrar_cannot_finalize_coding
def test_registrar_cannot_finalize_coding(api):
    """PRD §2.1: "When the headers are well-formed but the named role is not permitted to
    invoke the requested operation, the request is rejected with ERR_FORBIDDEN_ROLE (HTTP 403)."
    PRD §2.1: "A Coder assigns and finalizes diagnostic and procedure coding."

    A Registrar calling the Coder-only finalize endpoint is rejected.

    Design: Corner/rbac/registrar_cannot_finalize_coding
    """
    payer, patient, policy, encounter, coding = setup_charges_captured_encounter(
        principal_icd10="E11.65", secondary_icd10=["I10"],
    )
    resp = api.finalize_coding(coding["id"], REGISTRAR)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value, expected_status=403)


# missing_auth_headers_returns_401
def test_missing_auth_headers_returns_401(api):
    """PRD §2.1: "A request missing either header, or carrying a malformed value, is rejected
    with ERR_UNAUTHENTICATED (HTTP 401)."

    Design: Corner/rbac/missing_auth_headers_returns_401
    """
    resp = _api.create_patient(
        {"full_name": "No Auth", "date_of_birth": "1980-04-01"}, headers={}
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value, expected_status=401)


# write_off_by_same_user_as_coder_blocked
def test_write_off_by_coder_user_blocked_segregation_of_duties(api):
    """PRD §3.11: "the approving FinanceManager's X-User-ID must not equal the
    finalized_by_user_id recorded on the encounter's coding assignment - the operator who
    finalized the coding may not be the one who forgives the resulting balance - and a
    violation is rejected with ERR_SEGREGATION_OF_DUTIES."

    Coding finalized by 'shared-user-1'; the same user (as FinanceManager) attempts the
    write-off => rejected.

    Design: Corner/rbac/write_off_by_same_user_as_coder_blocked
    """
    payer, patient, policy, encounter, statement = setup_in_collections_statement(
        issued_clock="2026-03-01T00:00:00Z", aged_clock="2026-08-01T00:00:00Z",
        partial_payment_cents=None, denial=True, coder_user_id="shared-user-1",
    )
    stmt = validate_success(api.get_statement(statement["id"], FINANCE))
    resp = api.write_off_statement(
        stmt["id"], write_off_payload(stmt["version"]),
        make_finance_headers("shared-user-1"),
    )
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, expected_status=403)


# ===========================================================================
# cross_cutting_complexity_layers (OCC + version increment)
# ===========================================================================
# occ_stale_encounter_version_on_claim_submit
def test_stale_encounter_version_on_claim_submit_rejected(api):
    """PRD §2.8: "If this value does not match the encounter's current version - for instance
    because another writer's claim submission has already advanced the encounter to BILLED and
    bumped its version - the submission is rejected with ERR_STALE_ENCOUNTER_VERSION (HTTP 412),
    and no claim is created."

    Submitting with expected_encounter_version one behind current => rejected.

    Design: Corner/cross_cutting_complexity_layers/occ_stale_encounter_version_on_claim_submit
    """
    payer, patient, policy, encounter, coding = setup_coded_encounter(
        charge_cents=300000, deductible_cents=100000, coinsurance_pct=0.20, oop_max_cents=500000,
    )
    enc = validate_success(api.get_encounter(encounter["id"], BILLING))
    resp = _api.submit_claim(
        encounter["id"], submit_claim_payload(payer["id"], enc["version"] - 1), BILLING
    )
    validate_error(resp, ApiErrorId.ERR_STALE_ENCOUNTER_VERSION.value, expected_status=412)


# occ_stale_statement_version_on_writeoff
def test_stale_statement_version_on_writeoff_rejected(api):
    """PRD §2.8: "Approving a bad-debt write-off against a patient statement requires the
    request body to include expected_patient_statement_version carrying the client's last
    observed version of that PatientStatement. If this value does not match the statement's
    current version ... the write-off is rejected with ERR_STALE_STATEMENT_VERSION (HTTP 412),
    and no write-off is recorded."

    A write-off carrying a version one behind the statement's current version is rejected.

    Design: Corner/cross_cutting_complexity_layers/occ_stale_statement_version_on_writeoff
    """
    payer, patient, policy, encounter, statement = setup_in_collections_statement(
        issued_clock="2026-03-01T00:00:00Z", aged_clock="2026-08-01T00:00:00Z",
        partial_payment_cents=None, denial=False, allowed_amount_cents=200000,
    )
    stmt = validate_success(api.get_statement(statement["id"], FINANCE))
    resp = api.write_off_statement(
        statement["id"], write_off_payload(stmt["version"] - 1),
        make_finance_headers("finance-mgr-1"),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_STATEMENT_VERSION.value, expected_status=412)


# version_increments_on_each_encounter_mutation
def test_encounter_version_increments_on_eligibility(api):
    """PRD §2.4: "a version integer that starts at 1 and increments by exactly 1 each time the
    resource is mutated."
    PRD §3.4: "advances the encounter REGISTERED -> ELIGIBILITY_VERIFIED".

    An encounter at version 1 advances to version 2 after the eligibility-check mutation.

    Design: Corner/cross_cutting_complexity_layers/version_increments_on_each_encounter_mutation
    """
    payer, patient, policy = create_active_policy()
    encounter = create_encounter(patient["id"], policy["id"])
    assert encounter["version"] == 1, f"new encounter should be version 1, got {encounter['version']}"
    add_charge(encounter["id"], unit_price_cents=300000)
    run_eligibility(encounter["id"])
    enc = validate_success(api.get_encounter(encounter["id"], REGISTRAR))
    assert enc["version"] == 2, f"version should be 2 after eligibility, got {enc['version']}"
    assert enc["status"] == "ELIGIBILITY_VERIFIED"


# ===========================================================================
# consistency_model
# ===========================================================================
# account_balance_visible_immediately_after_payment
def test_account_balance_visible_immediately_after_payment(api):
    """PRD §3.10: "Posting a payment increases the statement's amount_paid_cents and recomputes
    the encounter's account_balance_cents. If the payment is strictly less than the outstanding
    balance, the statement moves to PARTIALLY_PAID".
    PRD §3.10: "The encounter's account_balance_cents is reconciled after every money movement
    as the encounter's patient_responsibility_cents minus the total of all payment amount_cents
    posted against its statement minus the statement's written_off_cents, with the result
    floored at 0".

    A 50000 payment against a 120000 statement leaves account_balance 70000 immediately.

    Design: Corner/consistency_model/account_balance_visible_immediately_after_payment
    """
    payer, patient, policy, encounter, coding, claim, statement = setup_partially_paid_statement(
        allowed_amount_cents=200000, deductible_cents=100000, coinsurance_pct=0.20, oop_max_cents=500000,
    )
    validate_success(_api.post_payment(statement["id"], payment_payload(50000), BILLING),
                     expected_status=201)
    enc = validate_success(api.get_encounter(encounter["id"], BILLING))
    assert enc["account_balance_cents"] == 70000, (
        f"account_balance should be 70000, got {enc['account_balance_cents']}"
    )
    stmt = validate_success(api.get_statement(statement["id"], BILLING))
    assert stmt["status"] == "PARTIALLY_PAID"
