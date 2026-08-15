"""Compensating invariants: complete/reopen conserves billed fees, and
file/reject conserves pending-claims exposure — both with zero drift."""
from test_helpers import (
    FINDINGS_UTILITY_300K,
    FINDINGS_UTILITY_310K,
    UTILITY_ONLY_DEPARTMENTS,
    complete_task,
    file_discrepancy,
    get_delivery,
    get_order,
    get_task,
    make_qa_reviewer_headers,
    record_findings,
    resolve_discrepancy,
    setup_delivered,
    setup_identified_order,
    start_review,
)

QA = make_qa_reviewer_headers("qa_1")


def _identified_order_with_completed_task(parcel):
    """Single-department order, task completed with a 300000 utility balance
    (fees 5000, payoff 300000), plus a pre-delivery BALANCE_MISMATCH claim of
    50000 against the task, under review."""
    ctx = setup_identified_order(
        parcel, departments=UTILITY_ONLY_DEPARTMENTS, with_association=False
    )
    task = ctx["tasks"][0]
    record_findings(task, FINDINGS_UTILITY_300K)
    complete_task(task["id"])
    discrepancy = file_discrepancy(
        ctx["order"]["id"], "RESEARCH_TASK", task["id"],
        "BALANCE_MISMATCH", 50000, "Balance wrong",
    )
    start_review(discrepancy["id"], headers=QA)
    return ctx, task, discrepancy


def test_task_reopen_reverses_billed_fee_and_payoff(api):
    """PRD 3.8: "For a confirmed correction whose subject is a research task,
    the subject task reopens from `COMPLETED` to `IN_PROGRESS`: the order's
    `total_fees_cents` decreases by the task's `fee_charged_cents`, which itself
    resets to zero, the order's `total_payoff_cents` decreases by the task's
    `unpaid_balance_cents`, and `completed_by_user_id` is cleared."
    PRD 3.4: "Likewise `total_fees_cents` is the sum of `fee_charged_cents` over
    `COMPLETED` tasks plus the sum of `lifetime_fees_cents` over estoppels in
    `RECEIVED` or `EXPIRED`; once charged, fees are never refunded, even by
    cancellation."

    Design: Difficulty/compensating_invariant/complete_reopen_pair_conserves_billed_fees
    """
    ctx, task, discrepancy = _identified_order_with_completed_task("P-F1")
    order = get_order(ctx["order"]["id"])
    assert order["total_fees_cents"] == 5000
    assert order["total_payoff_cents"] == 300000

    resolve_discrepancy(discrepancy["id"], "CONFIRMED_CORRECTION", headers=QA)

    order = get_order(ctx["order"]["id"])
    assert order["total_fees_cents"] == 0, (
        "The compensating reopen subtracts exactly the billed fee — zero drift"
    )
    assert order["total_payoff_cents"] == 0
    reopened = get_task(task["id"])
    assert reopened["status"] == "IN_PROGRESS"
    assert reopened["fee_charged_cents"] == 0


def test_recompletion_restores_fee_with_corrected_findings(api):
    """PRD 3.4: "Completing a task — allowed only once findings have been
    recorded — moves it from `IN_PROGRESS` to `COMPLETED`, records the caller in
    `completed_by_user_id`, and fixes `fee_charged_cents` as the snapshotted
    `fee_base_cents` plus, when the owning order is `RUSH`, the snapshotted
    `fee_rush_surcharge_cents`. The order's `total_fees_cents` grows by that
    charge and its `total_payoff_cents` grows by the task's
    `unpaid_balance_cents`."

    Design: Difficulty/compensating_invariant/complete_reopen_pair_conserves_billed_fees
    """
    ctx, task, discrepancy = _identified_order_with_completed_task("P-F2")
    resolve_discrepancy(discrepancy["id"], "CONFIRMED_CORRECTION", headers=QA)

    # Re-record corrected findings (310000) against the reopened task and
    # complete again: the fee/balance pair round-trips with no drift.
    reopened = get_task(task["id"])
    record_findings(reopened, FINDINGS_UTILITY_310K)
    complete_task(task["id"])

    order = get_order(ctx["order"]["id"])
    assert order["total_fees_cents"] == 5000
    assert order["total_payoff_cents"] == 310000


def test_filing_claim_adds_pending_exposure(api):
    """PRD 3.8: "Filing immediately adds `claimed_amount_cents` to the order's
    `pending_claims_cents`, the running exposure across the order's `OPEN` and
    `UNDER_REVIEW` claims."

    Design: Difficulty/compensating_invariant/file_reject_pair_conserves_pending_claims
    """
    ctx = setup_delivered(
        "P-H1",
        departments=UTILITY_ONLY_DEPARTMENTS,
        findings_per_task=[FINDINGS_UTILITY_300K],
    )
    assert get_order(ctx["order"]["id"])["pending_claims_cents"] == 0

    discrepancy = file_discrepancy(
        ctx["order"]["id"], "SEARCH_ORDER", ctx["order"]["id"],
        "MISSED_ITEM", 60000, "Missed code lien",
    )
    assert discrepancy["status"] == "OPEN"
    assert get_order(ctx["order"]["id"])["pending_claims_cents"] == 60000


def test_rejected_claim_releases_pending_exposure(api):
    """PRD 3.8: "Every resolution records `resolved_by_user_id` and subtracts
    the `claimed_amount_cents` from `pending_claims_cents`."
    PRD 3.8: "Claims resolved as `REJECTED_INVALID` simply release their
    pending amount with no further cascade, as do the force-resolved
    `VOID_ORDER_CANCELLED` outcomes produced by order cancellation."

    Design: Difficulty/compensating_invariant/file_reject_pair_conserves_pending_claims
    """
    ctx = setup_delivered(
        "P-H2",
        departments=UTILITY_ONLY_DEPARTMENTS,
        findings_per_task=[FINDINGS_UTILITY_300K],
    )
    discrepancy = file_discrepancy(
        ctx["order"]["id"], "SEARCH_ORDER", ctx["order"]["id"],
        "MISSED_ITEM", 60000, "Missed code lien",
    )
    assert get_order(ctx["order"]["id"])["pending_claims_cents"] == 60000
    start_review(discrepancy["id"], headers=QA)

    resolve_discrepancy(discrepancy["id"], "REJECTED_INVALID", headers=QA)

    order = get_order(ctx["order"]["id"])
    assert order["pending_claims_cents"] == 0, (
        "The reject resolution subtracts exactly the claimed amount — zero drift"
    )
    assert order["total_liability_cents"] == 0, (
        "Rejected claims accrue no liability"
    )
    assert order["status"] == "DELIVERED"
    assert get_delivery(ctx["delivery"]["id"])["status"] == "DELIVERED"
