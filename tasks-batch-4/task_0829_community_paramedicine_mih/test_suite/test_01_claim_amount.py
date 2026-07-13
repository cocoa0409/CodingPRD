"""Billing-claim amount computation: provisional vs final variants, the non-linear
base+bonus formula, and the two amount-related submit guards."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    setup_dual_variant_claim, setup_enrollment_with_active_plan,
    setup_single_visit_claim, create_draft_claim, submit_claim,
)


def test_claim_provisional_amount_projects_scheduled_encounters(api):
    """PRD 3.9: "The provisional variant, computed into provisional_amount_cents at draft
    creation, counts both SCHEDULED and COMPLETED visits and sessions, projecting
    still-scheduled encounters as if they will occur."
    With 3 home visits (2 completed + 1 scheduled) and 1 completed telehealth, the
    provisional amount is 3*15000 + 1*8000 + 50000 diversion bonus = 103000.

    Design: Difficulty/dual_variant_calc/claim_provisional_vs_final_amount
    """
    ctx = setup_dual_variant_claim(api)
    claim = ctx["claim_created"]
    assert claim["provisional_amount_cents"] == 103000, (
        f"expected provisional 103000, got {claim['provisional_amount_cents']}")


def test_claim_final_amount_counts_only_completed_encounters(api):
    """PRD 3.9: "The final variant, computed at submit and resubmit, counts only COMPLETED
    visits and sessions, so only realized encounters are paid."
    The same enrollment yields a final amount of 2*15000 + 1*8000 + 50000 = 88000, which
    differs from the provisional 103000 because the still-SCHEDULED visit drops out.

    Design: Difficulty/dual_variant_calc/claim_provisional_vs_final_amount
    """
    ctx = setup_dual_variant_claim(api)
    submitted = ctx["claim_submitted"]
    assert submitted["final_amount_cents"] == 88000, (
        f"expected final 88000, got {submitted['final_amount_cents']}")
    assert submitted["provisional_amount_cents"] != submitted["final_amount_cents"], (
        "provisional and final amounts must differ (103000 != 88000)")


def test_claim_final_amount_base_plus_diversion_bonus(api):
    """PRD 3.9: "The final amount is computed in this fixed order - base first, then add the
    diversion bonus, then subtract the readmission penalty - and is finally floored at zero,
    so the amount is never negative."
    With 2 completed visits, 1 completed telehealth, 0 ED visits (diversion achieved,
    target 1) and no readmission, final = max(0, 38000 + 8000 + 50000 - 0) = 88000.

    Design: Difficulty/combinatorial_formula/claim_amount_nonlinear_min_bonus_penalty
    """
    ctx = setup_dual_variant_claim(api)
    assert ctx["claim_submitted"]["final_amount_cents"] == 88000


def test_claim_billable_counts_reflect_completed_only(api):
    """PRD 3.9: "The system first counts the enrollment's billable home visits ... whose
    status is in the variant's set ... recording that count as billable_visit_count, and
    likewise counts qualifying telehealth sessions into billable_telehealth_count."
    Under the final variant only COMPLETED encounters count: 2 visits and 1 telehealth.

    Design: Difficulty/combinatorial_formula/claim_amount_nonlinear_min_bonus_penalty
    """
    ctx = setup_dual_variant_claim(api)
    submitted = ctx["claim_submitted"]
    assert submitted["billable_visit_count"] == 2, (
        f"expected 2 billable visits, got {submitted['billable_visit_count']}")
    assert submitted["billable_telehealth_count"] == 1, (
        f"expected 1 billable telehealth, got {submitted['billable_telehealth_count']}")


def test_submit_claim_without_completed_events_rejected(api):
    """PRD 3.9: "There must be at least one realized billable encounter in the period - that
    is, billable_visit_count plus billable_telehealth_count must be greater than zero -
    otherwise ERR_CLAIM_NO_BILLABLE_EVENTS."

    Design: Corner/validations/claim_submit_no_completed_events_returns_no_billable
    """
    ctx = setup_enrollment_with_active_plan(api)
    claim = create_draft_claim(api, ctx["org"], ctx["enrollment_id"])
    resp = api.submit_billing_claim(claim["id"], ctx["org"]["biller_headers"])
    validate_error(resp, ApiErrorId.ERR_CLAIM_NO_BILLABLE_EVENTS)


def test_submit_claim_over_budget_rejected(api):
    """PRD 3.9: "the computed final amount must be less than or equal to the program's
    available_budget_cents, otherwise ERR_BUDGET_EXCEEDED."
    A 60000-budget program with one completed visit yields amount 15000 + 50000 = 65000,
    which exceeds the budget.

    Design: Corner/validations/claim_submit_over_budget_returns_budget_exceeded
    """
    ctx = setup_single_visit_claim(api, program_overrides={"budget_cap_cents": 60000})
    resp = api.submit_billing_claim(ctx["claim_id"], ctx["org"]["biller_headers"])
    validate_error(resp, ApiErrorId.ERR_BUDGET_EXCEEDED)
