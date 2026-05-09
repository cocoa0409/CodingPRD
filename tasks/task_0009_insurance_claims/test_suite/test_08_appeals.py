"""Appeal lifecycle: file, withdraw, secondary review, segregation of duties.

Pinned to PRD §3.7 (appeals), §2.7 (segregation of duties at secondary review).
"""
import pytest
from test_helpers import (
    validate_success, validate_error,
    create_appeal_payload, create_appeal_decision_payload,
    setup_claim_denied, setup_claim_appealed, create_appeal,
    record_appeal_decision, record_primary_decision, get_claim,
    make_customer_headers, make_reviewer_headers, make_adjuster_headers,
    TEST_USERS,
    assert_appeal,
)


# ─── §3.7 file appeal ────────────────────────────────────────────
def test_appeal_creation_advances_to_under_reconsideration(api):
    """PRD §3.7: "Filing creates an `Appeal` row in `SUBMITTED` status, which
    the server immediately auto-advances to `UNDER_RECONSIDERATION` as a
    side effect of creation; the parent claim transitions from `DENIED` to
    `APPEALED`."

    Claim: POST /appeals on a DENIED claim -> Appeal in UNDER_RECONSIDERATION,
    Claim in APPEALED.
    """
    state = setup_claim_denied(claimed_amount_cents=5_000_000,
                                assessed_loss_cents=5_000_000,
                                coverage_limit_cents=100_000_000)
    state = create_appeal(state)
    assert state["appeal"]["status"] == "UNDER_RECONSIDERATION"
    assert state["claim"]["status"] == "APPEALED"
    assert_appeal(state["appeal"])


def test_appeal_only_by_original_claimant(api):
    """PRD §3.7: "The appeal capability is restricted to the original
    claimant (the appeal's `requestor_id` is set from the caller's
    `X-User-ID` and must equal `Claim.claimant_id`)."

    Claim: a non-claimant Customer cannot file the appeal.
    """
    state = setup_claim_denied(claimed_amount_cents=5_000_000,
                                assessed_loss_cents=5_000_000,
                                coverage_limit_cents=100_000_000)
    foreign = "foreign-customer-3030"
    res = api.create_appeal(
        state["claim"]["id"],
        create_appeal_payload(grounds="g"),
        make_customer_headers(foreign),
    )
    body = res.json()
    assert res.status_code >= 400, f"Foreign customer must not appeal: {body}"


def test_only_one_appeal_per_claim(api):
    """PRD §3.7: "Two simultaneous appeal-creation attempts on the same
    denied claim serialise on the per-claim uniqueness constraint; the
    loser is rejected with `ERR_APPEAL_ALREADY_EXISTS`."

    Claim: a sequential second appeal attempt on a claim that already has
    an Appeal -> ERR_APPEAL_ALREADY_EXISTS (or ERR_INVALID_STATE because the
    claim has now left DENIED). Per PRD §2.6 priority, the state check
    runs first; we accept either error_id.
    """
    from test_helpers import validate_error_is_one_of
    state = setup_claim_appealed(claimed_amount_cents=5_000_000,
                                  assessed_loss_cents=5_000_000,
                                  coverage_limit_cents=100_000_000)
    # The claim is now APPEALED; a second appeal must fail.
    res = api.create_appeal(
        state["claim"]["id"],
        create_appeal_payload(grounds="another"),
        make_customer_headers(state["insured_party_id"]),
    )
    validate_error_is_one_of(res, ["ERR_APPEAL_ALREADY_EXISTS", "ERR_INVALID_STATE"])


def test_appeal_only_for_denied_claim(api):
    """PRD §3.7: "A customer whose claim has reached `DENIED` may file
    exactly one appeal".

    Claim: appeal on an APPROVED claim -> ERR_INVALID_STATE.
    """
    from test_helpers import setup_claim_approved
    state = setup_claim_approved(claimed_amount_cents=5_000_000,
                                  assessed_loss_cents=500_000,
                                  coverage_limit_cents=10_000_000)
    res = api.create_appeal(
        state["claim"]["id"],
        create_appeal_payload(grounds="appeal denial"),
        make_customer_headers(state["insured_party_id"]),
    )
    validate_error(res, "ERR_INVALID_STATE")


# ─── §3.7 secondary review (overturn) ────────────────────────────
def test_appeal_overturn_transitions_claim_to_approved(api):
    """PRD §3.7: "An `OVERTURN` outcome writes a new `ReviewDecision` row
    with `review_level` `SECONDARY` and `outcome` `APPROVE`, transitions
    the appeal to `OVERTURNED`, transitions the claim from `APPEALED` to
    `APPROVED`, and recomputes `Claim.gross_payout_cents` and
    `Claim.net_payout_cents` against the latest figures."

    Claim: OVERTURN -> Appeal OVERTURNED, Claim APPROVED, ReviewDecision
    SECONDARY/APPROVE recorded.

    # difficulty: non_linear_state_machine/claim_branching_with_revert
    """
    state = setup_claim_appealed(claimed_amount_cents=5_000_000,
                                  assessed_loss_cents=5_000_000,
                                  coverage_limit_cents=100_000_000)
    state = record_appeal_decision(state, outcome="OVERTURN",
                                     reviewer_label="rev-overturn-1")
    refreshed = get_claim(state["claim"]["id"])
    assert refreshed["status"] == "APPROVED"
    decision = state["secondary_decision"]
    assert decision["review_level"] == "SECONDARY"
    assert decision["outcome"] == "APPROVE"


def test_appeal_uphold_transitions_claim_to_closed(api):
    """PRD §3.7: "An `UPHOLD` outcome writes a `ReviewDecision` row with
    `review_level` `SECONDARY` and `outcome` `DENY`, transitions the
    appeal to `UPHELD_DENIAL`, and transitions the claim from `APPEALED`
    directly to `CLOSED` (denial is final — no second appeal is permitted
    because each claim is allowed at most one appeal)."

    Claim: UPHOLD -> Appeal UPHELD_DENIAL, Claim CLOSED, ReviewDecision
    SECONDARY/DENY recorded.
    """
    state = setup_claim_appealed(claimed_amount_cents=5_000_000,
                                  assessed_loss_cents=5_000_000,
                                  coverage_limit_cents=100_000_000)
    state = record_appeal_decision(state, outcome="UPHOLD",
                                     reviewer_label="rev-uphold-1")
    refreshed = get_claim(state["claim"]["id"])
    assert refreshed["status"] == "CLOSED"
    decision = state["secondary_decision"]
    assert decision["review_level"] == "SECONDARY"
    assert decision["outcome"] == "DENY"


# ─── §2.7 segregation at secondary review ────────────────────────
def test_secondary_reviewer_cannot_be_adjuster(api):
    """PRD §2.7: "At secondary-review time (during an appeal), the
    `X-User-ID` recording the appeal decision must differ from both the
    `Investigation.adjuster_id` and the `reviewer_id` recorded on the
    primary `ReviewDecision` row; both kinds of overlap also yield
    `ERR_SEGREGATION_OF_DUTIES`."

    Claim: a secondary reviewer whose X-User-ID == adjuster id ->
    ERR_SEGREGATION_OF_DUTIES.
    """
    state = setup_claim_appealed(claimed_amount_cents=5_000_000,
                                  assessed_loss_cents=5_000_000,
                                  coverage_limit_cents=100_000_000)
    headers = {"X-User-ID": state["adjuster"]["id"], "X-User-Role": "Reviewer"}
    res = api.create_appeal_decision(
        state["claim"]["id"], state["appeal"]["id"],
        create_appeal_decision_payload(outcome="OVERTURN"),
        headers,
    )
    validate_error(res, "ERR_SEGREGATION_OF_DUTIES")


def test_secondary_reviewer_cannot_be_primary_reviewer(api):
    """PRD §2.7: "At secondary-review time (during an appeal), the
    `X-User-ID` recording the appeal decision must differ from both the
    `Investigation.adjuster_id` and the `reviewer_id` recorded on the
    primary `ReviewDecision` row; both kinds of overlap also yield
    `ERR_SEGREGATION_OF_DUTIES`."

    Claim: a secondary reviewer whose X-User-ID equals the primary
    reviewer's id -> ERR_SEGREGATION_OF_DUTIES.
    """
    state = setup_claim_appealed(claimed_amount_cents=5_000_000,
                                  assessed_loss_cents=5_000_000,
                                  coverage_limit_cents=100_000_000)
    primary_headers = state["primary_reviewer_headers"]
    res = api.create_appeal_decision(
        state["claim"]["id"], state["appeal"]["id"],
        create_appeal_decision_payload(outcome="OVERTURN"),
        primary_headers,  # SAME id as the primary reviewer
    )
    validate_error(res, "ERR_SEGREGATION_OF_DUTIES")


# ─── §3.7 withdraw appeal ────────────────────────────────────────
def test_withdraw_appeal_only_by_requestor(api):
    """PRD §3.7: "Withdrawal is restricted to the `requestor_id`; another
    customer cannot withdraw someone else's appeal."

    Claim: a non-requestor Customer cannot DELETE the appeal.
    """
    state = setup_claim_appealed(claimed_amount_cents=5_000_000,
                                  assessed_loss_cents=5_000_000,
                                  coverage_limit_cents=100_000_000)
    foreign = "foreign-customer-90"
    res = api.withdraw_appeal(
        state["claim"]["id"], state["appeal"]["id"],
        make_customer_headers(foreign),
    )
    body = res.json()
    assert res.status_code >= 400, f"Foreign customer must not withdraw: {body}"


def test_appeal_decision_rbac_reviewer_only(api, customer_headers):
    """PRD §4 endpoints table: POST /claims/{id}/appeals/{appeal_id}/decisions
    is Reviewer-only.

    Claim: Customer calling appeal-decisions -> ERR_FORBIDDEN.
    """
    state = setup_claim_appealed(claimed_amount_cents=5_000_000,
                                  assessed_loss_cents=5_000_000,
                                  coverage_limit_cents=100_000_000)
    res = api.create_appeal_decision(
        state["claim"]["id"], state["appeal"]["id"],
        create_appeal_decision_payload(outcome="OVERTURN"),
        customer_headers,
    )
    validate_error(res, "ERR_FORBIDDEN")
