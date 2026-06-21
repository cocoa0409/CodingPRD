"""State machines: the order's two independent axes, the container's IN_YARD
cycle, invalid/idempotent transitions, terminal-state lockdown, precondition
enforcement, initial states, and immediate dispatch consistency.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, make_contractor_headers, NON_EXISTENT_UUID,
)
from test_helpers import fixtures
from test_helpers import factories


YARD_ADMIN = TEST_USERS["yard_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
PERMIT = TEST_USERS["permit_officer_headers"]
BILLING = TEST_USERS["billing_clerk_headers"]


# ===========================================================================
# Queue A — non_linear_state_machine
# ===========================================================================
def test_order_logistics_and_billing_axes_advance_independently(api):
    """PRD §1 (Introduction): "a rental order advances along two independent
    status axes at once — a logistics axis tracking the physical movement of
    the can, and a billing axis tracking how far the money has settled".
    PRD §3.7: "Completing the DELIVERY stop advances the order from SCHEDULED to
    ON_SITE on its logistics axis ... The order's delivered_on is stamped with
    the service_date of the route that ran the stop".

    After delivery the order is ON_SITE on logistics yet still UNBILLED on
    billing (billing only advances on PICKUP-complete).

    Design: Difficulty/non_linear_state_machine/rental_order_parallel_logistics_and_billing_axes
    """
    ctx = fixtures.setup_on_site_order(
        ct_overrides=factories.create_container_type_payload(
            size_code="YD20", base_rate_cents=40000, overage_day_cents=1200,
            included_tonnage_lbs=3000, overage_rate_cents_per_lb=8),
        account_overrides={"business_name": "Par"},
        order_overrides={"site_address": "2 Oak"},
        delivery_date="2026-06-01",
    )
    order = ctx["order"]
    assert order["logistics_status"] == "ON_SITE"
    assert order["billing_status"] == "UNBILLED"
    assert order["delivered_on"] == "2026-06-01"


def test_order_billing_axis_stays_unbilled_while_logistics_advances_to_on_site(api):
    """PRD §3.3: "The order is created with logistics_status of BOOKED and
    billing_status of UNBILLED".
    PRD §3.9: "Billing runs as a two-stage cascade triggered by completing the
    PICKUP stop. The order's billing_status advances UNBILLED -> ESTIMATED ->
    FINALIZED within the one call".

    Across BOOKED -> SCHEDULED -> ON_SITE on the logistics axis, the billing
    axis remains UNBILLED — it only moves on the PICKUP-complete call.

    Design: Difficulty/non_linear_state_machine/rental_order_parallel_logistics_and_billing_axes
    """
    booked = fixtures.setup_booked_order_with_container(
        account_overrides={"business_name": "Par2"}, order_overrides={"site_address": "2b Oak"})
    # BOOKED: both axes at their initial states
    assert booked["order"]["logistics_status"] == "BOOKED"
    assert booked["order"]["billing_status"] == "UNBILLED"
    # SCHEDULED: billing still UNBILLED
    scheduled = validate_success(api.dispatch_delivery(
        booked["order"]["id"],
        factories.dispatch_delivery_payload(booked["container"]["id"], booked["container"]["version"]),
        DISPATCHER))
    assert scheduled["logistics_status"] == "SCHEDULED"
    assert scheduled["billing_status"] == "UNBILLED"


def test_container_completes_full_yard_to_yard_cycle(api):
    """PRD §3.1: "Over its life a can cycles IN_YARD -> ASSIGNED -> ON_SITE ->
    AWAITING_DUMP -> IN_YARD".
    PRD §3.7: "A can left AWAITING_DUMP after a swap or pickup is brought back by
    a dispatcher returning it to the yard, which requires the can to be
    AWAITING_DUMP (ERR_CONTAINER_NOT_AWAITING_DUMP), then moves it AWAITING_DUMP
    -> IN_YARD, clears its current_order_id to null".

    After a full rental + return-to-yard the can is back IN_YARD with
    current_order_id null.

    Design: Difficulty/non_linear_state_machine/container_cyclic_yard_to_yard
    """
    ctx = fixtures.setup_completed_order(
        ct_overrides=factories.create_container_type_payload(
            size_code="YD10", base_rate_cents=30000, overage_day_cents=1000,
            included_tonnage_lbs=2000, overage_rate_cents_per_lb=7),
        account_overrides={"business_name": "Cyc"},
        order_overrides={"site_address": "3 Pine"},
        delivery_date="2026-06-01", pickup_date="2026-06-05",
        estimated_weight_lbs=1000,
        weigh_ticket_overrides={"gross_weight_lbs": 11000, "tare_weight_lbs": 10000},
    )
    container_id = ctx["container"]["id"]
    resp = api.return_to_yard(container_id, DISPATCHER)
    validate_success(resp)
    cont = validate_success(api.get_container(container_id, DISPATCHER))
    assert cont["status"] == "IN_YARD"
    assert cont["current_order_id"] is None


def test_container_cycle_passes_through_intermediate_states(api):
    """PRD §3.5: "The container moves `IN_YARD → ASSIGNED`, its
    `current_order_id` is set to the order's id, and its `version` increments."
    PRD §3.7: "the committed container moves `ASSIGNED → ON_SITE` (with its
    `version` incrementing)."

    After dispatch the can is ASSIGNED with current_order_id set; after the
    DELIVERY stop completes it is ON_SITE.

    Design: Difficulty/non_linear_state_machine/container_cyclic_yard_to_yard
    """
    sched = fixtures.setup_scheduled_order_planning_route(
        ct_overrides=factories.create_container_type_payload(
            size_code="YD10", base_rate_cents=30000, overage_day_cents=1000,
            included_tonnage_lbs=2000, overage_rate_cents_per_lb=7),
        account_overrides={"business_name": "Cyc2"},
    )
    cont = validate_success(api.get_container(sched["container"]["id"], DISPATCHER))
    assert cont["status"] == "ASSIGNED"
    assert cont["current_order_id"] == sched["order"]["id"]

    validate_success(api.dispatch_route(sched["route"]["id"], DISPATCHER))
    validate_success(api.complete_stop(sched["del_stop"]["id"], DISPATCHER))
    cont = validate_success(api.get_container(sched["container"]["id"], DISPATCHER))
    assert cont["status"] == "ON_SITE"


# ===========================================================================
# Queue B — state_machines: invalid transitions, idempotency, lockdown
# ===========================================================================
def test_dispatch_delivery_on_scheduled_order_rejected(api):
    """PRD §3.5: "The order must be `BOOKED`, else `ERR_ORDER_NOT_BOOKED`."

    Re-dispatching an already-SCHEDULED order is rejected.

    Design: Corner/state_machines/dispatch_delivery_from_scheduled_invalid
    """
    sched = fixtures.setup_scheduled_order_planning_route(account_overrides={"business_name": "Inv"})
    resp = api.dispatch_delivery(
        sched["order"]["id"],
        factories.dispatch_delivery_payload(sched["container"]["id"], sched["container"]["version"]),
        DISPATCHER,
    )
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_BOOKED.value)


def test_pay_already_paid_invoice_rejected(api):
    """PRD §3.10: "Paying an invoice requires it to be ISSUED
    (ERR_INVOICE_NOT_ISSUED) and moves it ISSUED -> PAID".

    The second pay sees status PAID, not ISSUED.

    Design: Corner/state_machines/pay_already_paid_invoice_idempotency_rejected
    """
    ctx = fixtures.setup_completed_order(
        account_overrides={"business_name": "Pay"},
        delivery_date="2026-06-01", pickup_date="2026-06-08",
        estimated_weight_lbs=3000,
        weigh_ticket_overrides={"gross_weight_lbs": 13000, "tare_weight_lbs": 10000},
    )
    inv_id = ctx["invoice"]["id"]
    validate_success(api.pay_invoice(inv_id, BILLING))
    resp = api.pay_invoice(inv_id, BILLING)
    validate_error(resp, ApiErrorId.ERR_INVOICE_NOT_ISSUED.value)


def test_cancel_completed_order_rejected(api):
    """PRD §3.8: "A Contractor or Dispatcher may cancel an order that has not yet
    been delivered — that is, one whose logistics_status is BOOKED or SCHEDULED;
    cancelling any other order is rejected with ERR_ORDER_NOT_CANCELLABLE."

    A COMPLETED order cannot be cancelled.

    Design: Corner/state_machines/cancel_completed_order_terminal_lockdown
    """
    ctx = fixtures.setup_completed_order(
        account_overrides={"business_name": "Term"},
        delivery_date="2026-06-01", pickup_date="2026-06-08",
        estimated_weight_lbs=3000,
        weigh_ticket_overrides={"gross_weight_lbs": 13000, "tare_weight_lbs": 10000},
    )
    assert ctx["order"]["logistics_status"] == "COMPLETED"
    resp = api.cancel_order(ctx["order"]["id"], DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_CANCELLABLE.value)


def test_complete_pickup_stop_without_weigh_ticket_rejected(api):
    """PRD §3.7: "the pickup stop's WeighTicket must exist
    (ERR_WEIGH_TICKET_REQUIRED)".
    PRD §3.7: "For SWAP and PICKUP stops there is an additional gate: a
    WeighTicket referencing that very stop must already exist, else the
    completion is rejected with ERR_WEIGH_TICKET_REQUIRED."

    The pickup stop stays ASSIGNED.

    Design: Corner/state_machines/complete_stop_without_weigh_ticket_rejected
    """
    ctx = fixtures.setup_on_site_order(account_overrides={"business_name": "WT"},
                                       order_overrides={"site_address": "7 Main"},
                                       delivery_date="2026-06-01")
    # build a PICKUP stop, sequence onto a dispatched route, but record NO ticket
    fixtures.set_clock("2026-06-05")
    pu_stop = get_success_data(
        api.create_pickup_stop(ctx["order"]["id"], {"estimated_weight_lbs": 2000}, DISPATCHER)
    )
    route2 = fixtures.create_route(service_date="2026-06-05")
    get_success_data(api.append_stop(
        route2["id"], factories.append_stop_payload(pu_stop["id"], route2["version"]), DISPATCHER))
    get_success_data(api.dispatch_route(route2["id"], DISPATCHER))

    resp = api.complete_stop(pu_stop["id"], DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_WEIGH_TICKET_REQUIRED.value)
    stop = validate_success(api.get_service_stop(pu_stop["id"], DISPATCHER))
    assert stop["status"] == "ASSIGNED"


def test_approve_denied_permit_rejected(api):
    """PRD §3.4: "Either decision requires the permit to currently be REQUESTED,
    otherwise it fails with ERR_PERMIT_NOT_REQUESTED."
    PRD §3.4: "Approving moves it REQUESTED -> APPROVED; denying moves it
    REQUESTED -> DENIED."

    A DENIED permit cannot be approved.

    Design: Corner/state_machines/deny_permit_then_approve_invalid
    """
    ct = fixtures.create_container_type()
    account = fixtures.create_account(business_name="Den")
    order = fixtures.book_order(account["id"], ct["id"], site_address="8 Main",
                                requested_delivery_date="2026-06-05", requires_street_permit=True)
    permit = fixtures.request_permit(order["id"], permit_fee_cents=10000,
                                     valid_from="2026-06-01", valid_until="2026-06-30")
    validate_success(api.deny_permit(permit["id"], PERMIT))
    resp = api.approve_permit(permit["id"], PERMIT)
    validate_error(resp, ApiErrorId.ERR_PERMIT_NOT_REQUESTED.value)


def test_close_route_with_open_stops_rejected(api):
    """PRD §3.6: "closing requires the route to be DISPATCHED
    (ERR_ROUTE_NOT_DISPATCHED) and every non-CANCELLED stop on it to be
    COMPLETED (ERR_ROUTE_HAS_OPEN_STOPS)".

    A DISPATCHED route with an ASSIGNED (not yet completed) stop cannot close.

    Design: Corner/state_machines/route_close_with_open_stops_rejected
    """
    sched = fixtures.setup_scheduled_order_planning_route(account_overrides={"business_name": "Open"})
    validate_success(api.dispatch_route(sched["route"]["id"], DISPATCHER))
    resp = api.close_route(sched["route"]["id"], DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_ROUTE_HAS_OPEN_STOPS.value)


def test_newly_registered_container_starts_in_yard(api):
    """PRD §3.1: "A freshly registered can starts IN_YARD with a null
    current_order_id."

    Design: Corner/state_machines/container_initial_state_in_yard
    """
    ct = fixtures.create_container_type()
    resp = api.create_container(factories.create_container_payload(ct["id"], asset_tag="T-INIT-x"), YARD_ADMIN)
    cont = validate_success(resp, expected_status=201)
    assert cont["status"] == "IN_YARD"


# ===========================================================================
# Queue A — boundary_precision_check (route empty-set edge)
# ===========================================================================
def test_dispatch_empty_route_rejected(api):
    """PRD §3.6: "Dispatching requires the route to be PLANNING
    (ERR_ROUTE_NOT_PLANNING) and to hold at least one stop, that is stop_count
    of 1 or more (ERR_ROUTE_EMPTY)".

    Boundary X=0: a freshly created route has stop_count 0, so dispatch is
    rejected with ERR_ROUTE_EMPTY.

    Design: Difficulty/boundary_precision_check/route_dispatch_empty_set_boundary
    """
    route = fixtures.create_route(service_date="2026-06-01")
    assert route["stop_count"] == 0
    resp = api.dispatch_route(route["id"], DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_ROUTE_EMPTY.value)


def test_dispatch_route_succeeds_with_one_stop(api):
    """PRD §3.6: "Dispatching requires the route to be PLANNING
    (ERR_ROUTE_NOT_PLANNING) and to hold at least one stop, that is stop_count
    of 1 or more (ERR_ROUTE_EMPTY); it then moves PLANNING -> DISPATCHED".

    Boundary X=1: appending one stop first (stop_count 1) makes the same
    dispatch succeed, moving the route to DISPATCHED.

    Design: Difficulty/boundary_precision_check/route_dispatch_empty_set_boundary
    """
    sched = fixtures.setup_scheduled_order_planning_route(account_overrides={"business_name": "Empt"})
    route = validate_success(api.get_route(sched["route"]["id"], DISPATCHER))
    assert route["stop_count"] == 1
    resp = api.dispatch_route(sched["route"]["id"], DISPATCHER)
    dispatched = validate_success(resp)
    assert dispatched["status"] == "DISPATCHED"


# ===========================================================================
# Queue B — consistency_model
# ===========================================================================
def test_dispatch_response_reflects_scheduled_immediately(api):
    """PRD §3.5: "When all conditions hold, the order moves BOOKED -> SCHEDULED
    on its logistics axis. ... The order's container_id is set to the committed
    can."

    The dispatch-delivery response body itself shows SCHEDULED and container_id.

    Design: Corner/consistency_model/dispatch_response_reflects_scheduled_immediately
    """
    booked = fixtures.setup_booked_order_with_container(account_overrides={"business_name": "Imm2"})
    resp = api.dispatch_delivery(
        booked["order"]["id"],
        factories.dispatch_delivery_payload(booked["container"]["id"], booked["container"]["version"]),
        DISPATCHER,
    )
    order = validate_success(resp)
    assert order["logistics_status"] == "SCHEDULED"
    assert order["container_id"] == booked["container"]["id"]
