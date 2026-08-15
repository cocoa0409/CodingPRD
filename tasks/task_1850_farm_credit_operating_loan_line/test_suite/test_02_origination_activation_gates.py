"""Loan activation: the four gates between APPROVED and ACTIVE, their evaluation
order, and the insurance/collateral safety gates (PRD sections 3.2, 3.5).
"""
from test_helpers import (
    ApiErrorId, TEST_USERS, api_client, add_assigned_policy, add_collateral,
    create_approved_loan, create_budget, create_ucc_filing_payload, get_loan,
    get_success_data, set_clock, setup_activatable_loan,
    setup_loan_with_approved_budget, validate_error, validate_success,
)

OFFICER = TEST_USERS["loan_officer_headers"]


def test_activate_without_perfected_collateral_rejected(api):
    """PRD section 3.2: "Second, at least one collateral item must be `PLEDGED`
    with `perfection_state` `PERFECTED`, else `ERR_COLLATERAL_UNPERFECTED` — the
    insurance gate is checked before the collateral gate, so a loan missing both
    reports the insurance failure."

    Design: Corner/validations/activate_without_perfected_collateral_rejected
    """
    ctx = setup_loan_with_approved_budget()
    col, _ = add_collateral(ctx, perfect=False)  # PLEDGED but UNPERFECTED
    add_assigned_policy(ctx)
    resp = api.activate_loan(ctx["loan"]["id"], OFFICER)
    validate_error(resp, ApiErrorId.ERR_COLLATERAL_UNPERFECTED)
    assert get_loan(ctx["loan"]["id"])["status"] == "APPROVED", \
        "a rejected activation leaves the loan APPROVED"


def test_activate_with_draft_budget_rejected(api):
    """PRD section 3.2: "Fourth, an `APPROVED` crop budget must exist for this
    loan and season, else `ERR_BUDGET_NOT_APPROVED`."

    Design: Corner/validations/activate_with_draft_budget_rejected
    """
    ctx = create_approved_loan()
    create_budget(ctx)  # stays DRAFT — never approved
    add_collateral(ctx)  # PERFECTED
    add_assigned_policy(ctx)
    resp = api.activate_loan(ctx["loan"]["id"], OFFICER)
    validate_error(resp, ApiErrorId.ERR_BUDGET_NOT_APPROVED)
    assert get_loan(ctx["loan"]["id"])["status"] == "APPROVED"


def test_activate_no_insurance_beats_maturity_then_maturity_revealed(api):
    """PRD section 3.2: "Four gates stand between `APPROVED` and `ACTIVE`,
    evaluated in this order. First, at least one insurance policy with `status`
    `ACTIVE` and `assignment_status` `ASSIGNED` to this loan must exist, else
    `ERR_INSURANCE_NOT_ASSIGNED`." PRD section 3.2: "Third, the logical clock must
    sit strictly before the loan's `maturity_date`; a clock at or past maturity is
    rejected with `ERR_MATURITY_PASSED`." PRD section 3.5: "A `LoanOfficer` assigns
    a policy by naming the `loan_account_id`, and four checks guard the act: the
    policy must be `ACTIVE`, else `ERR_POLICY_NOT_ACTIVE`; it must not already be
    `ASSIGNED`, else `ERR_POLICY_ALREADY_ASSIGNED`; the loan and the policy must
    belong to the same association, else `ERR_CROSS_ASSOCIATION_REFERENCE`; and the
    coverage window must contain the loan season — the clock at or after
    `coverage_start`, and `coverage_end` at or after the loan's `maturity_date` —
    else `ERR_INVALID_REQUEST`."

    Design: Difficulty/priority_pair_validation_conflict/loan_activate_safety_error_beats_temporal_error
    """
    ctx = setup_loan_with_approved_budget(commitment_cents=30_000_000,
                                          approved_commitment_cents=30_000_000,
                                          maturity_date="2026-06-01T00:00:00Z")
    add_collateral(ctx, collateral_type="REAL_ESTATE",
                   appraised_value_cents=40_000_000, description="320 acres")
    set_clock("2026-06-15T00:00:00Z")  # past maturity, no insurance at all

    resp = api.activate_loan(ctx["loan"]["id"], OFFICER)
    validate_error(resp, ApiErrorId.ERR_INSURANCE_NOT_ASSIGNED)

    pol = add_assigned_policy(ctx)  # assign has no maturity gate; all four checks pass
    assert pol["assignment_status"] == "ASSIGNED"

    resp = api.activate_loan(ctx["loan"]["id"], OFFICER)
    validate_error(resp, ApiErrorId.ERR_MATURITY_PASSED)
    assert get_loan(ctx["loan"]["id"])["status"] == "APPROVED", \
        "both failed activations leave the loan APPROVED"


def test_activate_unperfected_collateral_beats_maturity_then_maturity_revealed(api):
    """PRD section 3.2: "Second, at least one collateral item must be `PLEDGED`
    with `perfection_state` `PERFECTED`, else `ERR_COLLATERAL_UNPERFECTED`". PRD
    section 3.2: "Third, the logical clock must sit strictly before the loan's
    `maturity_date`; a clock at or past maturity is rejected with
    `ERR_MATURITY_PASSED`." PRD section 2.7: "9. **Insurance and perfection
    gates.** Activation and draw approval require an `ASSIGNED` `ACTIVE` policy —
    `ERR_INSURANCE_NOT_ASSIGNED` — and activation requires a `PLEDGED` `PERFECTED`
    collateral — `ERR_COLLATERAL_UNPERFECTED`. Within this tier the insurance check
    precedes the collateral check." (tier 9 sits before tier 10, temporal windows.)

    Design: Difficulty/priority_pair_validation_conflict/loan_activate_safety_error_beats_temporal_error
    """
    ctx = setup_loan_with_approved_budget(commitment_cents=30_000_000,
                                          approved_commitment_cents=30_000_000,
                                          maturity_date="2026-06-01T00:00:00Z")
    col, _ = add_collateral(ctx, perfect=False)
    add_assigned_policy(ctx)
    set_clock("2026-06-15T00:00:00Z")  # past maturity AND unperfected collateral

    resp = api.activate_loan(ctx["loan"]["id"], OFFICER)
    validate_error(resp, ApiErrorId.ERR_COLLATERAL_UNPERFECTED)

    get_success_data(api.create_ucc_filing(
        create_ucc_filing_payload(collateral_id=col["id"]), OFFICER))
    resp = api.activate_loan(ctx["loan"]["id"], OFFICER)
    validate_error(resp, ApiErrorId.ERR_MATURITY_PASSED)
    assert get_loan(ctx["loan"]["id"])["status"] == "APPROVED"


def test_activate_blocked_after_only_policy_cancelled(api):
    """PRD section 3.5: "a clean cancel moves the policy to `CANCELLED`, releases
    any assignment (`ASSIGNED` → `RELEASED`), and clears `assigned_loan_id`." PRD
    section 3.2: "First, at least one insurance policy with `status` `ACTIVE` and
    `assignment_status` `ASSIGNED` to this loan must exist, else
    `ERR_INSURANCE_NOT_ASSIGNED`."

    Design: Difficulty/cross_entity_state_dependency/draw_approve_requires_assigned_active_policy
    """
    ctx = setup_activatable_loan()
    resp = api.cancel_insurance_policy(ctx["pol"]["id"], OFFICER)
    pol = validate_success(resp, 200)
    assert pol["status"] == "CANCELLED"
    assert pol["assignment_status"] == "RELEASED", "cancel releases the assignment"
    assert pol["assigned_loan_id"] is None, "cancel clears assigned_loan_id"

    resp = api.activate_loan(ctx["loan"]["id"], OFFICER)
    validate_error(resp, ApiErrorId.ERR_INSURANCE_NOT_ASSIGNED)
    assert get_loan(ctx["loan"]["id"])["status"] == "APPROVED"
