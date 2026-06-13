"""Repair execution workflow: start-repair preconditions (technician present,
parts ready), mark-ready completeness, the parallel notify dimension, parts-state
guards, and terminal-state cancellation lockdown.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success, validate_error,
    create_parts_order_payload,
    TEST_USERS, make_technician_headers,
    set_clock, create_customer, create_service_type, create_technician,
    create_ticket, add_item, add_service_line, add_part, create_draft_estimate,
    present_estimate, approve_estimate, complete_line,
    setup_approved, setup_in_repair, setup_ready_for_pickup, setup_picked_up,
)

FRONT_DESK = TEST_USERS["front_desk_headers"]
SHOP_MANAGER = TEST_USERS["shop_manager_headers"]


# ── Corner: start-repair without an assigned technician ──────────────────
def test_start_repair_without_technician_rejected(api):
    """PRD §3.6: "Starting requires that the ticket have an `assigned_technician_id` set and that the named technician be active; otherwise the request is rejected with `ERR_NO_TECHNICIAN`."

    Design: Corner/state_machines/start_repair_without_technician_rejected
    """
    set_clock()
    customer = create_customer()
    st = create_service_type(base_price_cents=4000, item_category="SHOE")
    tech = create_technician(skills=["SHOE"])  # authors estimate, but NOT assigned to ticket
    ticket = create_ticket(customer["id"])  # no assigned_technician_id
    item = add_item(ticket["id"], item_category="SHOE")
    add_service_line(ticket["id"], item["id"], st["id"], tech["id"])
    est = create_draft_estimate(ticket["id"], tech["id"])
    est = present_estimate(est["id"], ticket["id"], tech["id"])
    approve_estimate(est["id"], customer["id"])
    res = api.start_repair(ticket["id"], make_technician_headers(tech["id"]))
    validate_error(res, "ERR_NO_TECHNICIAN", 409)


# ── Difficulty: start-repair blocked by pending parts (≥2 tests) ─────────
def _setup_awaiting_parts_with_ordered_part():
    """Ticket in AWAITING_PARTS with one ORDERED (not RECEIVED) part."""
    set_clock("2026-03-01T09:00:00Z")
    customer = create_customer()
    st = create_service_type(base_price_cents=4000, item_category="SHOE",
                             standard_turnaround_days=3, warranty_days=90)
    tech = create_technician(skills=["SHOE"])
    ticket = create_ticket(customer["id"], assigned_technician_id=tech["id"])
    item = add_item(ticket["id"], item_category="SHOE")
    line = add_service_line(ticket["id"], item["id"], st["id"], tech["id"])
    part = add_part(ticket["id"], line["id"], 1200, 5, tech["id"], quantity=1)
    est = create_draft_estimate(ticket["id"], tech["id"])
    est = present_estimate(est["id"], ticket["id"], tech["id"])
    validate_success(api_client.order_part(part["id"], make_technician_headers(tech["id"])), 200)
    approve_estimate(est["id"], customer["id"])  # outstanding ORDERED part -> AWAITING_PARTS
    return customer, tech, ticket, line, part


def test_start_repair_blocked_while_part_ordered(api):
    """PRD §3.6: "When starting from `AWAITING_PARTS`, every parts order on the ticket must already be in `RECEIVED` or `CANCELLED`, failing with `ERR_PARTS_NOT_READY` otherwise."

    Design: Difficulty/cross_entity_state_dependency/start_repair_blocked_by_pending_parts
    """
    customer, tech, ticket, line, part = _setup_awaiting_parts_with_ordered_part()
    res = api.start_repair(ticket["id"], make_technician_headers(tech["id"]))
    validate_error(res, "ERR_PARTS_NOT_READY", 409)
    ticket_after = validate_success(api.get_repair_ticket(ticket["id"], FRONT_DESK), 200)
    assert ticket_after["repair_status"] == "AWAITING_PARTS"


def test_start_repair_succeeds_once_part_received(api):
    """PRD §3.4: "Receiving does not auto-advance the ticket: when the ticket is in `AWAITING_PARTS` and every parts order has reached `RECEIVED` or `CANCELLED`, the ticket merely becomes eligible for the technician to start repair, which the technician triggers explicitly."

    Design: Difficulty/cross_entity_state_dependency/start_repair_blocked_by_pending_parts
    """
    customer, tech, ticket, line, part = _setup_awaiting_parts_with_ordered_part()
    validate_success(api.receive_part(part["id"], make_technician_headers(tech["id"])), 200)
    started = validate_success(api.start_repair(ticket["id"], make_technician_headers(tech["id"])), 200)
    assert started["repair_status"] == "IN_REPAIR"


# ── Corner: mark-ready with an incomplete line ───────────────────────────
def test_mark_ready_with_incomplete_line_rejected(api):
    """PRD §3.6: "Marking the ticket ready transitions it from `IN_REPAIR` to `READY_FOR_PICKUP` and is permitted only when every non-`VOIDED` service line on the ticket is `COMPLETED`; an incomplete line set is rejected with `ERR_LINES_NOT_COMPLETED`."

    Design: Corner/state_machines/mark_ready_with_incomplete_line_rejected
    """
    s = setup_in_repair()  # ticket IN_REPAIR, line still QUOTED
    res = api.mark_ready(s["ticket"]["id"], make_technician_headers(s["technician"]["id"]))
    validate_error(res, "ERR_LINES_NOT_COMPLETED", 409)


# ── Corner: notify-ready flips parallel dimension only ───────────────────
def test_notify_ready_flips_parallel_dimension(api):
    """PRD §3.6: "A `FrontDeskClerk` sends the ready-for-pickup notification, which moves the ticket's `notify_status` from `NONE` to `READY_NOTIFIED` and appends a `READY_FOR_PICKUP` notification, incrementing the ticket's `version`. This `notify_status` dimension ... evolves independently of `repair_status`."

    Design: Corner/state_machines/notify_ready_parallel_dimension_independent
    """
    s = setup_ready_for_pickup()
    res = api.notify_ready(s["ticket"]["id"], FRONT_DESK)
    updated = validate_success(res, 200)
    assert updated["notify_status"] == "READY_NOTIFIED"
    assert updated["repair_status"] == "READY_FOR_PICKUP"


# ── Corner: cancel a PICKED_UP ticket ────────────────────────────────────
def test_cancel_picked_up_ticket_not_cancellable(api):
    """PRD §3.4: "Cancelling a whole ticket is reserved for a `ShopManager` and is permitted only while the ticket is in `INTAKE`, `AWAITING_APPROVAL`, `REVISION_REQUESTED`, `APPROVED`, or `AWAITING_PARTS`; any other state is rejected with `ERR_NOT_CANCELLABLE`."

    Design: Corner/state_machines/cancel_picked_up_ticket_not_cancellable
    """
    s = setup_picked_up(item_category="WATCH",
                        service_overrides={"item_category": "WATCH", "base_price_cents": 1500,
                                           "standard_turnaround_days": 1, "warranty_days": 90})
    res = api.cancel_ticket(s["ticket"]["id"], SHOP_MANAGER)
    validate_error(res, "ERR_NOT_CANCELLABLE", 409)


# ── Corner: receive a part still in REQUESTED ────────────────────────────
def test_receive_part_before_order_invalid_parts_state(api):
    """PRD §3.4: "A parts order is created in status `REQUESTED` ... A parts order's `status` moves along the pipeline `REQUESTED → ORDERED → RECEIVED`".
    PRD §2.9: "eighth, the target resource being in the correct state for the requested transition (the invalid-state family)."

    Design: Corner/errors/invalid_parts_state_on_receive_before_order
    """
    set_clock()
    customer = create_customer()
    st = create_service_type(base_price_cents=4000, item_category="SHOE")
    tech = create_technician(skills=["SHOE"])
    ticket = create_ticket(customer["id"])
    item = add_item(ticket["id"], item_category="SHOE")
    line = add_service_line(ticket["id"], item["id"], st["id"], tech["id"])
    part = validate_success(
        api.create_parts_order(
            create_parts_order_payload(ticket["id"], line["id"], 500, 1),
            make_technician_headers(tech["id"]),
        ),
        201,
    )
    res = api.receive_part(part["id"], make_technician_headers(tech["id"]))
    validate_error(res, "ERR_INVALID_PARTS_STATE", 409)
