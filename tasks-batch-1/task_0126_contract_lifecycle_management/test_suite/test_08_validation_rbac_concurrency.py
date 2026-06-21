"""Cross-cutting guards: clause-key uniqueness, signer completeness, RBAC denials,
authentication, optimistic concurrency on the contract aggregate, and the
not-found error for an unknown non-contract resource.

Tests here translate queue B (Corner) instances under sections validations, rbac,
cross_cutting_complexity_layers, and errors.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success, validate_error,
    factories as F, fixtures as FX,
    build_user_headers,
    ApiErrorId,
)

ADMIN = FX.ADMIN
LIBRARIAN = FX.LIBRARIAN
MGR = FX.MGR


@pytest.fixture
def api():
    return api_client


# ─── validations ──────────────────────────────────────────────────────

def test_duplicate_active_clause_key_rejected(api):
    """PRD §3.1: "An attempt to create a clause template whose key already belongs to
    an active clause of that organization is rejected with ERR_DUPLICATE_CLAUSE_KEY."

    Design: Corner/validations/duplicate_clause_key_among_active_returns_conflict
    """
    org = FX.create_organization(api)
    FX.create_clause(api, org["id"], clause_key="LIABILITY_CAP", risk_weight=10, category="LIABILITY")
    resp = api.create_clause_template(
        F.create_clause_template_payload(
            org["id"], clause_key="LIABILITY_CAP", category="LIABILITY",
            standard_text="s2", risk_weight=20,
        ),
        LIBRARIAN,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_CLAUSE_KEY.value, 409)


def test_send_for_signature_missing_counterparty_signer_rejected(api):
    """PRD §3.5: "The signer gate requires that the signers list contain at least one
    signer whose side is INTERNAL and at least one whose side is COUNTERPARTY; an
    incomplete list is refused with ERR_SIGNERS_INCOMPLETE."

    Design: Corner/validations/send_for_signature_missing_counterparty_signer
    """
    setup = FX.setup_approved_contract(
        api, FX.simple_clause_defs(), FX.simple_clauses_spec(),
        org_overrides={"risk_appetite_threshold": 100},
    )
    approved = setup["contract_approved"]
    resp = api.send_for_signature(
        approved["id"],
        F.send_for_signature_payload(approved["version"], [F.signer_entry("INTERNAL", "Us")]),
        MGR,
    )
    validate_error(resp, ApiErrorId.ERR_SIGNERS_INCOMPLETE.value, 409)


# ─── rbac ─────────────────────────────────────────────────────────────

def test_contract_manager_cannot_create_clause_template(api):
    """PRD §2.1: "When the headers are valid but the named role is not permitted to
    invoke the requested operation, the request is rejected with ERR_UNAUTHORIZED."
    A ClauseLibrarian "owns the configuration libraries — clause templates"; a
    ContractManager does not.

    Design: Corner/rbac/contract_manager_cannot_create_clause_template
    """
    org = FX.create_organization(api)
    resp = api.create_clause_template(
        F.create_clause_template_payload(org["id"], clause_key="K"), MGR
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value, 403)


def test_risk_officer_cannot_record_approval_step(api):
    """PRD §2.1: "A ContractApprover records approve and reject decisions on approval
    workflows." A RiskOfficer is a distinct seat ("grants or denies deviation
    approvals"); calling the approver-only endpoint yields ERR_UNAUTHORIZED.

    Design: Corner/rbac/risk_officer_cannot_record_approval_step
    """
    setup = FX.setup_under_review(
        api, FX.simple_clause_defs(), FX.simple_clauses_spec(),
        org_overrides={"risk_appetite_threshold": 100},
    )
    resp = api.create_approval_step(
        setup["workflow"]["id"], F.approval_step_payload(setup["workflow"]["id"], "APPROVE"),
        build_user_headers("risk-1", "RiskOfficer"),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value, 403)


def test_unknown_role_returns_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or if X-User-Role does not name a role
    the system recognizes, the request is rejected with ERR_UNAUTHENTICATED."

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    org = FX.create_organization(api)
    resp = api.get_organization(org["id"], build_user_headers("x", "BogusRole"))
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)


# ─── cross_cutting: optimistic concurrency ────────────────────────────

def test_submit_with_stale_expected_version_rejected(api):
    """PRD §2.7: "Submitting a contract for review requires expected_contract_version
    to match the contract's current version; if another writer has already created a
    new version and thereby advanced the contract, the submit is rejected with
    ERR_STALE_VERSION (HTTP 412)".

    Design: Corner/cross_cutting_complexity_layers/occ_stale_contract_version_on_submit
    """
    org = FX.create_organization(api, risk_appetite_threshold=100)
    clause = FX.create_clause(api, org["id"], clause_key="K")
    template = FX.create_contract_template(api, org["id"], [clause["id"]])
    contract = FX.create_contract(api, org["id"], template["id"])
    c_v0 = contract["version"]
    # A version-create bumps the contract's version beyond c_v0.
    FX.add_version(api, contract["id"], [F.clause_entry(clause["id"], text="s")], c_v0)
    # Submit carrying the pre-bump (stale) version.
    resp = api.submit_contract(contract["id"], F.submit_payload(c_v0), MGR)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value, 412)


def test_version_create_with_stale_expected_version_rejected(api):
    """PRD §2.7: "creating a new contract version requires expected_contract_version
    to match the contract's current version; a writer working from a stale view is
    rejected with ERR_STALE_VERSION (HTTP 412) rather than being allowed to branch
    the redline history off a version that is no longer current."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_contract_version_on_version_create
    """
    org = FX.create_organization(api, risk_appetite_threshold=100)
    clause = FX.create_clause(api, org["id"], clause_key="K")
    template = FX.create_contract_template(api, org["id"], [clause["id"]])
    contract = FX.create_contract(api, org["id"], template["id"])
    c_v0 = contract["version"]
    FX.add_version(api, contract["id"], [F.clause_entry(clause["id"], text="s")], c_v0)  # bumps version
    # A second version-create reusing the now-stale c_v0.
    resp = api.create_version(
        contract["id"],
        F.create_version_payload(contract["id"], [F.clause_entry(clause["id"], text="s2")], c_v0),
        MGR,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value, 412)


def test_contract_version_increments_on_mutation(api):
    """PRD §2.4: "The version field is an integer that starts at its initial value and
    increments by one on every mutation of the resource".

    Design: Corner/cross_cutting_complexity_layers/version_increments_on_every_mutation
    """
    org = FX.create_organization(api)
    clause = FX.create_clause(api, org["id"], clause_key="K")
    template = FX.create_contract_template(api, org["id"], [clause["id"]])
    contract = FX.create_contract(api, org["id"], template["id"])
    assert contract["version"] == 1, f"contract.version must start at 1, got {contract['version']}"
    FX.add_version(api, contract["id"], [F.clause_entry(clause["id"], text="s")], contract["version"])
    after = FX.get_contract(api, contract["id"])
    assert after["version"] == 2, \
        f"contract.version must increment to 2 after the version-create mutation, got {after['version']}"


# ─── errors ───────────────────────────────────────────────────────────

def test_unknown_workflow_returns_resource_not_found(api):
    """PRD §2.6: "For a path whose leading identifier addresses a non-contract
    resource — a clause template, contract template, organization, approval workflow,
    signature request, obligation, deviation approval, or contract version — a
    missing resource yields ERR_RESOURCE_NOT_FOUND."

    Design: Corner/errors/resource_not_found_on_unknown_workflow
    """
    resp = api.get_approval_workflow(
        "22222222-2222-4222-8222-222222222222", FX.APPROVER
    )
    validate_error(resp, ApiErrorId.ERR_RESOURCE_NOT_FOUND.value, 404)
