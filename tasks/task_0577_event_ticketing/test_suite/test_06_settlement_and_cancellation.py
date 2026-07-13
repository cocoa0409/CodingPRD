"""Settlement gross-vs-net accounting, settlement readiness, and the event-cancellation
cascade (order -> ticket -> seat)."""
import pytest

from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    create_refund_request_payload,
    make_buyer_headers, make_promoter_headers,
    setup_paid_order, setup_onsale_event, set_status, set_clock,
)

BOX = TEST_USERS["box_office_headers"]
PROMOTER = make_promoter_headers()


# ─── Difficulty: gross vs net settlement variants ─────────────────────────
def _finalized_settlement_one_of_two_refunded(api):
    """2-seat paid order (tickets face 9990 each); one ticket refunded to ORIGINAL; event
    COMPLETED; settlement finalized. Returns the finalized Settlement."""
    p = setup_paid_order(num_seats=2, delivery_method="MOBILE")
    o = p["order"]["id"]
    hb = make_buyer_headers(p["buyer"]["id"])
    ov = validate_success(api.get_order(o, hb), 200)["version"]
    rr = validate_success(
        api.create_refund_request(
            o,
            create_refund_request_payload(
                "CUSTOMER_REQUEST", "ORIGINAL", ov, ticket_ids=[p["tickets"][0]["id"]]
            ),
            hb,
        ),
        201,
    )
    validate_success(api.approve_refund_request(rr["id"], BOX), 200)

    set_clock("2026-08-01T20:00:00Z")  # at/after event_datetime so COMPLETED is legal
    set_status(p["event"]["id"], "COMPLETED")
    return validate_success(api.finalize_settlement(p["event"]["id"], PROMOTER), 200)


def test_settlement_net_to_promoter_counts_valid_tickets_only(api):
    """PRD §3.7: "Its `net_to_promoter_cents` is the net variant and the actual payout basis:
    the sum of `face_value_cents` over only the tickets whose `status` is `VALID`, so refunded
    and voided face is excluded." PRD §3.7: "Finalization moves the settlement from `PENDING`
    to `FINALIZED`".

    Design: Difficulty/dual_variant_calc/settlement_gross_vs_net_to_promoter
    """
    settlement = _finalized_settlement_one_of_two_refunded(api)
    assert settlement["net_to_promoter_cents"] == 9990
    assert settlement["status"] == "FINALIZED"


def test_settlement_gross_face_counts_all_issued_tickets(api):
    """PRD §3.7: "Its `gross_face_cents` is the gross variant:" the sum of face value over all
    tickets ever issued, "regardless of whether they ended up `VALID`, `REFUNDED`, or `VOID`."

    Design: Difficulty/dual_variant_calc/settlement_gross_vs_net_to_promoter
    """
    settlement = _finalized_settlement_one_of_two_refunded(api)
    assert settlement["gross_face_cents"] == 19980


# ─── Corner: settlement readiness gate ────────────────────────────────────
def test_settlement_finalize_before_completed_returns_not_ready(api):
    """PRD §3.7: "Finalizing the settlement is available to the box office or the promoter and
    requires that the event is `COMPLETED`; finalizing before completion is rejected with
    `ERR_SETTLEMENT_NOT_READY`."

    Design: Corner/validations/settlement_finalize_before_completed_returns_not_ready
    """
    env = setup_onsale_event(num_seats=1)
    res = api.finalize_settlement(env["event"]["id"], BOX)
    validate_error(res, ApiErrorId.ERR_SETTLEMENT_NOT_READY.value, expected_status=409)


# ─── Difficulty: event-cancel depth-3 cascade ─────────────────────────────
def _paid_then_canceled(api):
    p = setup_paid_order(num_seats=1, delivery_method="MOBILE")
    set_status(p["event"]["id"], "CANCELED")
    return p


def test_cancel_refunds_order_and_voids_ticket(api):
    """PRD §3.6: "Every `PAID` or `PARTIALLY_REFUNDED` order moves to `REFUNDED`, with an
    automatic full refund created for the reason `EVENT_CANCELED` and destination `ORIGINAL`;
    every remaining `VALID` ticket of such an order moves to `VOID` and each voided ticket's
    seat returns to `AVAILABLE`."

    Design: Difficulty/transitive_cascade/event_cancel_cascades_order_ticket_seat
    """
    p = _paid_then_canceled(api)
    order = validate_success(api.get_order(p["order"]["id"], BOX), 200)
    assert order["status"] == "REFUNDED"
    ticket = validate_success(api.get_ticket(p["tickets"][0]["id"], BOX), 200)
    assert ticket["status"] == "VOID"


def test_cancel_frees_voided_ticket_seat(api):
    """PRD §3.6: "every remaining `VALID` ticket of such an order moves to `VOID` and each
    voided ticket's seat returns to `AVAILABLE`." PRD §2.8: counters are "recomputed after any
    seat status change (hold creation, release, expiry, payment, refund, or voiding)."

    Design: Difficulty/transitive_cascade/event_cancel_cascades_order_ticket_seat
    """
    p = _paid_then_canceled(api)
    seat = validate_success(api.get_seat(p["seats"][0]["id"], BOX), 200)
    assert seat["status"] == "AVAILABLE"
    event = validate_success(api.get_event(p["event"]["id"], BOX), 200)
    assert event["seats_sold"] == 0
    assert event["seats_available"] == 1
