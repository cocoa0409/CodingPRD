"""Loan approval pipeline behavior: out-of-order, double decision, rejection
cascade, withdraw on terminal lifecycle (PRD §3.4, §2.8)."""
from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_success,
)

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    approve_loan_fully,
    list_loan_tasks,
    make_participant_headers,
    request_loan,
    setup_disbursed_loan,
    setup_plan_and_participant,
    setup_repaid_loan,
)

ADMIN = TEST_USERS["admin_headers"]
SPONSOR = TEST_USERS["sponsor_headers"]
PAYROLL = TEST_USERS["payroll_headers"]


def test_approval_out_of_order_decision_rejected(api):
    """PRD §3.4: "Steps are strictly ordered: deciding step N while any
    lower-`step_order` task on the same subject is still `PENDING` fails with
    `ERR_APPROVAL_OUT_OF_ORDER`".

    Design: Corner/state_machines/approval_out_of_order_decision_rejected
    """
    plan, participant = setup_plan_and_participant(vested_balance_cents=10_000_000)
    loan = request_loan(participant, principal_amount_cents=500_000, term_months=12)
    tasks = list_loan_tasks(loan["id"])
    step2 = tasks[1]  # RECORDKEEPER_ADMIN step; step 1 still PENDING
    res = api.decide_approval_task(
        step2["id"], {"decision": "APPROVE"}, ADMIN
    )
    validate_error(res, ApiErrorId.ERR_APPROVAL_OUT_OF_ORDER, expected_status=409)

    # Both tasks remain PENDING; loan still REQUESTED
    t1 = validate_success(api.get_approval_task(tasks[0]["id"], ADMIN), 200)
    t2 = validate_success(api.get_approval_task(tasks[1]["id"], ADMIN), 200)
    loan_after = validate_success(api.get_loan(loan["id"], ADMIN), 200)
    assert t1["status"] == "PENDING"
    assert t2["status"] == "PENDING"
    assert loan_after["lifecycle_status"] == "REQUESTED"


def test_double_decision_on_task_rejected(api):
    """PRD §3.4: "deciding a task that already stands `APPROVED`, `REJECTED`, or
    `CANCELLED` fails with `ERR_TASK_ALREADY_DECIDED`."

    Design: Corner/state_machines/double_decision_on_task_rejected
    """
    plan, participant = setup_plan_and_participant(vested_balance_cents=10_000_000)
    loan = request_loan(participant, principal_amount_cents=500_000, term_months=12)
    tasks = list_loan_tasks(loan["id"])
    step1 = tasks[0]
    # First decision succeeds
    validate_success(
        api.decide_approval_task(step1["id"], {"decision": "APPROVE"}, SPONSOR), 200
    )
    # Second decision on the same task (even by a different operator) is rejected
    sponsor2 = TEST_USERS["sponsor2_headers"]
    res = api.decide_approval_task(step1["id"], {"decision": "REJECT"}, sponsor2)
    validate_error(res, ApiErrorId.ERR_TASK_ALREADY_DECIDED, expected_status=409)

    # Task remains APPROVED
    t1 = validate_success(api.get_approval_task(step1["id"], ADMIN), 200)
    assert t1["status"] == "APPROVED"


def test_loan_rejection_cancels_sibling_tasks(api):
    """PRD §3.4: "Any rejection moves the subject from `REQUESTED` to `DENIED`
    and cancels the sibling tasks still `PENDING`." The denied loan is then in a
    terminal state, so a subsequent disburse fails (PRD §2.8 priority 6
    from-state validity with `ERR_INVALID_STATE`).

    Design: Corner/state_machines/loan_rejection_cancels_sibling_tasks
    """
    plan, participant = setup_plan_and_participant(vested_balance_cents=10_000_000)
    loan = request_loan(participant, principal_amount_cents=500_000, term_months=12)
    tasks = list_loan_tasks(loan["id"])
    step1, step2 = tasks[0], tasks[1]
    # Step 1 REJECT
    validate_success(
        api.decide_approval_task(step1["id"], {"decision": "REJECT"}, SPONSOR), 200
    )
    loan_after = validate_success(api.get_loan(loan["id"], ADMIN), 200)
    t2_after = validate_success(api.get_approval_task(step2["id"], ADMIN), 200)
    assert loan_after["lifecycle_status"] == "DENIED"
    assert t2_after["status"] == "CANCELLED"

    # Disburse on the denied loan is rejected
    res = api.disburse_loan(loan["id"], ADMIN)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


def test_withdraw_repaid_loan_returns_invalid_state(api):
    """PRD §2.8 priority 6: "From-state validity. The target resource is in a
    valid from-state for the requested transition. ... all other from-state
    failures carry `ERR_INVALID_STATE`." PRD §3.4: "While a loan stands
    `REQUESTED`, the requesting participant may withdraw it" — REPAID is not
    REQUESTED, so the withdraw is rejected.

    Design: Corner/state_machines/withdraw_repaid_loan_returns_invalid_state
    """
    _, participant, loan, _, _ = setup_repaid_loan(
        principal_amount_cents=1_000_000, term_months=12,
        vested_balance_cents=10_000_000,
    )
    assert loan["lifecycle_status"] == "REPAID"
    res = api.withdraw_loan(loan["id"], make_participant_headers(participant["id"]))
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
    # Loan state is unchanged
    loan_after = validate_success(api.get_loan(loan["id"], ADMIN), 200)
    assert loan_after["lifecycle_status"] == "REPAID"
