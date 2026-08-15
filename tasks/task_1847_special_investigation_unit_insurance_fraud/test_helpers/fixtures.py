"""Composite setup helpers: multi-step state builders used across test files.

All helpers use get_success_data() so setup failures surface as clear errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_adjuster_payload, create_claim_payload, create_referral_payload,
    create_investigator_payload, create_evidence_payload, create_euo_session_payload,
    create_provider_pattern_payload, create_payment_payload, create_ledger_payload,
)
from .test_users import (
    make_adjuster_headers, make_investigator_headers, make_manager_headers,
)


# ---------------------------------------------------------------------------
# Tier 1: base entities
# ---------------------------------------------------------------------------

def create_adjuster(state_licenses=None, manager_headers=None, **overrides):
    """Register an adjuster; return (adjuster_dict, adjuster_headers)."""
    mh = manager_headers or make_manager_headers()
    payload = create_adjuster_payload(state_licenses=state_licenses or ["CA"], **overrides)
    resp = api_client.create_adjuster(payload, mh)
    adj = get_success_data(resp)
    return adj, make_adjuster_headers(adj["id"])


def create_investigator(state_certifications=None, max_active_cases=5,
                        manager_headers=None, **overrides):
    """Register an investigator; return (investigator_dict, investigator_headers)."""
    mh = manager_headers or make_manager_headers()
    payload = create_investigator_payload(
        state_certifications=state_certifications or ["CA"],
        max_active_cases=max_active_cases, **overrides)
    resp = api_client.create_investigator(payload, mh)
    inv = get_success_data(resp)
    return inv, make_investigator_headers(inv["id"])


def create_claim(adjuster, state_code="CA", claimed_amount_cents=5_000_000, **overrides):
    """Create a claim owned by adjuster (dict or id). Returns claim dict."""
    adj_id = adjuster["id"] if isinstance(adjuster, dict) else adjuster
    ah = make_adjuster_headers(adj_id)
    payload = create_claim_payload(adj_id, state_code=state_code,
                                   claimed_amount_cents=claimed_amount_cents, **overrides)
    resp = api_client.create_claim(payload, ah)
    return get_success_data(resp)


def create_referral(claim, submitted_by_role="ADJUSTER",
                    red_flag_codes=None, headers=None, **overrides):
    """Create a referral against claim (dict or id). Returns referral dict."""
    claim_id = claim["id"] if isinstance(claim, dict) else claim
    if headers is None:
        # default: claim's owning adjuster submits
        cid_adj = claim.get("adjuster_id") if isinstance(claim, dict) else None
        headers = make_adjuster_headers(cid_adj) if cid_adj else make_manager_headers()
    payload = create_referral_payload(
        claim_id, submitted_by_role=submitted_by_role,
        red_flag_codes=red_flag_codes or ["UNWITNESSED_LOSS"], **overrides)
    resp = api_client.create_referral(payload, headers)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 2: referral pipeline -> case
# ---------------------------------------------------------------------------

def triage_referral(referral, modifier_overrides=None, manager_headers=None):
    mh = manager_headers or make_manager_headers()
    rid = referral["id"] if isinstance(referral, dict) else referral
    payload = {}
    if modifier_overrides is not None:
        payload["modifier_overrides"] = modifier_overrides
    resp = api_client.triage_referral(rid, payload, mh)
    return get_success_data(resp)


def accept_referral(referral, manager_headers=None):
    """Accept referral; returns newly created SIUCase."""
    mh = manager_headers or make_manager_headers()
    rid = referral["id"] if isinstance(referral, dict) else referral
    resp = api_client.accept_referral(rid, mh)
    return get_success_data(resp)


def open_case(case, manager_headers=None):
    mh = manager_headers or make_manager_headers()
    kid = case["id"] if isinstance(case, dict) else case
    resp = api_client.open_case(kid, mh)
    return get_success_data(resp)


def assign_investigator(case, investigator, manager_headers=None):
    """Assign investigator to case (case must be OPEN or UNDER_INVESTIGATION).
    Returns (assignment_dict, updated_case_dict)."""
    mh = manager_headers or make_manager_headers()
    inv_id = investigator["id"] if isinstance(investigator, dict) else investigator
    kid = case["id"] if isinstance(case, dict) else case
    payload = {"investigator_id": inv_id, "expected_case_version": case["version"]}
    resp = api_client.create_assignment(kid, payload, mh)
    asg = get_success_data(resp)
    refreshed = get_success_data(api_client.get_case(kid, mh))
    return asg, refreshed


# ---------------------------------------------------------------------------
# Tier 3: evidence pipeline
# ---------------------------------------------------------------------------

def log_evidence(case, investigator, **overrides):
    """Investigator logs evidence on case. Returns evidence dict."""
    inv_id = investigator["id"] if isinstance(investigator, dict) else investigator
    ih = make_investigator_headers(inv_id)
    kid = case["id"] if isinstance(case, dict) else case
    payload = create_evidence_payload(**overrides)
    resp = api_client.create_evidence(kid, payload, ih)
    return get_success_data(resp)


def submit_evidence_review(case, evidence, investigator):
    inv_id = investigator["id"] if isinstance(investigator, dict) else investigator
    ih = make_investigator_headers(inv_id)
    kid = case["id"] if isinstance(case, dict) else case
    eid = evidence["id"] if isinstance(evidence, dict) else evidence
    resp = api_client.submit_evidence_review(kid, eid, ih)
    return get_success_data(resp)


def admit_evidence(case, evidence, expected_case_version, manager_headers=None):
    """Manager admits evidence; returns (evidence_dict, refreshed_case_dict)."""
    mh = manager_headers or make_manager_headers()
    kid = case["id"] if isinstance(case, dict) else case
    eid = evidence["id"] if isinstance(evidence, dict) else evidence
    payload = {"expected_case_version": expected_case_version}
    resp = api_client.admit_evidence(kid, eid, payload, mh)
    ev = get_success_data(resp)
    refreshed = get_success_data(api_client.get_case(kid, mh))
    return ev, refreshed


# ---------------------------------------------------------------------------
# Tier 4: composite case pipelines
# ---------------------------------------------------------------------------

def setup_case_under_investigation(state_code="CA", claimed_amount_cents=5_000_000,
                                   red_flag_codes=None, max_active_cases=5):
    """Adjuster+Claim+Referral accepted; case opened and assigned to investigator.
    Returns dict of all resources built."""
    mh = make_manager_headers()
    adj, ah = create_adjuster(state_licenses=[state_code], manager_headers=mh)
    inv, ih = create_investigator(state_certifications=[state_code],
                                  max_active_cases=max_active_cases,
                                  manager_headers=mh)
    claim = create_claim(adj, state_code=state_code,
                         claimed_amount_cents=claimed_amount_cents)
    ref = create_referral(claim, red_flag_codes=red_flag_codes or ["UNWITNESSED_LOSS"],
                          headers=ah)
    triage_referral(ref, manager_headers=mh)
    case = accept_referral(ref, manager_headers=mh)
    case = open_case(case, manager_headers=mh)
    asg, case = assign_investigator(case, inv, manager_headers=mh)
    return {
        "manager_headers": mh,
        "adjuster": adj, "adjuster_headers": ah,
        "investigator": inv, "investigator_headers": ih,
        "claim": claim, "referral": ref,
        "case": case, "assignment": asg,
    }


def setup_case_with_admitted_evidence(state_code="CA", claimed_amount_cents=5_000_000,
                                      red_flag_codes=None, evidence_overrides=None):
    """Case UNDER_INVESTIGATION with one ADMITTED evidence item.
    Returns dict including 'evidence' and refreshed 'case'."""
    ctx = setup_case_under_investigation(
        state_code=state_code, claimed_amount_cents=claimed_amount_cents,
        red_flag_codes=red_flag_codes)
    ev = log_evidence(ctx["case"], ctx["investigator"], **(evidence_overrides or {}))
    ev = submit_evidence_review(ctx["case"], ev, ctx["investigator"])
    ev, case = admit_evidence(ctx["case"], ev, ctx["case"]["version"],
                              manager_headers=ctx["manager_headers"])
    ctx["evidence"] = ev
    ctx["case"] = case
    return ctx


def setup_case_decision_pending(state_code="CA", claimed_amount_cents=5_000_000,
                                red_flag_codes=None, evidence_overrides=None):
    """Case in DECISION_PENDING with one ADMITTED evidence item."""
    ctx = setup_case_with_admitted_evidence(
        state_code=state_code, claimed_amount_cents=claimed_amount_cents,
        red_flag_codes=red_flag_codes, evidence_overrides=evidence_overrides)
    resp = api_client.submit_case_for_decision(ctx["case"]["id"], ctx["investigator_headers"])
    ctx["case"] = get_success_data(resp)
    return ctx


def setup_case_closed_substantiated(state_code="CA", claimed_amount_cents=100_000_000,
                                    fraud_amount_cents=600_000,
                                    evidence_materiality="SUBSTANTIVE"):
    """Case closed SUBSTANTIATED; auto-creates restitution ledger and (when
    required) a DRAFT bureau referral. Returns ctx including 'ledger' (first
    ledger) and 'bureau_referral' (first bureau referral, may be None)."""
    evidence_overrides = {"materiality": evidence_materiality,
                          "fraud_amount_cents": fraud_amount_cents}
    ctx = setup_case_decision_pending(
        state_code=state_code, claimed_amount_cents=claimed_amount_cents,
        red_flag_codes=["PRIOR_FRAUD_CONVICTION"],
        evidence_overrides=evidence_overrides)
    resp = api_client.close_case(ctx["case"]["id"], {"closed_reason": "SUBSTANTIATED"},
                                 ctx["manager_headers"])
    ctx["case"] = get_success_data(resp)
    ledgers_resp = api_client.list_case_ledgers(ctx["case"]["id"], ctx["manager_headers"])
    ledgers = get_success_data(ledgers_resp)
    ctx["ledger"] = ledgers[0] if ledgers else None
    bur_resp = api_client.list_case_bureau_referrals(ctx["case"]["id"], ctx["manager_headers"])
    burs = get_success_data(bur_resp)
    ctx["bureau_referral"] = burs[0] if burs else None
    return ctx
