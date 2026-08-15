"""Cyclic state machines: the estoppel expiry/renewal loop and the
verification reject/re-verify loop."""
from test_helpers import (
    ESTOPPEL_PAYOFF,
    complete_all_tasks,
    get_estoppel,
    get_order,
    list_order_estoppels,
    make_qa_reviewer_headers,
    place_estoppel,
    receive_estoppel,
    set_clock,
    setup_identified_order,
    setup_in_verification,
    submit_order,
    validate_success,
    verify_order,
)

QA = make_qa_reviewer_headers("qa_1")


def _received_estoppel_on_untouched_order(parcel):
    """Order identified with an association; estoppel placed and received on
    2026-08-01 (valid_through 2026-08-31); tasks left PENDING so the order
    stays RESEARCH_IN_PROGRESS and the expiry sweep applies."""
    ctx = setup_identified_order(parcel)
    estoppel = ctx["estoppels"][0]
    place_estoppel(estoppel["id"], 10000)
    receive_estoppel(estoppel["id"], ESTOPPEL_PAYOFF)
    return ctx, estoppel["id"]


def test_received_estoppel_expires_after_valid_through(api):
    """PRD 3.5: "Whenever the logical clock is set past a received estoppel's
    `valid_through` and the owning order is neither `DELIVERED` nor `CANCELLED`,
    the sweep moves the estoppel from `RECEIVED` to `EXPIRED` and subtracts its
    `payoff_amount_cents` from the order's `total_payoff_cents` — the lifetime
    fees, once earned, stay in `total_fees_cents`."
    PRD 3.5: "`valid_through` is computed as the received date plus the
    association's `estoppel_validity_days` calendar days"

    Design: Difficulty/non_linear_state_machine/estoppel_order_renewal_cycle
    """
    ctx, estoppel_id = _received_estoppel_on_untouched_order("P-E1")
    assert get_estoppel(estoppel_id)["valid_through"] == "2026-08-31"
    assert get_order(ctx["order"]["id"])["total_payoff_cents"] == 45000

    set_clock("2026-09-01T00:00:00Z")
    expired = get_estoppel(estoppel_id)
    assert expired["status"] == "EXPIRED", (
        "The sweep moves a RECEIVED estoppel past its valid_through to EXPIRED"
    )
    order = get_order(ctx["order"]["id"])
    assert order["total_payoff_cents"] == 0, (
        "Expiry subtracts the estoppel payoff from the order total"
    )
    assert order["total_fees_cents"] == 10000, (
        "Lifetime fees once earned stay in total_fees_cents after expiry"
    )


def test_expired_estoppel_renews_with_lifetime_fees(api):
    """PRD 3.5: "An expired letter can be renewed by placing it again: the same
    cap check applies, `renewal_count` increments by 1, `ordered_at` and
    `statutory_due_at` are recomputed, the previous receipt's `received_at`,
    `payoff_amount_cents`, `valid_through`, and `late_delivery` are cleared, and
    `current_fee_cents` returns to zero until the next receipt."
    PRD 3.5: "When the letter arrives while the estoppel is `ORDERED`, receipt
    is on time: `received_at` is stamped, `late_delivery` is set false,
    `current_fee_cents` becomes the quoted fee — clamped as the lesser of
    `fee_quoted_cents` and the pinned cap, though placement already guarantees
    the quote is within cap — and `lifetime_fees_cents` grows by that amount."

    Design: Difficulty/non_linear_state_machine/estoppel_order_renewal_cycle
    """
    ctx, estoppel_id = _received_estoppel_on_untouched_order("P-E2")
    set_clock("2026-09-01T00:00:00Z")
    assert get_estoppel(estoppel_id)["status"] == "EXPIRED"

    renewed = place_estoppel(estoppel_id, 8000)
    assert renewed["status"] == "ORDERED"
    assert renewed["renewal_count"] == 1
    # Ordered 2026-09-01 + 10 response days -> end of 2026-09-11.
    assert renewed["statutory_due_at"] == "2026-09-11T23:59:59.000Z"

    received = receive_estoppel(estoppel_id, 46000)
    assert received["status"] == "RECEIVED"
    assert received["current_fee_cents"] == 8000
    assert received["lifetime_fees_cents"] == 18000, (
        "The first receipt's 10000 survives expiry; the renewal adds 8000"
    )
    assert get_order(ctx["order"]["id"])["total_payoff_cents"] == 46000


def test_reject_verification_returns_order_to_research(api):
    """PRD 3.6: "A reviewer who is not satisfied instead rejects the
    verification with a `reason`, returning the order to
    `RESEARCH_IN_PROGRESS` and clearing both verification fields."

    Design: Difficulty/non_linear_state_machine/search_order_verification_reject_reverify_cycle
    """
    ctx = setup_in_verification("P-V1")
    assert ctx["order"]["status"] == "VERIFICATION"

    rejected = validate_success(
        api.reject_verification(
            ctx["order"]["id"], {"reason": "recheck utility balance"}, QA
        ),
        200,
    )
    assert rejected["status"] == "RESEARCH_IN_PROGRESS"
    assert rejected.get("payoff_verified_by_user_id") is None
    assert rejected.get("payoff_verified_at") is None


def test_resubmit_and_verify_after_rejection(api):
    """PRD 3.6: "Once every research task of an order is `COMPLETED` or
    `UNABLE_TO_REACH` — any task still `PENDING` or `IN_PROGRESS` blocks
    submission with `ERR_TASKS_OUTSTANDING` — and every estoppel order is
    `RECEIVED` (anything else blocks with `ERR_ESTOPPEL_NOT_CURRENT`) with a
    `valid_through` on or after the `closing_date` (a stale letter blocks with
    `ERR_ESTOPPEL_STALE_FOR_CLOSING`), a `ResearchAnalyst` submits the order for
    verification, moving it to `VERIFICATION` and stamping
    `research_completed_by_user_id` with the caller's identity."
    PRD 3.6: "Successful verification moves the order to `READY_FOR_DELIVERY`,
    records `payoff_verified_by_user_id`, and stamps `payoff_verified_at`."

    Design: Difficulty/non_linear_state_machine/search_order_verification_reject_reverify_cycle
    """
    ctx = setup_in_verification("P-V2")
    validate_success(
        api.reject_verification(
            ctx["order"]["id"], {"reason": "recheck utility balance"}, QA
        ),
        200,
    )
    resubmitted = submit_order(ctx["order"]["id"])
    assert resubmitted["status"] == "VERIFICATION", (
        "The reject loop is not a dead end; resubmission is allowed"
    )

    computed = get_order(ctx["order"]["id"])["total_payoff_cents"]
    assert computed == 356500
    verified = verify_order(ctx["order"]["id"], computed)
    assert verified["status"] == "READY_FOR_DELIVERY"
    assert verified["payoff_verified_by_user_id"] == "qa_1"
