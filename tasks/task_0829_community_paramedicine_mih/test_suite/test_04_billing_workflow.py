"""Billing claim workflow: the DENIED -> SUBMITTED -> PAID resubmit cycle, the
compensating budget release on denial, and the CLOSED-program submit guard."""
from test_helpers import (
    validate_error, ApiErrorId,
    setup_submitted_claim, setup_single_visit_claim,
    refetch_program, refetch_claim, assert_budget_conserved,
)


def test_claim_denial_resubmit_cycle_reaches_paid(api):
    """PRD 3.9: "A BillingSpecialist may resubmit a denied claim, moving it DENIED ->
    SUBMITTED." and "A paid outcome moves the claim SUBMITTED -> PAID and increments the
    enrollment's billed_amount_cents by the claim's amount_cents."
    A submitted claim that is denied, resubmitted, and paid ends in PAID.

    Design: Difficulty/non_linear_state_machine/billing_claim_denial_resubmit_cycle
    """
    ctx = setup_submitted_claim(api)
    org, claim_id = ctx["org"], ctx["claim_id"]
    api.adjudicate_billing_claim(claim_id, {"outcome": "DENIED", "denial_reason": "docs"},
                                 org["payer_reviewer_headers"])
    api.resubmit_billing_claim(claim_id, org["biller_headers"])
    api.adjudicate_billing_claim(claim_id, {"outcome": "PAID"}, org["payer_reviewer_headers"])
    claim = refetch_claim(api, org, claim_id)
    assert claim["status"] == "PAID", f"expected PAID, got {claim['status']}"


def test_claim_resubmit_recomputes_same_amount(api):
    """PRD 3.9: "Resubmission recomputes final_amount_cents and amount_cents with the final
    variant and requires that the recomputed final amount still fit within
    available_budget_cents (otherwise ERR_BUDGET_EXCEEDED); on success it again debits
    available_budget_cents and credits committed_spend_cents by the new amount_cents." With
    one completed visit and diversion achieved, the recomputed
    amount stays
    15000 + 50000 = 65000 through the denial/resubmit cycle to PAID.

    Design: Difficulty/non_linear_state_machine/billing_claim_denial_resubmit_cycle
    """
    ctx = setup_submitted_claim(api)
    org, claim_id = ctx["org"], ctx["claim_id"]
    api.adjudicate_billing_claim(claim_id, {"outcome": "DENIED", "denial_reason": "docs"},
                                 org["payer_reviewer_headers"])
    api.resubmit_billing_claim(claim_id, org["biller_headers"])
    api.adjudicate_billing_claim(claim_id, {"outcome": "PAID"}, org["payer_reviewer_headers"])
    claim = refetch_claim(api, org, claim_id)
    assert claim["amount_cents"] == 65000, f"expected amount 65000, got {claim['amount_cents']}"


def test_denial_restores_available_budget(api):
    """PRD 2.9: "When a submitted claim is denied, that same amount is credited back to
    available_budget_cents and decremented from committed_spend_cents - a compensating
    release that returns the program to the state it would have been in had the claim never
    been submitted."
    After a 65000 commit and its denial, available_budget_cents returns to the full
    1000000 cap and committed_spend_cents returns to 0.

    Design: Difficulty/compensating_invariant/budget_commit_release_conserves_cap
    """
    ctx = setup_submitted_claim(api)
    org, claim_id = ctx["org"], ctx["claim_id"]
    api.adjudicate_billing_claim(claim_id, {"outcome": "DENIED", "denial_reason": "no docs"},
                                 org["payer_reviewer_headers"])
    program = refetch_program(api, org)
    assert program["available_budget_cents"] == 1000000, (
        f"expected available 1000000, got {program['available_budget_cents']}")
    assert program["committed_spend_cents"] == 0, (
        f"expected committed 0, got {program['committed_spend_cents']}")


def test_budget_commit_release_conserves_cap_invariant(api):
    """PRD 2.9: "the committed amount is debited from available_budget_cents and credited to
    committed_spend_cents" and denial performs "a compensating release". The conserved
    quantity available_budget_cents + committed_spend_cents always equals budget_cap_cents
    (1000000) both after the commit and after the compensating denial.

    Design: Difficulty/compensating_invariant/budget_commit_release_conserves_cap
    """
    ctx = setup_submitted_claim(api)
    org, claim_id = ctx["org"], ctx["claim_id"]
    assert_budget_conserved(refetch_program(api, org), 1000000)  # after commit
    api.adjudicate_billing_claim(claim_id, {"outcome": "DENIED", "denial_reason": "no docs"},
                                 org["payer_reviewer_headers"])
    assert_budget_conserved(refetch_program(api, org), 1000000)  # after release


def test_submit_claim_against_closed_program_rejected(api):
    """PRD 3.9: "The claim's program must be ACTIVE, otherwise ERR_PROGRAM_NOT_ACTIVE."
    Closing the program before submit blocks the submission.

    Design: Difficulty/cross_entity_state_dependency/claim_submit_requires_program_active
    """
    ctx = setup_single_visit_claim(api)
    org = ctx["org"]
    api.close_program(org["program_id"], org["admin_headers"])
    resp = api.submit_billing_claim(ctx["claim_id"], org["biller_headers"])
    validate_error(resp, ApiErrorId.ERR_PROGRAM_NOT_ACTIVE)


def test_closed_program_submit_leaves_budget_uncommitted(api):
    """PRD 3.9: "The claim's program must be ACTIVE, otherwise ERR_PROGRAM_NOT_ACTIVE."
    A rejected submit against a CLOSED program commits nothing, so available_budget_cents
    stays at the full cap and committed_spend_cents stays 0.

    Design: Difficulty/cross_entity_state_dependency/claim_submit_requires_program_active
    """
    ctx = setup_single_visit_claim(api)
    org = ctx["org"]
    api.close_program(org["program_id"], org["admin_headers"])
    api.submit_billing_claim(ctx["claim_id"], org["biller_headers"])
    program = refetch_program(api, org)
    assert program["committed_spend_cents"] == 0, (
        f"expected committed 0 after rejected submit, got {program['committed_spend_cents']}")
    assert program["available_budget_cents"] == 1000000, (
        f"expected available 1000000, got {program['available_budget_cents']}")
