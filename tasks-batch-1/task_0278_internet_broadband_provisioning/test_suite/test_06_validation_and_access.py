"""Serviceability / speed gates, validation-priority conflicts, uniqueness,
plan-change, account state-machine corner cases, and role-based access control.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, build_customer_headers,
    create_service_plan_payload, create_equipment_unit_payload,
    create_install_appointment_payload, create_account_payload,
    set_clock, create_address, create_plan, create_technician,
    create_slot, create_account, create_order, get_account_version,
    setup_active_self_install_account, setup_disconnected_account,
)

AGENT = TEST_USERS["provisioning_agent_headers"]
NETOPS = TEST_USERS["network_ops_headers"]
DISPATCH = TEST_USERS["dispatcher_headers"]


# ===========================================================================
# Queue A — cross_entity_state_dependency: booking needs serviceable address
# ===========================================================================
def test_booking_against_not_serviceable_address_rejected(api):
    """PRD §2.5: "The first gate requires the target address's `coverage_status` to be exactly `SERVICEABLE`; any other coverage status fails this gate with `ERR_ADDRESS_NOT_SERVICEABLE`."

    Design: Difficulty/cross_entity_state_dependency/order_schedule_depends_on_address_serviceable
    """
    set_clock("2026-06-01T00:00:00Z")
    addr = create_address(coverage_status="NOT_SERVICEABLE",
                          technology="FIXED_WIRELESS", max_serviceable_mbps=100,
                          self_install_eligible=False)
    plan = create_plan(download_mbps=50, throttled_mbps=10, included_gb=300,
                       monthly_fee_cents=4000)
    tech = create_technician()
    slot = create_slot(tech["id"], capacity=2)
    acct = create_account(addr["id"], plan["id"], "cust-edge")
    order = create_order(acct["id"], plan["id"], install_mode="TECH_INSTALL")
    resp = api.create_install_appointment(
        create_install_appointment_payload(order["id"], slot["id"], acct["version"]), AGENT)
    validate_error(resp, ApiErrorId.ERR_ADDRESS_NOT_SERVICEABLE, expected_status=409)
    order_after = validate_success(api.get_service_order(order["id"], AGENT))
    assert order_after["status"] == "DRAFT", \
        f"order must remain DRAFT, got {order_after['status']}"


def test_booking_against_pre_order_address_rejected(api):
    """PRD §2.5: "The first gate requires the target address's `coverage_status` to be exactly `SERVICEABLE`; any other coverage status fails this gate with `ERR_ADDRESS_NOT_SERVICEABLE`."

    A PRE_ORDER address is "any other coverage status" and also fails the gate.

    Design: Difficulty/cross_entity_state_dependency/order_schedule_depends_on_address_serviceable
    """
    set_clock("2026-06-01T00:00:00Z")
    addr = create_address(coverage_status="PRE_ORDER", self_install_eligible=False)
    plan = create_plan()
    tech = create_technician()
    slot = create_slot(tech["id"], capacity=2)
    acct = create_account(addr["id"], plan["id"], "cust-pre")
    order = create_order(acct["id"], plan["id"], install_mode="TECH_INSTALL")
    resp = api.create_install_appointment(
        create_install_appointment_payload(order["id"], slot["id"], acct["version"]), AGENT)
    validate_error(resp, ApiErrorId.ERR_ADDRESS_NOT_SERVICEABLE, expected_status=409)


# ===========================================================================
# Queue A — priority_pair_validation_conflict: speed (p8) beats slot capacity (p10)
# ===========================================================================
def test_speed_violation_beats_slot_capacity(api):
    """PRD §3.12: "The domain-specific business checks follow in their own order — serviceability before speed, then self-install eligibility, then slot capacity, then technician double-booking".

    A booking that violates BOTH speed (plan exceeds plant) and slot capacity
    reports the speed error, which is checked first.

    Design: Difficulty/priority_pair_validation_conflict/speed_vs_slot_capacity_priority
    """
    set_clock("2026-06-01T00:00:00Z")
    addr = create_address(technology="DSL", max_serviceable_mbps=300,
                          self_install_eligible=False)
    fast_plan = create_plan(tier="GIG", download_mbps=500, included_gb=1000)
    slow_plan = create_plan(tier="BASIC", download_mbps=200, throttled_mbps=25,
                            included_gb=500, monthly_fee_cents=5000)
    tech = create_technician()
    slot = create_slot(tech["id"], capacity=1)
    # Fill the capacity-1 slot with a serviceable (slow-plan) booking.
    filler = create_account(addr["id"], slow_plan["id"], "cust-filler")
    filler_order = create_order(filler["id"], slow_plan["id"], install_mode="TECH_INSTALL")
    get_success_data(api.create_install_appointment(
        create_install_appointment_payload(filler_order["id"], slot["id"], filler["version"],
                                            start_iso="2026-06-02T09:00:00Z",
                                            end_iso="2026-06-02T10:00:00Z"), AGENT))
    # Conflicting booking: fast plan (exceeds 300 plant) AND slot already full.
    conf = create_account(addr["id"], fast_plan["id"], "cust-conf")
    conf_order = create_order(conf["id"], fast_plan["id"], install_mode="TECH_INSTALL")
    resp = api.create_install_appointment(
        create_install_appointment_payload(conf_order["id"], slot["id"], conf["version"],
                                            start_iso="2026-06-02T11:00:00Z",
                                            end_iso="2026-06-02T12:00:00Z"), AGENT)
    validate_error(resp, ApiErrorId.ERR_PLAN_EXCEEDS_SERVICEABLE_SPEED, expected_status=409)


def test_speed_gate_fires_before_any_booking_is_consumed(api):
    """PRD §2.5: "a plan whose download speed exceeds the plant's ceiling by even one megabit per second fails with `ERR_PLAN_EXCEEDS_SERVICEABLE_SPEED`."
    PRD §3.12: "serviceability before speed, then self-install eligibility, then slot capacity".

    Because the speed gate (checked before slot capacity) rejects the request,
    the order stays DRAFT and the full slot's booked_count is untouched.

    Design: Difficulty/priority_pair_validation_conflict/speed_vs_slot_capacity_priority
    """
    set_clock("2026-06-01T00:00:00Z")
    addr = create_address(technology="DSL", max_serviceable_mbps=300,
                          self_install_eligible=False)
    fast_plan = create_plan(tier="GIG", download_mbps=500, included_gb=1000)
    slow_plan = create_plan(tier="BASIC", download_mbps=200, throttled_mbps=25,
                            included_gb=500, monthly_fee_cents=5000)
    tech = create_technician()
    slot = create_slot(tech["id"], capacity=1)
    filler = create_account(addr["id"], slow_plan["id"], "cust-filler2")
    filler_order = create_order(filler["id"], slow_plan["id"], install_mode="TECH_INSTALL")
    get_success_data(api.create_install_appointment(
        create_install_appointment_payload(filler_order["id"], slot["id"], filler["version"],
                                            start_iso="2026-06-02T09:00:00Z",
                                            end_iso="2026-06-02T10:00:00Z"), AGENT))
    conf = create_account(addr["id"], fast_plan["id"], "cust-conf2")
    conf_order = create_order(conf["id"], fast_plan["id"], install_mode="TECH_INSTALL")
    resp = api.create_install_appointment(
        create_install_appointment_payload(conf_order["id"], slot["id"], conf["version"],
                                            start_iso="2026-06-02T11:00:00Z",
                                            end_iso="2026-06-02T12:00:00Z"), AGENT)
    validate_error(resp, ApiErrorId.ERR_PLAN_EXCEEDS_SERVICEABLE_SPEED, expected_status=409)
    order_after = validate_success(api.get_service_order(conf_order["id"], AGENT))
    assert order_after["status"] == "DRAFT", \
        f"rejected order must remain DRAFT, got {order_after['status']}"
    slot_after = validate_success(api.get_install_slot(slot["id"], AGENT))
    assert slot_after["booked_count"] == 1, \
        f"slot booked_count must stay 1, got {slot_after['booked_count']}"


# ===========================================================================
# Queue A — priority_pair_validation_conflict: state (p5) beats OCC (p16)
# ===========================================================================
def test_state_violation_beats_stale_version(api):
    """PRD §3.12: "State legality is fifth: a target resource not in a state permitting the requested transition yields `ERR_INVALID_STATE`."
    PRD §3.12: "The optimistic-concurrency check on `expected_account_version`, when it applies, is evaluated within this domain band".

    A disconnect on an already-DISCONNECTED account with a stale version reports
    the state error, which is checked ahead of the OCC band.

    Design: Difficulty/priority_pair_validation_conflict/state_vs_occ_priority
    """
    ctx = setup_disconnected_account()
    # The pre-disconnect version is now stale (disconnect advanced it), and the
    # account is already DISCONNECTED — both the state and OCC guards would fire.
    stale_v = ctx["version_before_disconnect"]
    resp = api.disconnect_account(
        ctx["account"]["id"], {"expected_account_version": stale_v}, AGENT)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


def test_disconnect_on_disconnected_account_reports_state_not_occ(api):
    """PRD §3.12: "State legality is fifth: a target resource not in a state permitting the requested transition yields `ERR_INVALID_STATE`."

    Even when the supplied version matches the account's CURRENT (post-disconnect)
    version, a disconnect on a terminal DISCONNECTED account is rejected on the
    state check (the OCC check would have passed), confirming state precedes OCC.

    Design: Difficulty/priority_pair_validation_conflict/state_vs_occ_priority
    """
    ctx = setup_disconnected_account()
    current_v = get_account_version(ctx["account"]["id"])
    resp = api.disconnect_account(
        ctx["account"]["id"], {"expected_account_version": current_v}, AGENT)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


# ===========================================================================
# Queue B — entities: uniqueness constraints
# ===========================================================================
def test_duplicate_plan_code_rejected(api):
    """PRD §2.10: "A `ServicePlan` carries a `code` that must be unique across all plans; creating a plan whose code is already in use is rejected with `ERR_DUPLICATE_PLAN_CODE`."

    Design: Corner/entities/duplicate_plan_code_rejected
    """
    get_success_data(api.create_service_plan(
        create_service_plan_payload(code="DUP-CODE-1"), AGENT))
    resp = api.create_service_plan(
        create_service_plan_payload(code="DUP-CODE-1", tier="BASIC"), AGENT)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_PLAN_CODE, expected_status=409)


def test_duplicate_equipment_serial_rejected(api):
    """PRD §2.10: "An `EquipmentUnit` carries a hardware `serial` that must be unique across all equipment units; creating a unit whose serial already exists is rejected with `ERR_DUPLICATE_SERIAL`."

    Design: Corner/entities/duplicate_equipment_serial_rejected
    """
    get_success_data(api.create_equipment_unit(
        create_equipment_unit_payload(serial="DUP-SERIAL-1"), AGENT))
    resp = api.create_equipment_unit(
        create_equipment_unit_payload(serial="DUP-SERIAL-1", kind="ROUTER"), AGENT)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_SERIAL, expected_status=409)


# ===========================================================================
# Queue B — endpoints: change-plan updates plan and bumps version
# ===========================================================================
def test_change_plan_updates_plan_and_bumps_version(api):
    """PRD §3.3: "Once an account is `ACTIVE`, a `ProvisioningAgent` may change its provisioned plan. A plan change names the `new_plan_id` to switch to and carries `expected_account_version` for the concurrency guard described in §2.11; on success the account's `plan_id` is updated and its `version` increments by one."

    Design: Corner/endpoints/change_plan_updates_plan_and_bumps_version
    """
    # change-plan is gated on ACTIVE (PRD §3.3); activate first.
    ctx = setup_active_self_install_account(
        plan_overrides={"download_mbps": 500},
        address_overrides={"max_serviceable_mbps": 1000})
    # A second serviceable plan B (download 900 <= plant ceiling 1000).
    plan_b = create_plan(tier="GIG", download_mbps=900, throttled_mbps=90,
                         included_gb=2000, monthly_fee_cents=11999)
    before_v = get_account_version(ctx["account"]["id"])
    updated = validate_success(api.change_plan(
        ctx["account"]["id"],
        {"new_plan_id": plan_b["id"], "expected_account_version": before_v}, AGENT))
    assert updated["plan_id"] == plan_b["id"], \
        f"plan_id must be plan B, got {updated['plan_id']}"
    assert updated["version"] == before_v + 1, \
        f"version must increment by one to {before_v + 1}, got {updated['version']}"


# ===========================================================================
# Queue B — state_machines: account-machine corner cases
# ===========================================================================
def test_resume_active_account_rejected(api):
    """PRD §3.3: "Both actions are agent-driven and require the account to be in the appropriate originating administrative state."
    PRD §3.12: "a target resource not in a state permitting the requested transition yields `ERR_INVALID_STATE`."

    Resuming an ACTIVE (never-suspended) account is rejected.

    Design: Corner/state_machines/resume_from_active_returns_invalid_state
    """
    ctx = setup_active_self_install_account()
    resp = api.resume_account(ctx["account"]["id"], AGENT)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
    acct = validate_success(api.get_account(ctx["account"]["id"], AGENT))
    assert acct["status"] == "ACTIVE", f"account must stay ACTIVE, got {acct['status']}"


def test_suspend_disconnected_account_rejected(api):
    """PRD §3.3: "Suspending an `ACTIVE` account moves its `status` to `SUSPENDED".
    PRD §3.12: "a target resource not in a state permitting the requested transition yields `ERR_INVALID_STATE`."

    A terminal DISCONNECTED account cannot be suspended.

    Design: Corner/state_machines/terminal_disconnected_account_cannot_suspend
    """
    ctx = setup_disconnected_account()
    resp = api.suspend_account(ctx["account"]["id"], AGENT)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


# ===========================================================================
# Queue B — validations: self-install eligibility
# ===========================================================================
def test_ship_kit_on_ineligible_address_rejected(api):
    """PRD §3.2: "Requesting a kit when the address is not self-install eligible is rejected with `ERR_SELF_INSTALL_NOT_ELIGIBLE`."

    Design: Corner/validations/self_install_not_eligible_rejected
    """
    set_clock("2026-06-01T00:00:00Z")
    addr = create_address(self_install_eligible=False)
    plan = create_plan()
    acct = create_account(addr["id"], plan["id"], "cust-sie")
    order = create_order(acct["id"], plan["id"], install_mode="SELF_INSTALL")
    resp = api.ship_kit(order["id"], AGENT)
    validate_error(resp, ApiErrorId.ERR_SELF_INSTALL_NOT_ELIGIBLE, expected_status=409)


# ===========================================================================
# Queue B — rbac: peer-role access control
# ===========================================================================
def test_customer_cannot_close_billing_cycle(api):
    """PRD §2.1: "When a role is well-formed and recognized but is not permitted to invoke the requested operation, the request is rejected with `ERR_FORBIDDEN_FOR_ROLE`."

    Closing a billing cycle is a NetworkOps action; a Customer is forbidden.

    Design: Corner/rbac/customer_cannot_close_billing_cycle
    """
    ctx = setup_active_self_install_account(customer_user_id="cust-rbac")
    resp = api.close_cycle(ctx["cycle"]["id"], build_customer_headers("cust-rbac"))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE, expected_status=403)


def test_customer_cannot_cancel_other_accounts_appointment(api):
    """PRD §2.1: "When the caller's `X-User-Role` is `Customer`, any action that targets an account, an order, or an appointment belonging to an account is permitted only when that account's `customer_user_id` equals the caller's `X-User-ID`; a `Customer` acting on an account they do not own is rejected with `ERR_NOT_ACCOUNT_OWNER`."

    Design: Corner/rbac/customer_cannot_act_on_other_accounts_appointment
    """
    set_clock("2026-06-01T00:00:00Z")
    owner1 = build_customer_headers("cust-owner-1")
    addr = create_address(self_install_eligible=False)
    plan = create_plan()
    tech = create_technician()
    slot = create_slot(tech["id"], capacity=2)
    acct = get_success_data(api.create_account(
        create_account_payload(addr["id"], plan["id"], "cust-owner-1"), owner1))
    order = get_success_data(api.create_service_order(
        {"account_id": acct["id"], "order_type": "NEW_INSTALL",
         "install_mode": "TECH_INSTALL", "requested_plan_id": plan["id"]}, owner1))
    appt = get_success_data(api.create_install_appointment(
        create_install_appointment_payload(order["id"], slot["id"], acct["version"]), owner1))
    # A different customer attempts to cancel owner-1's appointment.
    resp = api.cancel_appointment(appt["id"], build_customer_headers("cust-owner-2"))
    validate_error(resp, ApiErrorId.ERR_NOT_ACCOUNT_OWNER, expected_status=403)


def test_missing_user_context_header_rejected(api):
    """PRD §2.1: "If either header is missing or malformed, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

    Design: Corner/rbac/missing_user_context_header_rejected
    """
    resp = api.create_service_plan(
        create_service_plan_payload(code="C-NOAUTH", tier="BASIC", download_mbps=100,
                                    throttled_mbps=10, monthly_fee_cents=4000,
                                    included_gb=300),
        {"Content-Type": "application/json"})
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
                   expected_status=400)
