"""Composite setup helpers for the Hospital Revenue Cycle API.

Each test runs against a freshly-rebooted, empty database, so every fixture builds
its preconditions from scratch using only PRD-declared endpoints. Setup calls use
get_success_data() (lenient) so setup failures surface as clear "Setup failed" errors.

Naming reflects the PRD revenue-cycle stages:
  reference data (payer/patient/policy) -> encounter -> charges -> eligibility ->
  discharge -> coding (draft/finalize/clear) -> claim (submit/adjudicate/deny/...) ->
  statement (issue/pay/collections/write-off).
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import TEST_USERS, make_coder_headers, make_finance_headers
from .factories import (
    create_payer_payload,
    create_patient_payload,
    create_policy_payload,
    create_encounter_payload,
    create_charge_payload,
    create_coding_payload,
    submit_claim_payload,
    adjudicate_payload,
    single_line,
    deny_payload,
    payment_payload,
)

REGISTRAR = TEST_USERS["registrar_headers"]
CODER = TEST_USERS["coder_headers"]
BILLING = TEST_USERS["billing_headers"]
FINANCE = TEST_USERS["finance_headers"]


# ---------------------------------------------------------------------------
# Test clock
# ---------------------------------------------------------------------------
def set_clock(iso8601: str, headers=BILLING):
    """Set the server's current UTC clock for deterministic temporal tests."""
    return get_success_data(api_client.set_clock(iso8601, headers))


# ---------------------------------------------------------------------------
# Tier 1: reference data
# ---------------------------------------------------------------------------
def create_payer(active=True, **overrides):
    payload = create_payer_payload(active=active, **overrides)
    return get_success_data(api_client.create_payer(payload, REGISTRAR))


def create_patient(**overrides):
    payload = create_patient_payload(**overrides)
    return get_success_data(api_client.create_patient(payload, REGISTRAR))


def create_policy(patient_id, payer_id, **overrides):
    payload = create_policy_payload(patient_id, payer_id, **overrides)
    return get_success_data(api_client.create_policy(payload, REGISTRAR))


def create_active_policy(deductible_cents=100000, coinsurance_pct=0.20,
                         oop_max_cents=500000, plan_year=2026, payer=None,
                         patient=None, member_number="M-001"):
    """Create payer + patient + policy, then verify -> ACTIVE (opens accumulator).
    Returns (payer, patient, policy)."""
    if payer is None:
        payer = create_payer(active=True)
    if patient is None:
        patient = create_patient()
    policy = create_policy(
        patient["id"], payer["id"],
        member_number=member_number, plan_year=plan_year,
        deductible_cents=deductible_cents, coinsurance_pct=coinsurance_pct,
        oop_max_cents=oop_max_cents,
    )
    policy = get_success_data(api_client.verify_policy(policy["id"], REGISTRAR))
    return payer, patient, policy


def get_benefit_accumulator_for_policy(policy_id, headers=BILLING):
    """Return the BenefitAccumulator row for a policy (opened on verify)."""
    data, _meta = _list(api_client.list_benefit_accumulators(headers, params={"policy_id": policy_id}))
    assert data, f"no benefit accumulator found for policy {policy_id}"
    return data[0]


def _list(response):
    """Return (data_list, meta) from a paginated list response."""
    body = response.json()
    return body.get("data", []), body.get("meta", {})


# ---------------------------------------------------------------------------
# Tier 2: encounter + charges + eligibility
# ---------------------------------------------------------------------------
def create_encounter(patient_id, policy_id=None, admission_at="2026-03-01T09:00:00Z"):
    overrides = {"admission_at": admission_at}
    if policy_id is not None:
        overrides["policy_id"] = policy_id
    payload = create_encounter_payload(patient_id, **overrides)
    return get_success_data(api_client.create_encounter(payload, REGISTRAR))


def add_charge(encounter_id, cpt_code="99285", units=1, unit_price_cents=300000):
    payload = create_charge_payload(cpt_code=cpt_code, units=units, unit_price_cents=unit_price_cents)
    return get_success_data(api_client.create_charge(encounter_id, payload, REGISTRAR))


def run_eligibility(encounter_id):
    return get_success_data(api_client.create_eligibility_check(encounter_id, REGISTRAR))


def setup_registered_encounter(deductible_cents=100000, coinsurance_pct=0.20,
                               oop_max_cents=500000, member_number="M-001",
                               admission_at="2026-03-01T09:00:00Z"):
    """ACTIVE policy + a REGISTERED encounter referencing it (no charges yet).
    Returns (payer, patient, policy, encounter)."""
    payer, patient, policy = create_active_policy(
        deductible_cents=deductible_cents, coinsurance_pct=coinsurance_pct,
        oop_max_cents=oop_max_cents, member_number=member_number,
    )
    encounter = create_encounter(patient["id"], policy["id"], admission_at=admission_at)
    return payer, patient, policy, encounter


def setup_eligibility_verified_encounter(charge_cents=300000, **policy_kwargs):
    """REGISTERED encounter with one POSTED charge, advanced to ELIGIBILITY_VERIFIED.
    Returns (payer, patient, policy, encounter)."""
    payer, patient, policy, encounter = setup_registered_encounter(**policy_kwargs)
    add_charge(encounter["id"], unit_price_cents=charge_cents)
    run_eligibility(encounter["id"])
    encounter = get_success_data(api_client.get_encounter(encounter["id"], REGISTRAR))
    return payer, patient, policy, encounter


# ---------------------------------------------------------------------------
# Tier 3: coding (draft / finalize / clear) -> CODED encounter
# ---------------------------------------------------------------------------
def create_coding(encounter_id, principal_icd10="E11.65", secondary_icd10=None,
                  coder_headers=CODER):
    overrides = {"principal_icd10": principal_icd10}
    if secondary_icd10 is not None:
        overrides["secondary_icd10"] = secondary_icd10
    payload = create_coding_payload(**overrides)
    return get_success_data(api_client.create_coding_assignment(encounter_id, payload, coder_headers))


def setup_charges_captured_encounter(principal_icd10="E11.65", secondary_icd10=None,
                                     charge_cents=300000, extra_charges=None,
                                     coder_user_id=None, **policy_kwargs):
    """Encounter discharged to CHARGES_CAPTURED with a DRAFT coding assignment.

    `extra_charges` is an optional list of (cpt_code, unit_price_cents) tuples posted
    in addition to the primary 99285 charge (used to vary distinct CPT counts).
    `coder_user_id` controls the X-User-ID of the Coder who creates/finalizes coding.
    Returns (payer, patient, policy, encounter, coding)."""
    payer, patient, policy, encounter = setup_registered_encounter(**policy_kwargs)
    add_charge(encounter["id"], cpt_code="99285", unit_price_cents=charge_cents)
    if extra_charges:
        for cpt, price in extra_charges:
            add_charge(encounter["id"], cpt_code=cpt, unit_price_cents=price)
    run_eligibility(encounter["id"])
    get_success_data(api_client.discharge_encounter(encounter["id"], REGISTRAR))
    coder_headers = make_coder_headers(coder_user_id) if coder_user_id else CODER
    coding = create_coding(
        encounter["id"], principal_icd10=principal_icd10,
        secondary_icd10=secondary_icd10, coder_headers=coder_headers,
    )
    encounter = get_success_data(api_client.get_encounter(encounter["id"], REGISTRAR))
    return payer, patient, policy, encounter, coding


def setup_coded_encounter(principal_icd10="E11.65", secondary_icd10=None,
                          charge_cents=300000, coder_user_id=None, **policy_kwargs):
    """CODED encounter: coding finalized and cleared (bubbles encounter CHARGES_CAPTURED->CODED).
    Returns (payer, patient, policy, encounter, coding)."""
    payer, patient, policy, encounter, coding = setup_charges_captured_encounter(
        principal_icd10=principal_icd10, secondary_icd10=secondary_icd10,
        charge_cents=charge_cents, coder_user_id=coder_user_id, **policy_kwargs,
    )
    coder_headers = make_coder_headers(coder_user_id) if coder_user_id else CODER
    get_success_data(api_client.finalize_coding(coding["id"], coder_headers))
    get_success_data(api_client.clear_coding(coding["id"], BILLING))
    encounter = get_success_data(api_client.get_encounter(encounter["id"], REGISTRAR))
    coding = get_success_data(api_client.get_coding_assignment(coding["id"], BILLING))
    return payer, patient, policy, encounter, coding


# ---------------------------------------------------------------------------
# Tier 3b: claim submission
# ---------------------------------------------------------------------------
def submit_claim(encounter_id, payer_id, headers=BILLING):
    """Submit a claim using the encounter's current version as expected_encounter_version."""
    enc = get_success_data(api_client.get_encounter(encounter_id, headers))
    payload = submit_claim_payload(payer_id, enc["version"])
    return get_success_data(api_client.submit_claim(encounter_id, payload, headers))


def setup_submitted_claim(charge_cents=300000, coder_user_id=None, **policy_kwargs):
    """CODED encounter with a SUBMITTED claim.
    Returns (payer, patient, policy, encounter, coding, claim)."""
    payer, patient, policy, encounter, coding = setup_coded_encounter(
        charge_cents=charge_cents, coder_user_id=coder_user_id, **policy_kwargs,
    )
    claim = submit_claim(encounter["id"], payer["id"])
    return payer, patient, policy, encounter, coding, claim


# ---------------------------------------------------------------------------
# Tier 4: adjudication / denial -> statements
# ---------------------------------------------------------------------------
def adjudicate(claim_id, allowed_amount_cents, cpt_code="99285", headers=BILLING):
    payload = adjudicate_payload(
        allowed_amount_cents, single_line(cpt_code, allowed_amount_cents)
    )
    return get_success_data(api_client.adjudicate_claim(claim_id, payload, headers))


def deny(claim_id, denial_reason, headers=BILLING):
    return get_success_data(api_client.deny_claim(claim_id, deny_payload(denial_reason), headers))


def get_statement_for_encounter(encounter_id, headers=BILLING):
    """Return the (first) PatientStatement for an encounter, or None if none issued."""
    data, _meta = _list(api_client.list_statements_for_encounter(encounter_id, headers))
    return data[0] if data else None


def setup_partially_paid_statement(allowed_amount_cents=200000, charge_cents=300000,
                                   coder_user_id=None, **policy_kwargs):
    """Adjudicate a claim with a positive patient responsibility so a PatientStatement is
    issued (ISSUED). Returns (payer, patient, policy, encounter, coding, claim, statement)."""
    payer, patient, policy, encounter, coding, claim = setup_submitted_claim(
        charge_cents=charge_cents, coder_user_id=coder_user_id, **policy_kwargs,
    )
    adjudicate(claim["id"], allowed_amount_cents)
    statement = get_statement_for_encounter(encounter["id"])
    encounter = get_success_data(api_client.get_encounter(encounter["id"], REGISTRAR))
    return payer, patient, policy, encounter, coding, claim, statement


def setup_denied_statement(denial_reason="NOT_COVERED", charge_cents=300000,
                           coder_user_id=None, **policy_kwargs):
    """Deny a claim so the full balance is billed and a PatientStatement (ISSUED) is created.
    Returns (payer, patient, policy, encounter, coding, claim, statement)."""
    payer, patient, policy, encounter, coding, claim = setup_submitted_claim(
        charge_cents=charge_cents, coder_user_id=coder_user_id, **policy_kwargs,
    )
    deny(claim["id"], denial_reason)
    statement = get_statement_for_encounter(encounter["id"])
    encounter = get_success_data(api_client.get_encounter(encounter["id"], REGISTRAR))
    return payer, patient, policy, encounter, coding, claim, statement


# ---------------------------------------------------------------------------
# Tier 5: collections / write-off (terminal)
# ---------------------------------------------------------------------------
def setup_in_collections_statement(issued_clock="2026-03-01T00:00:00Z",
                                   aged_clock="2026-08-01T00:00:00Z",
                                   partial_payment_cents=None,
                                   denial=True, allowed_amount_cents=200000,
                                   coder_user_id=None, member_number="M-001",
                                   **policy_kwargs):
    """Drive a statement to IN_COLLECTIONS.

    Sets the clock to `issued_clock` before building the encounter so issued_at is fixed,
    optionally posts a partial payment, then advances the clock past the 120-day aging
    window (`aged_clock`) and sends to collections.
    Returns (payer, patient, policy, encounter, statement)."""
    set_clock(issued_clock)
    if denial:
        payer, patient, policy, encounter, coding, claim, statement = setup_denied_statement(
            coder_user_id=coder_user_id, member_number=member_number, **policy_kwargs,
        )
    else:
        payer, patient, policy, encounter, coding, claim, statement = setup_partially_paid_statement(
            allowed_amount_cents=allowed_amount_cents, coder_user_id=coder_user_id,
            member_number=member_number, **policy_kwargs,
        )
    if partial_payment_cents:
        get_success_data(api_client.post_payment(
            statement["id"], payment_payload(partial_payment_cents), BILLING
        ))
    set_clock(aged_clock)
    get_success_data(api_client.send_statement_to_collections(statement["id"], BILLING))
    statement = get_success_data(api_client.get_statement(statement["id"], FINANCE))
    encounter = get_success_data(api_client.get_encounter(encounter["id"], REGISTRAR))
    return payer, patient, policy, encounter, statement
