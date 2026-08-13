"""Corner queue B — Section 2: state machines (invalid transitions, terminal lockdown, initial state)."""

from test_helpers import (
    api_client,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    create_customer_payload,
    create_tank_site_payload,
    create_tank_payload,
    create_settle_payload,
    create_adjust_payload,
    create_active_customer_with_installed_tank,
    create_customer,
    setup_completed_pickup,
)


def test_customer_activate_from_active_returns_invalid_state(api):
    """PRD §3.1: "the customer must currently be `PROSPECT` (otherwise `ERR_CUSTOMER_NOT_PROSPECT`)".

    Design: Corner/state_machines/customer_activate_from_active_returns_invalid_state
    """
    base = create_active_customer_with_installed_tank()
    resp = api_client.activate_customer(base["customer"]["id"], TEST_USERS["route_planner_headers"])
    validate_error(resp, ApiErrorId.ERR_CUSTOMER_NOT_PROSPECT)


def test_customer_terminated_lockdown(api):
    """PRD §3.1: "Termination (`ACTIVE` → `TERMINATED`, the terminal state)" and "Suspension (`ACTIVE` → `SUSPENDED`) requires an `ACTIVE` customer (otherwise `ERR_CUSTOMER_NOT_ACTIVE`)".

    Design: Corner/state_machines/customer_terminated_lockdown
    """
    base = create_active_customer_with_installed_tank()
    # Terminate
    get_success_data(api_client.terminate_customer(base["customer"]["id"], TEST_USERS["route_planner_headers"]))
    # Suspend on TERMINATED → ERR_CUSTOMER_NOT_ACTIVE
    resp1 = api_client.suspend_customer(base["customer"]["id"], TEST_USERS["route_planner_headers"])
    validate_error(resp1, ApiErrorId.ERR_CUSTOMER_NOT_ACTIVE)
    # Terminate on TERMINATED → ERR_CUSTOMER_NOT_ACTIVE
    resp2 = api_client.terminate_customer(base["customer"]["id"], TEST_USERS["route_planner_headers"])
    validate_error(resp2, ApiErrorId.ERR_CUSTOMER_NOT_ACTIVE)


def test_pickup_ticket_provisional_initial_state(api):
    """PRD §3.4: "a `PickupTicket` is created in `PROVISIONAL` with the full settlement calculation of §3.5".

    Design: Corner/state_machines/pickup_ticket_provisional_initial_state
    """
    ctx = setup_completed_pickup(route_code="PT-INIT", route_eligibility_override=True)
    assert ctx["ticket"]["payment_status"] == "PROVISIONAL"


def test_ticket_settle_on_adjusted_returns_invalid_state(api):
    """PRD §3.6: "Settling a ticket (`PROVISIONAL` → `SETTLED`) requires the ticket to be `PROVISIONAL` (otherwise `ERR_TICKET_NOT_PROVISIONAL`)" and "Adjustment lands the ticket in `ADJUSTED`, the only truly terminal payment state."

    Design: Corner/state_machines/ticket_settle_on_adjusted_returns_invalid_state
    """
    ctx = setup_completed_pickup(
        credit_terms="NET30", route_eligibility_override=True, route_code="ADJ-LOCK",
    )
    api_client.dispute_pickup_ticket(ctx["ticket"]["id"], TEST_USERS["settlement_clerk_headers"])
    api_client.adjust_pickup_ticket(
        ctx["ticket"]["id"],
        create_adjust_payload(corrected_metered_volume_gallons=80),
        TEST_USERS["settlement_clerk_headers"],
    )
    cust_now = get_success_data(api_client.get_customer(ctx["customer"]["id"], TEST_USERS["settlement_clerk_headers"]))
    resp = api_client.settle_pickup_ticket(
        ctx["ticket"]["id"],
        create_settle_payload(cust_now["version"]),
        TEST_USERS["settlement_clerk_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_TICKET_NOT_PROVISIONAL)
