"""Prior-authorization branching fork, its RBAC, and rate-ingest OCC."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    create_negotiated_rate_payload, create_prior_authorization_payload,
    approve_prior_authorization_payload,
    fixtures, TEST_USERS,
)

PROVIDER = TEST_USERS["provider_staff_headers"]
PAYER = TEST_USERS["payer_analyst_headers"]


def _selfpay_estimate_with_two_prior_auths(api):
    plan = fixtures.new_benefit_plan(api)
    patient = fixtures.new_patient(api, plan["id"])
    estimate = fixtures.new_estimate(api, patient["id"], estimate_type="GFE_SELFPAY")
    pa1 = validate_success(api.create_prior_authorization(
        create_prior_authorization_payload(estimate["id"], procedure_code="70450"),
        PROVIDER), 201)
    pa2 = validate_success(api.create_prior_authorization(
        create_prior_authorization_payload(estimate["id"], procedure_code="74177"),
        PROVIDER), 201)
    return pa1, pa2


# --------------------------------------------------------------------------
# Difficulty — REQUESTED forks to APPROVED / DENIED
# --------------------------------------------------------------------------
def test_prior_auth_approve_branch(api):
    """PRD §3.6: "Approval advances it from REQUESTED to APPROVED, sets the
    payer-issued auth_number, the approved_units granted, and the expiration_date
    after which the authorization is no longer valid, and increments its version
    by 1."

    Design: Difficulty/non_linear_state_machine/nlsm_prior_auth_branching
    """
    pa1, _ = _selfpay_estimate_with_two_prior_auths(api)
    approved = validate_success(api.approve_prior_authorization(
        pa1["id"],
        approve_prior_authorization_payload(auth_number="AUTH-1", approved_units=1),
        PAYER), 200)
    assert approved["status"] == "APPROVED"
    assert approved["auth_number"] == "AUTH-1"


def test_prior_auth_deny_branch(api):
    """PRD §3.6: "Denial advances it from `REQUESTED` to `DENIED`, records a
    `denial_reason`, and increments its `version` by 1."

    Design: Difficulty/non_linear_state_machine/nlsm_prior_auth_branching
    """
    pa1, pa2 = _selfpay_estimate_with_two_prior_auths(api)
    validate_success(api.approve_prior_authorization(
        pa1["id"], approve_prior_authorization_payload(auth_number="AUTH-1"), PAYER), 200)
    denied = validate_success(api.deny_prior_authorization(
        pa2["id"], {"denial_reason": "Not medically necessary"}, PAYER), 200)
    assert denied["status"] == "DENIED"
    assert denied["denial_reason"] == "Not medically necessary"


# --------------------------------------------------------------------------
# Corner — RBAC on approve
# --------------------------------------------------------------------------
def test_provider_cannot_approve_prior_auth(api):
    """PRD §2.1: "When the headers are well-formed but the acting role is not
    permitted to perform the requested operation, the request is rejected with
    ERR_UNAUTHORIZED." Section 4 authorizes only PayerAnalyst for approve.

    Design: Corner/rbac/provider_cannot_approve_prior_auth
    """
    pa1, _ = _selfpay_estimate_with_two_prior_auths(api)
    resp = api.approve_prior_authorization(
        pa1["id"], approve_prior_authorization_payload(auth_number="AUTH-Z"), PROVIDER)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value, 403)


# --------------------------------------------------------------------------
# Corner — rate ingest OCC on contract version
# --------------------------------------------------------------------------
def test_stale_contract_version_on_second_ingest(api):
    """PRD §2.6: "If expected_contract_version does not equal the contract's
    current version, the ingest is rejected with ERR_STALE_CONTRACT_VERSION
    (HTTP 412). A newer rate for the same contract-and-procedure pair supersedes
    the prior one, so a stale contract version signals that another ingest batch
    already advanced the contract."

    Design: Corner/cross_cutting_complexity_layers/occ_rate_stale_contract_version_conflict
    """
    contract = fixtures.new_contract(api)  # DRAFT, version 1
    procedure = fixtures.new_procedure(api)
    stale_version = contract["version"]
    fixtures.ingest_flat_rate(api, contract["id"], procedure["id"], 200000,
                              expected_contract_version=stale_version)  # -> version 2
    payload = create_negotiated_rate_payload(
        contract["id"], procedure["id"], stale_version,
        rate_type="FLAT", flat_amount_cents=250000)
    resp = api.create_negotiated_rate(payload, PAYER)
    validate_error(resp, ApiErrorId.ERR_STALE_CONTRACT_VERSION.value, 412)
