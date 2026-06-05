"""Risk scoring and the legal-review cost estimate.

Covers the provisional-vs-final risk dual variant and the marginal-tiered cost
estimate (queue A difficulty), plus the zero-deviation base, mandatory-miss
penalty, ceiling clamp, and immediate-consistency corners (queue B).
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    factories as F, fixtures as FX,
    assert_cost_estimate,
)

ADMIN = FX.ADMIN
MGR = FX.MGR
RISK = FX.RISK


@pytest.fixture
def api():
    return api_client


def _two_deviation_setup(api, threshold):
    """Org (threshold) + LIABILITY_CAP(w=40) + INDEMNITY(w=30), a contract whose v1
    deviates BOTH clauses (provisional risk 70), plus a PENDING DeviationApproval on
    the LIABILITY_CAP clause. Returns the setup dict augmented with workflow,
    deviation id, and the contract.version after the deviation request."""
    setup = FX.setup_draft_contract_with_version(
        api,
        clauses_spec=[
            {"clause_index": 0, "is_deviation": True, "text": "edited-liab"},
            {"clause_index": 1, "is_deviation": True, "text": "edited-indem"},
        ],
        clause_defs=[
            {"clause_key": "LIABILITY_CAP", "risk_weight": 40, "category": "LIABILITY"},
            {"clause_key": "INDEMNITY", "risk_weight": 30, "category": "INDEMNITY"},
        ],
        org_overrides={"risk_appetite_threshold": threshold, "auto_renew_lead_days": 30},
    )
    liab_id = setup["clauses"][0]["id"]
    dev = FX.request_deviation(api, setup["contract"]["id"], setup["version"]["id"], liab_id)
    setup["deviation"] = dev
    return setup


# ─── Queue A: dual_variant_calc / risk provisional vs final ───────────

def test_risk_score_provisional_at_submit_counts_all_deviations(api):
    """PRD §2.8: "The provisional score is computed at submit time and at
    version-create time, while the workflow is still pending; its input set includes
    every clause currently flagged as a deviation, including those whose
    DeviationApproval is still pending."

    Design: Difficulty/dual_variant_calc/risk_score_provisional_vs_final_on_deviation_grant
    """
    setup = _two_deviation_setup(api, threshold=60)
    contract = setup["contract_after"]
    submitted = FX.submit_contract(api, contract["id"], contract["version"])
    assert submitted["risk_score"] == 70, \
        f"provisional risk must count both deviations (40+30=70), got {submitted['risk_score']}"


def test_risk_score_final_at_approval_excludes_granted_deviation(api):
    """PRD §2.8: "The final score is recomputed when the workflow reaches approval;
    its input set excludes the risk_weight of any deviated clause that has a granted
    DeviationApproval pinned to the current version — those deviations count as
    cleared and no longer add weight".
    PRD §3.3: "the contract's risk_score is recomputed in its final form (clearing
    granted deviations as described in §2.8)".

    Design: Difficulty/dual_variant_calc/risk_score_provisional_vs_final_on_deviation_grant
    """
    setup = _two_deviation_setup(api, threshold=60)
    contract = setup["contract_after"]
    submitted = FX.submit_contract(api, contract["id"], contract["version"])
    assert submitted["risk_score"] == 70  # provisional

    # Grant the LIABILITY_CAP (w=40) deviation, then reach quorum.
    FX.decide_deviation(api, setup["deviation"]["id"], decision="GRANT")
    workflow = FX.get_open_workflow(api, contract["id"])
    FX.record_approval(api, workflow["id"], decision="APPROVE")

    final = FX.get_contract(api, contract["id"])
    assert final["status"] == "APPROVED", f"contract must reach APPROVED, got {final['status']}"
    assert final["risk_score"] == 30, \
        f"final risk must exclude the GRANTED w=40 deviation (only INDEMNITY w=30 remains), got {final['risk_score']}"


# ─── Queue A: combinatorial_formula / cost marginal tiering ───────────

def _five_deviation_contract(api):
    """A DRAFT contract whose v1 deviates all 5 clauses (deviation_count 5)."""
    return FX.setup_draft_contract_with_version(
        api,
        clauses_spec=[{"clause_index": i, "is_deviation": True, "text": f"d{i}"} for i in range(5)],
        clause_defs=[{"clause_key": f"C{i+1}", "risk_weight": 1} for i in range(5)],
        org_overrides={"risk_appetite_threshold": 100},
    )


def test_cost_estimate_marginal_tiering_at_five_deviations(api):
    """PRD §3.8: "a version with a deviation_count of five costs the base plus three
    units at the tier-one rate plus two units at the tier-two rate." (50000 +
    3*10000 + 2*7500 = 95000).

    Design: Difficulty/combinatorial_formula/cost_estimate_marginal_tiering_mode_a
    """
    setup = _five_deviation_contract(api)
    resp = api.get_cost_estimate(setup["contract"]["id"], RISK)
    data = validate_success(resp, 200)
    assert_cost_estimate(data)
    assert data["review_cost_cents"] == 95000, \
        f"marginal cost for 5 deviations must be 95000, got {data['review_cost_cents']}"


def test_cost_estimate_echoes_deviation_count(api):
    """PRD §3.8: "The result, review_cost_cents, is the base plus this marginal sum;
    the response also echoes the contract_id and the deviation_count."

    Design: Difficulty/combinatorial_formula/cost_estimate_marginal_tiering_mode_a
    """
    setup = _five_deviation_contract(api)
    resp = api.get_cost_estimate(setup["contract"]["id"], RISK)
    data = validate_success(resp, 200)
    assert data["deviation_count"] == 5, \
        f"cost-estimate must echo deviation_count 5, got {data['deviation_count']}"
    assert data["contract_id"] == setup["contract"]["id"], "cost-estimate must echo contract_id"


# ─── Queue B: calculations corners ────────────────────────────────────

def test_cost_estimate_zero_deviations_is_base_only(api):
    """PRD §3.8: "The estimate always begins from a base of 50000 cents." With no
    deviations, no tier units are added.

    Design: Corner/calculations/cost_estimate_zero_deviations_base_only
    """
    setup = FX.setup_draft_contract_with_version(
        api, FX.simple_clauses_spec(), clause_defs=FX.simple_clause_defs()
    )
    resp = api.get_cost_estimate(setup["contract"]["id"], RISK)
    data = validate_success(resp, 200)
    assert data["review_cost_cents"] == 50000, \
        f"zero-deviation estimate must be base 50000, got {data['review_cost_cents']}"


def test_risk_score_adds_mandatory_miss_penalty(api):
    """PRD §2.8: "for each clause template that the contract's ContractTemplate lists
    in its clause_template_ids and marks with is_mandatory true, but which is
    entirely absent from the current version's clauses... a penalty of 25 points is
    added."

    Design: Corner/calculations/risk_score_mandatory_miss_penalty_applied
    """
    # Mandatory TERMINATION (w=10) + non-mandatory INDEMNITY (w=30); v1 deviates only
    # INDEMNITY and omits TERMINATION -> 30 + 25 = 55.
    setup = FX.setup_draft_contract_with_version(
        api,
        clauses_spec=[{"clause_index": 1, "is_deviation": True, "text": "edited"}],
        clause_defs=[
            {"clause_key": "TERMINATION", "risk_weight": 10, "category": "TERMINATION", "is_mandatory": True},
            {"clause_key": "INDEMNITY", "risk_weight": 30, "category": "INDEMNITY", "is_mandatory": False},
        ],
        org_overrides={"risk_appetite_threshold": 100},
    )
    contract = setup["contract_after"]
    submitted = FX.submit_contract(api, contract["id"], contract["version"])
    assert submitted["risk_score"] == 55, \
        f"risk must be 30 (deviation) + 25 (mandatory-miss) = 55, got {submitted['risk_score']}"


def test_risk_score_clamped_to_ceiling(api):
    """PRD §2.8: "The risk score is the sum of the raw weight and the mandatory-miss
    penalty, summed first and then clamped into the range 0 through 100 — a floor of
    0 and a ceiling of 100, applied only after the summation."

    Design: Corner/calculations/risk_score_clamped_at_ceiling_100
    """
    # Three deviations w=40, w=40, w=30 -> raw 110 -> clamp to 100.
    setup = FX.setup_draft_contract_with_version(
        api,
        clauses_spec=[
            {"clause_index": 0, "is_deviation": True, "text": "d"},
            {"clause_index": 1, "is_deviation": True, "text": "d"},
            {"clause_index": 2, "is_deviation": True, "text": "d"},
        ],
        clause_defs=[
            {"clause_key": "L1", "risk_weight": 40, "category": "LIABILITY"},
            {"clause_key": "L2", "risk_weight": 40, "category": "LIABILITY"},
            {"clause_key": "I1", "risk_weight": 30, "category": "INDEMNITY"},
        ],
        org_overrides={"risk_appetite_threshold": 100},
    )
    contract = setup["contract_after"]
    submitted = FX.submit_contract(api, contract["id"], contract["version"])
    assert submitted["risk_score"] == 100, \
        f"raw 110 must clamp to ceiling 100, got {submitted['risk_score']}"


def test_submit_response_reflects_provisional_risk_immediately(api):
    """PRD §3.2: "It recomputes risk_score provisionally, appends a SUBMITTED audit
    event, and increments the contract's version." The recomputed score is part of
    the returned contract (PRD §2.4 derived-field changes are mutations of the
    contract).

    Design: Corner/consistency_model/immediate_consistency_risk_score_visible_in_submit_response
    """
    setup = FX.setup_draft_contract_with_version(
        api,
        clauses_spec=[{"clause_index": 0, "is_deviation": True, "text": "edit"}],
        clause_defs=[{"clause_key": "LIABILITY_CAP", "risk_weight": 40, "category": "LIABILITY"}],
        org_overrides={"risk_appetite_threshold": 100},
    )
    contract = setup["contract_after"]
    resp = api.submit_contract(contract["id"], F.submit_payload(contract["version"]), MGR)
    data = validate_success(resp, 200)
    assert data["risk_score"] == 40, \
        f"submit response must immediately reflect provisional risk 40, got {data['risk_score']}"
    assert data["status"] == "UNDER_REVIEW", f"submit must move to UNDER_REVIEW, got {data['status']}"
