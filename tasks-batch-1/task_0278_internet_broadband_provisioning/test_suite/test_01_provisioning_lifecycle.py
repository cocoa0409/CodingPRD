"""Account / order / equipment provisioning lifecycle.

Covers account creation, the activation join cascade, the cyclic equipment
lifecycle, and order-state-machine corner cases.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, TEST_USERS,
    assert_account, assert_equipment_unit,
    create_account_payload,
    set_clock, create_address, create_plan, create_equipment, create_account,
    create_order, get_account_version,
    setup_active_tech_install_account,
    setup_disconnected_account, setup_draft_self_install_order,
)

AGENT = TEST_USERS["provisioning_agent_headers"]
NETOPS = TEST_USERS["network_ops_headers"]


# ===========================================================================
# Queue B — entities: account creation, identity, computed fields
# ===========================================================================
def test_create_account_returns_201_with_system_fields(api):
    """PRD §3.2: "A new account is born in `PENDING` administrative `status` with `service_state` of `PROVISIONING` and `version` 1".

    Design: Corner/entities/create_account_returns_201_with_system_fields
    """
    addr = create_address()
    plan = create_plan()
    resp = api.create_account(
        create_account_payload(addr["id"], plan["id"], "cust-create"), AGENT)
    data = validate_success(resp, expected_status=201)
    assert_account(data)
    assert data["version"] == 1, f"new account version must be 1, got {data['version']}"
    assert data["status"] == "PENDING", f"new account status must be PENDING, got {data['status']}"
    assert data["service_state"] == "PROVISIONING", \
        f"new account service_state must be PROVISIONING, got {data['service_state']}"


def test_get_account_not_found_returns_404(api):
    """PRD §2.9: "the first identifier that does not resolve causes the request to fail with `ERR_NOT_FOUND`."

    Design: Corner/entities/get_account_not_found_returns_404
    """
    resp = api.get_account("00000000-0000-4000-8000-000000000000", AGENT)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


def test_create_account_missing_required_field_returns_invalid_request(api):
    """PRD §3.12: "Request well-formedness is fourth: a malformed body, a missing
    required field, or a non-positive `gb`, `amount_cents`, or `capacity`, or an
    interval whose end is not after its start, yields `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_account_missing_required_field_returns_invalid_request
    """
    addr = create_address()
    # plan_id omitted (required input field per PRD §3.2).
    resp = api.create_account(
        {"service_address_id": addr["id"], "customer_user_id": "cust-x"}, AGENT)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


def test_computed_credit_balance_reflects_issued_credit(api):
    """PRD §3.11: "The account's `credit_balance_cents` is always the sum of the `amount_cents` of that account's un-applied credits."

    Design: Corner/entities/computed_credit_balance_reflects_issued_credit
    """
    addr = create_address()
    plan = create_plan()
    acct = create_account(addr["id"], plan["id"], "cust-cb")
    get_success_data(api.issue_goodwill_credit(acct["id"], {"amount_cents": 500}, AGENT))
    refreshed = validate_success(api.get_account(acct["id"], AGENT))
    assert refreshed["credit_balance_cents"] == 500, \
        f"credit_balance_cents must be 500, got {refreshed['credit_balance_cents']}"


def test_list_accounts_paginated_envelope(api):
    """PRD §2.3: "The pagination fields surfaced in `meta` are `limit`, `offset`, `total_count`, and `has_more`, where `total_count` reflects the full size of the filtered collection and `has_more` indicates whether records remain beyond the current window."

    Design: Corner/entities/list_accounts_paginated_envelope
    """
    addr = create_address()
    plan = create_plan()
    create_account(addr["id"], plan["id"], "cust-l1")
    create_account(addr["id"], plan["id"], "cust-l2")
    data, meta = validate_paginated(
        api.list_accounts(AGENT, params={"service_address_id": addr["id"]}))
    assert meta["total_count"] == 2, f"expected total_count 2, got {meta['total_count']}"
    assert meta["has_more"] is False, f"expected has_more False, got {meta['has_more']}"


# ===========================================================================
# Queue A — transitive_cascade: activate two-hop
# ===========================================================================
def test_activate_order_leases_equipment_and_activates_account(api):
    """PRD §3.2: "activation is the join point: the system selects an `EquipmentUnit` that is `IN_INVENTORY`, assigns it to the order by setting the order's `equipment_unit_id`, transitions that unit from `IN_INVENTORY` to `LEASED` while stamping its `leased_at_iso` to the current instant, and sets the account's `equipment_unit_id` to point at the now-leased unit."
    PRD §3.2: "Activation also drives the account from `PENDING` to `ACTIVE".

    Design: Difficulty/transitive_cascade/activate_two_hop_cascade
    """
    ctx = setup_active_tech_install_account()
    unit = validate_success(api.get_equipment_unit(ctx["equipment"]["id"], AGENT))
    assert unit["status"] == "LEASED", f"unit must be LEASED after activate, got {unit['status']}"
    acct = validate_success(api.get_account(ctx["account"]["id"], AGENT))
    assert acct["status"] == "ACTIVE", f"account must be ACTIVE, got {acct['status']}"


def test_activate_order_opens_exactly_one_billing_cycle(api):
    """PRD §3.2: "a fresh `OPEN` billing cycle is created with `cycle_start_iso` at the current instant and `cycle_end_iso` exactly 30 days later."

    Design: Difficulty/transitive_cascade/activate_two_hop_cascade
    """
    ctx = setup_active_tech_install_account()
    data, meta = validate_paginated(
        api.list_billing_cycles(NETOPS, params={"account_id": ctx["account"]["id"]}))
    open_cycles = [c for c in data if c["billing_state"] == "OPEN"]
    assert len(open_cycles) == 1, f"expected exactly one OPEN cycle, got {len(open_cycles)}"


# ===========================================================================
# Queue A — non_linear_state_machine: equipment cyclic re-lease
# ===========================================================================
def test_equipment_unit_re_leases_to_second_account_after_restock(api):
    """PRD §2.6: "A unit that completes its return and is restocked re-enters inventory and may be leased to a different account, so the same hardware traverses the cycle repeatedly over its service life."

    Design: Difficulty/non_linear_state_machine/equipment_unit_cyclic_release_release
    """
    set_clock("2026-06-01T00:00:00Z")
    addr = create_address()
    plan = create_plan()
    unit = create_equipment()
    # Account A: activate, disconnect, confirm-return, restock.
    acct_a = create_account(addr["id"], plan["id"], "cust-a")
    order_a = create_order(acct_a["id"], plan["id"], install_mode="SELF_INSTALL")
    get_success_data(api.ship_kit(order_a["id"], AGENT))
    get_success_data(api.activate_order(order_a["id"], AGENT))
    v = get_account_version(acct_a["id"])
    get_success_data(api.disconnect_account(acct_a["id"], {"expected_account_version": v}, AGENT))
    get_success_data(api.confirm_return_equipment(unit["id"], AGENT))
    get_success_data(api.restock_equipment(unit["id"], AGENT))
    # Account B: activate — the SAME unit must re-lease.
    acct_b = create_account(addr["id"], plan["id"], "cust-b")
    order_b = create_order(acct_b["id"], plan["id"], install_mode="SELF_INSTALL")
    get_success_data(api.ship_kit(order_b["id"], AGENT))
    get_success_data(api.activate_order(order_b["id"], AGENT))
    final = validate_success(api.get_equipment_unit(unit["id"], AGENT))
    assert final["status"] == "LEASED", \
        f"re-leased unit must be LEASED, got {final['status']}"
    assert final["account_id"] == acct_b["id"], \
        f"re-leased unit must belong to account B, got {final['account_id']}"


def test_equipment_unit_cyclic_returns_to_inventory_on_restock(api):
    """PRD §3.7: "it becomes assignable again only after an explicit restock moves it from `RETURNED` back to `IN_INVENTORY`, closing the cycle so the same hardware can be leased to a new account."

    Design: Difficulty/non_linear_state_machine/equipment_unit_cyclic_release_release
    """
    ctx = setup_disconnected_account()
    unit_id = ctx["equipment"]["id"]
    get_success_data(api.confirm_return_equipment(unit_id, AGENT))
    restocked = validate_success(api.restock_equipment(unit_id, AGENT))
    assert restocked["status"] == "IN_INVENTORY", \
        f"restocked unit must be IN_INVENTORY, got {restocked['status']}"
    assert_equipment_unit(restocked)


# ===========================================================================
# Queue B — endpoints: no equipment available at activation
# ===========================================================================
def test_activate_with_no_equipment_available_rejected(api):
    """PRD §3.2: "If no `IN_INVENTORY` unit is available to assign, activation fails with `ERR_NO_EQUIPMENT_AVAILABLE`."

    Design: Corner/endpoints/no_equipment_available_at_activation
    """
    ctx = setup_draft_self_install_order(with_equipment=False)
    get_success_data(api.ship_kit(ctx["order"]["id"], AGENT))
    resp = api.activate_order(ctx["order"]["id"], AGENT)
    validate_error(resp, ApiErrorId.ERR_NO_EQUIPMENT_AVAILABLE, expected_status=409)


# ===========================================================================
# Queue B — state_machines: order-machine corner cases
# ===========================================================================
def test_ship_kit_on_tech_install_order_rejected(api):
    """PRD §3.2: "shipping a kit requires the order's install mode to be `SELF_INSTALL".
    PRD §3.12: "a target resource not in a state permitting the requested transition yields `ERR_INVALID_STATE`."

    Design: Corner/state_machines/ship_kit_on_tech_install_order_returns_invalid_state
    """
    set_clock("2026-06-01T00:00:00Z")
    addr = create_address()
    plan = create_plan()
    acct = create_account(addr["id"], plan["id"], "cust-sk")
    order = create_order(acct["id"], plan["id"], install_mode="TECH_INSTALL")
    resp = api.ship_kit(order["id"], AGENT)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


def test_cancel_scheduled_order_releases_appointment_and_slot(api):
    """PRD §3.2: "Cancelling a `SCHEDULED` order cascades to its booked appointment: that appointment moves to `CANCELLED`, the appointment's slot decrements its `booked_count` by one, and a slot that had been `FULL` returns to `OPEN`."

    Design: Corner/state_machines/cancel_scheduled_order_releases_appointment_and_slot
    """
    ctx = setup_draft_tech_install_with_booking_capacity1(api)
    get_success_data(api.cancel_order(ctx["order"]["id"], AGENT))
    appt = validate_success(api.get_install_appointment(ctx["appointment"]["id"], AGENT))
    assert appt["status"] == "CANCELLED", f"appointment must be CANCELLED, got {appt['status']}"
    slot = validate_success(api.get_install_slot(ctx["slot"]["id"], AGENT))
    assert slot["booked_count"] == 0, f"slot booked_count must be 0, got {slot['booked_count']}"
    assert slot["status"] == "OPEN", f"slot must return to OPEN, got {slot['status']}"


def setup_draft_tech_install_with_booking_capacity1(api):
    """Local helper: a SCHEDULED order whose one BOOKED appointment fills a
    capacity-1 slot (slot FULL)."""
    from test_helpers import (create_technician, create_slot,
                              create_install_appointment_payload)
    set_clock("2026-06-01T00:00:00Z")
    addr = create_address(self_install_eligible=False)
    plan = create_plan()
    tech = create_technician()
    slot = create_slot(tech["id"], capacity=1)
    acct = create_account(addr["id"], plan["id"], "cust-cxl")
    order = create_order(acct["id"], plan["id"], install_mode="TECH_INSTALL")
    appt = get_success_data(api.create_install_appointment(
        create_install_appointment_payload(order["id"], slot["id"], acct["version"]), AGENT))
    return {"slot": slot, "order": order, "appointment": appt, "account": acct}
