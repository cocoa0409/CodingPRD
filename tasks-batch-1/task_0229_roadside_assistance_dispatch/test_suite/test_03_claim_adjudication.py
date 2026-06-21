"""Reimbursement-claim adjudication tests.

Covers the SUBMITTED -> UNDER_REVIEW -> INFO_REQUESTED -> SUBMITTED revision loop,
the financial conserved-balance invariant (complete books cost, approve compensates),
and the cross-entity precondition that approval requires the linked call COMPLETED.
"""
from test_helpers import (
    validate_success, validate_error,
    setup_claim_under_review, setup_en_route_call, file_claim,
    ApiErrorId, TEST_USERS, make_member_headers,
)

OP = TEST_USERS["dispatch_operator_headers"]


# =========================================================================
# Queue A — non_linear_state_machine (claim revision loop)
# =========================================================================
def test_claim_revision_loop_returns_to_submitted(api):
    """PRD §3.10: "From `UNDER_REVIEW` the operator may request more information,
    moving the claim to `INFO_REQUESTED`; the owning member then supplies it and
    resubmits, moving the claim from `INFO_REQUESTED` back to `SUBMITTED`, which closes
    the revision loop `SUBMITTED → UNDER_REVIEW → INFO_REQUESTED → SUBMITTED`."

    Design: Difficulty/non_linear_state_machine/reimbursement_claim_cyclic_info_request_resubmit_loop
    """
    ctx = setup_claim_under_review(claimed_amount_cents=1500)
    claim_id = ctx["claim"]["id"]
    validate_success(api.request_info_claim(claim_id, OP))
    info = validate_success(api.get_claim(claim_id, OP))
    assert info["status"] == "INFO_REQUESTED", f"expected INFO_REQUESTED, got {info['status']}"
    data = validate_success(api.resubmit_claim(claim_id, make_member_headers(ctx["member"]["id"])))
    assert data["status"] == "SUBMITTED", f"resubmit must return to SUBMITTED, got {data['status']}"


def test_claim_can_reenter_review_after_resubmit(api):
    """PRD §3.10: "An operator begins review, moving the claim from `SUBMITTED` to
    `UNDER_REVIEW`."

    After the revision loop returns the claim to SUBMITTED, the operator can begin
    review again, proving the cycle is genuinely re-enterable.

    Design: Difficulty/non_linear_state_machine/reimbursement_claim_cyclic_info_request_resubmit_loop
    """
    ctx = setup_claim_under_review(claimed_amount_cents=1500)
    claim_id = ctx["claim"]["id"]
    validate_success(api.request_info_claim(claim_id, OP))
    validate_success(api.resubmit_claim(claim_id, make_member_headers(ctx["member"]["id"])))
    data = validate_success(api.begin_review_claim(claim_id, OP))
    assert data["status"] == "UNDER_REVIEW", f"expected UNDER_REVIEW again, got {data['status']}"


# =========================================================================
# Queue A — compensating_invariant (financial balance nets to zero)
# =========================================================================
def test_complete_then_approve_nets_balance_to_zero(api):
    """PRD §3.2: "The field `outstanding_balance_cents` is a conserved quantity: it
    equals the sum of `member_out_of_pocket_cents` across the member's `COMPLETED`
    service calls minus the sum of `approved_amount_cents` across the member's
    `APPROVED` reimbursement claims."

    Complete books +3000; approving a 3000 claim subtracts 3000, netting to 0.

    Design: Difficulty/compensating_invariant/financial_balance_invariant_complete_then_approve_nets_to_zero
    """
    ctx = setup_claim_under_review(claimed_amount_cents=3000, final_towed_miles=20)
    data = validate_success(api.approve_claim(ctx["claim"]["id"], OP))
    assert data["approved_amount_cents"] == 3000, f"expected 3000, got {data['approved_amount_cents']}"
    member = validate_success(api.get_member(ctx["member"]["id"], OP))
    assert member["outstanding_balance_cents"] == 0, \
        f"balance should net to 0, got {member['outstanding_balance_cents']}"


def test_balance_booked_on_completion_before_compensation(api):
    """PRD §3.8: "On a successful completion the system increments `services_used_this_year`
    by one, adds `member_out_of_pocket_cents` to the member's `outstanding_balance_cents`,
    returns the provider to `AVAILABLE` and clears its `active_call_id`, and increments
    the call's `version`."

    The forward action of the conserved-balance invariant: completion alone books
    +3000 to the member's outstanding balance.

    Design: Difficulty/compensating_invariant/financial_balance_invariant_complete_then_approve_nets_to_zero
    """
    ctx = setup_en_route_call()
    from test_helpers import complete_call
    complete_call(ctx["call"]["id"], ctx["provider"]["id"], final_towed_miles=20)
    member = validate_success(api.get_member(ctx["member"]["id"], OP))
    assert member["outstanding_balance_cents"] == 3000, \
        f"completion should book +3000, got {member['outstanding_balance_cents']}"


# =========================================================================
# Queue A — cross_entity_state_dependency (claim approve requires call COMPLETED)
# =========================================================================
def test_approve_claim_on_non_completed_call_rejected(api):
    """PRD §3.10: "Approval is permitted only when the claim is `UNDER_REVIEW` and
    additionally requires the linked call to be `COMPLETED`; a claim whose linked call
    has not reached `COMPLETED` is rejected with `ERR_CALL_NOT_COMPLETED`."

    The claim is filed against an EN_ROUTE (not COMPLETED) call and reviewed; approval
    is then attempted.

    Design: Difficulty/cross_entity_state_dependency/claim_approve_requires_call_completed_claim_depends_on_call
    """
    ctx = setup_en_route_call()
    claim = file_claim(ctx["member"]["id"], ctx["call"]["id"], 1500)
    validate_success(api.begin_review_claim(claim["id"], OP))
    resp = api.approve_claim(claim["id"], OP)
    validate_error(resp, ApiErrorId.ERR_CALL_NOT_COMPLETED.value)


def test_claim_depends_on_linked_call_state(api):
    """PRD §3.10: "a claim whose linked call has not reached `COMPLETED` is rejected
    with `ERR_CALL_NOT_COMPLETED`."

    A second assertion of the ReimbursementClaim -> ServiceCall dependency: an
    UNDER_REVIEW claim whose call is only EN_ROUTE cannot be approved.

    Design: Difficulty/cross_entity_state_dependency/claim_approve_requires_call_completed_claim_depends_on_call
    """
    ctx = setup_en_route_call()
    claim = file_claim(ctx["member"]["id"], ctx["call"]["id"], 2000)
    validate_success(api.begin_review_claim(claim["id"], OP))
    resp = api.approve_claim(claim["id"], OP)
    validate_error(resp, ApiErrorId.ERR_CALL_NOT_COMPLETED.value)
