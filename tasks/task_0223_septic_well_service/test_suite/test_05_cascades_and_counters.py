"""Cascades (account hold -> WO cancel -> route recount; pump complete -> due date ->
reminder) and conserved route counters, plus invoicing/balance reconciliation and
filtered/paginated listings.

Translates queue A `transitive_cascade`, `compensating_invariant`, and queue B
`endpoints` instances.
"""
import pytest
from test_helpers import (
    validate_success, validate_paginated, get_success_data, TEST_USERS,
    make_field_tech_headers,
    create_account, create_site, create_technician, create_route,
    create_service_plan, create_work_order_payload,
    create_completed_work_order, get_work_order, get_route, get_site, get_account,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]


# ─── Difficulty: transitive_cascade ────────────────────

def test_account_hold_cascade_cancel_then_route_recount(api):
    """PRD §3.10: "Putting the account on hold cancels every work order belonging to the
    account's sites whose status is DRAFT, SCHEDULED, or DISPATCHED, driving each to
    CANCELLED. Each of those cancellations, where the order had a route_id, in turn triggers
    that route's counter recompute — its assigned_stop_count and booked_minutes are
    recalculated".

    Design: Difficulty/transitive_cascade/account_hold_cascade_cancel_then_route_recount
    """
    account = create_account()
    site = create_site(account["id"])
    tech = create_technician()
    route = create_route(tech["id"], "2026-06-14")
    wo = get_success_data(api.create_work_order(
        create_work_order_payload(site["id"], "PUMPING", "2026-06-14", 540, estimated_gallons=500),
        DISPATCHER,
    ))
    get_success_data(api.schedule_work_order(wo["id"], {"route_id": route["id"]}, DISPATCHER))
    # Precondition sanity: route counts the one scheduled stop.
    assert get_route(route["id"])["assigned_stop_count"] == 1
    assert get_route(route["id"])["booked_minutes"] == 60

    get_success_data(api.hold_account(account["id"], DISPATCHER))

    wo_after = get_work_order(wo["id"])
    assert wo_after["status"] == "CANCELLED"
    assert wo_after["route_id"] is None
    route_after = get_route(route["id"])
    assert route_after["assigned_stop_count"] == 0
    assert route_after["booked_minutes"] == 0


def test_account_hold_cancels_open_work_order(api):
    """PRD §3.10: "Putting the account on hold cancels every work order belonging to the
    account's sites whose status is DRAFT, SCHEDULED, or DISPATCHED, driving each to
    CANCELLED."

    Design: Difficulty/transitive_cascade/account_hold_cascade_cancel_then_route_recount
    """
    account = create_account()
    site = create_site(account["id"])
    tech = create_technician()
    route = create_route(tech["id"], "2026-06-14")
    wo = get_success_data(api.create_work_order(
        create_work_order_payload(site["id"], "PUMPING", "2026-06-14", 540, estimated_gallons=500),
        DISPATCHER,
    ))
    get_success_data(api.schedule_work_order(wo["id"], {"route_id": route["id"]}, DISPATCHER))
    held = validate_success(api.hold_account(account["id"], DISPATCHER), 200)
    assert held["standing"] == "HOLD"
    assert get_work_order(wo["id"])["status"] == "CANCELLED"


def test_pumping_complete_cascade_due_date_then_reminder(api):
    """PRD §3.7: "First, the site's last_pumped_date is set to the completed order's
    scheduled_date. Then the site's next_pump_due_date is recomputed using the projection
    rule of §3.2 ... That recompute, in turn, emits a Reminder of reminder_type PUMP_DUE
    whose due_date is the freshly computed next_pump_due_date."

    Design: Difficulty/transitive_cascade/pumping_complete_cascade_due_date_then_reminder
    """
    account = create_account()
    site = create_site(account["id"])
    create_service_plan(site["id"], site["version"], frequency_months=36, estimated_gallons=800)
    tech = create_technician()
    route = create_route(tech["id"], "2026-06-15")
    create_completed_work_order(
        site["id"], route["id"], tech["id"], "2026-06-15", 540,
        work_type="PUMPING", complete_payload={"measured_gallons": 900},
    )
    site_after = get_site(site["id"])
    assert site_after["last_pumped_date"][:10] == "2026-06-15"
    assert site_after["next_pump_due_date"][:10] == "2029-06-15"

    data, _ = validate_paginated(api.list_site_reminders(site["id"], DISPATCHER))
    pump_due = [r for r in data if r["reminder_type"] == "PUMP_DUE"]
    assert len(pump_due) == 1
    assert pump_due[0]["due_date"][:10] == "2029-06-15"


def test_pumping_complete_sets_last_pumped_and_due_date(api):
    """PRD §3.7: "the site's last_pumped_date is set to the completed order's
    scheduled_date."
    PRD §3.2: "the due date is the last_pumped_date advanced forward by the active plan's
    frequency_months number of months".

    Design: Difficulty/transitive_cascade/pumping_complete_cascade_due_date_then_reminder
    """
    account = create_account()
    site = create_site(account["id"])
    create_service_plan(site["id"], site["version"], frequency_months=36, estimated_gallons=800)
    tech = create_technician()
    route = create_route(tech["id"], "2026-06-15")
    create_completed_work_order(
        site["id"], route["id"], tech["id"], "2026-06-15", 540,
        work_type="PUMPING", complete_payload={"measured_gallons": 900},
    )
    site_after = get_site(site["id"])
    assert site_after["last_pumped_date"][:10] == "2026-06-15"
    assert site_after["next_pump_due_date"][:10] == "2029-06-15"


# ─── Difficulty: compensating_invariant ────────────────

def test_route_stop_count_conserved_on_schedule_then_cancel(api):
    """PRD §3.4: "The assigned_stop_count is the number of work orders whose route_id is
    this route and whose status is SCHEDULED or DISPATCHED."
    PRD §3.3: "Cancelling from SCHEDULED or DISPATCHED additionally clears the order's
    route_id and technician_id and recomputes the route's assigned_stop_count and
    booked_minutes, since the order has left the counted set."

    Design: Difficulty/compensating_invariant/route_stop_count_conserved_on_schedule_then_cancel
    """
    account = create_account()
    site = create_site(account["id"])
    tech = create_technician()
    route = create_route(tech["id"], "2026-06-22")
    wo = get_success_data(api.create_work_order(
        create_work_order_payload(site["id"], "PUMPING", "2026-06-22", 540, estimated_gallons=500),
        DISPATCHER,
    ))
    get_success_data(api.schedule_work_order(wo["id"], {"route_id": route["id"]}, DISPATCHER))
    assert get_route(route["id"])["assigned_stop_count"] == 1
    get_success_data(api.cancel_work_order(wo["id"], DISPATCHER))
    assert get_route(route["id"])["assigned_stop_count"] == 0
    assert get_work_order(wo["id"])["route_id"] is None


def test_route_stop_count_increments_on_schedule(api):
    """PRD §3.4: "The assigned_stop_count is the number of work orders whose route_id is
    this route and whose status is SCHEDULED or DISPATCHED."
    PRD §3.4: "it opens with status OPEN, an assigned_stop_count of 0".

    Design: Difficulty/compensating_invariant/route_stop_count_conserved_on_schedule_then_cancel
    """
    account = create_account()
    site = create_site(account["id"])
    tech = create_technician()
    route = create_route(tech["id"], "2026-06-22")
    assert route["assigned_stop_count"] == 0
    wo = get_success_data(api.create_work_order(
        create_work_order_payload(site["id"], "PUMPING", "2026-06-22", 540, estimated_gallons=500),
        DISPATCHER,
    ))
    get_success_data(api.schedule_work_order(wo["id"], {"route_id": route["id"]}, DISPATCHER))
    assert get_route(route["id"])["assigned_stop_count"] == 1


def test_route_booked_minutes_conserved_on_schedule_then_complete(api):
    """PRD §3.4: "The booked_minutes is the sum, over that same set, of each order's window
    length (window_end_minute minus window_start_minute)."
    PRD §3.5: "recomputes the route counters since the order has left the counted set".

    Design: Difficulty/compensating_invariant/route_booked_minutes_conserved_on_schedule_then_complete
    """
    account = create_account()
    site = create_site(account["id"])
    tech = create_technician()
    route = create_route(tech["id"], "2026-06-23")
    wo = create_completed_work_order(
        site["id"], route["id"], tech["id"], "2026-06-23", 540,
        work_type="PUMPING", estimated_gallons=500, complete_payload={"measured_gallons": 500},
    )
    assert wo["status"] == "COMPLETED"
    assert get_route(route["id"])["booked_minutes"] == 0


def test_route_booked_minutes_reflects_scheduled_window(api):
    """PRD §3.4: "The booked_minutes is the sum, over that same set, of each order's window
    length (window_end_minute minus window_start_minute)."
    PRD §3.4: "computes window_end_minute as window_start_minute plus the site's
    service_minutes".

    Design: Difficulty/compensating_invariant/route_booked_minutes_conserved_on_schedule_then_complete
    """
    account = create_account()
    site = create_site(account["id"])  # service_minutes=60
    tech = create_technician()
    route = create_route(tech["id"], "2026-06-23")
    wo = get_success_data(api.create_work_order(
        create_work_order_payload(site["id"], "PUMPING", "2026-06-23", 540, estimated_gallons=500),
        DISPATCHER,
    ))
    get_success_data(api.schedule_work_order(wo["id"], {"route_id": route["id"]}, DISPATCHER))
    assert get_route(route["id"])["booked_minutes"] == 60


# ─── Corner: endpoints ─────────────────────────────────

def test_list_work_orders_filtered_by_site_id(api):
    """PRD §3.12: "The work-order listing accepts optional site_id, technician_id, route_id,
    and status filters alongside the limit and offset pagination controls".
    PRD §2.3: "List responses carry the pagination fields limit, offset, total_count, and
    has_more inside the meta object of the envelope."

    Design: Corner/endpoints/list_work_orders_filtered_by_site_id
    """
    account = create_account()
    site = create_site(account["id"])
    get_success_data(api.create_work_order(
        create_work_order_payload(site["id"], "PUMPING", "2026-07-12", 540, estimated_gallons=500),
        DISPATCHER,
    ))
    get_success_data(api.create_work_order(
        create_work_order_payload(site["id"], "REPAIR", "2026-07-12", 700), DISPATCHER
    ))
    data, meta = validate_paginated(api.list_work_orders(DISPATCHER, params={"site_id": site["id"]}))
    assert meta["total_count"] == 2


def test_pagination_limit_offset_on_work_orders(api):
    """PRD §2.3: "The limit parameter caps how many items are returned; it defaults to 10
    when omitted, and is constrained to a minimum of 1 and a maximum of 100."
    PRD §2.3: "List responses carry the pagination fields limit, offset, total_count, and
    has_more inside the meta object of the envelope."

    Design: Corner/endpoints/pagination_limit_offset_on_work_orders
    """
    account = create_account()
    site = create_site(account["id"])
    get_success_data(api.create_work_order(
        create_work_order_payload(site["id"], "PUMPING", "2026-07-13", 540, estimated_gallons=500),
        DISPATCHER,
    ))
    get_success_data(api.create_work_order(
        create_work_order_payload(site["id"], "REPAIR", "2026-07-13", 700), DISPATCHER
    ))
    data, meta = validate_paginated(
        api.list_work_orders(DISPATCHER, params={"site_id": site["id"], "limit": 1, "offset": 0})
    )
    assert len(data) == 1
    assert meta["has_more"] is True
    assert meta["total_count"] == 2


def test_invoice_and_pay_reconcile_account_balance(api):
    """PRD §3.6: "invoicing freezes invoice_total_cents onto the invoice and increases the
    owning account's outstanding_balance_cents by that amount. Recording payment advances
    INVOICED -> PAID and decreases the owning account's outstanding_balance_cents by the
    same invoice_total_cents."

    Design: Corner/endpoints/invoice_and_pay_reconcile_account_balance
    """
    account = create_account()
    site = create_site(account["id"])
    tech = create_technician()
    route = create_route(tech["id"], "2026-07-14")
    wo = create_completed_work_order(
        site["id"], route["id"], tech["id"], "2026-07-14", 540,
        work_type="PUMPING", estimated_gallons=800, complete_payload={"measured_gallons": 800},
    )
    invoiced = validate_success(api.invoice_work_order(wo["id"], DISPATCHER), 200)
    assert invoiced["invoice_total_cents"] == 29000
    assert get_account(account["id"])["outstanding_balance_cents"] == 29000

    paid = validate_success(api.pay_work_order(wo["id"], DISPATCHER), 200)
    assert paid["billing_status"] == "PAID"
    assert get_account(account["id"])["outstanding_balance_cents"] == 0
