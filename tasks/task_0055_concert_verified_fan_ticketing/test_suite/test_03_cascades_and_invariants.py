"""Sold-out / flag cascades, ticket parallel dimensions, transfer gating, and
refund compensation invariants.

Covers difficulty queue A rules transitive_cascade, non_linear_state_machine
(ticket dimensions), cross_entity_state_dependency (transfer verified),
compensating_invariant.
"""
from test_helpers import (
    validate_success,
    validate_error,
    setup_event_with_tier,
    register_and_verify_fan,
    register_fan,
    create_offered_entry,
    create_pending_order,
    create_paid_order,
    setup_held_ticket,
    setup_pending_transfer,
    join_queue,
    advance,
    create_tier,
    create_event,
    open_to_phase,
    get_ticket_for_order,
    make_fan_headers,
)
from test_helpers.fixtures import PROMOTER
from test_helpers.factories import create_resale_listing_payload, create_transfer_payload


def test_pay_last_seat_sells_out_and_revokes_waiting(api):
    """PRD §3.4: "If after this the event's tickets_sold_count equals its
    venue_capacity, the event transitions to SOLD_OUT (from either PRESALE or
    GENERAL), and that sold-out transition in turn revokes every remaining
    WAITING queue entry for the event."

    Design: Difficulty/transitive_cascade/pay_to_soldout_revokes_waiting_entries
    """
    event, tier = setup_event_with_tier(phase="GENERAL", venue_capacity=1, allocation=5)
    fan_h = register_and_verify_fan("h@x.com", device="dev-h")
    fan_w = register_and_verify_fan("w@x.com", device="dev-w")
    # H gets the only seat offered; W is left WAITING.
    qe_h = join_queue(event, tier, fan_h, requested_qty=1)
    qe_w = join_queue(event, tier, fan_w, requested_qty=1)
    advance(event["id"], tier_id=tier["id"], max_offers=1)
    order = validate_success(api.create_order(
        {"queue_entry_id": qe_h["id"], "fan_id": fan_h["id"], "tier_id": tier["id"], "quantity": 1},
        make_fan_headers(fan_h["id"]),
    ), 201)
    validate_success(api.pay_order(
        order["id"], {"expected_order_version": order["version"]},
        make_fan_headers(fan_h["id"]),
    ), 200)
    ev_after = validate_success(api.get_event(event["id"], PROMOTER), 200)
    assert ev_after["sales_status"] == "SOLD_OUT", ev_after
    assert ev_after["tickets_sold_count"] == 1, ev_after
    w_after = validate_success(api.get_queue_entry(qe_w["id"], make_fan_headers(fan_w["id"])), 200)
    assert w_after["status"] == "REVOKED", w_after


def test_queue_join_flag_cascade_revokes_holds(api):
    """PRD §3.1: "Each time a verified fan joins a queue, the risk_score is
    recomputed, and if it has risen to 70 or above, the system transitions the
    fan VERIFIED → FLAGGED on the spot. This flagging cascades: every one of that
    fan's queue entries currently in WAITING or OFFERED is revoked to REVOKED,
    releasing any held seats back to the pool as described in §3.3."

    Fan F shares device with 3 others (3*20=60 device pts) and joins a 3rd time
    in the velocity window (1 paid join over the free 2 -> 15 velocity pts) so the
    recomputed score reaches 70 and flips VERIFIED -> FLAGGED.

    Design: Difficulty/transitive_cascade/flag_fan_revokes_queue_holds_releases_seats
    """
    event = create_event(venue_capacity=100, presale_code="S", face_value_cents=10000)
    tier1 = create_tier(event["id"], allocation=50, name="FLOOR")
    tier2 = create_tier(event["id"], allocation=50, name="MEZZ")
    tier3 = create_tier(event["id"], allocation=50, name="BALC")
    event = open_to_phase(event, "GENERAL")
    ff = register_and_verify_fan("f@x.com", device="dev-f")
    # Three more fans on the same device -> device_pts = min(60, 3*20) = 60 for F.
    register_fan("f2@x.com", device="dev-f", full_name="F2")
    register_fan("f3@x.com", device="dev-f", full_name="F3")
    register_fan("f4@x.com", device="dev-f", full_name="F4")
    qf1 = join_queue(event, tier1, ff, requested_qty=1)
    qf2 = join_queue(event, tier2, ff, requested_qty=1)
    # 3rd join: velocity=3 -> (3-2)*15 = 15; device 60 -> 75 >= 70 -> FLAGGED.
    join_queue(event, tier3, ff, requested_qty=1)
    f_after = validate_success(api.get_fan(ff["id"], make_fan_headers(ff["id"])), 200)
    assert f_after["verification_status"] == "FLAGGED", f_after
    e1 = validate_success(api.get_queue_entry(qf1["id"], make_fan_headers(ff["id"])), 200)
    e2 = validate_success(api.get_queue_entry(qf2["id"], make_fan_headers(ff["id"])), 200)
    assert e1["status"] == "REVOKED", e1
    assert e2["status"] == "REVOKED", e2


def test_listing_ticket_sets_holding_listed_entry_stays_valid(api):
    """PRD §3.5: "A ticket carries two independent dimensions. The entry_status
    is the mobile-entry dimension ... and the holding_status is the
    transfer/resale dimension ... These two dimensions evolve independently of
    each other."
    PRD §3.7: "Listing is permitted only when the ticket is HELD and VALID, and
    it moves the ticket's holding_status from HELD to LISTED while creating a
    listing in OPEN."

    Design: Difficulty/non_linear_state_machine/ticket_parallel_entry_and_holding_dimensions
    """
    event, tier, fan, order, ticket = setup_held_ticket(phase="GENERAL")
    validate_success(api.create_resale_listing(
        create_resale_listing_payload(ticket["id"], fan["id"], 11000),
        make_fan_headers(fan["id"]),
    ), 201)
    refreshed = validate_success(api.get_ticket(ticket["id"], make_fan_headers(fan["id"])), 200)
    assert refreshed["holding_status"] == "LISTED", refreshed
    assert refreshed["entry_status"] == "VALID", refreshed


def test_transfer_accept_requires_recipient_verified(api):
    """PRD §3.6: "acceptance requires the acting fan to be the recipient_fan_id,
    the recipient's verification_status to be VERIFIED, and the ticket to be
    TRANSFER_PENDING".
    PRD §3.8: "An unverified actor on any of these is rejected with
    ERR_FAN_NOT_VERIFIED."

    Design: Difficulty/cross_entity_state_dependency/transfer_accept_requires_recipient_verified
    """
    event, tier, sender, recipient, ticket, transfer = setup_pending_transfer(
        recipient_verified=False
    )
    res = api.accept_transfer(transfer["id"], make_fan_headers(recipient["id"]))
    validate_error(res, "ERR_FAN_NOT_VERIFIED")
    t_after = validate_success(api.get_transfer(transfer["id"], make_fan_headers(sender["id"])), 200)
    assert t_after["status"] == "PENDING", t_after


def test_refund_conserves_tier_sold_count(api):
    """PRD §3.4: "the tier's seats move from reserved to sold (reserved_count
    decreased by quantity, sold_count increased by quantity)".
    PRD §3.4: "Refund is a depth-three compensation cascade: all of the order's
    tickets are voided (entry_status → VOID); the tier's sold_count is decreased
    by quantity".

    After pay-then-refund, tier sold_count returns to its pre-pay value of 0.

    Design: Difficulty/compensating_invariant/refund_conserves_tier_seat_occupancy
    """
    event, tier = setup_event_with_tier(phase="GENERAL")
    fan = register_and_verify_fan("n@x.com", device="dev-n")
    _qe, paid = create_paid_order(event, tier, fan, requested_qty=2)
    tier_paid = validate_success(api.get_price_tier(tier["id"], PROMOTER), 200)
    assert tier_paid["sold_count"] == 2, tier_paid
    refunded = validate_success(api.refund_order(
        paid["id"], {"expected_order_version": paid["version"]},
        make_fan_headers(fan["id"]),
    ), 200)
    assert refunded["status"] == "REFUNDED", refunded
    tier_after = validate_success(api.get_price_tier(tier["id"], PROMOTER), 200)
    assert tier_after["sold_count"] == 0, tier_after


def test_refund_conserves_event_and_fan_counters(api):
    """PRD §3.4: "the event's tickets_sold_count is decreased by quantity; the
    buyer's completed_purchase_count is decreased by 1".

    After pay-then-refund, Event.tickets_sold_count and Fan.completed_purchase_count
    return to 0.

    Design: Difficulty/compensating_invariant/refund_conserves_event_tickets_sold_count
    """
    event, tier = setup_event_with_tier(phase="GENERAL")
    fan = register_and_verify_fan("q@x.com", device="dev-q")
    _qe, paid = create_paid_order(event, tier, fan, requested_qty=1)
    validate_success(api.refund_order(
        paid["id"], {"expected_order_version": paid["version"]},
        make_fan_headers(fan["id"]),
    ), 200)
    ev_after = validate_success(api.get_event(event["id"], PROMOTER), 200)
    assert ev_after["tickets_sold_count"] == 0, ev_after
    fan_after = validate_success(api.get_fan(fan["id"], make_fan_headers(fan["id"])), 200)
    assert fan_after["completed_purchase_count"] == 0, fan_after
