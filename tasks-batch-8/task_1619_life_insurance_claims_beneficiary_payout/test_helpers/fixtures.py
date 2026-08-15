"""Composite setup helpers.

Multi-step preconditions (reviewed claims, approved claims with validated
beneficiaries, funded retained asset accounts, legal-hold disputes) are built
here so tests focus on assertions. All helpers use the lenient
get_success_data() validator so setup failures surface as clear
"Setup failed" errors. Every chain replays from an empty database using only
PRD-declared endpoints.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_FILING, STATUTE_PRESETS
from .factories import (
    create_beneficiary_claim_payload,
    create_claim_payload,
    create_designation_payload,
    create_dmf_match_payload,
    create_document_payload,
    create_election_payload,
    create_policy_payload,
    create_statute_payload,
)
from .test_users import (
    APPROVER_1,
    EXAMINER_1,
    EXAMINER_2,
    TEST_USERS,
)

POLICY_ADMIN = TEST_USERS["policy_administrator_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
LEGAL = TEST_USERS["legal_counsel_headers"]
SYSADMIN = TEST_USERS["system_admin_headers"]


# ---------------------------------------------------------------------------
# Tier 0: clock, statutes, policies, designations
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str):
    """Pin the server logical clock (PRD §2.4); also runs the time-based sweep."""
    resp = api_client.set_logical_clock(to_iso8601, SYSADMIN)
    return get_success_data(resp)


def create_statute(state: str = "IL", **overrides):
    """Configure a state's claims statute from a preset plus overrides."""
    merged = dict(STATUTE_PRESETS[state])
    merged.update(overrides)
    payload = create_statute_payload(**merged)
    resp = api_client.create_state_statute(payload, COMPLIANCE)
    return get_success_data(resp)


def create_policy(state_code: str = "IL", **overrides):
    payload = create_policy_payload(state_code=state_code, **overrides)
    resp = api_client.create_policy(payload, POLICY_ADMIN)
    return get_success_data(resp)


def create_policy_with_statute(state: str = "IL", statute_overrides=None,
                               **policy_overrides):
    """Statute + policy for that state. Returns the policy."""
    create_statute(state, **(statute_overrides or {}))
    return create_policy(state_code=state, **policy_overrides)


def get_policy(policy_id: str):
    resp = api_client.get_policy(policy_id, POLICY_ADMIN)
    return get_success_data(resp)


def create_designation(policy_id: str, expected_policy_version=None, **overrides):
    """Add a beneficiary designation (OCC-guarded on the policy version).
    When expected_policy_version is None the current version is fetched first."""
    if expected_policy_version is None:
        expected_policy_version = get_policy(policy_id)["version"]
    payload = create_designation_payload(
        expected_policy_version=expected_policy_version, **overrides)
    resp = api_client.create_beneficiary_designation(policy_id, payload, POLICY_ADMIN)
    return get_success_data(resp)


def list_designations(policy_id: str, params=None):
    resp = api_client.list_beneficiary_designations(policy_id, POLICY_ADMIN, params=params)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 1: claims and proof-of-death documents
# ---------------------------------------------------------------------------

def file_claim(policy_id: str, date_of_death: str = "2026-03-01", headers=None,
               **overrides):
    payload = create_claim_payload(policy_id=policy_id, date_of_death=date_of_death,
                                   **overrides)
    resp = api_client.create_claim(payload, headers or EXAMINER_1)
    return get_success_data(resp)


def get_claim(claim_id: str, headers=None):
    resp = api_client.get_claim(claim_id, headers or EXAMINER_1)
    return get_success_data(resp)


def list_claims(params=None, headers=None):
    resp = api_client.list_claims(headers or EXAMINER_1, params=params)
    return get_success_data(resp)


def begin_review(claim_id: str, headers=None):
    resp = api_client.begin_review(claim_id, headers or EXAMINER_1)
    return get_success_data(resp)


def upload_document(claim_id: str, doc_type: str = "CERTIFIED_DEATH_CERTIFICATE",
                    headers=None):
    payload = create_document_payload(doc_type=doc_type)
    resp = api_client.upload_document(claim_id, payload, headers or EXAMINER_1)
    return get_success_data(resp)


def review_document(claim_id: str, document_id: str, review_result: str = "VERIFIED",
                    headers=None, **overrides):
    payload = {"review_result": review_result}
    payload.update(overrides)
    resp = api_client.review_document(claim_id, document_id, payload,
                                      headers or EXAMINER_2)
    return get_success_data(resp)


def file_claim_with_verified_docs(policy_id: str, date_of_death: str = "2026-03-01",
                                  filing_clock: str = CLOCK_FILING,
                                  review_clock: str = None,
                                  doc_types=("CERTIFIED_DEATH_CERTIFICATE",),
                                  begin: bool = True):
    """File a claim at filing_clock, upload the given document types, have them
    reviewed VERIFIED by a different examiner (at review_clock when given),
    then begin review. Returns (claim_after_begin_or_filing, documents)."""
    set_clock(filing_clock)
    claim = file_claim(policy_id, date_of_death)
    docs = [upload_document(claim["id"], dt) for dt in doc_types]
    if review_clock is not None:
        set_clock(review_clock)
    for doc in docs:
        review_document(claim["id"], doc["id"], "VERIFIED")
    if begin:
        claim = begin_review(claim["id"])
    return claim, docs


def approve_claim(claim_id: str, headers=None):
    resp = api_client.approve_claim(claim_id, headers or APPROVER_1)
    return get_success_data(resp)


def execute_payment(claim_id: str, headers=None):
    resp = api_client.execute_payment(claim_id, headers or APPROVER_1)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 2: beneficiary claims
# ---------------------------------------------------------------------------

def file_beneficiary_claim(claim_id: str, headers=None, **overrides):
    payload = create_beneficiary_claim_payload(**overrides)
    resp = api_client.file_beneficiary_claim(claim_id, payload, headers or EXAMINER_1)
    return get_success_data(resp)


def get_beneficiary_claim(beneficiary_claim_id: str, headers=None):
    resp = api_client.get_beneficiary_claim(beneficiary_claim_id, headers or EXAMINER_1)
    return get_success_data(resp)


def list_beneficiary_claims_of(claim_id: str, params=None, headers=None):
    resp = api_client.list_claim_beneficiary_claims(claim_id, headers or EXAMINER_1,
                                                    params=params)
    return get_success_data(resp)


def validate_beneficiary_claim(beneficiary_claim_id: str, headers=None):
    resp = api_client.validate_beneficiary_claim(beneficiary_claim_id,
                                                 headers or EXAMINER_1)
    return get_success_data(resp)


def withdraw_beneficiary_claim(beneficiary_claim_id: str, headers=None):
    resp = api_client.withdraw_beneficiary_claim(beneficiary_claim_id,
                                                 headers or EXAMINER_1)
    return get_success_data(resp)


def reject_beneficiary_claim(beneficiary_claim_id: str, rejection_reason: str,
                             headers=None):
    resp = api_client.reject_beneficiary_claim(
        beneficiary_claim_id, {"rejection_reason": rejection_reason},
        headers or EXAMINER_1)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 3: payout elections
# ---------------------------------------------------------------------------

def create_election(beneficiary_claim_id: str, claim_id: str, option: str = "LUMP_SUM",
                    expected_claim_version=None, headers=None):
    """Record a settlement election (OCC-guarded on the claim version). When
    expected_claim_version is None the current claim version is fetched first."""
    if expected_claim_version is None:
        expected_claim_version = get_claim(claim_id)["version"]
    payload = create_election_payload(
        option=option, expected_claim_version=expected_claim_version)
    resp = api_client.create_payout_election(beneficiary_claim_id, payload,
                                             headers or EXAMINER_1)
    return get_success_data(resp)


def confirm_election(election_id: str, headers=None):
    resp = api_client.confirm_payout_election(election_id, headers or EXAMINER_1)
    return get_success_data(resp)


def list_elections(beneficiary_claim_id: str, params=None, headers=None):
    resp = api_client.list_payout_elections(beneficiary_claim_id, headers or EXAMINER_1,
                                            params=params)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 4: composite lifecycle fixtures
# ---------------------------------------------------------------------------

def setup_approved_claim(state: str = "TX", statute_overrides=None,
                         face_amount_cents: int = 10000000,
                         beneficiaries=None,
                         date_of_death: str = "2026-03-01",
                         filing_clock: str = CLOCK_FILING,
                         approve_clock: str = None,
                         policy_overrides=None):
    """Full chain through approval: statute + policy + designations + claim +
    verified CERTIFIED_DEATH_CERTIFICATE + begin-review + one beneficiary claim
    per spec (filed and validated) + approve.

    beneficiaries: list of dicts {"name", "type", "share", "effective_date"?}
    where type is PRIMARY/CONTINGENT (a designation is created and cited) or
    ESTATE (no designation). Pass an empty list for an empty allocation pool.

    Returns a ctx dict: policy, claim (post-approve), designations (parallel to
    beneficiaries, None for ESTATE), beneficiary_claims, documents.
    """
    if beneficiaries is None:
        beneficiaries = [{"name": "Alice Roe", "type": "PRIMARY", "share": 100}]
    policy = create_policy_with_statute(
        state, statute_overrides=statute_overrides,
        face_amount_cents=face_amount_cents, **(policy_overrides or {}))
    designations = []
    for spec in beneficiaries:
        if spec["type"] == "ESTATE":
            designations.append(None)
        else:
            des = create_designation(
                policy["id"],
                beneficiary_name=spec["name"],
                beneficiary_type=spec["type"],
                share_percent=spec["share"],
                effective_date=spec.get("effective_date", "2024-03-01"),
            )
            designations.append(des)
    claim, docs = file_claim_with_verified_docs(
        policy["id"], date_of_death=date_of_death, filing_clock=filing_clock)
    bcs = []
    for spec, des in zip(beneficiaries, designations):
        overrides = {
            "claimant_name": spec["name"],
            "claimant_type": "ESTATE" if spec["type"] == "ESTATE" else "NAMED_BENEFICIARY",
        }
        if des is not None:
            overrides["designation_id"] = des["id"]
        bc = file_beneficiary_claim(claim["id"], **overrides)
        validate_beneficiary_claim(bc["id"])
        bcs.append(bc)
    if approve_clock is not None:
        set_clock(approve_clock)
    claim = approve_claim(claim["id"])
    return {
        "policy": policy,
        "claim": claim,
        "designations": designations,
        "beneficiary_claims": bcs,
        "documents": docs,
    }


def setup_election(ctx: dict, option: str = "LUMP_SUM", confirm: bool = True,
                   beneficiary_index: int = 0):
    """Create (and optionally confirm) a payout election for one beneficiary
    claim of an approved-claim ctx. Returns the election."""
    claim = ctx["claim"]
    bc = ctx["beneficiary_claims"][beneficiary_index]
    election = create_election(bc["id"], claim["id"], option=option)
    if confirm:
        election = confirm_election(election["id"])
    ctx["election"] = election
    return election


def list_accounts(params=None, headers=None):
    resp = api_client.list_retained_asset_accounts(headers or APPROVER_1, params=params)
    return get_success_data(resp)


def get_account(account_id: str, headers=None):
    resp = api_client.get_retained_asset_account(account_id, headers or APPROVER_1)
    return get_success_data(resp)


def setup_paid_claim_with_raa(payment_clock: str = None, **approved_kwargs):
    """Approved claim + confirmed RETAINED_ASSET_ACCOUNT election +
    execute-payment. Returns ctx dict additionally carrying election and the
    single retained asset account created by the payment."""
    ctx = setup_approved_claim(**approved_kwargs)
    setup_election(ctx, option="RETAINED_ASSET_ACCOUNT", confirm=True)
    if payment_clock is not None:
        set_clock(payment_clock)
    ctx["claim"] = execute_payment(ctx["claim"]["id"])
    accounts = list_accounts({"claim_id": ctx["claim"]["id"]})
    assert isinstance(accounts, list) and len(accounts) == 1, (
        f"Setup failed: expected exactly one retained asset account, got {accounts}")
    ctx["account"] = accounts[0]
    return ctx


def setup_dormant_raa(dormancy_years: int = 3, **approved_kwargs):
    """Funded retained asset account swept past its dormancy anniversary.
    The account is funded at 2026-04-01 and the clock is then advanced one day
    past the anniversary (strictly-more-than rule, PRD §3.9), flipping it
    DORMANT and spawning a DUE_DILIGENCE escheatment case (its due-diligence
    start already lies in the past). Returns ctx with account and case."""
    ctx = setup_paid_claim_with_raa(
        payment_clock="2026-04-01T00:00:00Z",
        statute_overrides={"dormancy_years": dormancy_years},
        **approved_kwargs)
    anniversary = {3: "2029-04-02T00:00:00Z", 5: "2031-04-02T00:00:00Z"}[dormancy_years]
    set_clock(anniversary)
    ctx["account"] = get_account(ctx["account"]["id"])
    cases = list_escheatment_cases({"account_id": ctx["account"]["id"]})
    assert isinstance(cases, list) and len(cases) == 1, (
        f"Setup failed: expected exactly one escheatment case, got {cases}")
    ctx["case"] = cases[0]
    return ctx


# ---------------------------------------------------------------------------
# Tier 5: escheatment cases and death-master matches
# ---------------------------------------------------------------------------

def list_escheatment_cases(params=None, headers=None):
    resp = api_client.list_escheatment_cases(headers or COMPLIANCE, params=params)
    return get_success_data(resp)


def get_escheatment_case(case_id: str, headers=None):
    resp = api_client.get_escheatment_case(case_id, headers or COMPLIANCE)
    return get_success_data(resp)


def create_dmf_match(policy_id: str, headers=None, **overrides):
    payload = create_dmf_match_payload(**overrides)
    resp = api_client.create_death_master_match(policy_id, payload,
                                                headers or COMPLIANCE)
    return get_success_data(resp)
