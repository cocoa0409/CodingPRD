"""The redline negotiation cycle, the multi-hop cascades it (and termination)
trigger, and the conserved-quantity invariants that survive them.

All tests here translate queue A (Difficulty) instances under rules
non_linear_state_machine, transitive_cascade, and compensating_invariant.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    factories as F, fixtures as FX,
)

ADMIN = FX.ADMIN
MGR = FX.MGR


@pytest.fixture
def api():
    return api_client


def _under_review_simple(api, *, auto_renew=False, threshold=100):
    """A simple single-clause contract submitted to UNDER_REVIEW (PENDING workflow)."""
    return FX.setup_under_review(
        api, FX.simple_clause_defs(), FX.simple_clauses_spec(),
        org_overrides={"risk_appetite_threshold": threshold},
        template_overrides={"auto_renew_default": auto_renew},
        contract_overrides={"auto_renew": auto_renew},
    )


# ─── non_linear_state_machine: redline cycle A->B->A ──────────────────

def test_new_version_while_under_review_bounces_to_redlining(api):
    """PRD §3.2: "Authoring a new version while the contract is UNDER_REVIEW bounces
    it into REDLINING".

    Design: Difficulty/non_linear_state_machine/contract_redline_cycle_under_review_to_redlining_and_back
    """
    setup = _under_review_simple(api)
    contract_id = setup["contract"]["id"]
    submitted = setup["contract_submitted"]
    FX.add_version(
        api, contract_id,
        [F.clause_entry(setup["clauses"][0]["id"], text="redline", is_deviation=True)],
        submitted["version"], authored_by_party="COUNTERPARTY",
    )
    after = FX.get_contract(api, contract_id)
    assert after["status"] == "REDLINING", \
        f"a redline while UNDER_REVIEW must bounce to REDLINING, got {after['status']}"


def test_resubmit_after_redline_returns_to_under_review(api):
    """PRD §3.2: "Resubmitting after a redline closes the cycle: it returns the
    contract from REDLINING to UNDER_REVIEW, again creating a fresh PENDING workflow
    pinned to the now-current version".

    Design: Difficulty/non_linear_state_machine/contract_redline_cycle_under_review_to_redlining_and_back
    """
    setup = _under_review_simple(api)
    contract_id = setup["contract"]["id"]
    submitted = setup["contract_submitted"]
    FX.add_version(
        api, contract_id,
        [F.clause_entry(setup["clauses"][0]["id"], text="redline", is_deviation=True)],
        submitted["version"], authored_by_party="COUNTERPARTY",
    )
    redlining = FX.get_contract(api, contract_id)
    assert redlining["status"] == "REDLINING"
    resubmitted = FX.submit_contract(api, contract_id, redlining["version"])
    assert resubmitted["status"] == "UNDER_REVIEW", \
        f"resubmit must close the cycle back to UNDER_REVIEW, got {resubmitted['status']}"


# ─── transitive_cascade: redline depth-3 supersede/void/deny ──────────

def _under_review_with_pending_deviation(api):
    """A contract UNDER_REVIEW on v1 (one w=40 deviation) with a PENDING workflow and
    a PENDING DeviationApproval pinned to v1. Returns dict with version1, dev, workflow,
    contract_submitted."""
    setup = FX.setup_draft_contract_with_version(
        api,
        clauses_spec=[{"clause_index": 0, "is_deviation": True, "text": "edit"}],
        clause_defs=[{"clause_key": "LIABILITY_CAP", "risk_weight": 40, "category": "LIABILITY"}],
        org_overrides={"risk_appetite_threshold": 60},
    )
    contract_id = setup["contract"]["id"]
    liab_id = setup["clauses"][0]["id"]
    dev = FX.request_deviation(api, contract_id, setup["version"]["id"], liab_id)
    submitted = FX.submit_contract(api, contract_id, setup["contract_after"]["version"])
    workflow = FX.get_open_workflow(api, contract_id)
    setup["deviation"] = dev
    setup["contract_submitted"] = submitted
    setup["workflow"] = workflow
    return setup


def test_redline_supersedes_prior_version_and_voids_workflow(api):
    """PRD §3.2: "the prior current version's status becomes SUPERSEDED, the
    previously open approval workflow becomes VOIDED because its pinned version is no
    longer current".

    Design: Difficulty/transitive_cascade/redline_cascade_supersede_void_deny_depth3
    """
    setup = _under_review_with_pending_deviation(api)
    contract_id = setup["contract"]["id"]
    v1_id = setup["version"]["id"]
    wf_id = setup["workflow"]["id"]
    FX.add_version(
        api, contract_id,
        [F.clause_entry(setup["clauses"][0]["id"], text="redline2", is_deviation=True)],
        setup["contract_submitted"]["version"], authored_by_party="COUNTERPARTY",
    )
    v1 = FX.get_success_data(api.get_version(v1_id, MGR))
    assert v1["status"] == "SUPERSEDED", f"prior version must be SUPERSEDED, got {v1['status']}"
    wf = FX.get_success_data(api.get_approval_workflow(wf_id, MGR))
    assert wf["status"] == "VOIDED", f"pinned workflow must be VOIDED, got {wf['status']}"


def test_redline_denies_pending_deviation_on_superseded_version(api):
    """PRD §3.2: "any PENDING deviation approval whose contract_version_id is that
    now-superseded version is moved to DENIED as stale-version compensation."

    Design: Difficulty/transitive_cascade/redline_cascade_supersede_void_deny_depth3
    """
    setup = _under_review_with_pending_deviation(api)
    contract_id = setup["contract"]["id"]
    dev_id = setup["deviation"]["id"]
    FX.add_version(
        api, contract_id,
        [F.clause_entry(setup["clauses"][0]["id"], text="redline2", is_deviation=True)],
        setup["contract_submitted"]["version"], authored_by_party="COUNTERPARTY",
    )
    dev = FX.get_success_data(api.get_deviation_approval(dev_id, MGR))
    assert dev["status"] == "DENIED", \
        f"PENDING deviation on the superseded version must be DENIED, got {dev['status']}"


# ─── transitive_cascade: terminate depth-2 obligations/alerts ─────────

def test_terminate_cascades_open_obligation_to_waived(api):
    """PRD §3.7: "Termination cascades: every obligation still OPEN is moved to
    WAIVED, any renewal alert still SCHEDULED or DUE is moved to CANCELLED".

    Design: Difficulty/transitive_cascade/terminate_cascade_obligations_alerts_depth2
    """
    setup = FX.setup_simple_active(api, auto_renew=True, activation_clock="2026-06-01T00:00:00Z")
    contract_id = setup["contract"]["id"]
    obl = FX.get_success_data(api.create_obligation(
        contract_id, F.create_obligation_payload(contract_id, "2026-12-01T00:00:00Z"), MGR
    ))
    active = FX.get_contract(api, contract_id)
    validate_success(api.terminate_contract(contract_id, F.occ_payload(active["version"]), MGR), 200)

    terminated = FX.get_contract(api, contract_id)
    assert terminated["status"] == "TERMINATED", f"expected TERMINATED, got {terminated['status']}"
    obls = FX.get_success_data(api.list_obligations(contract_id, MGR))
    assert obls[0]["status"] == "WAIVED", f"OPEN obligation must be WAIVED on terminate, got {obls[0]['status']}"


def test_terminate_cancels_scheduled_renewal_alert(api):
    """PRD §3.7: "any renewal alert still SCHEDULED or DUE is moved to CANCELLED, a
    TERMINATED audit event is appended, and the contract's version is incremented."

    Design: Difficulty/transitive_cascade/terminate_cascade_obligations_alerts_depth2
    """
    setup = FX.setup_simple_active(api, auto_renew=True, activation_clock="2026-06-01T00:00:00Z")
    contract_id = setup["contract"]["id"]
    active = FX.get_contract(api, contract_id)
    validate_success(api.terminate_contract(contract_id, F.occ_payload(active["version"]), MGR), 200)

    alerts = FX.get_success_data(api.list_renewal_alerts(contract_id, MGR))
    assert alerts[0]["status"] == "CANCELLED", \
        f"SCHEDULED renewal alert must be CANCELLED on terminate, got {alerts[0]['status']}"


# ─── compensating_invariant: single current version ───────────────────

def test_redline_keeps_exactly_one_non_superseded_version(api):
    """PRD §2.5: "superseded versions are marked accordingly". PRD §3.2: "The
    contract's current_version_id advances to the new version" and "the prior current
    version's status becomes SUPERSEDED" — so the new version is the only
    non-superseded one.

    Design: Difficulty/compensating_invariant/redline_supersede_preserves_single_current_version
    """
    setup = _under_review_simple(api)
    contract_id = setup["contract"]["id"]
    v1_id = setup["version"]["id"]
    v2 = FX.add_version(
        api, contract_id,
        [F.clause_entry(setup["clauses"][0]["id"], text="redline", is_deviation=True)],
        setup["contract_submitted"]["version"], authored_by_party="COUNTERPARTY",
    )
    versions = FX.get_success_data(api.list_versions(contract_id, MGR))
    non_superseded = [v for v in versions if v["status"] != "SUPERSEDED"]
    assert len(non_superseded) == 1, \
        f"exactly one version must be non-SUPERSEDED, got {len(non_superseded)}"
    assert non_superseded[0]["id"] == v2["id"], "the non-superseded version must be the new one"
    v1 = FX.get_success_data(api.get_version(v1_id, MGR))
    assert v1["status"] == "SUPERSEDED", f"v1 must be SUPERSEDED, got {v1['status']}"


def test_redline_advances_current_version_id_to_new_version(api):
    """PRD §3.2: "The contract's current_version_id advances to the new version and
    its risk_score is recomputed provisionally".

    Design: Difficulty/compensating_invariant/redline_supersede_preserves_single_current_version
    """
    setup = _under_review_simple(api)
    contract_id = setup["contract"]["id"]
    v2 = FX.add_version(
        api, contract_id,
        [F.clause_entry(setup["clauses"][0]["id"], text="redline", is_deviation=True)],
        setup["contract_submitted"]["version"], authored_by_party="COUNTERPARTY",
    )
    contract = FX.get_contract(api, contract_id)
    assert contract["current_version_id"] == v2["id"], \
        f"current_version_id must advance to the new version, got {contract['current_version_id']}"


# ─── compensating_invariant: contiguous renewal term ──────────────────

def test_renewal_effective_date_equals_prior_expiry(api):
    """PRD §3.7: "A renewal... sets the contract's effective_date to the prior
    expiry_date so that terms are contiguous with no gap".

    Design: Difficulty/compensating_invariant/renewal_preserves_contiguous_term_no_gap
    """
    setup = FX.setup_simple_active(api, auto_renew=False, activation_clock="2026-06-01T00:00:00Z")
    contract_id = setup["contract"]["id"]
    before = FX.get_contract(api, contract_id)
    expiry_before = before["expiry_date"]
    FX.set_clock(api, "2027-05-02T00:00:00Z")  # alert now DUE
    active = FX.get_contract(api, contract_id)
    data = validate_success(api.renew_contract(contract_id, F.occ_payload(active["version"]), MGR), 200)
    assert data["effective_date"] == expiry_before, \
        f"renewal effective_date must equal prior expiry {expiry_before}, got {data['effective_date']}"
    assert data["effective_date"] == "2027-06-01T00:00:00.000Z", \
        f"prior expiry was 2027-06-01, got {data['effective_date']}"


def test_renewal_rolls_expiry_one_more_term_with_no_gap(api):
    """PRD §3.7: "recomputes expiry_date as that new effective date plus term_months
    calendar months — anchoring on the prior expiry rather than the renewal clock
    time keeps renewed terms gap-free and order-independent."

    Design: Difficulty/compensating_invariant/renewal_preserves_contiguous_term_no_gap
    """
    setup = FX.setup_simple_active(api, auto_renew=False, activation_clock="2026-06-01T00:00:00Z")
    contract_id = setup["contract"]["id"]
    FX.set_clock(api, "2027-05-02T00:00:00Z")  # alert DUE; renewal clock is NOT the anchor
    active = FX.get_contract(api, contract_id)
    data = validate_success(api.renew_contract(contract_id, F.occ_payload(active["version"]), MGR), 200)
    assert data["expiry_date"] == "2028-06-01T00:00:00.000Z", \
        f"renewed expiry must be prior expiry + 12mo = 2028-06-01 (not anchored on clock 2027-05-02), got {data['expiry_date']}"
