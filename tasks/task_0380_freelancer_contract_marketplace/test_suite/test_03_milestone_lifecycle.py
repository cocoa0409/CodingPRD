"""Milestone lifecycle: creation, funding, submission, the APPROVE/DISPUTE fork, and the
cross-entity precondition that funding requires an ACTIVE parent contract.

Queue A: non_linear_state_machine / milestone_branching_fork_approve_vs_dispute;
         cross_entity_state_dependency / cross_milestone_fund_requires_contract_active.
Queue B: initial state, invalid transition, terminal lockdown, open-item gating,
         insufficient wallet, duplicate ordinal, immediate visibility.
"""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, NON_EXISTENT_UUID,
    create_milestone_payload, fund_payload, dispute_payload,
    assert_milestone,
    make_client_headers, make_freelancer_headers, make_admin_headers,
    create_client, create_freelancer,
    create_active_contract, add_milestone, fund_milestone,
    setup_funded_milestone, setup_submitted_milestone, setup_approved_milestone,
    setup_released_milestone,
)


# ─── Branching fork: APPROVE vs DISPUTE ───────────────────────────────
def _two_submitted_milestones():
    """Active FIXED contract with two FUNDED->SUBMITTED milestones (20000 each).
    Returns (ctx, m_a, m_b)."""
    ctx = create_active_contract(billing_type="FIXED", skills=("c",), bid_amount_cents=40000,
                                 budget_cents=60000, deposit_cents=100000, tax_id_on_file=True)
    m_a = add_milestone(ctx, 20000, ordinal=1, title="A")
    m_b = add_milestone(ctx, 20000, ordinal=2, title="B")
    m_a = fund_milestone(ctx, m_a["id"])
    m_b = fund_milestone(ctx, m_b["id"])
    validate_success(api_client.submit_milestone(ctx["contract"]["id"], m_a["id"], ctx["freelancer_headers"]), 200)
    validate_success(api_client.submit_milestone(ctx["contract"]["id"], m_b["id"], ctx["freelancer_headers"]), 200)
    return ctx, m_a, m_b


def test_fork_approve_branch_no_dispute_side_effect(api):
    """PRD §3.5: "On the approval branch, a Client approves a SUBMITTED milestone, moving
    it to APPROVED".
    PRD §3.3: "open_dispute_count counts non-terminal disputes on the contract."

    Design: Difficulty/non_linear_state_machine/milestone_branching_fork_approve_vs_dispute
    """
    ctx, m_a, m_b = _two_submitted_milestones()
    approved = validate_success(api.approve_milestone(ctx["contract"]["id"], m_a["id"], ctx["client_headers"]), 200)
    assert approved["status"] == "APPROVED"
    contract = validate_success(api.get_contract(ctx["contract"]["id"], ctx["client_headers"]), 200)
    assert contract["open_dispute_count"] == 0


def test_fork_dispute_branch_increments_open_dispute_count(api):
    """PRD §3.7: "The act moves the milestone to DISPUTED, creates a Dispute in OPEN whose
    contract_id is copied from the milestone and whose milestone_id names the disputed
    milestone, and increments the contract's open_dispute_count. This is the second branch
    of the fork out of SUBMITTED, and it carries a different side-effect set than approval."

    Design: Difficulty/non_linear_state_machine/milestone_branching_fork_approve_vs_dispute
    """
    ctx, m_a, m_b = _two_submitted_milestones()
    validate_success(api.approve_milestone(ctx["contract"]["id"], m_a["id"], ctx["client_headers"]), 200)
    dispute_res = api.dispute_milestone(
        ctx["contract"]["id"], m_b["id"],
        dispute_payload("CLIENT", claimed_release_cents=20000, reason="rework"), ctx["client_headers"])
    validate_success(dispute_res, 201)
    m_b_after = validate_success(api.get_milestone_in_contract(ctx["contract"]["id"], m_b["id"], ctx["client_headers"]), 200)
    assert m_b_after["status"] == "DISPUTED"
    m_a_after = validate_success(api.get_milestone_in_contract(ctx["contract"]["id"], m_a["id"], ctx["client_headers"]), 200)
    assert m_a_after["status"] == "APPROVED"
    contract = validate_success(api.get_contract(ctx["contract"]["id"], ctx["client_headers"]), 200)
    assert contract["open_dispute_count"] == 1


# Note: the difficulty instance
# cross_entity_state_dependency/cross_milestone_fund_requires_contract_active is SKIPPED.
# Its trigger funds a non-existent milestone id on an existing DRAFT contract and expects
# ERR_CONTRACT_NOT_ACTIVE, but PRD §2.5 uniquely derives the opposite for that exact request:
# "only once the contract resolves does a bad milestone identifier surface as
# ERR_MILESTONE_NOT_FOUND." A real milestone cannot exist on a non-ACTIVE contract
# (milestones are only created on ACTIVE contracts, and the only non-ACTIVE successors are
# the terminal states that cancel milestones), so no reachable state uniquely yields
# ERR_CONTRACT_NOT_ACTIVE. The instance therefore fails unique-derivability and is not
# translated.


# ─── Corner: state-machine and constraint claims ──────────────────────
def test_initial_state_milestone_is_draft(api):
    """PRD §3.3: "A milestone opens in DRAFT."
    PRD §3.3: "The system tracks funded_cents, released_gross_cents, and refunded_cents
    against the escrow ledger as those events land."

    Design: Corner/state_machines/initial_state_milestone_is_draft
    """
    ctx = create_active_contract(billing_type="FIXED", skills=("x",), bid_amount_cents=20000,
                                 budget_cents=30000, deposit_cents=0, tax_id_on_file=True)
    res = api.create_milestone(ctx["contract"]["id"],
                               create_milestone_payload(amount_cents=20000, ordinal=1),
                               ctx["client_headers"])
    milestone = validate_success(res, 201)
    assert_milestone(milestone)
    assert milestone["status"] == "DRAFT"
    assert milestone["funded_cents"] == 0
    assert milestone["released_gross_cents"] == 0


def test_invalid_transition_approve_from_funded(api):
    """PRD §3.5: "approving a milestone not in SUBMITTED is rejected with
    ERR_INVALID_MILESTONE_STATE."

    Design: Corner/state_machines/invalid_transition_approve_from_funded
    """
    ctx, milestone = setup_funded_milestone(amount_cents=20000)
    res = api.approve_milestone(ctx["contract"]["id"], milestone["id"], ctx["client_headers"])
    validate_error(res, "ERR_INVALID_MILESTONE_STATE", expected_status=409)
    after = validate_success(api.get_milestone_in_contract(ctx["contract"]["id"], milestone["id"], ctx["client_headers"]), 200)
    assert after["status"] == "FUNDED"


def test_terminal_lockdown_release_already_released(api):
    """PRD §3.5: "a release attempt on a milestone not in APPROVED is rejected with
    ERR_INVALID_MILESTONE_STATE."

    Design: Corner/state_machines/terminal_lockdown_release_already_released
    """
    ctx, milestone = setup_released_milestone(amount_cents=20000)
    assert milestone["status"] == "RELEASED"
    assert milestone["released_gross_cents"] == 20000
    cv = validate_success(api.get_contract(ctx["contract"]["id"], ctx["client_headers"]), 200)["version"]
    res = api.release_milestone(ctx["contract"]["id"], milestone["id"], fund_payload(cv), ctx["client_headers"])
    validate_error(res, "ERR_INVALID_MILESTONE_STATE", expected_status=409)
    after = validate_success(api.get_milestone_in_contract(ctx["contract"]["id"], milestone["id"], ctx["client_headers"]), 200)
    assert after["released_gross_cents"] == 20000


def test_precondition_complete_blocked_by_open_milestone(api):
    """PRD §3.8: "Completion requires the contract to be ACTIVE, requires open_milestone_count
    to be zero — meaning every milestone has reached RELEASED, REFUNDED, or CANCELLED — and
    requires open_dispute_count to be zero; a completion attempt while either count is above
    zero is rejected with ERR_CONTRACT_HAS_OPEN_ITEMS".

    Design: Corner/state_machines/precondition_complete_blocked_by_open_milestone
    """
    ctx, milestone = setup_funded_milestone(amount_cents=20000)  # FUNDED is non-terminal
    res = api.complete_contract(ctx["contract"]["id"], ctx["client_headers"])
    validate_error(res, "ERR_CONTRACT_HAS_OPEN_ITEMS", expected_status=409)
    after = validate_success(api.get_contract(ctx["contract"]["id"], ctx["client_headers"]), 200)
    assert after["status"] == "ACTIVE"


def test_insufficient_wallet_on_fund(api):
    """PRD §3.5: "only when the client's wallet_balance_cents is at least the milestone's
    amount_cents ... An insufficient wallet is rejected with ERR_INSUFFICIENT_WALLET".

    Design: Corner/validations/insufficient_wallet_on_fund
    """
    ctx = create_active_contract(billing_type="FIXED", skills=("x",), bid_amount_cents=20000,
                                 budget_cents=30000, deposit_cents=5000, tax_id_on_file=True)
    milestone = add_milestone(ctx, 20000, ordinal=1)
    cv = validate_success(api.get_contract(ctx["contract"]["id"], ctx["client_headers"]), 200)["version"]
    res = api.fund_milestone(ctx["contract"]["id"], milestone["id"], fund_payload(cv), ctx["client_headers"])
    validate_error(res, "ERR_INSUFFICIENT_WALLET", expected_status=402)
    after = validate_success(api.get_milestone_in_contract(ctx["contract"]["id"], milestone["id"], ctx["client_headers"]), 200)
    assert after["status"] == "DRAFT"
    client_after = validate_success(api.get_client(ctx["client"]["id"], ctx["client_headers"]), 200)
    assert client_after["wallet_balance_cents"] == 5000


def test_duplicate_milestone_ordinal_rejected(api):
    """PRD §3.3: "an ordinal that fixes the one-based sequence position and must be unique
    within the contract — a repeated ordinal is rejected with ERR_DUPLICATE_MILESTONE_ORDINAL."

    Design: Corner/validations/duplicate_milestone_ordinal_rejected
    """
    ctx = create_active_contract(billing_type="FIXED", skills=("x",), bid_amount_cents=20000,
                                 budget_cents=30000, deposit_cents=0, tax_id_on_file=True)
    validate_success(api.create_milestone(ctx["contract"]["id"],
                     create_milestone_payload(title="M1", amount_cents=5000, ordinal=1),
                     ctx["client_headers"]), 201)
    res = api.create_milestone(ctx["contract"]["id"],
                               create_milestone_payload(title="Dup", amount_cents=6000, ordinal=1),
                               ctx["client_headers"])
    validate_error(res, "ERR_DUPLICATE_MILESTONE_ORDINAL", expected_status=409)


def test_immediate_visibility_fund_reflected_in_get(api):
    """PRD §3.5: "On success the system debits the client's wallet_balance_cents by
    amount_cents, writes a FUND EscrowTransaction in HELD status setting the milestone's
    funded_cents to amount_cents, and increments the contract's version by one."

    Design: Corner/consistency_model/immediate_visibility_fund_reflected_in_get
    """
    ctx = create_active_contract(billing_type="FIXED", skills=("x",), bid_amount_cents=20000,
                                 budget_cents=30000, deposit_cents=20000, tax_id_on_file=True)
    milestone = add_milestone(ctx, 20000, ordinal=1)
    funded = fund_milestone(ctx, milestone["id"])
    assert funded["status"] == "FUNDED"
    fetched = validate_success(api.get_milestone_in_contract(ctx["contract"]["id"], milestone["id"], ctx["client_headers"]), 200)
    assert fetched["funded_cents"] == 20000
    assert fetched["status"] == "FUNDED"
