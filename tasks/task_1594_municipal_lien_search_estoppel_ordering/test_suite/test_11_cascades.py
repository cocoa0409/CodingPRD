"""Transitive cascades: the clock-sweep expiry chain and the confirmed
task-discrepancy reopen chain."""
from test_helpers import (
    file_discrepancy,
    get_delivery,
    get_estoppel,
    get_order,
    get_task,
    make_qa_reviewer_headers,
    resolve_discrepancy,
    set_clock,
    setup_delivered,
    setup_with_ready_delivery,
    start_review,
)

QA2 = make_qa_reviewer_headers("qa_2")


def test_expiry_sweep_reverts_ready_order_and_recomputes_payoff(api):
    """PRD 3.5: "Whenever the logical clock is set past a received estoppel's
    `valid_through` and the owning order is neither `DELIVERED` nor `CANCELLED`,
    the sweep moves the estoppel from `RECEIVED` to `EXPIRED` and subtracts its
    `payoff_amount_cents` from the order's `total_payoff_cents` — the lifetime
    fees, once earned, stay in `total_fees_cents`. If the order was sitting in
    `VERIFICATION` or `READY_FOR_DELIVERY` at that moment, it reverts to
    `RESEARCH_IN_PROGRESS` with its payoff verification cleared, and any `READY`
    delivery of the order is voided."

    Design: Difficulty/transitive_cascade/clock_sweep_estoppel_expiry_reverts_order_and_voids_delivery
    """
    # Estoppel received 2026-08-01 -> valid_through 2026-08-31; order READY.
    ctx = setup_with_ready_delivery("P-X1")
    estoppel_id = ctx["estoppels"][0]["id"]
    assert get_order(ctx["order"]["id"])["total_payoff_cents"] == 356500

    set_clock("2026-09-01T00:00:00Z")
    assert get_estoppel(estoppel_id)["status"] == "EXPIRED"

    order = get_order(ctx["order"]["id"])
    # 356500 - 45000 estoppel payoff; the three task balances remain.
    assert order["total_payoff_cents"] == 311500
    assert order["status"] == "RESEARCH_IN_PROGRESS"
    assert order.get("payoff_verified_by_user_id") is None


def test_expiry_sweep_voids_ready_delivery(api):
    """PRD 3.5: "If the order was sitting in `VERIFICATION` or
    `READY_FOR_DELIVERY` at that moment, it reverts to `RESEARCH_IN_PROGRESS`
    with its payoff verification cleared, and any `READY` delivery of the order
    is voided."

    Design: Difficulty/transitive_cascade/clock_sweep_estoppel_expiry_reverts_order_and_voids_delivery
    """
    ctx = setup_with_ready_delivery("P-X2")
    delivery_id = ctx["delivery"]["id"]
    assert ctx["delivery"]["status"] == "READY"

    set_clock("2026-09-01T00:00:00Z")
    assert get_delivery(delivery_id)["status"] == "VOIDED", (
        "The order leaving READY_FOR_DELIVERY voids its READY delivery"
    )
    assert get_order(ctx["order"]["id"])["status"] == "RESEARCH_IN_PROGRESS"


def _delivered_order_with_task_claim():
    """Delivered Config A order (fees 26000, payoff 356500) plus a post-delivery
    BALANCE_MISMATCH claim of 50000 against the utility task, under review."""
    ctx = setup_delivered("P-Y1", order_overrides={"property_address": "8 Y St"})
    utility_task = ctx["tasks"][0]
    discrepancy = file_discrepancy(
        ctx["order"]["id"], "RESEARCH_TASK", utility_task["id"],
        "BALANCE_MISMATCH", 50000, "Utility balance understated",
    )
    start_review(discrepancy["id"])
    return ctx, utility_task, discrepancy


def test_confirmed_task_discrepancy_reopens_task(api):
    """PRD 3.8: "For a confirmed correction whose subject is a research task,
    the subject task reopens from `COMPLETED` to `IN_PROGRESS`: the order's
    `total_fees_cents` decreases by the task's `fee_charged_cents`, which itself
    resets to zero, the order's `total_payoff_cents` decreases by the task's
    `unpaid_balance_cents`, and `completed_by_user_id` is cleared."

    Design: Difficulty/transitive_cascade/confirmed_task_discrepancy_reopens_task_and_reverses_fees
    """
    ctx, task, discrepancy = _delivered_order_with_task_claim()
    assert task["status"] == "COMPLETED"
    assert task["fee_charged_cents"] == 5000

    resolve_discrepancy(discrepancy["id"], "CONFIRMED_CORRECTION")
    reopened = get_task(task["id"])
    assert reopened["status"] == "IN_PROGRESS"
    assert reopened["fee_charged_cents"] == 0
    assert reopened.get("completed_by_user_id") is None


def test_confirmed_task_discrepancy_reverses_order_totals(api):
    """PRD 3.8: "For a confirmed correction whose subject is a research task,
    the subject task reopens from `COMPLETED` to `IN_PROGRESS`: the order's
    `total_fees_cents` decreases by the task's `fee_charged_cents`, which itself
    resets to zero, the order's `total_payoff_cents` decreases by the task's
    `unpaid_balance_cents`, and `completed_by_user_id` is cleared."
    PRD 3.4: "`total_payoff_cents` is the sum of `unpaid_balance_cents` over the
    order's `COMPLETED` research tasks plus the sum of `payoff_amount_cents`
    over its `RECEIVED` estoppel orders — tasks in any other state and estoppels
    in any other state contribute zero."

    Design: Difficulty/transitive_cascade/confirmed_task_discrepancy_reopens_task_and_reverses_fees
    """
    ctx, task, discrepancy = _delivered_order_with_task_claim()
    resolve_discrepancy(discrepancy["id"], "CONFIRMED_CORRECTION")

    order = get_order(ctx["order"]["id"])
    # 26000 - 5000 reopened task fee; 356500 - 300000 reopened task balance.
    assert order["total_fees_cents"] == 21000
    assert order["total_payoff_cents"] == 56500
