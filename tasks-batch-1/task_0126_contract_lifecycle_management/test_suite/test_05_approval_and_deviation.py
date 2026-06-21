"""Approval quorum, segregation of duties, the deviation-clearing send gate, and the
cross-entity dependencies (breached obligation blocks renew; superseded version
blocks a deviation decide).

Tests here translate queue A (Difficulty) rules combinatorial_formula (send gate),
priority_pair_validation_conflict, and cross_entity_state_dependency, plus queue B
corners under sections endpoints and errors.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success, validate_error, validate_error_is_one_of,
    factories as F, fixtures as FX,
    build_user_headers,
    ApiErrorId,
)

ADMIN = FX.ADMIN
MGR = FX.MGR
RISK = FX.RISK


@pytest.fixture
def api():
    return api_client


# ─── combinatorial_formula: send gate evaluation order (mode c) ───────

def _two_deviations_both_granted_approved(api):
    """Org threshold 60; LIABILITY_CAP(w=40) + INDEMNITY(w=30) both deviated; BOTH
    deviations GRANTED; contract APPROVED. Returns the contract_approved dict."""
    setup = FX.setup_draft_contract_with_version(
        api,
        clauses_spec=[
            {"clause_index": 0, "is_deviation": True, "text": "edit"},
            {"clause_index": 1, "is_deviation": True, "text": "edit"},
        ],
        clause_defs=[
            {"clause_key": "LIABILITY_CAP", "risk_weight": 40, "category": "LIABILITY"},
            {"clause_key": "INDEMNITY", "risk_weight": 30, "category": "INDEMNITY"},
        ],
        org_overrides={"risk_appetite_threshold": 60},
    )
    contract_id = setup["contract"]["id"]
    version_id = setup["version"]["id"]
    dev_liab = FX.request_deviation(api, contract_id, version_id, setup["clauses"][0]["id"])
    dev_indem = FX.request_deviation(api, contract_id, version_id, setup["clauses"][1]["id"])
    FX.decide_deviation(api, dev_liab["id"], "GRANT")
    FX.decide_deviation(api, dev_indem["id"], "GRANT")
    submitted = FX.submit_contract(api, contract_id, setup["contract_after"]["version"])
    workflow = FX.get_open_workflow(api, contract_id)
    FX.record_approval(api, workflow["id"], "APPROVE")
    return FX.get_contract(api, contract_id)


def test_send_for_signature_succeeds_when_all_deviations_granted(api):
    """PRD §3.5: "The risk gate requires either that the contract's risk_score be
    strictly below the organization's risk_appetite_threshold, or that every clause
    template deviated in the current version have a GRANTED deviation approval whose
    contract_version_id equals the contract's current_version_id".

    Design: Difficulty/combinatorial_formula/send_for_signature_evaluation_order_mode_c
    """
    approved = _two_deviations_both_granted_approved(api)
    resp = api.send_for_signature(
        approved["id"], F.send_for_signature_payload(approved["version"], F.default_signers()), MGR
    )
    validate_success(resp, 200)


def test_send_for_signature_moves_contract_out_for_signature(api):
    """PRD §3.5: "Sending an APPROVED contract for signature is a ContractManager
    action that carries it to OUT_FOR_SIGNATURE."

    Design: Difficulty/combinatorial_formula/send_for_signature_evaluation_order_mode_c
    """
    approved = _two_deviations_both_granted_approved(api)
    validate_success(api.send_for_signature(
        approved["id"], F.send_for_signature_payload(approved["version"], F.default_signers()), MGR
    ), 200)
    contract = FX.get_contract(api, approved["id"])
    assert contract["status"] == "OUT_FOR_SIGNATURE", \
        f"contract must be OUT_FOR_SIGNATURE after a cleared send, got {contract['status']}"


# ─── priority_pair: state (@6) vs deviation-required (@12) on send ────
# PRD §3.5 does not pin the deviation gate as strictly pre-empted by the state
# check, so a faithful PRD-only implementer could surface either error first.
# Per the error-precedence rule, both ERR_INVALID_STATE and ERR_DEVIATION_REQUIRED
# are acceptable.

def _draft_above_threshold_uncovered(api):
    """A DRAFT contract whose current version has uncovered deviations summing to 70
    (org threshold 60), never submitted (still DRAFT)."""
    setup = FX.setup_draft_contract_with_version(
        api,
        clauses_spec=[
            {"clause_index": 0, "is_deviation": True, "text": "edit"},
            {"clause_index": 1, "is_deviation": True, "text": "edit"},
        ],
        clause_defs=[
            {"clause_key": "LIABILITY_CAP", "risk_weight": 40, "category": "LIABILITY"},
            {"clause_key": "INDEMNITY", "risk_weight": 30, "category": "INDEMNITY"},
        ],
        org_overrides={"risk_appetite_threshold": 60},
    )
    return setup["contract_after"]


def test_send_on_draft_with_uncovered_deviation_is_rejected(api):
    """PRD §3.5: send is "Sending an APPROVED contract for signature" — a DRAFT
    contract is not in a valid state for the transition, "otherwise ERR_INVALID_STATE".
    PRD §3.5: "failing this, the send is refused with ERR_DEVIATION_REQUIRED."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_deviation_required_on_send
    """
    contract = _draft_above_threshold_uncovered(api)
    resp = api.send_for_signature(
        contract["id"], F.send_for_signature_payload(contract["version"], F.default_signers()), MGR
    )
    validate_error_is_one_of(
        resp, [ApiErrorId.ERR_INVALID_STATE.value, ApiErrorId.ERR_DEVIATION_REQUIRED.value]
    )


def test_send_on_draft_does_not_transition_contract(api):
    """PRD §3.5: send only "carries it to OUT_FOR_SIGNATURE" from APPROVED; a rejected
    send must leave a DRAFT contract in DRAFT (the transition is not applied).

    Design: Difficulty/priority_pair_validation_conflict/state_vs_deviation_required_on_send
    """
    contract = _draft_above_threshold_uncovered(api)
    api.send_for_signature(
        contract["id"], F.send_for_signature_payload(contract["version"], F.default_signers()), MGR
    )
    after = FX.get_contract(api, contract["id"])
    assert after["status"] == "DRAFT", \
        f"a rejected send must leave the contract DRAFT, got {after['status']}"


# ─── priority_pair: self-approval (@8) vs mandatory-clause-missing (@9) ─

def _under_review_drafter_omits_mandatory(api, drafter_id="mgr-1"):
    """Contract drafted by drafter_id whose current version OMITS a mandatory clause,
    submitted to UNDER_REVIEW (quorum 1). Returns the setup dict (with workflow)."""
    return FX.setup_under_review(
        api,
        clause_defs=[
            {"clause_key": "TERMINATION", "risk_weight": 10, "category": "TERMINATION", "is_mandatory": True},
            {"clause_key": "OTHER1", "risk_weight": 0, "category": "OTHER", "is_mandatory": False},
        ],
        clauses_spec=[{"clause_index": 1, "is_deviation": False, "text": "s"}],  # omits mandatory clause 0
        org_overrides={"risk_appetite_threshold": 100},
        drafter_id=drafter_id,
    )


def test_drafter_approving_own_contract_returns_self_approval(api):
    """PRD §3.3: "segregation of duties is enforced: the caller's X-User-ID must
    differ from the contract's drafter_user_id and from the current version's
    authored_by_user_id; a caller who is the drafter or the version author is refused
    with ERR_SELF_APPROVAL." And: "The segregation check is evaluated before the
    mandatory-clause check."

    Design: Difficulty/priority_pair_validation_conflict/self_approval_vs_mandatory_clause_missing
    """
    setup = _under_review_drafter_omits_mandatory(api, drafter_id="mgr-1")
    # The drafter (mgr-1) acts as the approver AND the version omits a mandatory clause.
    resp = api.create_approval_step(
        setup["workflow"]["id"], F.approval_step_payload(setup["workflow"]["id"], "APPROVE"),
        build_user_headers("mgr-1", "ContractApprover"),
    )
    validate_error(resp, ApiErrorId.ERR_SELF_APPROVAL.value, 403)


def test_self_approval_takes_precedence_over_mandatory_clause_missing(api):
    """PRD §3.3: "The segregation check is evaluated before the mandatory-clause
    check." — so when the drafter approves a version that also omits a mandatory
    clause, ERR_SELF_APPROVAL (not ERR_MANDATORY_CLAUSE_MISSING) is returned.

    Design: Difficulty/priority_pair_validation_conflict/self_approval_vs_mandatory_clause_missing
    """
    setup = _under_review_drafter_omits_mandatory(api, drafter_id="mgr-1")
    resp = api.create_approval_step(
        setup["workflow"]["id"], F.approval_step_payload(setup["workflow"]["id"], "APPROVE"),
        build_user_headers("mgr-1", "ContractApprover"),
    )
    error = validate_error(resp, ApiErrorId.ERR_SELF_APPROVAL.value, 403)
    assert error["error_id"] == ApiErrorId.ERR_SELF_APPROVAL.value, \
        "self-approval must pre-empt the mandatory-clause check"


# ─── cross_entity: breached obligation blocks renew ───────────────────

def _active_with_breached_obligation_and_due_alert(api):
    """ACTIVE auto_renew contract (effective 2026-06-01, expiry 2027-06-01, trigger
    2027-05-02) with an obligation due 2026-12-01 that has BREACHED, and the renewal
    alert advanced to DUE. Returns (contract_id, obligation_id)."""
    setup = FX.setup_simple_active(api, auto_renew=False, activation_clock="2026-06-01T00:00:00Z")
    contract_id = setup["contract"]["id"]
    obl = FX.get_success_data(api.create_obligation(
        contract_id, F.create_obligation_payload(contract_id, "2026-12-01T00:00:00Z"), MGR
    ))
    FX.set_clock(api, "2026-12-02T00:00:00Z")  # past obligation due -> BREACHED
    FX.set_clock(api, "2027-05-02T00:00:00Z")  # alert -> DUE
    return contract_id, obl["id"]


def test_open_obligation_breaches_after_due_date(api):
    """PRD §3.6: "any obligation still OPEN whose due_date is strictly in the past
    relative to the current clock time, on a contract that is still ACTIVE, moves
    from OPEN to BREACHED".

    Design: Difficulty/cross_entity_state_dependency/renew_blocked_by_breached_obligation
    """
    contract_id, obl_id = _active_with_breached_obligation_and_due_alert(api)
    obls = FX.get_success_data(api.list_obligations(contract_id, MGR))
    breached = next(o for o in obls if o["id"] == obl_id)
    assert breached["status"] == "BREACHED", \
        f"obligation past due_date must be BREACHED, got {breached['status']}"


def test_renew_blocked_by_breached_obligation(api):
    """PRD §3.7: "manual renewal requires that a renewal alert with status DUE exist
    for the contract (otherwise ERR_RENEWAL_NOT_DUE) and that no obligation on the
    contract be BREACHED (otherwise ERR_OPEN_BREACH)."

    Design: Difficulty/cross_entity_state_dependency/renew_blocked_by_breached_obligation
    """
    contract_id, _ = _active_with_breached_obligation_and_due_alert(api)
    active = FX.get_contract(api, contract_id)
    resp = api.renew_contract(contract_id, F.occ_payload(active["version"]), MGR)
    validate_error(resp, ApiErrorId.ERR_OPEN_BREACH.value, 409)


# ─── cross_entity: superseded version blocks a deviation decide ───────

def _pending_deviation_then_superseded(api):
    """Contract on v1 with a PENDING DeviationApproval pinned to v1, submitted, then a
    new v2 created so v1 is superseded (and the deviation auto-DENIED). Returns the
    deviation id."""
    setup = FX.setup_draft_contract_with_version(
        api,
        clauses_spec=[{"clause_index": 0, "is_deviation": True, "text": "edit1"}],
        clause_defs=[{"clause_key": "LIABILITY_CAP", "risk_weight": 40, "category": "LIABILITY"}],
        org_overrides={"risk_appetite_threshold": 60},
    )
    contract_id = setup["contract"]["id"]
    dev = FX.request_deviation(api, contract_id, setup["version"]["id"], setup["clauses"][0]["id"])
    submitted = FX.submit_contract(api, contract_id, setup["contract_after"]["version"])
    # Redline supersedes v1.
    FX.add_version(
        api, contract_id,
        [F.clause_entry(setup["clauses"][0]["id"], text="edit2", is_deviation=True)],
        submitted["version"], authored_by_party="COUNTERPARTY",
    )
    return dev["id"]


def test_deviation_auto_denied_when_version_superseded(api):
    """PRD §3.4: "Beyond an explicit deny, the system itself denies a pending
    deviation approval as a cascade when the version it covers is superseded by a
    redline."

    Design: Difficulty/cross_entity_state_dependency/deviation_decide_blocked_when_version_superseded
    """
    dev_id = _pending_deviation_then_superseded(api)
    dev = FX.get_success_data(api.get_deviation_approval(dev_id, MGR))
    assert dev["status"] == "DENIED", \
        f"deviation on the superseded version must be auto-DENIED, got {dev['status']}"


def test_decide_superseded_deviation_is_rejected(api):
    """PRD §3.4: "the request's contract_version_id must still equal the contract's
    current_version_id — if the version has since been superseded, the decide is
    refused with ERR_DEVIATION_STALE". (The deviation may already be DENIED, so the
    state guard ERR_INVALID_STATE is equally faithful.)

    Design: Difficulty/cross_entity_state_dependency/deviation_decide_blocked_when_version_superseded
    """
    dev_id = _pending_deviation_then_superseded(api)
    resp = api.decide_deviation_approval(dev_id, F.decide_payload("GRANT"), RISK)
    validate_error_is_one_of(
        resp, [ApiErrorId.ERR_DEVIATION_STALE.value, ApiErrorId.ERR_INVALID_STATE.value]
    )


# ─── Queue B: endpoints / quorum of two distinct approvers ────────────

def test_quorum_two_requires_two_distinct_approvals(api):
    """PRD §3.2: "The optional required_approver_count field sets the quorum for the
    workflow this submit creates; it must be at least 1 and defaults to 1 if omitted."
    PRD §3.3: "When approvals_received reaches or exceeds the workflow's
    required_approver_count, the workflow moves from PENDING to APPROVED".

    Design: Corner/endpoints/approval_quorum_two_distinct_approvers_reaches_approved
    """
    setup = FX.setup_under_review(
        api, FX.simple_clause_defs(), FX.simple_clauses_spec(),
        org_overrides={"risk_appetite_threshold": 100},
        required_approver_count=2,
    )
    contract_id = setup["contract"]["id"]
    wf_id = setup["workflow"]["id"]
    assert setup["workflow"]["required_approver_count"] == 2, "quorum must be 2"

    FX.record_approval(api, wf_id, "APPROVE", approver_id="appr-1")
    mid = FX.get_contract(api, contract_id)
    assert mid["status"] == "UNDER_REVIEW", \
        f"after one of two approvals the contract must stay UNDER_REVIEW, got {mid['status']}"

    FX.record_approval(api, wf_id, "APPROVE", approver_id="appr-2")
    final = FX.get_contract(api, contract_id)
    assert final["status"] == "APPROVED", \
        f"after the second distinct approval the contract must reach APPROVED, got {final['status']}"


# ─── Queue B: errors / drafter cannot decide own deviation ────────────

def test_deviation_decide_by_drafter_returns_self_approval(api):
    """PRD §3.4: "segregation of duties requires the caller's X-User-ID to differ
    from the contract's drafter_user_id, failing otherwise with ERR_SELF_APPROVAL."

    Design: Corner/errors/deviation_decide_by_drafter_returns_self_approval
    """
    setup = FX.setup_draft_contract_with_version(
        api,
        clauses_spec=[
            {"clause_index": 0, "is_deviation": True, "text": "edit"},
            {"clause_index": 1, "is_deviation": True, "text": "edit"},
        ],
        clause_defs=[
            {"clause_key": "LIABILITY_CAP", "risk_weight": 40, "category": "LIABILITY"},
            {"clause_key": "INDEMNITY", "risk_weight": 30, "category": "INDEMNITY"},
        ],
        org_overrides={"risk_appetite_threshold": 60},
        drafter_id="dual-1",
    )
    contract_id = setup["contract"]["id"]
    dev = FX.request_deviation(
        api, contract_id, setup["version"]["id"], setup["clauses"][0]["id"], drafter_id="dual-1"
    )
    # The drafter (dual-1) acts as the RiskOfficer to decide their own deviation.
    resp = api.decide_deviation_approval(
        dev["id"], F.decide_payload("GRANT"), build_user_headers("dual-1", "RiskOfficer")
    )
    validate_error(resp, ApiErrorId.ERR_SELF_APPROVAL.value, 403)
