"""The ticket-cancellation transitive cascade: cancel -> parts CANCELLED ->
owning line VOIDED -> open estimate REJECTED (depth 3).
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    TEST_USERS, make_technician_headers,
    set_clock, create_customer, create_service_type, create_technician,
    create_ticket, add_item, add_service_line, add_part, create_draft_estimate,
    present_estimate, get_ticket_version,
)

FRONT_DESK = TEST_USERS["front_desk_headers"]
SHOP_MANAGER = TEST_USERS["shop_manager_headers"]


def _setup_cancellable_with_ordered_part():
    """Ticket AWAITING_APPROVAL with a PRESENTED estimate and one ORDERED part on
    its single QUOTED line — the state from which all three cascade hops fire."""
    set_clock("2026-03-01T09:00:00Z")
    customer = create_customer()
    st = create_service_type(base_price_cents=4000, item_category="SHOE",
                             standard_turnaround_days=3, warranty_days=90)
    tech = create_technician(skills=["SHOE"])
    ticket = create_ticket(customer["id"], assigned_technician_id=tech["id"])
    item = add_item(ticket["id"], item_category="SHOE")
    line = add_service_line(ticket["id"], item["id"], st["id"], tech["id"])
    part = add_part(ticket["id"], line["id"], 800, 5, tech["id"], quantity=1)
    est = create_draft_estimate(ticket["id"], tech["id"])
    est = present_estimate(est["id"], ticket["id"], tech["id"])
    validate_success(api_client.order_part(part["id"], make_technician_headers(tech["id"])), 200)
    return customer, tech, ticket, line, part, est


def test_cancel_cascades_ticket_and_part(api):
    """PRD §3.4: "The ticket's `repair_status` becomes `CANCELLED` and its `version` increments by one."
    PRD §3.4: "First, every parts order of the ticket that is not yet `RECEIVED` transitions to `CANCELLED`."

    Design: Difficulty/transitive_cascade/cancel_cascade_parts_to_lines_to_estimate_depth3
    """
    customer, tech, ticket, line, part, est = _setup_cancellable_with_ordered_part()
    cancelled = validate_success(api.cancel_ticket(ticket["id"], SHOP_MANAGER), 200)
    assert cancelled["repair_status"] == "CANCELLED"
    part_after = validate_success(api.get_parts_order(part["id"], FRONT_DESK), 200)
    assert part_after["status"] == "CANCELLED"


def test_cancel_cascades_line_and_estimate(api):
    """PRD §3.4: "Second, each parts order entering `CANCELLED` as part of this cascade transitions its owning service line (named by the order's `service_line_id`) from `QUOTED` or `COMPLETED` to `VOIDED`."
    PRD §3.4: "Third, each service line entering `VOIDED` causes the ticket's still-open estimate — one whose status is `DRAFT` or `PRESENTED` — to be rejected (moved to `REJECTED`), because the set of lines backing the quote has changed."

    Design: Difficulty/transitive_cascade/cancel_cascade_parts_to_lines_to_estimate_depth3
    """
    customer, tech, ticket, line, part, est = _setup_cancellable_with_ordered_part()
    validate_success(api.cancel_ticket(ticket["id"], SHOP_MANAGER), 200)
    line_after = validate_success(api.get_service_line(line["id"], FRONT_DESK), 200)
    assert line_after["status"] == "VOIDED"
    est_after = validate_success(api.get_estimate(est["id"], FRONT_DESK), 200)
    assert est_after["status"] == "REJECTED"
