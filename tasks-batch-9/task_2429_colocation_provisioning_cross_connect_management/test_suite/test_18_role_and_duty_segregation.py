"""Role gates and the three structural separations of duty.

Every case below pairs a refusal with the call that the same workflow accepts, so the
refusal is shown to be about who is acting rather than about the request being
malformed, and the refused attempt is shown to have written nothing.
"""

from datetime import datetime, timezone

from test_helpers import assertions as ax, factories as f, fixtures as fx
from test_helpers import (
    ApiErrorId,
    ENGINEER_1,
    ENGINEER_1_ID,
    ENGINEER_2,
    ENGINEER_2_ID,
    FACILITY_MANAGER,
    FACILITY_MANAGER_1_ID,
    SECURITY_OFFICER,
    make_customer_admin_headers,
    make_security_officer_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


# --- local helpers ---------------------------------------------------------


def _instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp regardless of how many fractional digits it
    carries, so an instant is compared as an instant."""
    assert isinstance(value, str), f"expected an ISO 8601 timestamp, got {value!r}"
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def assert_instant_equals(actual, expected: str, label: str) -> None:
    assert actual is not None, f"{label} must be present"
    assert _instant(actual) == _instant(expected), (
        f"{label}: expected {expected}, got {actual}"
    )


# ---------------------------------------------------------------------------
# Authentication and plain role gates
# ---------------------------------------------------------------------------


def test_a_role_name_outside_the_declared_five_is_unauthenticated(
    api, unknown_role_headers, facility_manager_headers
):
    """PRD §2.1: "A request whose `X-User-Role` header is missing, empty, or does not name one of the five declared roles is rejected with `ERR_UNAUTHENTICATED` before the body is parsed, before any path identifier is resolved, and before any concurrency token is compared."
    PRD §2.1: "The five roles are `CustomerAdmin`, `ProvisioningEngineer`, `FacilityManager`, `SecurityOfficer`, and `BillingOperator`."

    Design: Corner/rbac/unknown_role_header_is_unauthenticated
    """
    fx.set_clock(api)
    payload = f.create_row_payload(hall_code="H8", row_code="R1")

    validate_error(
        api.create_row(payload, unknown_role_headers), ApiErrorId.ERR_UNAUTHENTICATED
    )

    rows, meta = validate_paginated(api.list_rows(facility_manager_headers))
    assert rows == [], f"the refused create must have stored nothing, found {rows}"
    assert meta["total_count"] == 0, (
        f"the refused create must have stored nothing, total_count is {meta['total_count']}"
    )


def test_only_the_data_hall_owner_may_create_a_floor_row(
    api, provisioning_engineer_headers, facility_manager_headers
):
    """PRD §2.1: "A `FacilityManager` is the data-hall owner: it creates and re-limits floor rows, approves cross-connect routes and decommissions, and sends proposed routes back for re-routing."
    PRD §3.2: "A `FacilityManager` creates a row with its `hall_code`, a `row_code` that must be unique within that hall, the number of physical cabinet positions in `cabinet_slot_count` (at least one), the `design_density_kw_per_cabinet` figure the row was engineered to (strictly positive), the hard busway limit `max_row_power_kw` (strictly positive), and the sensible cooling capacity serving the row, `cooling_capacity_kw` (strictly positive)."
    PRD §3.2: "A freshly created row reports `row_status` of `OPEN` and every capacity rollup at zero."

    Design: Corner/rbac/provisioning_engineer_cannot_create_a_floor_row
    """
    fx.set_clock(api)
    payload = f.create_row_payload(
        hall_code="H1",
        row_code="R1",
        cabinet_slot_count=10,
        design_density_kw_per_cabinet=25.0,
        max_row_power_kw=200.0,
        cooling_capacity_kw=60.0,
    )

    validate_error(
        api.create_row(payload, provisioning_engineer_headers), ApiErrorId.ERR_UNAUTHORIZED
    )

    row = validate_success(
        api.create_row(payload, facility_manager_headers), expected_status=201
    )
    ax.assert_floor_row(row)
    ax.assert_row_capacity_view(
        row,
        occupied_slot_count=0,
        density_ceiling_kw=0.000,
        allocated_power_kw=0.000,
        cooling_load_kw=0.000,
        energized_cabinet_count=0,
        row_status="OPEN",
    )


def test_energization_is_closed_to_the_billing_role_that_may_still_meter(
    api, billing_operator_headers
):
    """PRD §3.4: "Energization is where the site's scarcity rules concentrate, and it is exclusive to a `ProvisioningEngineer`."
    PRD §3.4: "A `FacilityManager` or a `BillingOperator` appends one interval at a time to a circuit, supplying `interval_start`, `interval_end`, the consumed `kwh` and the observed `peak_kw` for that interval."

    Design: Corner/rbac/billing_operator_cannot_energize_a_power_circuit
    """
    scenario = fx.setup_approved_circuit(
        api,
        contract={"committed_cabinet_count": 1, "power_commit_kw": 20.0},
        cabinet={"cabinet_code": "C01", "rated_power_kw": 20.0},
        circuit={"circuit_code": "A-1", "breaker_amps": 50, "volts": 240},
    )
    row_version = fx.row_version(api, scenario.row_id)

    validate_error(
        api.energize_circuit(
            scenario.circuit_id, {"expected_row_version": row_version}, billing_operator_headers
        ),
        ApiErrorId.ERR_UNAUTHORIZED,
    )

    circuit = fx.read_circuit(api, scenario.circuit_id)
    ax.assert_circuit_power(circuit, status="APPROVED")
    row = fx.read_row(api, scenario.row_id)
    ax.assert_row_capacity_view(row, allocated_power_kw=0.000, cooling_load_kw=0.000)
    ax.assert_version_is(row, row_version, "row")

    # The very same role owns the metering stream on the very same circuit.
    validate_success(
        api.append_meter_reading(
            scenario.circuit_id,
            f.meter_reading_payload(
                "2026-07-20T00:00:00Z", "2026-07-21T00:00:00Z", 120.0, 6.0
            ),
            billing_operator_headers,
        ),
        expected_status=201,
    )


def test_dispatch_is_closed_to_the_data_hall_owner(api, facility_manager_headers):
    """PRD §3.6: "Dispatch is exclusive to a `ProvisioningEngineer`, takes no body fields, and moves `execution_state` from `QUEUED` to `DISPATCHED`."
    PRD §3.6: "On success `dispatched_at` is stamped from the logical clock and `sla_breached` is set true only when `dispatched_at` is strictly later than `response_deadline_at`; a dispatch landing exactly on the deadline instant has met the commitment, not breached it."
    PRD §3.6: "`response_deadline_at` is `authorized_at` advanced by 30 minutes for a `CRITICAL` ticket, by 120 minutes for a `HIGH` ticket, and by 480 minutes — eight hours — for a `STANDARD` ticket."

    Design: Corner/rbac/facility_manager_cannot_dispatch_remote_hands
    """
    scenario = fx.setup_authorized_ticket(api, severity="HIGH")
    ticket_id = scenario.ticket["id"]

    validate_error(
        api.dispatch_ticket(ticket_id, facility_manager_headers), ApiErrorId.ERR_UNAUTHORIZED
    )
    held = fx.read_ticket(api, ticket_id)
    assert held["execution_state"] == "QUEUED", (
        f"the refused dispatch moved execution to {held['execution_state']}"
    )

    dispatched = validate_success(api.dispatch_ticket(ticket_id, ENGINEER_2))
    assert dispatched["execution_state"] == "DISPATCHED", (
        f"execution_state: expected DISPATCHED, got {dispatched['execution_state']}"
    )
    assert_instant_equals(
        dispatched["dispatched_at"], "2026-08-01T00:00:00Z", "ticket.dispatched_at"
    )
    assert_instant_equals(
        dispatched["response_deadline_at"],
        "2026-08-01T02:00:00Z",
        "ticket.response_deadline_at",
    )
    assert dispatched["sla_breached"] is False, (
        "a dispatch two hours ahead of a HIGH deadline has met the commitment"
    )


def test_a_customer_admin_reading_another_customers_contract_is_out_of_scope(api):
    """PRD §2.1: "When `X-User-Role` is `CustomerAdmin`, `X-User-ID` is the `id` of the acting `Customer`; ownership checks on any resource that references a `Customer` compare the resource's owning-customer chain to `X-User-ID`, so a `CustomerAdmin` reading or writing another customer's contract, cabinet, circuit, cross-connect order, ticket, visit or invoice line is rejected with `ERR_CUSTOMER_SCOPE_VIOLATION`."
    PRD §2.1: "That ownership check deliberately runs after existence resolution, so it can compare the loaded row's customer: a `CustomerAdmin` touching a contract that exists but belongs to somebody else receives 403, not 404."

    Design: Corner/rbac/customer_admin_cannot_read_another_customers_contract
    """
    fx.set_clock(api)
    owner = fx.create_customer(api)
    stranger = fx.create_customer(api)
    contract = fx.create_contract(api, owner["id"])

    validate_error(
        api.get_contract(contract["id"], make_customer_admin_headers(stranger["id"])),
        ApiErrorId.ERR_CUSTOMER_SCOPE_VIOLATION,
    )

    mine = validate_success(
        api.get_contract(contract["id"], make_customer_admin_headers(owner["id"]))
    )
    assert mine["id"] == contract["id"], "the owner must read back its own contract"
    assert mine["contract_number"] == contract["contract_number"], (
        f"contract_number: expected {contract['contract_number']}, got {mine['contract_number']}"
    )
    assert mine["status"] == "DRAFT", f"status: expected DRAFT, got {mine['status']}"


def test_a_security_officer_may_authorize_a_remote_hands_ticket(api, security_officer_headers):
    """PRD §3.6: "Authorization is a separate act by a separate person, performed by a `CustomerAdmin` or a `SecurityOfficer`, and names the `authorizing_contact_id` alongside the target `to_state`."
    PRD §3.6: "Authorizing a `PENDING_AUTHORIZATION` ticket stamps `authorized_at` from the logical clock and derives `response_deadline_at` from it, leaving `execution_state` untouched because the dimensions are independent."
    PRD §3.6: "`response_deadline_at` is `authorized_at` advanced by 30 minutes for a `CRITICAL` ticket, by 120 minutes for a `HIGH` ticket, and by 480 minutes — eight hours — for a `STANDARD` ticket."

    Design: Corner/rbac/security_officer_shares_the_ticket_authorization_operation
    """
    scenario = fx.setup_ticket_scenery(api)
    ticket = fx.raise_ticket(api, scenario, severity="CRITICAL")

    authorized = validate_success(
        api.set_ticket_authorization(
            ticket["id"],
            f.state_payload("AUTHORIZED", authorizing_contact_id=scenario.contacts[1]["id"]),
            security_officer_headers,
        )
    )
    assert authorized["authorization_state"] == "AUTHORIZED", (
        f"authorization_state: expected AUTHORIZED, got {authorized['authorization_state']}"
    )
    assert authorized["authorizing_contact_id"] == scenario.contacts[1]["id"], (
        "the authorizing contact must be pinned from the request body"
    )
    assert_instant_equals(
        authorized["authorized_at"], "2026-08-01T00:00:00Z", "ticket.authorized_at"
    )
    assert_instant_equals(
        authorized["response_deadline_at"],
        "2026-08-01T00:30:00Z",
        "ticket.response_deadline_at",
    )
    assert authorized["execution_state"] == "QUEUED", (
        f"the execution dimension is independent; it became {authorized['execution_state']}"
    )


# ---------------------------------------------------------------------------
# Separation one: a ticket may not be self-authorized
# ---------------------------------------------------------------------------


def test_a_ticket_cannot_be_authorized_by_the_user_id_that_created_it(api):
    """PRD §2.5: "The `X-User-ID` authorizing a remote-hands ticket differs from the `X-User-ID` that created it, otherwise `ERR_SELF_AUTHORIZATION_FORBIDDEN` (409)."
    PRD §3.6: "The authorizing contact must belong to the contract's customer and hold the `REMOTE_HANDS` scope, otherwise `ERR_CONTACT_NOT_AUTHORIZED`, and must not be the contact that requested the work; a self-authorization, whether detected through the contact reference or through an `X-User-ID` identical to the ticket's creator, is refused with `ERR_SELF_AUTHORIZATION_FORBIDDEN`."

    Design: Corner/rbac/same_user_id_cannot_create_and_authorize_one_ticket
    """
    scenario = fx.setup_ticket_scenery(api)
    ticket = fx.raise_ticket(api, scenario, severity="STANDARD")
    body = f.state_payload("AUTHORIZED", authorizing_contact_id=scenario.contacts[1]["id"])

    # A permitted role, an eligible contact — but the creator's own staff identifier.
    validate_error(
        api.set_ticket_authorization(
            ticket["id"], body, make_security_officer_headers(ENGINEER_1_ID)
        ),
        ApiErrorId.ERR_SELF_AUTHORIZATION_FORBIDDEN,
    )
    held = fx.read_ticket(api, ticket["id"])
    assert held["authorization_state"] == "PENDING_AUTHORIZATION", (
        f"the refused authorization moved the ticket to {held['authorization_state']}"
    )

    authorized = validate_success(
        api.set_ticket_authorization(ticket["id"], body, SECURITY_OFFICER)
    )
    assert authorized["authorization_state"] == "AUTHORIZED", (
        f"authorization_state: expected AUTHORIZED, got {authorized['authorization_state']}"
    )
    assert_instant_equals(
        authorized["response_deadline_at"],
        "2026-08-01T08:00:00Z",
        "ticket.response_deadline_at",
    )


def test_a_ticket_cannot_be_authorized_by_the_contact_that_requested_it(
    api, security_officer_headers
):
    """PRD §2.9: "A remote-hands ticket may not be authorized by the `X-User-ID` that created it."
    PRD §3.6: "The authorizing contact must belong to the contract's customer and hold the `REMOTE_HANDS` scope, otherwise `ERR_CONTACT_NOT_AUTHORIZED`, and must not be the contact that requested the work; a self-authorization, whether detected through the contact reference or through an `X-User-ID` identical to the ticket's creator, is refused with `ERR_SELF_AUTHORIZATION_FORBIDDEN`."

    Design: Corner/rbac/same_user_id_cannot_create_and_authorize_one_ticket
    """
    scenario = fx.setup_ticket_scenery(api)
    ticket = fx.raise_ticket(api, scenario, severity="STANDARD")

    validate_error(
        api.set_ticket_authorization(
            ticket["id"],
            f.state_payload("AUTHORIZED", authorizing_contact_id=scenario.contacts[0]["id"]),
            security_officer_headers,
        ),
        ApiErrorId.ERR_SELF_AUTHORIZATION_FORBIDDEN,
    )
    held = fx.read_ticket(api, ticket["id"])
    assert held["authorization_state"] == "PENDING_AUTHORIZATION", (
        f"the refused authorization moved the ticket to {held['authorization_state']}"
    )


# ---------------------------------------------------------------------------
# Separation two: an order may not be approved by its creator
# ---------------------------------------------------------------------------


def test_a_cross_connect_order_cannot_be_approved_by_the_engineer_who_raised_it(api):
    """PRD §3.5: "The approving `X-User-ID` must differ from the one that created the order, otherwise `ERR_SEGREGATION_OF_DUTIES`."
    PRD §3.5: "On success `approved_by_user_id` is pinned from the header and the order's `version` increments."
    PRD §3.5: "A `ProvisioningEngineer` then records physical installation, moving `APPROVED` → `INSTALLED` and taking both ports `RESERVED` → `ASSIGNED`."

    Design: Corner/rbac/cross_connect_approval_by_its_own_creator_is_rejected
    """
    scenario = fx.setup_routed_order(api)
    order_id = scenario.orders[0]["id"]

    validate_error(
        api.set_cross_connect_order_state(order_id, f.state_payload("APPROVED"), ENGINEER_1),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
    )
    held = fx.read_order(api, order_id)
    assert held["status"] == "ROUTE_PROPOSED", (
        f"the refused approval moved the order to {held['status']}"
    )

    approved = validate_success(
        api.set_cross_connect_order_state(order_id, f.state_payload("APPROVED"), FACILITY_MANAGER)
    )
    assert approved["status"] == "APPROVED", (
        f"status: expected APPROVED, got {approved['status']}"
    )
    assert approved["approved_by_user_id"] == FACILITY_MANAGER_1_ID, (
        f"approved_by_user_id: expected {FACILITY_MANAGER_1_ID}, "
        f"got {approved['approved_by_user_id']}"
    )

    # The creator is free to drive the later step.
    installed = validate_success(
        api.set_cross_connect_order_state(order_id, f.state_payload("INSTALLED"), ENGINEER_1)
    )
    assert installed["status"] == "INSTALLED", (
        f"status: expected INSTALLED, got {installed['status']}"
    )
    for port in (fx.a_ports(scenario)[0], fx.z_ports(scenario)[0]):
        stored = fx.read_port(api, port["id"])
        assert stored["status"] == "ASSIGNED", (
            f"port {stored['panel_code']}/{stored['port_number']}: expected ASSIGNED, "
            f"got {stored['status']}"
        )


# ---------------------------------------------------------------------------
# Separation three: the two decommission steps need two operators
# ---------------------------------------------------------------------------


def test_the_second_decommission_step_cannot_repeat_the_first_operator(api):
    """PRD §3.8: "Recording the second step is where the two branches join, and it carries an additional separation rule: recording `CABLE_RECLAMATION` requires an `X-User-ID` different from `equipment_removed_by_user_id`, and recording `EQUIPMENT_REMOVAL` requires one different from `cables_reclaimed_by_user_id`, with a violation refused as `ERR_SEGREGATION_OF_DUTIES`."
    PRD §3.8: "Once both steps carry timestamps the order auto-advances to `READY_FOR_RELEASE` within that same request — the join is not a separate call — and the order's `version` increments."
    PRD §2.9: "And the two recorded decommission steps must be recorded by two different operators: whoever records cable reclamation may not be the operator recorded against equipment removal, and vice versa."

    Design: Corner/rbac/both_decommission_steps_recorded_by_one_engineer_are_rejected
    """
    scenario = fx.setup_installed_cabinet(api, cabinet={"cabinet_code": "C01"})
    scenario.contacts.append(fx.create_contact(api, scenario.customer_id))
    order = fx.raise_decommission_order(api, scenario)
    fx.move_decommission(api, order["id"], "APPROVED")
    fx.record_step(api, order["id"], "EQUIPMENT_REMOVAL", ENGINEER_1)

    validate_error(
        api.record_decommission_step(
            order["id"], {"step_code": "CABLE_RECLAMATION"}, ENGINEER_1
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
    )
    held = fx.read_decommission(api, order["id"])
    assert held["status"] == "IN_PROGRESS", (
        f"the refused step moved the order to {held['status']}"
    )
    assert held.get("cables_reclaimed_at") is None, (
        f"the refused step recorded cables_reclaimed_at as {held.get('cables_reclaimed_at')}"
    )
    assert held["equipment_removed_by_user_id"] == ENGINEER_1_ID, (
        f"equipment_removed_by_user_id: expected {ENGINEER_1_ID}, "
        f"got {held['equipment_removed_by_user_id']}"
    )

    joined = validate_success(
        api.record_decommission_step(
            order["id"], {"step_code": "CABLE_RECLAMATION"}, ENGINEER_2
        )
    )
    assert joined["cables_reclaimed_by_user_id"] == ENGINEER_2_ID, (
        f"cables_reclaimed_by_user_id: expected {ENGINEER_2_ID}, "
        f"got {joined['cables_reclaimed_by_user_id']}"
    )
    assert_instant_equals(
        joined["cables_reclaimed_at"], "2026-08-01T00:00:00Z", "order.cables_reclaimed_at"
    )
    assert joined["status"] == "READY_FOR_RELEASE", (
        f"the join happens in the same request; status is {joined['status']}"
    )

    cabinet = fx.read_cabinet(api, scenario.cabinet_id)
    assert cabinet["status"] == "DECOMMISSIONING", (
        f"recording steps does not release the cabinet; it is {cabinet['status']}"
    )
