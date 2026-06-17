"""Cascades and conserved-quantity invariants: the pickup-complete depth-3 chain
(stop -> finalize -> invoice -> account ledger), the cancel depth-2 chain
(order -> stop -> route), and the two compensating-invariant pairs
(dispatch+cancel conserves IN_YARD count; issue+void conserves outstanding).
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, TEST_USERS, make_contractor_headers,
)
from test_helpers import fixtures
from test_helpers import factories


YARD_ADMIN = TEST_USERS["yard_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
BILLING = TEST_USERS["billing_clerk_headers"]


# ===========================================================================
# Queue A — transitive_cascade
# ===========================================================================
def test_pickup_complete_cascades_to_invoice_and_account_ledger(api):
    """PRD §3.10: "When the order reaches FINALIZED, an Invoice is created in
    ISSUED status against the order's order_id".
    PRD §3.10: "Issuing the invoice recomputes the account's outstanding_cents
    and available_credit_cents, since the new ISSUED invoice enters the unpaid
    set."
    PRD §3.2: "The outstanding_cents is the sum of total_cents across every
    invoice on the account that is currently in ISSUED status".

    net 6200 -> final 74300; the account outstanding becomes 74300 and
    available 500000 - 74300 = 425700.

    Design: Difficulty/transitive_cascade/pickup_complete_finalize_invoice_account_depth3
    """
    ctx = fixtures.setup_pickup_ready(
        account_overrides={"business_name": "Casc"},
        delivery_date="2026-06-01", pickup_date="2026-06-10",
        estimated_weight_lbs=5000,
        weigh_ticket_overrides={"gross_weight_lbs": 16200, "tare_weight_lbs": 10000},
    )
    validate_success(api.complete_stop(ctx["pu_stop"]["id"], DISPATCHER))

    order = validate_success(api.get_rental_order(ctx["order"]["id"], DISPATCHER))
    assert order["billing_status"] == "FINALIZED"

    invs = validate_success(api.list_order_invoice(ctx["order"]["id"], BILLING))
    assert len(invs) == 1
    assert invs[0]["status"] == "ISSUED"
    assert invs[0]["total_cents"] == 74300

    acct = validate_success(api.get_contractor_account(ctx["account"]["id"], YARD_ADMIN))
    assert acct["outstanding_cents"] == 74300
    assert acct["available_credit_cents"] == 425700


def test_pickup_cascade_issued_invoice_carries_order_account_and_total(api):
    """PRD §3.10: "an Invoice is created in ISSUED status against the order's
    order_id, with the order's account_id copied onto it at finalization."
    PRD §3.10: "Its total_cents is the sum of base_cents, overage_day_cents,
    tonnage_cents, permit_cents, and contamination_cents."

    Also exercises the order-invoice computed-read breadth claim: the issued
    invoice for the completed order carries total_cents 74300, its order_id, and
    the copied account_id.

    Design: Difficulty/transitive_cascade/pickup_complete_finalize_invoice_account_depth3
    """
    ctx = fixtures.setup_completed_order(
        account_overrides={"business_name": "Casc2"},
        delivery_date="2026-06-01", pickup_date="2026-06-10",
        estimated_weight_lbs=5000,
        weigh_ticket_overrides={"gross_weight_lbs": 16200, "tare_weight_lbs": 10000},
    )
    inv = ctx["invoice"]
    assert inv["status"] == "ISSUED"
    assert inv["total_cents"] == 74300
    assert inv["order_id"] == ctx["order"]["id"]
    assert inv["account_id"] == ctx["account"]["id"]


def test_cancel_scheduled_order_cascades_to_stop_and_route(api):
    """PRD §3.8: "If the order was SCHEDULED, its DELIVERY stop is already
    ASSIGNED on a still-PLANNING route: that stop moves to CANCELLED, the
    route's stop_count is recomputed downward and its version increments, the
    committed container is released directly from ASSIGNED -> IN_YARD with its
    current_order_id cleared to null and its version incremented, and the
    order's container_id is cleared to null."

    Cancelling the SCHEDULED order moves the order CANCELLED, the DELIVERY stop
    CANCELLED, the route stop_count 1 -> 0, and releases the container.

    Design: Difficulty/transitive_cascade/cancel_scheduled_order_stop_route_depth2
    """
    sched = fixtures.setup_scheduled_order_planning_route(
        ct_overrides=factories.create_container_type_payload(
            size_code="YD20", base_rate_cents=40000, overage_day_cents=1200,
            included_tonnage_lbs=3000, overage_rate_cents_per_lb=8),
        account_overrides={"business_name": "Cxl"},
        order_overrides={"site_address": "7 Ash"},
    )
    resp = api.cancel_order(sched["order"]["id"], DISPATCHER)
    order = validate_success(resp)
    assert order["logistics_status"] == "CANCELLED"

    stop = validate_success(api.get_service_stop(sched["del_stop"]["id"], DISPATCHER))
    assert stop["status"] == "CANCELLED"

    route = validate_success(api.get_route(sched["route"]["id"], DISPATCHER))
    assert route["stop_count"] == 0

    cont = validate_success(api.get_container(sched["container"]["id"], DISPATCHER))
    assert cont["status"] == "IN_YARD"


def test_cancel_scheduled_order_clears_container_link_and_bumps_route_version(api):
    """PRD §3.8: "the committed container is released directly from ASSIGNED ->
    IN_YARD with its current_order_id cleared to null and its version
    incremented, and the order's container_id is cleared to null."
    PRD §3.8: "the route's stop_count is recomputed downward and its version
    increments".

    The stop-cancellation link drives the route version upward and the released
    container's current_order_id back to null while the order's container_id is
    cleared.

    Design: Difficulty/transitive_cascade/cancel_scheduled_order_stop_route_depth2
    """
    sched = fixtures.setup_scheduled_order_planning_route(
        ct_overrides=factories.create_container_type_payload(
            size_code="YD20", base_rate_cents=40000, overage_day_cents=1200,
            included_tonnage_lbs=3000, overage_rate_cents_per_lb=8),
        account_overrides={"business_name": "Cxl2"},
        order_overrides={"site_address": "7b Ash"},
    )
    route_before = validate_success(api.get_route(sched["route"]["id"], DISPATCHER))
    validate_success(api.cancel_order(sched["order"]["id"], DISPATCHER))

    route_after = validate_success(api.get_route(sched["route"]["id"], DISPATCHER))
    assert route_after["version"] > route_before["version"]

    order = validate_success(api.get_rental_order(sched["order"]["id"], DISPATCHER))
    assert order["container_id"] is None
    cont = validate_success(api.get_container(sched["container"]["id"], DISPATCHER))
    assert cont["current_order_id"] is None


# ===========================================================================
# Queue A — compensating_invariant
# ===========================================================================
def test_dispatch_then_cancel_conserves_in_yard_container_count(api):
    """PRD §3.5: "The container moves IN_YARD -> ASSIGNED, its current_order_id is
    set to the order's id".
    PRD §3.8: "the committed container is released directly from ASSIGNED ->
    IN_YARD with its current_order_id cleared to null".

    dispatch moves the only matching can IN_YARD->ASSIGNED (count 1->0); the
    compensating cancel moves it back ASSIGNED->IN_YARD (count 0->1), so the
    IN_YARD count of that type is unchanged at 1 with current_order_id null.

    Design: Difficulty/compensating_invariant/dispatch_then_cancel_conserves_inyard_count
    """
    booked = fixtures.setup_booked_order_with_container(
        account_overrides={"business_name": "Cons1"},
        order_overrides={"site_address": "16 Oak"},
    )
    ct_id = booked["ct"]["id"]
    cont_id = booked["container"]["id"]
    validate_success(api.dispatch_delivery(
        booked["order"]["id"],
        factories.dispatch_delivery_payload(cont_id, booked["container"]["version"]),
        DISPATCHER,
    ))
    validate_success(api.cancel_order(
        booked["order"]["id"], make_contractor_headers(booked["account"]["id"])))

    cont = validate_success(api.get_container(cont_id, DISPATCHER))
    assert cont["status"] == "IN_YARD"
    assert cont["current_order_id"] is None

    resp = api.list_containers(DISPATCHER, params={"container_type_id": ct_id, "status": "IN_YARD"})
    _data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1, f"expected 1 IN_YARD container of type, got {meta['total_count']}"


def test_dispatch_then_cancel_returns_container_assignable_again(api):
    """PRD §3.5: "The container moves IN_YARD -> ASSIGNED, its current_order_id is
    set to the order's id, and its version increments."
    PRD §3.8: "the committed container is released directly from ASSIGNED ->
    IN_YARD with its current_order_id cleared to null and its version
    incremented".

    The forward+compensating pair leaves the can IN_YARD and re-dispatchable: a
    fresh order can commit the same can again, proving the cancel truly restored
    its assignable state.

    Design: Difficulty/compensating_invariant/dispatch_then_cancel_conserves_inyard_count
    """
    booked = fixtures.setup_booked_order_with_container(
        account_overrides={"business_name": "Cons1b", "credit_limit_cents": 1000000},
        order_overrides={"site_address": "16b Oak"},
    )
    cont_id = booked["container"]["id"]
    validate_success(api.dispatch_delivery(
        booked["order"]["id"],
        factories.dispatch_delivery_payload(cont_id, booked["container"]["version"]),
        DISPATCHER))
    validate_success(api.cancel_order(
        booked["order"]["id"], make_contractor_headers(booked["account"]["id"])))

    # the can is IN_YARD and assignable again — commit it to a fresh order
    released = validate_success(api.get_container(cont_id, DISPATCHER))
    assert released["status"] == "IN_YARD"
    order2 = fixtures.book_order(booked["account"]["id"], booked["ct"]["id"], site_address="16c Oak")
    redispatched = validate_success(api.dispatch_delivery(
        order2["id"],
        factories.dispatch_delivery_payload(cont_id, released["version"]),
        DISPATCHER))
    assert redispatched["logistics_status"] == "SCHEDULED"
    assert redispatched["container_id"] == cont_id


def test_invoice_void_conserves_account_outstanding(api):
    """PRD §3.10: "voiding an invoice likewise requires ISSUED
    (ERR_INVOICE_NOT_ISSUED) and moves it ISSUED -> VOID. Either action removes
    the invoice from the unpaid set, so in both cases the account's
    outstanding_cents and available_credit_cents are recomputed."
    PRD §3.2: "invoices that have been paid or voided are excluded from the
    sum."

    Issuing the invoice on finalize raises outstanding 0 -> 74300; the
    compensating void returns it to 0 and available back to the full limit.

    Design: Difficulty/compensating_invariant/invoice_void_conserves_account_outstanding
    """
    ctx = fixtures.setup_completed_order(
        account_overrides={"business_name": "Cons2", "credit_limit_cents": 500000},
        delivery_date="2026-06-01", pickup_date="2026-06-10",
        estimated_weight_lbs=5000,
        weigh_ticket_overrides={"gross_weight_lbs": 16200, "tare_weight_lbs": 10000},
    )
    inv = ctx["invoice"]
    assert inv["total_cents"] == 74300
    # pre-void outstanding is 74300
    acct = validate_success(api.get_contractor_account(ctx["account"]["id"], YARD_ADMIN))
    assert acct["outstanding_cents"] == 74300

    resp = api.void_invoice(inv["id"], BILLING)
    voided = validate_success(resp)
    assert voided["status"] == "VOID"

    acct = validate_success(api.get_contractor_account(ctx["account"]["id"], YARD_ADMIN))
    assert acct["outstanding_cents"] == 0
    assert acct["available_credit_cents"] == 500000


def test_account_outstanding_excludes_voided_invoices(api):
    """PRD §3.2: "the outstanding_cents is the sum of total_cents across every
    invoice on the account that is currently in ISSUED status; invoices that
    have been paid or voided are excluded from the sum."

    Also exercises the issued-only outstanding-sum breadth claim: after void the
    sole invoice leaves the ISSUED set so outstanding returns to 0.

    Design: Difficulty/compensating_invariant/invoice_void_conserves_account_outstanding
    """
    ctx = fixtures.setup_completed_order(
        account_overrides={"business_name": "OnlyIssued", "credit_limit_cents": 500000},
        delivery_date="2026-06-01", pickup_date="2026-06-10",
        estimated_weight_lbs=5000,
        weigh_ticket_overrides={"gross_weight_lbs": 16200, "tare_weight_lbs": 10000},
    )
    validate_success(api.void_invoice(ctx["invoice"]["id"], BILLING))
    acct = validate_success(api.get_contractor_account(ctx["account"]["id"], YARD_ADMIN))
    assert acct["outstanding_cents"] == 0
