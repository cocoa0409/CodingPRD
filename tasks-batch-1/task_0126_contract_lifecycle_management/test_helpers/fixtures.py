"""Composite setup helpers for the Contract Lifecycle Management API.

Each test starts against an empty database (the runner restarts the server before
every test), so every fixture builds its preconditions from scratch using only
PRD-declared endpoints. Helpers use the lenient get_success_data() validator so a
broken setup surfaces a clear "Setup step failed" message.

Default operator identities (all roles are opaque, PRD §2.1):
  drafter / ContractManager : "mgr-1"
  ContractApprover          : "appr-1"  (distinct from drafter -> SoD satisfied)
  RiskOfficer               : "risk-1"  (distinct from drafter -> SoD satisfied)
  internal Signer           : "signer-int"
  counterparty Signer       : "signer-cp"
  PlatformAdmin             : "admin-1"
  ClauseLibrarian           : "librarian-1"

Any of these can be overridden so a test can make, e.g., the approver equal to the
drafter to exercise ERR_SELF_APPROVAL.
"""
from prd_bench_local_runner.testing import get_success_data, build_user_headers

from . import factories as F

# ─── Default operator headers ─────────────────────────────────────────
ADMIN = build_user_headers("admin-1", "PlatformAdmin")
LIBRARIAN = build_user_headers("librarian-1", "ClauseLibrarian")
MGR = build_user_headers("mgr-1", "ContractManager")
APPROVER = build_user_headers("appr-1", "ContractApprover")
RISK = build_user_headers("risk-1", "RiskOfficer")
SIGNER_INT = build_user_headers("signer-int", "Signer")
SIGNER_CP = build_user_headers("signer-cp", "Signer")

DRAFTER_ID = "mgr-1"


def _mgr(user_id="mgr-1"):
    return build_user_headers(user_id, "ContractManager")


# ─── Tier 1/2: Library + draft building blocks ────────────────────────

def create_organization(api, **overrides):
    """Create an organization. Returns the org dict."""
    resp = api.create_organization(F.create_organization_payload(**overrides), ADMIN)
    return get_success_data(resp)


def create_clause(api, org_id, clause_key, risk_weight=0, category="OTHER",
                  is_mandatory=False, standard_text="standard text"):
    """Create one ACTIVE clause template. Returns the clause dict."""
    resp = api.create_clause_template(
        F.create_clause_template_payload(
            org_id, clause_key=clause_key, risk_weight=risk_weight,
            category=category, is_mandatory=is_mandatory, standard_text=standard_text,
        ),
        LIBRARIAN,
    )
    return get_success_data(resp)


def create_contract_template(api, org_id, clause_template_ids,
                             default_term_months=12, auto_renew_default=False, name="Test Template"):
    """Create a contract template composing the given clause templates."""
    resp = api.create_contract_template(
        F.create_contract_template_payload(
            org_id, clause_template_ids,
            default_term_months=default_term_months,
            auto_renew_default=auto_renew_default,
            name=name,
        ),
        LIBRARIAN,
    )
    return get_success_data(resp)


def create_contract(api, org_id, template_id, drafter_id="mgr-1",
                    term_months=12, auto_renew=False, **overrides):
    """Create a DRAFT contract. Returns the contract dict (carries id & version)."""
    payload = F.create_contract_payload(
        org_id, template_id, term_months=term_months, auto_renew=auto_renew, **overrides
    )
    resp = api.create_contract(payload, _mgr(drafter_id))
    return get_success_data(resp)


def add_version(api, contract_id, clauses, expected_version, drafter_id="mgr-1",
                authored_by_party="INTERNAL"):
    """Create a new ContractVersion. Returns the version dict.

    Note: the response is the ContractVersion, not the Contract; fetch the
    contract afterwards if the new contract.version is needed."""
    resp = api.create_version(
        contract_id,
        F.create_version_payload(contract_id, clauses, expected_version,
                                 authored_by_party=authored_by_party),
        _mgr(drafter_id),
    )
    return get_success_data(resp)


def get_contract(api, contract_id, headers=None):
    """Fetch a contract. Returns the contract dict."""
    resp = api.get_contract(contract_id, headers or MGR)
    return get_success_data(resp)


# ─── Composite scenarios ──────────────────────────────────────────────

def setup_draft_contract_with_version(api, clauses_spec, *, org_overrides=None,
                                      template_overrides=None, contract_overrides=None,
                                      drafter_id="mgr-1", clause_defs=None):
    """Build org + clause templates + contract template + DRAFT contract + one version.

    clause_defs: list of dicts describing the clause templates to create, e.g.
        [{"clause_key": "LIABILITY_CAP", "risk_weight": 40, "category": "LIABILITY",
          "is_mandatory": False}, ...]
    clauses_spec: list of dicts mapping a created clause to a clauses[] entry, e.g.
        [{"clause_index": 0, "is_deviation": True, "text": "edit"}, ...]
      (clause_index refers to position in clause_defs). Clauses omitted from
      clauses_spec are simply not included in the version (so a mandatory clause
      can be left out to trigger a mandatory-miss).

    Returns a dict with keys:
        org, clauses (list of created clause dicts), template, contract,
        version (the created ContractVersion), contract_after (Contract after the
        version-create, carrying the bumped version).
    """
    org = create_organization(api, **(org_overrides or {}))
    org_id = org["id"]

    created_clauses = []
    for cd in (clause_defs or []):
        created_clauses.append(create_clause(
            api, org_id,
            clause_key=cd["clause_key"],
            risk_weight=cd.get("risk_weight", 0),
            category=cd.get("category", "OTHER"),
            is_mandatory=cd.get("is_mandatory", False),
            standard_text=cd.get("standard_text", "standard text"),
        ))

    clause_ids = [c["id"] for c in created_clauses]
    template = create_contract_template(
        api, org_id, clause_ids, **(template_overrides or {})
    )

    contract = create_contract(
        api, org_id, template["id"], drafter_id=drafter_id, **(contract_overrides or {})
    )

    clauses = []
    for spec in clauses_spec:
        ci = spec["clause_index"]
        clauses.append(F.clause_entry(
            clause_ids[ci],
            text=spec.get("text", "proposed text"),
            is_deviation=spec.get("is_deviation", False),
        ))

    version = add_version(
        api, contract["id"], clauses, contract["version"],
        drafter_id=drafter_id,
        authored_by_party=clauses_spec[0].get("authored_by_party", "INTERNAL") if clauses_spec else "INTERNAL",
    )
    contract_after = get_contract(api, contract["id"])

    return {
        "org": org,
        "clauses": created_clauses,
        "template": template,
        "contract": contract,
        "version": version,
        "contract_after": contract_after,
    }


def submit_contract(api, contract_id, expected_version, *, required_approver_count=None,
                    drafter_id="mgr-1"):
    """Submit a contract for review. Returns the contract dict after submit."""
    overrides = {}
    if required_approver_count is not None:
        overrides["required_approver_count"] = required_approver_count
    resp = api.submit_contract(
        contract_id, F.submit_payload(expected_version, **overrides), _mgr(drafter_id)
    )
    return get_success_data(resp)


def get_open_workflow(api, contract_id):
    """Return the (single) open approval workflow dict for a contract."""
    resp = api.list_contract_approval_workflows(contract_id, MGR)
    workflows = get_success_data(resp)
    assert workflows, "Setup step failed: expected at least one approval workflow"
    return workflows[0]


def record_approval(api, workflow_id, decision="APPROVE", approver_id="appr-1"):
    """Record an ApprovalStep. Returns the step dict."""
    resp = api.create_approval_step(
        workflow_id, F.approval_step_payload(workflow_id, decision=decision),
        build_user_headers(approver_id, "ContractApprover"),
    )
    return get_success_data(resp)


def request_deviation(api, contract_id, contract_version_id, clause_template_id,
                      drafter_id="mgr-1"):
    """Request a deviation approval. Returns the deviation-approval dict."""
    resp = api.create_deviation_approval(
        contract_id,
        F.create_deviation_approval_payload(contract_id, contract_version_id, clause_template_id),
        _mgr(drafter_id),
    )
    return get_success_data(resp)


def decide_deviation(api, deviation_id, decision="GRANT", risk_id="risk-1"):
    """Decide a deviation approval. Returns the deviation-approval dict."""
    resp = api.decide_deviation_approval(
        deviation_id, F.decide_payload(decision),
        build_user_headers(risk_id, "RiskOfficer"),
    )
    return get_success_data(resp)


def setup_under_review(api, clause_defs, clauses_spec, *, org_overrides=None,
                       template_overrides=None, contract_overrides=None,
                       required_approver_count=None, drafter_id="mgr-1"):
    """Build a contract through to UNDER_REVIEW with an open PENDING workflow.

    Returns a dict extending setup_draft_contract_with_version with:
        contract_submitted (Contract after submit), workflow (open workflow dict).
    """
    base = setup_draft_contract_with_version(
        api, clauses_spec, org_overrides=org_overrides,
        template_overrides=template_overrides, contract_overrides=contract_overrides,
        drafter_id=drafter_id, clause_defs=clause_defs,
    )
    submitted = submit_contract(
        api, base["contract"]["id"], base["contract_after"]["version"],
        required_approver_count=required_approver_count, drafter_id=drafter_id,
    )
    workflow = get_open_workflow(api, base["contract"]["id"])
    base["contract_submitted"] = submitted
    base["workflow"] = workflow
    return base


def setup_approved_contract(api, clause_defs, clauses_spec, *, org_overrides=None,
                            template_overrides=None, contract_overrides=None,
                            drafter_id="mgr-1", approver_id="appr-1"):
    """Build a contract through to APPROVED (quorum 1, single APPROVE step).

    Returns the setup_under_review dict plus:
        contract_approved (Contract after the bubble-up to APPROVED).
    """
    base = setup_under_review(
        api, clause_defs, clauses_spec, org_overrides=org_overrides,
        template_overrides=template_overrides, contract_overrides=contract_overrides,
        drafter_id=drafter_id,
    )
    record_approval(api, base["workflow"]["id"], decision="APPROVE", approver_id=approver_id)
    base["contract_approved"] = get_contract(api, base["contract"]["id"])
    return base


def setup_out_for_signature(api, clause_defs, clauses_spec, *, org_overrides=None,
                            template_overrides=None, contract_overrides=None,
                            drafter_id="mgr-1", approver_id="appr-1", signers=None):
    """Build a contract through to OUT_FOR_SIGNATURE with SENT signature requests.

    Returns the setup_approved_contract dict plus:
        signature_requests (list of SignatureRequest dicts).
    """
    base = setup_approved_contract(
        api, clause_defs, clauses_spec, org_overrides=org_overrides,
        template_overrides=template_overrides, contract_overrides=contract_overrides,
        drafter_id=drafter_id, approver_id=approver_id,
    )
    approved = base["contract_approved"]
    resp = api.send_for_signature(
        approved["id"],
        F.send_for_signature_payload(approved["version"], signers or F.default_signers()),
        _mgr(drafter_id),
    )
    get_success_data(resp)
    sr_resp = api.list_signature_requests(approved["id"], MGR)
    base["signature_requests"] = get_success_data(sr_resp)
    return base


def setup_active_contract(api, clause_defs, clauses_spec, *, org_overrides=None,
                          template_overrides=None, contract_overrides=None,
                          drafter_id="mgr-1", approver_id="appr-1",
                          activation_clock=None):
    """Build a contract all the way to ACTIVE (both signatures recorded).

    activation_clock: if given, the clock is set to this ISO8601 instant BEFORE the
    signing sequence so effective_date / expiry_date are deterministic. The fixture
    assumes the clause/contract template auto_renew defaults are set by the caller
    via template_overrides / contract_overrides.

    Returns the setup_out_for_signature dict plus:
        contract_active (Contract after the join to ACTIVE).
    """
    if activation_clock is not None:
        # set the clock before drafting so activation stamps a known effective_date
        get_success_data(api.set_clock(F.set_clock_payload(activation_clock), ADMIN))
    base = setup_out_for_signature(
        api, clause_defs, clauses_spec, org_overrides=org_overrides,
        template_overrides=template_overrides, contract_overrides=contract_overrides,
        drafter_id=drafter_id, approver_id=approver_id,
    )
    srs = base["signature_requests"]
    # Sign the internal then the counterparty request; the second triggers the join.
    get_success_data(api.sign_signature_request(srs[0]["id"], SIGNER_INT))
    get_success_data(api.sign_signature_request(srs[1]["id"], SIGNER_CP))
    base["contract_active"] = get_contract(api, base["contract"]["id"])
    return base


# ─── Convenience: the trivial single non-deviating clause ─────────────

def simple_clause_defs():
    """One non-risky, non-mandatory clause."""
    return [{"clause_key": "K", "risk_weight": 0, "category": "OTHER", "is_mandatory": False}]


def simple_clauses_spec(is_deviation=False, authored_by_party="INTERNAL"):
    """A version that includes the single simple clause."""
    return [{"clause_index": 0, "is_deviation": is_deviation, "text": "s",
             "authored_by_party": authored_by_party}]


def setup_simple_active(api, *, auto_renew=False, activation_clock="2026-06-01T00:00:00Z",
                        term_months=12, org_overrides=None):
    """Full lifecycle to ACTIVE for a single non-deviating clause.

    auto_renew controls both the template default and the contract value.
    Returns the setup_active_contract dict."""
    return setup_active_contract(
        api,
        simple_clause_defs(),
        simple_clauses_spec(),
        org_overrides=org_overrides,
        template_overrides={"auto_renew_default": auto_renew, "default_term_months": term_months},
        contract_overrides={"auto_renew": auto_renew, "term_months": term_months},
        activation_clock=activation_clock,
    )


def set_clock(api, iso8601):
    """Advance the logical clock. Returns the clock response data."""
    return get_success_data(api.set_clock(F.set_clock_payload(iso8601), ADMIN))
