"""Indemnity payment workflow: authority routing boundary, segregation of duties, coverage
limit, SIU hold gating, terminal lockdown, hold-lift, void compensation, and reject branch.

Translates boundary_precision (approval authority), cross_entity_state_dependency (SIU hold),
compensating_invariant (issue/void), non_linear_state_machine (reject branch) difficulty
instances and several payment corner instances.
"""
from test_helpers import (
    validate_success, validate_error, TEST_USERS,
    setup_assigned_claim, post_reserve_change, create_pending_payment,
    create_approved_payment, create_issued_payment, create_siu_referral,
    get_claim,
)

CM = TEST_USERS["claims_manager_headers"]
FO = TEST_USERS["finance_officer_headers"]
SIU = TEST_USERS["siu_investigator_headers"]


# --------------------------------------------------------------------------- #
# Approval-authority boundary (strict greater-than)
# --------------------------------------------------------------------------- #
def test_payment_equal_to_authority_needs_no_manager(api):
    """PRD §3.5: "At creation the system computes `requires_manager_approval`: it is true
    exactly when `amount_cents` is strictly greater than the creating adjuster's
    `authority_limit_cents`, and false when the amount equals or is below that limit (an amount
    equal to the limit is within authority)."

    Design: Difficulty/boundary_precision_check/payment_manager_approval_at_authority_vs_over
    """
    env = setup_assigned_claim(
        api, account_overrides={"account_code": "BP1"},
        adjuster_overrides={"authority_limit_cents": 5000000})
    payment = create_pending_payment(api, env["claim"]["id"], env["adj_headers"], 5000000)
    assert payment["requires_manager_approval"] is False


def test_payment_over_authority_rejects_adjuster_approval(api):
    """PRD §3.5: "when it is true only a `ClaimsManager` may, and an attempt by any other role
    is rejected with `ERR_APPROVAL_AUTHORITY_REQUIRED`."

    Design: Difficulty/boundary_precision_check/payment_manager_approval_at_authority_vs_over
    """
    env = setup_assigned_claim(
        api, account_overrides={"account_code": "BP1b"},
        adjuster_overrides={"authority_limit_cents": 5000000})
    claim_id, adj = env["claim"]["id"], env["adj_headers"]
    payment = create_pending_payment(api, claim_id, adj, 5000001)
    assert payment["requires_manager_approval"] is True
    resp = api.transition_payment(payment["id"], "APPROVED", adj)
    validate_error(resp, "ERR_APPROVAL_AUTHORITY_REQUIRED")


# --------------------------------------------------------------------------- #
# Segregation of duties / coverage limit at issuance
# --------------------------------------------------------------------------- #
def test_adjuster_may_not_issue_payment(api):
    """PRD §3.5: "Issuance is the disbursement of cash and is reserved to a `FinanceOfficer`,
    moving the payment `APPROVED → ISSUED`."

    Design: Corner/validations/adjuster_cannot_issue_payment
    """
    env = setup_assigned_claim(api, account_overrides={"account_code": "C-AI"})
    claim_id, adj = env["claim"]["id"], env["adj_headers"]
    post_reserve_change(api, claim_id, adj, 200000)
    payment = create_approved_payment(api, claim_id, adj, 200000)
    validate_error(api.transition_payment(payment["id"], "ISSUED", adj), "ERR_UNAUTHORIZED")
    assert validate_success(api.get_payment(payment["id"], adj), 200)["status"] == "APPROVED"


def test_issue_exceeding_coverage_limit_rejected(api):
    """PRD §3.5: "the payment must fit within coverage — specifically `amount_cents` plus the
    claim's current `paid_indemnity_cents`, less the policy's `deductible_cents`, must be no
    greater than the policy's `coverage_limit_cents`, or the issuance is rejected with
    `ERR_COVERAGE_LIMIT_EXCEEDED`."

    Design: Corner/validations/coverage_limit_exceeded_on_issue
    """
    env = setup_assigned_claim(
        api, account_overrides={"account_code": "C-CL"},
        policy_overrides={"coverage_limit_cents": 500000})
    claim_id, adj = env["claim"]["id"], env["adj_headers"]
    post_reserve_change(api, claim_id, adj, 600000)
    payment = create_approved_payment(api, claim_id, adj, 600000)
    validate_error(api.transition_payment(payment["id"], "ISSUED", FO), "ERR_COVERAGE_LIMIT_EXCEEDED")


# --------------------------------------------------------------------------- #
# SIU hold gating on issuance (cross-entity)
# --------------------------------------------------------------------------- #
def test_issue_blocked_while_claim_on_siu_hold(api):
    """PRD §3.8: "while it is `HELD`, issuing a payment or paying a vendor invoice is blocked
    with `ERR_SIU_HOLD_ACTIVE`, and a claim that is `HELD` cannot be closed."

    Design: Difficulty/cross_entity_state_dependency/payment_issue_blocked_by_claim_siu_hold
    """
    env = setup_assigned_claim(api, account_overrides={"account_code": "CE1"})
    claim_id, adj = env["claim"]["id"], env["adj_headers"]
    post_reserve_change(api, claim_id, adj, 600000)
    payment = create_approved_payment(api, claim_id, adj, 600000)
    create_siu_referral(api, claim_id, place_hold=True)
    validate_error(api.transition_payment(payment["id"], "ISSUED", FO), "ERR_SIU_HOLD_ACTIVE")
    assert get_claim(api, claim_id, adj)["siu_status"] == "HELD"


def test_siu_hold_leaves_payment_in_approved(api):
    """PRD §2.8: "the claim is not on an SIU hold when issuing a payment or paying an invoice,
    else `ERR_SIU_HOLD_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/payment_issue_blocked_by_claim_siu_hold
    """
    env = setup_assigned_claim(api, account_overrides={"account_code": "CE1b"})
    claim_id, adj = env["claim"]["id"], env["adj_headers"]
    post_reserve_change(api, claim_id, adj, 600000)
    payment = create_approved_payment(api, claim_id, adj, 600000)
    create_siu_referral(api, claim_id, place_hold=True)
    validate_error(api.transition_payment(payment["id"], "ISSUED", FO), "ERR_SIU_HOLD_ACTIVE")
    assert validate_success(api.get_payment(payment["id"], adj), 200)["status"] == "APPROVED"


# --------------------------------------------------------------------------- #
# Terminal lockdown + hold lift
# --------------------------------------------------------------------------- #
def test_rejected_payment_cannot_be_approved(api):
    """PRD §3.5: "Alternatively a `ClaimsManager` may reject a pending payment, moving it
    `PENDING_APPROVAL → REJECTED`, which is terminal."

    Design: Corner/state_machines/payment_terminal_lockdown_from_rejected
    """
    env = setup_assigned_claim(api, account_overrides={"account_code": "C-TL"})
    claim_id, adj = env["claim"]["id"], env["adj_headers"]
    payment = create_pending_payment(api, claim_id, adj, 100000)
    validate_success(api.transition_payment(payment["id"], "REJECTED", CM), 200)
    validate_error(api.transition_payment(payment["id"], "APPROVED", CM), "ERR_INVALID_STATE")
    assert validate_success(api.get_payment(payment["id"], adj), 200)["status"] == "REJECTED"


def test_clearing_siu_hold_lets_payment_issue(api):
    """PRD §3.8: "Clearing a referral (`OPEN → CLEARED`) lifts any hold: if the claim's
    `siu_status` is currently `HELD`, it is set to `CLEARED`, which re-permits payment issuance
    and invoice payment."

    Design: Corner/state_machines/siu_clear_lifts_hold_then_pay
    """
    env = setup_assigned_claim(api, account_overrides={"account_code": "C-SC"})
    claim_id, adj = env["claim"]["id"], env["adj_headers"]
    post_reserve_change(api, claim_id, adj, 300000)
    payment = create_approved_payment(api, claim_id, adj, 300000)
    referral = create_siu_referral(api, claim_id, place_hold=True)
    validate_success(api.transition_siu_referral(referral["id"], "CLEARED", SIU), 200)
    validate_success(api.transition_payment(payment["id"], "ISSUED", FO), 200)
    claim = get_claim(api, claim_id, adj)
    assert claim["siu_status"] == "CLEARED"
    assert claim["paid_indemnity_cents"] == 300000
    assert validate_success(api.get_payment(payment["id"], adj), 200)["status"] == "ISSUED"


# --------------------------------------------------------------------------- #
# Issue/void conservation of incurred
# --------------------------------------------------------------------------- #
def test_gross_incurred_conserved_across_issue_and_void(api):
    """PRD §3.5: "Voiding an issued payment is a compensating reversal: it subtracts
    `amount_cents` back out of `paid_indemnity_cents`, restores `amount_cents` to
    `indemnity_reserve_cents` (undoing the reserve release performed at issuance), and
    recomputes the claim's incurred figures and the account roll-up."

    Design: Difficulty/compensating_invariant/incurred_conserved_across_payment_issue_and_void
    """
    env = setup_assigned_claim(api, account_overrides={"account_code": "CI1"})
    claim_id, adj = env["claim"]["id"], env["adj_headers"]
    post_reserve_change(api, claim_id, adj, 1000000)
    payment = create_issued_payment(api, claim_id, adj, 400000)
    validate_success(api.transition_payment(payment["id"], "VOID", FO), 200)
    assert get_claim(api, claim_id, adj)["gross_incurred_cents"] == 1000000


def test_buckets_restored_after_issue_and_void(api):
    """PRD §3.5: "Voiding an issued payment is a compensating reversal: it subtracts
    `amount_cents` back out of `paid_indemnity_cents`, restores `amount_cents` to
    `indemnity_reserve_cents` (undoing the reserve release performed at issuance), and
    recomputes the claim's incurred figures and the account roll-up."

    Design: Difficulty/compensating_invariant/incurred_conserved_across_payment_issue_and_void
    """
    env = setup_assigned_claim(api, account_overrides={"account_code": "CI1b"})
    claim_id, adj = env["claim"]["id"], env["adj_headers"]
    post_reserve_change(api, claim_id, adj, 1000000)
    payment = create_issued_payment(api, claim_id, adj, 400000)
    validate_success(api.transition_payment(payment["id"], "VOID", FO), 200)
    claim = get_claim(api, claim_id, adj)
    assert claim["indemnity_reserve_cents"] == 1000000
    assert claim["paid_indemnity_cents"] == 0


# --------------------------------------------------------------------------- #
# Reject branch draws no money
# --------------------------------------------------------------------------- #
def test_payment_reject_branch_reaches_rejected(api):
    """PRD §3.5: "Alternatively a `ClaimsManager` may reject a pending payment, moving it
    `PENDING_APPROVAL → REJECTED`, which is terminal."

    Design: Difficulty/non_linear_state_machine/payment_branch_pending_to_rejected
    """
    env = setup_assigned_claim(api, account_overrides={"account_code": "NL2"})
    claim_id, adj = env["claim"]["id"], env["adj_headers"]
    payment = create_pending_payment(api, claim_id, adj, 300000)
    rejected = validate_success(api.transition_payment(payment["id"], "REJECTED", CM), 200)
    assert rejected["status"] == "REJECTED"


def test_payment_reject_branch_draws_no_indemnity(api):
    """PRD §3.5: "On issuance the system adds `amount_cents` to `paid_indemnity_cents`,
    reduces `indemnity_reserve_cents` by `amount_cents` floored at zero (releasing reserve as
    it converts to paid), stamps `issued_at` with the clock, records `approved_by_role`, and
    recomputes the claim's incurred figures and the account roll-up."

    Design: Difficulty/non_linear_state_machine/payment_branch_pending_to_rejected
    """
    env = setup_assigned_claim(api, account_overrides={"account_code": "NL2b"})
    claim_id, adj = env["claim"]["id"], env["adj_headers"]
    payment = create_pending_payment(api, claim_id, adj, 300000)
    validate_success(api.transition_payment(payment["id"], "REJECTED", CM), 200)
    # The REJECTED branch never runs the issuance side effect, so no indemnity is paid.
    assert get_claim(api, claim_id, adj)["paid_indemnity_cents"] == 0
