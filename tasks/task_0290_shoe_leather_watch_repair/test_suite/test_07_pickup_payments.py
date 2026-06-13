"""Pickup gating, payment capture/refund conservation, the payment OCC guard, and
the state-over-fiscal validation precedence on pickup.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success, validate_error,
    create_payment_payload,
    TEST_USERS, make_technician_headers,
    set_clock, get_ticket_version, capture_full_payment,
    setup_in_repair, setup_ready_for_pickup,
)

FRONT_DESK = TEST_USERS["front_desk_headers"]
SHOP_MANAGER = TEST_USERS["shop_manager_headers"]

WATCH_SERVICE = {"item_category": "WATCH", "base_price_cents": 1500,
                 "standard_turnaround_days": 1, "warranty_days": 90}


# ── Corner: balance due blocks pickup with partial payment ───────────────
def test_pickup_with_partial_payment_rejected(api):
    """PRD §3.6: "pickup requires `amount_paid_cents` to be at least `final_charge_cents`, and a shortfall is rejected with `ERR_BALANCE_DUE`."

    Design: Corner/endpoints/balance_due_blocks_pickup_with_partial_payment
    """
    s = setup_ready_for_pickup(item_category="WATCH", service_overrides=WATCH_SERVICE)
    ticket_id = s["ticket"]["id"]
    final_charge = s["ready_ticket"]["final_charge_cents"]
    assert final_charge == 1500
    # Capture only part of the bill.
    v = get_ticket_version(ticket_id)
    validate_success(
        api.create_payment(create_payment_payload(ticket_id, 1000, v), FRONT_DESK), 201
    )
    res = api.pickup(ticket_id, FRONT_DESK)
    validate_error(res, "ERR_BALANCE_DUE", 402)
    ticket = validate_success(api.get_repair_ticket(ticket_id, FRONT_DESK), 200)
    assert ticket["repair_status"] == "READY_FOR_PICKUP"


# ── Difficulty: capture then refund conserves amount_paid (≥2 tests) ─────
def test_capture_sets_amount_paid(api):
    """PRD §3.6: "A captured payment takes `state` `CAPTURED`, and the ticket's `amount_paid_cents` is recomputed as the sum of `amount_cents` over the ticket's payments in state `CAPTURED`."

    Design: Difficulty/compensating_invariant/payment_capture_then_refund_conserves_amount_paid
    """
    s = setup_ready_for_pickup(item_category="WATCH", service_overrides=WATCH_SERVICE)
    ticket_id = s["ticket"]["id"]
    v = get_ticket_version(ticket_id)
    pay = validate_success(
        api.create_payment(create_payment_payload(ticket_id, 1500, v), FRONT_DESK), 201
    )
    assert pay["state"] == "CAPTURED"
    ticket = validate_success(api.get_repair_ticket(ticket_id, FRONT_DESK), 200)
    assert ticket["amount_paid_cents"] == 1500


def test_refund_restores_amount_paid_to_pre_capture(api):
    """PRD §3.6: "Refunding moves the payment's `state` from `CAPTURED` to `REFUNDED` and recomputes the ticket's `amount_paid_cents` with refunded payments excluded, restoring the balance to its pre-capture value; the ticket's `version` increments."

    Design: Difficulty/compensating_invariant/payment_capture_then_refund_conserves_amount_paid
    """
    s = setup_ready_for_pickup(item_category="WATCH", service_overrides=WATCH_SERVICE)
    ticket_id = s["ticket"]["id"]
    v = get_ticket_version(ticket_id)
    pay = validate_success(
        api.create_payment(create_payment_payload(ticket_id, 1500, v), FRONT_DESK), 201
    )
    refunded = validate_success(api.refund_payment(pay["id"], SHOP_MANAGER), 200)
    assert refunded["state"] == "REFUNDED"
    ticket = validate_success(api.get_repair_ticket(ticket_id, FRONT_DESK), 200)
    assert ticket["amount_paid_cents"] == 0


# ── Corner: OCC stale version on payment capture ─────────────────────────
def test_payment_capture_with_stale_ticket_version_rejected(api):
    """PRD §2.5: "Capturing a payment requires `expected_ticket_version` to match the target ticket's current `version`; if a mark-ready has refreshed `final_charge_cents` since the clerk last read the ticket, the ticket's version will have advanced, and a payment sized against the pre-recompute charge is rejected with `ERR_STALE_TICKET_VERSION` rather than being taken against a stale balance."

    Design: Corner/cross_cutting_complexity_layers/occ_payment_capture_stale_ticket_version
    """
    s = setup_ready_for_pickup(item_category="WATCH", service_overrides=WATCH_SERVICE)
    ticket_id = s["ticket"]["id"]
    # Clerk reads a version, then a notify-ready bumps the ticket version.
    stale_v = get_ticket_version(ticket_id)
    validate_success(api.notify_ready(ticket_id, FRONT_DESK), 200)
    res = api.create_payment(create_payment_payload(ticket_id, 1500, stale_v), FRONT_DESK)
    validate_error(res, "ERR_STALE_TICKET_VERSION", 412)
    ticket = validate_success(api.get_repair_ticket(ticket_id, FRONT_DESK), 200)
    assert ticket["amount_paid_cents"] == 0


# ── Difficulty: state precedence beats fiscal on pickup (≥2 tests) ───────
def test_pickup_in_repair_zero_payment_reports_state_error(api):
    """PRD §2.9: "the target resource being in the correct state for the requested transition (the invalid-state family)" is the eighth rank, while "Beyond the eighth rank sit the domain-specific guards — segregation of duties, warranty timing, unclaimed timing, and the balance-due check".
    PRD §2.9: "The governing principle is that a cheaper, more general failure is reported before a more specific business failure".

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_pickup
    """
    s = setup_in_repair()  # IN_REPAIR, no payment captured -> both state and balance-due violated
    res = api.pickup(s["ticket"]["id"], FRONT_DESK)
    validate_error(res, "ERR_INVALID_TICKET_STATE", 409)


def test_pickup_in_repair_leaves_ticket_in_repair(api):
    """PRD §3.6: "A `FrontDeskClerk` records pickup from either `READY_FOR_PICKUP` or `UNCLAIMED`".
    PRD §2.9: "a path to a non-existent ticket is reported as not-found before any body validation runs."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_pickup
    """
    s = setup_in_repair()
    api.pickup(s["ticket"]["id"], FRONT_DESK)
    ticket = validate_success(api.get_repair_ticket(s["ticket"]["id"], FRONT_DESK), 200)
    assert ticket["repair_status"] == "IN_REPAIR"


# ── Corner: refund an already-refunded payment ───────────────────────────
def test_refund_already_refunded_payment_rejected(api):
    """PRD §3.6: "A `ShopManager` may refund a captured payment, but only while it is `CAPTURED`; a refund on an already-refunded payment is rejected with `ERR_PAYMENT_NOT_REFUNDABLE`."

    Design: Corner/errors/payment_refund_not_refundable_when_already_refunded
    """
    s = setup_ready_for_pickup(item_category="WATCH", service_overrides=WATCH_SERVICE)
    ticket_id = s["ticket"]["id"]
    v = get_ticket_version(ticket_id)
    pay = validate_success(
        api.create_payment(create_payment_payload(ticket_id, 1500, v), FRONT_DESK), 201
    )
    validate_success(api.refund_payment(pay["id"], SHOP_MANAGER), 200)
    res = api.refund_payment(pay["id"], SHOP_MANAGER)
    validate_error(res, "ERR_PAYMENT_NOT_REFUNDABLE", 409)
