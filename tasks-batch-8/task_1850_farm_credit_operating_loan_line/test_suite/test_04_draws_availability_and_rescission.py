"""Draw lifecycle: availability boundaries and reservation accounting, approval
gates and their precedence, disbursement state rules, and same-day rescission
conservation (PRD sections 2.7, 3.5, 3.6).
"""
from test_helpers import (
    ApiErrorId, TEST_USERS, api_client, create_draw_payload, disburse_draw,
    get_loan, get_success_data, get_summary, make_borrower_headers, set_clock,
    setup_active_loan, setup_distressed_loan, setup_distressed_loan_with_plan,
    validate_error, validate_success,
)

OFFICER = TEST_USERS["loan_officer_headers"]

CAPPED_50M = {  # raw base 96,000,000 capped to the 50,000,000 commitment
    "collateral_type": "REAL_ESTATE",
    "appraised_value_cents": 60_000_000,
    "projected_revenue_cents": 80_000_000,
    "projected_expenses_cents": 50_000_000,
}


def test_draw_at_exact_availability_succeeds_one_cent_over_fails(api):
    """PRD section 3.6: "Available credit is the lesser of
    `approved_commitment_cents` and `borrowing_base_cents`, minus
    `outstanding_principal_cents`, minus `pending_draw_cents` — and
    `pending_draw_cents` sums `amount_cents` over exactly this loan's draws in
    `APPROVED` status, excluding `REQUESTED`, `DENIED`, `CANCELLED`, `DISBURSED`,
    and `RESCINDED` alike. An amount equal to available credit passes; only a
    strictly greater amount fails."

    Design: Difficulty/boundary_precision_check/draw_at_exact_availability_succeeds_one_cent_over_fails
    """
    ctx = setup_active_loan()  # base 19,000,000; availability 19,000,000
    loan_id = ctx["loan"]["id"]

    over = get_success_data(api.create_draw_request(
        create_draw_payload(loan_account_id=loan_id, amount_cents=19_000_001), OFFICER))
    resp = api.approve_draw_request(over["id"], OFFICER)
    validate_error(resp, ApiErrorId.ERR_DRAW_EXCEEDS_AVAILABILITY)
    assert get_success_data(api.get_draw_request(over["id"], OFFICER))["status"] == "REQUESTED"

    exact = get_success_data(api.create_draw_request(
        create_draw_payload(loan_account_id=loan_id, amount_cents=19_000_000), OFFICER))
    data = validate_success(api.approve_draw_request(exact["id"], OFFICER), 200)
    assert data["status"] == "APPROVED"
    summary = get_summary(loan_id)
    assert summary["pending_draw_cents"] == 19_000_000, \
        "the failed approval reserved nothing; the exact draw reserved the full amount"


def test_pending_draws_reduce_available_credit(api):
    """PRD section 3.6: "Available credit is the lesser of
    `approved_commitment_cents` and `borrowing_base_cents`, minus
    `outstanding_principal_cents`, minus `pending_draw_cents` — and
    `pending_draw_cents` sums `amount_cents` over exactly this loan's draws in
    `APPROVED` status, excluding `REQUESTED`, `DENIED`, `CANCELLED`, `DISBURSED`,
    and `RESCINDED` alike. An amount equal to available credit passes; only a
    strictly greater amount fails." PRD section 3.6: "Approval moves `REQUESTED` →
    `APPROVED` and reserves availability by adding the amount to
    `pending_draw_cents`."

    Design: Difficulty/boundary_precision_check/draw_at_exact_availability_succeeds_one_cent_over_fails
    """
    ctx = setup_active_loan()  # availability 19,000,000
    loan_id = ctx["loan"]["id"]

    d1 = get_success_data(api.create_draw_request(
        create_draw_payload(loan_account_id=loan_id, amount_cents=10_000_000), OFFICER))
    validate_success(api.approve_draw_request(d1["id"], OFFICER), 200)

    d2 = get_success_data(api.create_draw_request(
        create_draw_payload(loan_account_id=loan_id, amount_cents=9_000_001), OFFICER))
    validate_error(api.approve_draw_request(d2["id"], OFFICER),
                   ApiErrorId.ERR_DRAW_EXCEEDS_AVAILABILITY)

    d3 = get_success_data(api.create_draw_request(
        create_draw_payload(loan_account_id=loan_id, amount_cents=9_000_000), OFFICER))
    assert validate_success(api.approve_draw_request(d3["id"], OFFICER), 200)["status"] == "APPROVED"
    summary = get_summary(loan_id)
    assert summary["pending_draw_cents"] == 19_000_000
    assert summary["available_credit_cents"] == 0


def test_draw_disburse_rescind_conserves_loan_balances(api):
    """PRD section 3.6: "And an officer rescinds a `DISBURSED` draw on the same
    UTC date as its `disbursement_date` — any later date is rejected with
    `ERR_RESCIND_WINDOW_CLOSED` — subtracting the amount from outstanding principal
    with zero interest drift, because a same-day rescission spans zero accrual days
    on the draw amount; the draw ends `RESCINDED` and the standard cascade runs."

    Design: Difficulty/compensating_invariant/draw_disburse_rescind_conserves_loan_balances
    """
    ctx = setup_active_loan(**CAPPED_50M)
    set_clock("2026-04-01T00:00:00Z")
    loan_id = ctx["loan"]["id"]
    pre = get_summary(loan_id)
    assert (pre["outstanding_principal_cents"], pre["accrued_interest_cents"],
            pre["available_credit_cents"]) == (0, 0, 50_000_000)

    drw = get_success_data(api.create_draw_request(
        create_draw_payload(loan_account_id=loan_id, amount_cents=5_000_000,
                            purpose="LABOR"), OFFICER))
    get_success_data(api.approve_draw_request(drw["id"], OFFICER))
    get_success_data(api.disburse_draw_request(drw["id"], OFFICER))
    data = validate_success(api.rescind_draw_request(drw["id"], OFFICER), 200)
    assert data["status"] == "RESCINDED"

    post = get_summary(loan_id)
    assert post["outstanding_principal_cents"] == pre["outstanding_principal_cents"] == 0
    assert post["accrued_interest_cents"] == pre["accrued_interest_cents"] == 0
    assert post["available_credit_cents"] == pre["available_credit_cents"] == 50_000_000, \
        "a same-day disburse-then-rescind pair conserves every loan balance"


def test_rescind_of_second_draw_conserves_first_draw_state(api):
    """PRD section 3.6: "And an officer rescinds a `DISBURSED` draw on the same
    UTC date as its `disbursement_date` — any later date is rejected with
    `ERR_RESCIND_WINDOW_CLOSED` — subtracting the amount from outstanding principal
    with zero interest drift, because a same-day rescission spans zero accrual days
    on the draw amount; the draw ends `RESCINDED` and the standard cascade runs."

    Design: Difficulty/compensating_invariant/draw_disburse_rescind_conserves_loan_balances
    """
    ctx = setup_active_loan(**CAPPED_50M)
    set_clock("2026-04-01T00:00:00Z")
    drw1 = disburse_draw(ctx, 5_000_000, purpose="LABOR")
    loan_id = ctx["loan"]["id"]
    mid = get_summary(loan_id)
    assert (mid["outstanding_principal_cents"], mid["available_credit_cents"]) \
        == (5_000_000, 45_000_000)

    drw2 = disburse_draw(ctx, 3_000_000, purpose="FUEL")
    data = validate_success(api.rescind_draw_request(drw2["id"], OFFICER), 200)
    assert data["status"] == "RESCINDED"

    post = get_summary(loan_id)
    assert post["outstanding_principal_cents"] == 5_000_000
    assert post["accrued_interest_cents"] == 0, "zero accrual days on the rescinded draw"
    assert post["available_credit_cents"] == 45_000_000, \
        "the rescinded draw's full amount returns to availability"
    assert get_success_data(api.get_draw_request(drw1["id"], OFFICER))["status"] == "DISBURSED"


def test_draw_rescind_next_day_window_closed_rejected(api):
    """PRD section 3.6: "And an officer rescinds a `DISBURSED` draw on the same
    UTC date as its `disbursement_date` — any later date is rejected with
    `ERR_RESCIND_WINDOW_CLOSED` — subtracting the amount from outstanding principal
    with zero interest drift, because a same-day rescission spans zero accrual days
    on the draw amount; the draw ends `RESCINDED` and the standard cascade runs."

    Design: Corner/endpoints/draw_rescind_next_day_window_closed_rejected
    """
    ctx = setup_active_loan(**CAPPED_50M)
    set_clock("2026-04-01T00:00:00Z")
    drw = disburse_draw(ctx, 1_000_000, purpose="FUEL")
    set_clock("2026-04-02T00:00:00Z")  # one UTC date later
    resp = api.rescind_draw_request(drw["id"], OFFICER)
    validate_error(resp, ApiErrorId.ERR_RESCIND_WINDOW_CLOSED)
    assert get_success_data(api.get_draw_request(drw["id"], OFFICER))["status"] == "DISBURSED"
    assert get_summary(ctx["loan"]["id"])["outstanding_principal_cents"] == 1_000_000


def test_draw_disburse_from_requested_rejected(api):
    """PRD section 2.7: "7. **Generic state preconditions.** The requested
    transition is listed for the entity's current state, and terminal states accept
    no transitions — `ERR_INVALID_STATE_TRANSITION`." PRD section 3.6: "The officer
    disburses an `APPROVED` draw; interest first accrues to the clock date, then
    `outstanding_principal_cents` grows by the `amount_cents`, `pending_draw_cents`
    shrinks by the same amount, the `disbursement_date` is stamped with the clock,
    and the draw lands in `DISBURSED` with the standard cascade behind it."

    Design: Corner/state_machines/draw_disburse_from_requested_rejected
    """
    ctx = setup_active_loan(**CAPPED_50M)
    drw = get_success_data(api.create_draw_request(
        create_draw_payload(loan_account_id=ctx["loan"]["id"], amount_cents=100_000,
                            purpose="FUEL"), OFFICER))
    resp = api.disburse_draw_request(drw["id"], OFFICER)  # REQUESTED, never approved
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
    assert get_success_data(api.get_draw_request(drw["id"], OFFICER))["status"] == "REQUESTED"
    assert get_summary(ctx["loan"]["id"])["outstanding_principal_cents"] == 0


def test_paid_off_loan_blocks_new_draw_approval(api):
    """PRD section 3.6: "When the two balances both reach exactly zero, the loan
    auto-transitions `ACTIVE` → `PAID_OFF`." PRD section 2.7: "8. **Loan-level
    gates.** Draw approve, disburse, and rescind, plan creation, and deferral
    creation require the loan `ACTIVE`; repayment creation and claim payment accept
    `ACTIVE` or `RESTRUCTURING` — violations yield `ERR_LOAN_NOT_ACTIVE`."

    Design: Corner/state_machines/paid_off_loan_blocks_new_draw_approval
    """
    ctx = setup_active_loan(**CAPPED_50M)
    set_clock("2026-04-01T00:00:00Z")
    loan_id = ctx["loan"]["id"]
    disburse_draw(ctx, 1_000_000, purpose="FUEL")
    get_success_data(api.create_repayment(
        {"loan_account_id": loan_id, "amount_cents": 1_000_000,
         "source": "HARVEST_PROCEEDS"},
        make_borrower_headers(ctx["bor"]["id"])))
    assert get_loan(loan_id)["status"] == "PAID_OFF", \
        "same-day exact payoff auto-closes the loan"

    drw2 = get_success_data(api.create_draw_request(
        create_draw_payload(loan_account_id=loan_id, amount_cents=500_000), OFFICER))
    resp = api.approve_draw_request(drw2["id"], OFFICER)
    validate_error(resp, ApiErrorId.ERR_LOAN_NOT_ACTIVE)
    assert get_success_data(api.get_draw_request(drw2["id"], OFFICER))["status"] == "REQUESTED"


def test_draw_approve_state_error_beats_fiscal_error(api):
    """PRD section 2.7: "When a single request would violate several rules, the
    server reports only one failure: the violation whose category sits earliest in
    the precedence below." PRD section 2.7: "8. **Loan-level gates.** Draw approve,
    disburse, and rescind, plan creation, and deferral creation require the loan
    `ACTIVE`; repayment creation and claim payment accept `ACTIVE` or
    `RESTRUCTURING` — violations yield `ERR_LOAN_NOT_ACTIVE`." PRD section 2.7:
    "13. **Fiscal ceilings.** Draw amount against available credit —
    `ERR_DRAW_EXCEEDS_AVAILABILITY`; repayment against total debt —
    `ERR_PAYMENT_EXCEEDS_OUTSTANDING`; adjuster approval against remaining coverage
    — `ERR_CLAIM_EXCEEDS_COVERAGE`; collateral release against a deficiency —
    `ERR_RELEASE_WOULD_CREATE_DEFICIENCY`; patronage allocation against an eligible
    base — `ERR_NO_ELIGIBLE_PATRONAGE_BASE`."

    Design: Difficulty/priority_pair_validation_conflict/draw_approve_state_error_beats_fiscal_error
    """
    ctx = setup_distressed_loan_with_plan()  # loan RESTRUCTURING, availability negative
    loan_id = ctx["loan"]["id"]
    drw = get_success_data(api.create_draw_request(
        create_draw_payload(loan_account_id=loan_id, amount_cents=99_000_000,
                            purpose="FUEL"), OFFICER))
    resp = api.approve_draw_request(drw["id"], OFFICER)
    validate_error(resp, ApiErrorId.ERR_LOAN_NOT_ACTIVE)
    assert get_success_data(api.get_draw_request(drw["id"], OFFICER))["status"] == "REQUESTED"


def test_draw_approve_posture_error_beats_fiscal_error(api):
    """PRD section 2.7: "When a single request would violate several rules, the
    server reports only one failure: the violation whose category sits earliest in
    the precedence below." PRD section 2.7: "Draw approval additionally requires
    the posture not be `DELINQUENT` or `DEFAULT` —
    `ERR_LOAN_POSTURE_BLOCKS_DRAWS`." (the loan-level gates tier sits before
    the fiscal ceilings tier.)

    Design: Difficulty/priority_pair_validation_conflict/draw_approve_state_error_beats_fiscal_error
    """
    ctx = setup_distressed_loan()  # ACTIVE but DELINQUENT, availability -7,000,000
    loan_id = ctx["loan"]["id"]
    assert get_loan(loan_id)["status"] == "ACTIVE"
    drw = get_success_data(api.create_draw_request(
        create_draw_payload(loan_account_id=loan_id, amount_cents=500_000,
                            purpose="FUEL"), OFFICER))
    resp = api.approve_draw_request(drw["id"], OFFICER)
    validate_error(resp, ApiErrorId.ERR_LOAN_POSTURE_BLOCKS_DRAWS)
    assert get_success_data(api.get_draw_request(drw["id"], OFFICER))["status"] == "REQUESTED"


def test_draw_approve_delinquent_posture_blocked_rejected(api):
    """PRD section 3.6: "Approval belongs to the officer and enforces four gates
    in a fixed order: the loan must be `ACTIVE`, else `ERR_LOAN_NOT_ACTIVE`; the
    posture must not be `DELINQUENT` or `DEFAULT`, else
    `ERR_LOAN_POSTURE_BLOCKS_DRAWS`; at least one policy `ASSIGNED` and `ACTIVE`
    for this loan must exist, else `ERR_INSURANCE_NOT_ASSIGNED`; and the amount
    must fit available credit, else `ERR_DRAW_EXCEEDS_AVAILABILITY`."

    Design: Corner/validations/draw_approve_delinquent_posture_blocked_rejected
    """
    ctx = setup_distressed_loan()  # posture DELINQUENT; borrower now SUSPENDED
    loan_id = ctx["loan"]["id"]
    assert get_loan(loan_id)["status"] == "ACTIVE", \
        "the status gate does not fire — the loan is still ACTIVE"
    drw = get_success_data(api.create_draw_request(
        create_draw_payload(loan_account_id=loan_id, amount_cents=500_000,
                            purpose="FUEL"), OFFICER))  # officer files on the borrower's behalf
    resp = api.approve_draw_request(drw["id"], OFFICER)
    validate_error(resp, ApiErrorId.ERR_LOAN_POSTURE_BLOCKS_DRAWS)
    assert get_success_data(api.get_draw_request(drw["id"], OFFICER))["status"] == "REQUESTED"


def test_draw_approve_requires_assigned_active_policy(api):
    """PRD section 3.6: "Approval belongs to the officer and enforces four gates
    in a fixed order: the loan must be `ACTIVE`, else `ERR_LOAN_NOT_ACTIVE`; the
    posture must not be `DELINQUENT` or `DEFAULT`, else
    `ERR_LOAN_POSTURE_BLOCKS_DRAWS`; at least one policy `ASSIGNED` and `ACTIVE`
    for this loan must exist, else `ERR_INSURANCE_NOT_ASSIGNED`; and the amount
    must fit available credit, else `ERR_DRAW_EXCEEDS_AVAILABILITY`." PRD section
    3.5: "a clean cancel moves the policy to `CANCELLED`, releases any assignment
    (`ASSIGNED` → `RELEASED`), and clears `assigned_loan_id`."

    Design: Difficulty/cross_entity_state_dependency/draw_approve_requires_assigned_active_policy
    """
    ctx = setup_active_loan(**CAPPED_50M)
    loan_id = ctx["loan"]["id"]
    drw = get_success_data(api.create_draw_request(
        create_draw_payload(loan_account_id=loan_id, amount_cents=1_000_000,
                            purpose="FUEL"),
        make_borrower_headers(ctx["bor"]["id"])))

    pol = validate_success(api.cancel_insurance_policy(ctx["pol"]["id"], OFFICER), 200)
    assert pol["assignment_status"] == "RELEASED", "cancel releases the assignment"
    resp = api.approve_draw_request(drw["id"], OFFICER)
    validate_error(resp, ApiErrorId.ERR_INSURANCE_NOT_ASSIGNED)
    assert get_success_data(api.get_draw_request(drw["id"], OFFICER))["status"] == "REQUESTED"

    pol2 = get_success_data(api.create_insurance_policy(
        {"borrower_id": ctx["bor"]["id"], "policy_number": "POL-002",
         "crop_type": "CORN", "county": ctx["bor"]["county"],
         "coverage_start": "2026-03-01T00:00:00Z",
         "coverage_end": "2027-03-01T00:00:00Z",
         "coverage_amount_cents": 40_000_000}, OFFICER))
    get_success_data(api.assign_insurance_policy(
        pol2["id"], {"loan_account_id": loan_id}, OFFICER))
    data = validate_success(api.approve_draw_request(drw["id"], OFFICER), 200)
    assert data["status"] == "APPROVED", \
        "a freshly assigned replacement policy restores approvability"
