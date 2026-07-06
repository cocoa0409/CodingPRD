"""Ticket workflows: parallel payment/fulfillment dimensions, will-call pickup,
hold sweeps, inventory recomputation, and listing.
"""
from test_helpers import (
    get_success_data, validate_success, validate_error, validate_paginated,
    ApiErrorId,
    TEST_USERS, make_patron_headers,
)
import test_helpers as th

ADMIN = TEST_USERS["season_admin_headers"]
AGENT = TEST_USERS["box_office_agent_headers"]


# ==========================================================================
# Difficulty/non_linear_state_machine/ticket_parallel_payment_and_fulfillment_dimensions
# ==========================================================================
def test_pay_advances_payment_axis_to_paid(api):
    """PRD §3.5: "Paying for a ticket, an action a `BoxOfficeAgent` or `Patron`
    may take, advances `fulfillment_status` from `HELD` to `ISSUED` while
    independently moving `payment_status` from `UNPAID` to `PAID`".

    Design: Difficulty/non_linear_state_machine/ticket_parallel_payment_and_fulfillment_dimensions
    """
    ctx = th.setup_on_sale_performance(seats=[{"price_tier": "STANDARD", "row_label": "E"}])
    patron = th.create_patron(email="pay1@example.com")
    seat = ctx["seats"][0]
    ticket = th.hold_single_ticket(ctx["performance"]["id"], seat["id"], patron["id"],
                                   ctx["performance_version"])
    data = validate_success(api.pay_ticket(ticket["id"], make_patron_headers(patron["id"])), 200)
    assert data["payment_status"] == "PAID", f"payment axis should be PAID, got {data['payment_status']}"


def test_pay_advances_fulfillment_axis_to_issued(api):
    """PRD §3.5: "Paying for a ticket ... advances `fulfillment_status` from
    `HELD` to `ISSUED` while independently moving `payment_status` from `UNPAID`
    to `PAID`".

    The combined (PAID, ISSUED) state is reached by one trigger acting on two
    independent axes.

    Design: Difficulty/non_linear_state_machine/ticket_parallel_payment_and_fulfillment_dimensions
    """
    ctx = th.setup_on_sale_performance(seats=[{"price_tier": "STANDARD", "row_label": "E"}])
    patron = th.create_patron(email="pay2@example.com")
    seat = ctx["seats"][0]
    ticket = th.hold_single_ticket(ctx["performance"]["id"], seat["id"], patron["id"],
                                   ctx["performance_version"])
    assert ticket["fulfillment_status"] == "HELD"
    assert ticket["payment_status"] == "UNPAID"
    data = validate_success(api.pay_ticket(ticket["id"], make_patron_headers(patron["id"])), 200)
    assert data["fulfillment_status"] == "ISSUED", (
        f"fulfillment axis should be ISSUED, got {data['fulfillment_status']}")


# ==========================================================================
# Corner/state_machines/will_call_pickup_success_before_cutoff
# ==========================================================================
def test_will_call_pickup_before_cutoff_collects(api):
    """PRD §3.5: "Will-call pickup is a `BoxOfficeAgent` action that advances a
    ticket from `ISSUED` to `COLLECTED`; it requires the ticket to be `PAID` and
    requires the logical clock to be strictly earlier than `will_call_cutoff_minutes`
    before curtain — that is, the clock must be earlier than the curtain time minus
    the cutoff (otherwise `ERR_WILL_CALL_CLOSED`)."

    With curtain 19:30 and cutoff 30 min (cutoff instant 19:00), pickup at 18:00
    collects the ticket.

    Design: Corner/state_machines/will_call_pickup_success_before_cutoff
    """
    ctx = th.setup_paid_single_ticket(will_call_cutoff_minutes=30,
                                      starts_at="2026-07-01T19:30:00Z")
    th.set_clock("2026-07-01T18:00:00Z")
    data = validate_success(api.will_call_pickup(ctx["ticket"]["id"], AGENT), 200)
    assert data["fulfillment_status"] == "COLLECTED"


# ==========================================================================
# Corner/validations/will_call_pickup_inside_cutoff_rejected
# ==========================================================================
def test_will_call_pickup_inside_cutoff_rejected(api):
    """PRD §3.5: "requires the logical clock to be strictly earlier than
    `will_call_cutoff_minutes` before curtain — that is, the clock must be earlier
    than the curtain time minus the cutoff (otherwise `ERR_WILL_CALL_CLOSED`)."

    Pickup at 19:15, inside the 30-min cutoff before the 19:30 curtain (cutoff
    instant 19:00), is rejected with ERR_WILL_CALL_CLOSED.

    Design: Corner/validations/will_call_pickup_inside_cutoff_rejected
    """
    ctx = th.setup_paid_single_ticket(will_call_cutoff_minutes=30,
                                      starts_at="2026-07-01T19:30:00Z")
    th.set_clock("2026-07-01T19:15:00Z")
    validate_error(api.will_call_pickup(ctx["ticket"]["id"], AGENT),
                   ApiErrorId.ERR_WILL_CALL_CLOSED.value)


# ==========================================================================
# Corner/state_machines/ticket_pay_twice_idempotency_rejected
# ==========================================================================
def test_pay_already_paid_ticket_rejected(api):
    """PRD §3.5: "it is permitted only when the ticket is currently `UNPAID` and
    the bound performance is `ON_SALE`".

    Paying an already-PAID/ISSUED ticket again is rejected with ERR_INVALID_STATE.

    Design: Corner/state_machines/ticket_pay_twice_idempotency_rejected
    """
    ctx = th.setup_paid_single_ticket()
    ph = make_patron_headers(ctx["patron"]["id"])
    validate_error(api.pay_ticket(ctx["ticket"]["id"], ph), ApiErrorId.ERR_INVALID_STATE.value)


# ==========================================================================
# Corner/cross_cutting_complexity_layers/hold_expiry_sweep_voids_unpaid_ticket
# ==========================================================================
def test_sweep_voids_expired_unpaid_hold_and_frees_seat(api):
    """PRD §3.5: "The administrative sweep capability scans every `HELD` ticket
    whose `hold_expires_at` is at or before the current logical clock and whose
    `payment_status` is `UNPAID`, moves each to `VOID` fulfillment, recomputes the
    affected performances' inventory, and reports the swept ticket identifiers as
    `swept_ticket_ids`."

    Design: Corner/cross_cutting_complexity_layers/hold_expiry_sweep_voids_unpaid_ticket
    """
    ctx = th.setup_on_sale_performance(seats=[{"price_tier": "STANDARD", "row_label": "AE"}])
    patron = th.create_patron(email="sweep@example.com")
    seat = ctx["seats"][0]
    ticket = th.hold_single_ticket(ctx["performance"]["id"], seat["id"], patron["id"],
                                   ctx["performance_version"])
    th.set_clock("2026-06-30T00:00:00Z")
    get_success_data(api.sweep_holds(ADMIN))
    swept = get_success_data(api.get_ticket(ticket["id"], ADMIN))
    assert swept["fulfillment_status"] == "VOID"
    perf = get_success_data(api.get_performance(ctx["performance"]["id"], AGENT))
    assert perf["available_seat_count"] == 1, (
        f"freed seat should restore availability to 1, got {perf['available_seat_count']}")


# ==========================================================================
# Corner/consistency_model/performance_inventory_immediate_in_same_response
# ==========================================================================
def test_hold_reflects_inventory_immediately(api):
    """PRD §2.8: "The system reconciles these derived figures and parent-child
    states immediately and synchronously as part of the triggering request; there
    is no deferred or eventual settling."
    PRD §2.8: "`held_seat_count` is the number of tickets there in `HELD`
    fulfillment ... `available_seat_count` is the performance `capacity` minus
    `held_seat_count` minus `sold_seat_count`".

    Design: Corner/consistency_model/performance_inventory_immediate_in_same_response
    """
    ctx = th.setup_on_sale_performance(seats=[{"price_tier": "STANDARD", "row_label": "AF"}])
    patron = th.create_patron(email="imm@example.com")
    seat = ctx["seats"][0]
    th.hold_single_ticket(ctx["performance"]["id"], seat["id"], patron["id"],
                          ctx["performance_version"])
    perf = get_success_data(api.get_performance(ctx["performance"]["id"], AGENT))
    assert perf["held_seat_count"] == 1
    assert perf["available_seat_count"] == 0


# ==========================================================================
# Corner/calculations/gross_sales_aggregation_over_paid_tickets
# ==========================================================================
def test_gross_sales_counts_only_paid_tickets(api):
    """PRD §2.8: "`gross_sales_cents` is the sum of `price_cents` over all tickets
    on the performance whose `payment_status` is `PAID`."
    PRD §2.8: "`sold_seat_count` is the number in `ISSUED` or `COLLECTED`
    fulfillment".

    One PAID STANDARD ticket at 6000 yields gross_sales_cents=6000, sold=1, while
    a still-HELD ticket contributes nothing and held=1.

    Design: Corner/calculations/gross_sales_aggregation_over_paid_tickets
    """
    ctx = th.setup_on_sale_performance(
        seats=[{"price_tier": "STANDARD", "row_label": "U", "seat_number": 1},
               {"price_tier": "STANDARD", "row_label": "U", "seat_number": 2}],
        demand_multiplier=1.0)
    patron = th.create_patron(email="gross@example.com")
    ph = make_patron_headers(patron["id"])
    seat1, seat2 = ctx["seats"]
    t1 = th.hold_single_ticket(ctx["performance"]["id"], seat1["id"], patron["id"],
                               ctx["performance_version"], headers=ph)
    get_success_data(api.pay_ticket(t1["id"], ph))
    pv1 = th.get_performance_version(ctx["performance"]["id"])
    th.hold_single_ticket(ctx["performance"]["id"], seat2["id"], patron["id"], pv1, headers=ph)

    perf = get_success_data(api.get_performance(ctx["performance"]["id"], AGENT))
    assert perf["gross_sales_cents"] == 6000, f"expected 6000, got {perf['gross_sales_cents']}"
    assert perf["sold_seat_count"] == 1
    assert perf["held_seat_count"] == 1


# ==========================================================================
# Corner/endpoints/list_tickets_filtered_by_performance_paginated
# ==========================================================================
def test_list_tickets_filtered_by_performance(api):
    """PRD §2.3: "Each list response carries `limit`, `offset`, `total_count`, and
    `has_more` inside the `meta` object of the envelope."

    GET /tickets?performance_id=... returns only that performance's tickets as an
    array with total_count and has_more present.

    Design: Corner/endpoints/list_tickets_filtered_by_performance_paginated
    """
    ctx = th.setup_on_sale_performance(seats=[{"price_tier": "STANDARD", "row_label": "AB"}])
    patron = th.create_patron(email="listt@example.com")
    seat = ctx["seats"][0]
    th.hold_single_ticket(ctx["performance"]["id"], seat["id"], patron["id"],
                          ctx["performance_version"])
    resp = api.list_tickets(AGENT, params={"performance_id": ctx["performance"]["id"]})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1, f"expected total_count 1, got {meta['total_count']}"
    assert meta["has_more"] is False
    assert len(data) == 1
