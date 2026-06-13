"""Multi-hop cascades: policy cancellation and loss-claim approval.

Covers the depth-3 cancel cascade (policy -> election VOID -> unit VOID + commission
clawback, PRD §3.2/§3.3/§3.8) and the depth-2 approve cascade (loss approve -> election
INDEMNIFIED -> policy total_indemnity, PRD §3.6).
"""
import pytest
from test_helpers import (
    validate_success, get_success_data,
    setup_activated_policy, setup_submitted_loss_claim,
)


def test_policy_cancel_cascades_void_units_and_clawback(api):
    """PRD §3.2: "every coverage election under the policy that is not already VOID
    transitions to VOID; then each voided election in turn voids its non-SETTLED units and
    claws back the election's AgentCommission."
    PRD §3.8: "When the underlying election is voided, the commission flips to CLAWED_BACK
    and its clawback_cents is set equal to its commission_cents, reversing the earned
    amount."
    PRD §3.3: "its units that are still PENDING transition to VOID"

    Design: Difficulty/transitive_cascade/cascade_policy_cancel_void_units_clawback_depth3
    """
    # RP election (total 527900, commission 42232) with a PENDING unit (no acreage report).
    ctx = setup_activated_policy(plan_type="RP", aph_yield=180, coverage_level=0.75,
                                 acres=100, share=1, base_premium_rate=0.085)
    policy = validate_success(api.cancel_policy(ctx["policy"]["id"], ctx["sa_headers"]), 200)
    assert policy["status"] == "CANCELLED", policy["status"]

    elec = get_success_data(api.get_coverage_election(ctx["election"]["id"], ctx["sa_headers"]))
    assert elec["status"] == "VOID", elec["status"]

    unit = get_success_data(api.get_unit(ctx["unit"]["id"], ctx["sa_headers"]))
    assert unit["status"] == "VOID", unit["status"]

    comms = get_success_data(api.list_agent_commissions(
        ctx["sa_headers"], params={"coverage_election_id": ctx["election"]["id"]}))
    assert comms, "commission entry must exist for the activated election"
    comm = comms[0]
    assert comm["status"] == "CLAWED_BACK", comm["status"]
    assert comm["clawback_cents"] == 42232, comm["clawback_cents"]


def test_policy_cancel_recomputes_premium_ledger_dropping_voided(api):
    """PRD §3.2: "After the cascade, the policy's premium ledger — total_premium_cents,
    producer_premium_cents, and subsidy_cents — is recomputed with the voided elections
    dropped, and the policy's version increments by one."

    Design: Difficulty/transitive_cascade/cascade_policy_cancel_void_units_clawback_depth3
    """
    # Activate (premium present), then cancel: the sole election voids, so the policy
    # premium ledger recomputes to all-zero.
    ctx = setup_activated_policy(plan_type="RP", aph_yield=180, coverage_level=0.75,
                                 acres=100, share=1, base_premium_rate=0.085)
    assert ctx["policy"]["total_premium_cents"] == 527900, ctx["policy"]["total_premium_cents"]
    validate_success(api.cancel_policy(ctx["policy"]["id"], ctx["sa_headers"]), 200)
    policy = get_success_data(api.get_policy(ctx["policy"]["id"], ctx["sa_headers"]))
    assert policy["total_premium_cents"] == 0, policy["total_premium_cents"]
    assert policy["producer_premium_cents"] == 0, policy["producer_premium_cents"]
    assert policy["subsidy_cents"] == 0, policy["subsidy_cents"]


def test_loss_approve_cascades_indemnify_and_policy_ledger(api):
    """PRD §3.6: "the owning election bubbles from REPORTED to INDEMNIFIED, the approved
    indemnity_cents is added into the policy's total_indemnity_cents"

    Design: Difficulty/transitive_cascade/cascade_loss_approve_indemnify_policy_ledger_depth2
    """
    ctx = setup_submitted_loss_claim(plan_type="YP", production_to_count_bu=10000,
                                     publish_harvest=5.20)
    validate_success(api.approve_loss_claim(ctx["claim"]["id"], ctx["adj_headers"]), 200)

    elec = get_success_data(api.get_coverage_election(ctx["election"]["id"], ctx["sa_headers"]))
    assert elec["status"] == "INDEMNIFIED", elec["status"]

    policy = get_success_data(api.get_policy(ctx["policy"]["id"], ctx["sa_headers"]))
    assert policy["total_indemnity_cents"] == 1400000, policy["total_indemnity_cents"]


def test_loss_approve_settles_unit(api):
    """PRD §3.6: "the unit transitions to SETTLED if no other open claim remains on it."

    Design: Difficulty/transitive_cascade/cascade_loss_approve_indemnify_policy_ledger_depth2
    """
    ctx = setup_submitted_loss_claim(plan_type="YP", production_to_count_bu=10000,
                                     publish_harvest=5.20)
    validate_success(api.approve_loss_claim(ctx["claim"]["id"], ctx["adj_headers"]), 200)
    unit = get_success_data(api.get_unit(ctx["unit"]["id"], ctx["sa_headers"]))
    assert unit["status"] == "SETTLED", unit["status"]
