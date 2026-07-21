"""Multi-hop cascades: cancelling an event, and settling a refund into a payout."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_paginated,
    setup_onsale_event, setup_reserved_onsale_event, setup_paid_order,
    setup_refund_request, approve_refund, settle_refund, setup_payout,
    close_and_complete_event, create_buyer, read_order, read_payout,
    read_organizer, read_ticket_type, read_seat_block, read_refund_request,
    read_event, read_attendee, TEST_USERS,
)

FINANCE = TEST_USERS["finance_officer_headers"]


def _completed_event_with_payout_and_pending_refund(policy, refund_quantity):
    """Sell two tickets, open a refund before the show, then complete and settle.

    The refund request is opened while the clock is still before `starts_at`, the
    event is then closed and completed, and a payout is opened afterwards so its
    `reliability_score_snapshot` is frozen before the refund ever settles.
    """
    ctx = setup_onsale_event(
        clock="2026-07-05T10:00:00Z",
        event_overrides={"title": "Harbor Night", "starts_at": "2026-08-01T18:00:00Z",
                         "ends_at": "2026-08-01T22:00:00Z", "fee_mode": "PASS_ON",
                         "refund_policy": "FEE_RETAINED"})
    paid = setup_paid_order(ctx, quantity=2)
    request = setup_refund_request(paid, quantity=refund_quantity, policy=policy,
                                   reason="one guest dropped out")

    close_and_complete_event(ctx, "2026-08-02T00:00:00Z")
    payout = setup_payout(ctx)
    approve_refund(ctx, request["id"])

    ctx["paid"] = paid
    ctx["request"] = request
    ctx["payout"] = payout
    ctx["payout_id"] = payout["id"]
    return ctx


# ---------------------------------------------------------------------------
# The frozen reserve rate against its own refund feedback loop
# ---------------------------------------------------------------------------

def test_settled_refund_moves_the_payout_reserve_and_net():
    """PRD §3.8: "The third hop, caused by the order's refund figures moving, finds
    the payout whose `event_id` matches the order's event and whose status is
    `ACCRUING` or `ELIGIBLE`, and recomputes its `gross_cents`, `refunds_cents`,
    `platform_fee_cents`, `reserve_basis_cents`, `reserve_cents` and
    `net_amount_cents` using its frozen `reliability_score_snapshot`."
    PRD §3.9: "Step four sets `reserve_basis_cents` to `gross_cents` minus
    `refunds_cents` minus `platform_fee_cents`."

    Design: Difficulty/combinatorial_formula/payout_reserve_rate_frozen_against_its_own_refund_feedback_loop
    """
    ctx = _completed_event_with_payout_and_pending_refund("FEE_RETAINED", 1)
    before = read_payout(ctx["payout_id"])
    assert before["reserve_cents"] == 1000, \
        f"Before the refund the reserve is 10 percent of 10000, got {before['reserve_cents']}"
    assert before["net_amount_cents"] == 9000

    settle_refund(ctx["request"]["id"])

    payout = read_payout(ctx["payout_id"])
    assert payout["gross_cents"] == 10000
    assert payout["refunds_cents"] == 5000, \
        f"One 5000-cent ticket was charged back, got {payout['refunds_cents']}"
    assert payout["platform_fee_cents"] == 0, \
        "A pass-on event has already collected its fee from the buyer"
    assert payout["reserve_basis_cents"] == 5000
    assert payout["reserve_cents"] == 500, \
        f"Expected the reserve to fall 1000 -> 500, got {payout['reserve_cents']}"
    assert payout["net_amount_cents"] == 4500
    assert read_order(ctx["paid"]["order_id"],
                      ctx["paid"]["buyer"])["payment_status"] == "PARTIALLY_REFUNDED"


def test_payout_reserve_rate_stays_frozen_at_its_creation_snapshot():
    """PRD §3.9: "The apparent circularity in that chain is resolved deliberately:
    the reserve rate depends on a reliability score that is itself derived from the
    same refund data feeding step two. The cycle is broken by freezing
    `reliability_score_snapshot` at payout creation and never recomputing it. Later
    settled refunds move steps two, four, six and seven, but step five is immovable
    for the life of the payout."

    Design: Difficulty/combinatorial_formula/payout_reserve_rate_frozen_against_its_own_refund_feedback_loop
    """
    ctx = _completed_event_with_payout_and_pending_refund("FEE_RETAINED", 1)
    before = read_payout(ctx["payout_id"])
    assert before["reliability_score_snapshot"] == 65
    assert before["reserve_rate"] == pytest.approx(0.10)

    settle_refund(ctx["request"]["id"])

    after = read_payout(ctx["payout_id"])
    assert after["reliability_score_snapshot"] == 65, (
        "The frozen snapshot must survive the refund that would otherwise change it. "
        f"Got {after['reliability_score_snapshot']}")
    assert after["reserve_rate"] == pytest.approx(0.10), (
        "Step five is immovable for the life of the payout, got "
        f"{after['reserve_rate']}")


# ---------------------------------------------------------------------------
# Settling a full refund drives the order, the organiser and the payout
# ---------------------------------------------------------------------------

def test_settling_a_full_refund_refunds_the_order_and_charges_the_organizer():
    """PRD §3.8: "The first hop sets the request's status to `SETTLED` and stamps
    `settled_at` with the current time."
    PRD §3.8: "an order that reaches `REFUNDED` from `PAID` additionally has its
    `fulfillment_status` set to `VOIDED`, and an order sitting in `REFUND_PENDING`
    likewise reaches `REFUNDED` only on the settlement that brings `refunded_cents` up
    to `buyer_total_cents` exactly."

    Design: Difficulty/transitive_cascade/refund_settle_drives_order_then_payout_recompute_then_hold
    """
    ctx = _completed_event_with_payout_and_pending_refund("FEE_INCLUDED", 2)

    settle_refund(ctx["request"]["id"])

    request = read_refund_request(ctx["request"]["id"])
    assert request["status"] == "SETTLED"

    order = read_order(ctx["paid"]["order_id"], ctx["paid"]["buyer"])
    assert order["refunded_cents"] == 10728, \
        f"A fee-included refund returns face plus fee, got {order['refunded_cents']}"
    assert order["payment_status"] == "REFUNDED", \
        f"The refund exactly matches the buyer total, got {order['payment_status']}"
    assert order["fulfillment_status"] == "VOIDED"

    assert read_organizer(ctx["org_id"])["lifetime_refunds_cents"] == 10728


def test_settlement_recompute_pushes_the_payout_negative_and_holds_it():
    """PRD §3.8: "The fourth hop, caused by that recompute, sets that payout's status
    to `ON_HOLD` whenever the recomputed `net_amount_cents` is below zero — a clawback
    that exceeds the accrual freezes the settlement rather than paying out a negative
    sum."
    PRD §3.9: "Step six sets `reserve_cents` to the greater of zero and the reserve
    rate multiplied by `reserve_basis_cents`, rounded half up to a whole cent — the
    only rounding in the chain. Step seven sets `net_amount_cents` to
    `reserve_basis_cents` minus `reserve_cents`."

    Design: Difficulty/transitive_cascade/refund_settle_drives_order_then_payout_recompute_then_hold
    """
    ctx = _completed_event_with_payout_and_pending_refund("FEE_INCLUDED", 2)

    settle_refund(ctx["request"]["id"])

    payout = read_payout(ctx["payout_id"])
    assert payout["refunds_cents"] == 10728
    assert payout["reserve_basis_cents"] == -728, \
        f"Expected 10000 - 10728 - 0 = -728, got {payout['reserve_basis_cents']}"
    assert payout["reserve_cents"] == 0, \
        f"The reserve is clamped at zero on a negative basis, got {payout['reserve_cents']}"
    assert payout["net_amount_cents"] == -728
    assert payout["status"] == "ON_HOLD", \
        f"A clawback beyond the accrual freezes the settlement, got {payout['status']}"


# ---------------------------------------------------------------------------
# Cancelling an event unwinds everything at once
# ---------------------------------------------------------------------------

def _cancelled_reserved_event():
    """A paid two-seat reserved order, then the event is cancelled."""
    ctx = setup_reserved_onsale_event(
        clock="2026-07-05T10:00:00Z",
        event_overrides={"title": "Cascade Night", "starts_at": "2026-08-12T18:00:00Z",
                         "ends_at": "2026-08-12T22:00:00Z", "fee_mode": "PASS_ON"})
    ctx["paid"] = setup_paid_order(ctx, quantity=2, seat_numbers=[3, 4])
    assert read_seat_block(ctx["sb_id"])["seats_taken"] == 2
    assert read_ticket_type(ctx["tt_id"])["sold_count"] == 2

    validate_success(api_client.cancel_event(
        ctx["event_id"], ctx["org_headers"], {"reason": "artist illness"}), 200)
    return ctx


def test_cancelling_an_event_voids_its_orders_and_admissions():
    """PRD §3.8: "The second hop, caused by the first, sweeps the event's orders:
    every order whose `fulfillment_status` is `HELD`, `ISSUED`, `CHECKED_IN_PARTIAL`
    or `CHECKED_IN_FULL` is set to `VOIDED` fulfilment, and every such order whose
    `payment_status` is `PAID` is additionally set to `REFUND_PENDING`. The third hop,
    caused by those orders being voided, sets every admission belonging to them whose
    status is `ISSUED` or `CHECKED_IN` to `VOIDED`."

    Design: Difficulty/transitive_cascade/event_cancel_voids_orders_then_attendees_then_releases_seats
    """
    ctx = _cancelled_reserved_event()

    assert read_event(ctx["event_id"])["status"] == "CANCELLED"

    order = read_order(ctx["paid"]["order_id"], ctx["paid"]["buyer"])
    assert order["fulfillment_status"] == "VOIDED"
    assert order["payment_status"] == "REFUND_PENDING", \
        f"A paid order is queued for its money back, got {order['payment_status']}"

    rows, meta = validate_paginated(api_client.list_attendees(
        ctx["paid"]["buyer_headers"], params={"order_id": ctx["paid"]["order_id"]}))
    assert meta["total_count"] == 2, f"Expected both admissions, got {meta['total_count']}"
    assert all(row["status"] == "VOIDED" for row in rows), (
        "Every admission of a voided order is voided, got "
        f"{[row['status'] for row in rows]}")


def test_cancelling_an_event_frees_the_seats_and_opens_a_fee_included_refund():
    """PRD §3.8: "The fourth hop, caused by those admissions being voided, gives the
    inventory back: for each voided admission carrying a non-null `seat_block_id`, the
    block's `seats_taken` falls by 1 and the tier's `sold_count` falls by 1. The fifth
    hop, caused by the orders entering `REFUND_PENDING`, opens the money return: for
    each such order a refund request is created already in `APPROVED` status with
    `policy` of `FEE_INCLUDED`, with `item_refunds` covering every line of that order
    at its full remaining quantity, and with `refund_amount_cents`,
    `platform_retained_cents` and `organizer_charged_cents` computed by the refund
    calculation above."

    Design: Difficulty/transitive_cascade/event_cancel_voids_orders_then_attendees_then_releases_seats
    """
    ctx = _cancelled_reserved_event()

    assert read_seat_block(ctx["sb_id"])["seats_taken"] == 0, \
        "Both seats return to the pool"
    assert read_ticket_type(ctx["tt_id"])["sold_count"] == 0

    rows, meta = validate_paginated(api_client.list_refund_requests(
        ctx["org_headers"], params={"order_id": ctx["paid"]["order_id"]}))
    assert meta["total_count"] == 1, \
        f"Exactly one refund request is opened for the order, got {meta['total_count']}"

    auto = rows[0]
    assert auto["status"] == "APPROVED", \
        f"The cascade opens it already approved, got {auto['status']}"
    assert auto["policy"] == "FEE_INCLUDED"
    assert auto["refund_amount_cents"] == 10728, (
        "Face 10000 plus the 728-cent fee is returned under FEE_INCLUDED, got "
        f"{auto['refund_amount_cents']}")
