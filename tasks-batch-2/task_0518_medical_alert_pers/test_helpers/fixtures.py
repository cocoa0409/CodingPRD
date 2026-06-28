"""Composite setup helpers for multi-step test prerequisites.

Most interesting claims require the system to be in a state that takes 5-15 API calls to
reach (plan -> subscriber -> contract -> device -> test -> enroll -> activate, plus alarm
and equipment-return lifecycles). These helpers encapsulate those preambles.

Uses get_success_data() (lenient) internally so setup failures surface as clear
"Setup step failed" errors. Identity threading: every ownership-gated Subscriber call uses
make_subscriber_headers(subscriber["id"]) with the real Subscriber.id — never the shared
constant — because X-User-ID must equal the owning subscriber's id.

The harness restarts the server and clears the DB before EVERY test, so each fixture builds
its preconditions from scratch.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_plan_payload, create_subscriber_payload, create_contract_payload,
    create_device_payload, create_test_payload, create_contact_payload,
    create_alarm_payload, create_dispatch_payload, create_shift_payload, create_hold_payload,
    unique_email, unique_serial,
)
from .test_users import TEST_USERS, make_subscriber_headers, make_agent_headers

ADMIN = TEST_USERS["admin_headers"]
DEFAULT_CLOCK = "2026-06-01T00:00:00Z"


# ---------------------------------------------------------------------------
# Primitive helpers
# ---------------------------------------------------------------------------
def set_clock(instant: str):
    """Set the server logical clock (PlatformAdmin)."""
    return get_success_data(api_client.set_clock(instant, ADMIN))


def create_plan(**overrides):
    """Create a MonitoringPlan. Returns the plan dict."""
    return get_success_data(api_client.create_plan(create_plan_payload(**overrides), ADMIN))


def create_subscriber(**overrides):
    """Create a Subscriber. Returns the subscriber dict."""
    return get_success_data(api_client.create_subscriber(create_subscriber_payload(**overrides), ADMIN))


def create_contract(subscriber_id, plan_id, **overrides):
    """Create a PENDING_ACTIVATION Contract. Returns the contract dict."""
    return get_success_data(
        api_client.create_contract(create_contract_payload(subscriber_id, plan_id, **overrides), ADMIN)
    )


def create_device(contract_id, subscriber_id, **overrides):
    """Register a device under a contract as the owning subscriber. Returns the device dict."""
    headers = make_subscriber_headers(subscriber_id)
    return get_success_data(api_client.create_device(create_device_payload(contract_id, **overrides), headers))


def submit_test(device_id, subscriber_id, **overrides):
    """Submit a DeviceTest as the owning subscriber. Returns the DeviceTest dict."""
    headers = make_subscriber_headers(subscriber_id)
    return get_success_data(api_client.submit_test(device_id, create_test_payload(**overrides), headers))


def enroll_device(device_id, subscriber_id):
    """Enroll a device as the owning subscriber. Returns the device dict."""
    headers = make_subscriber_headers(subscriber_id)
    return get_success_data(api_client.enroll_device(device_id, headers))


def activate_contract(contract_id):
    """Activate a contract (PlatformAdmin). Returns the contract dict."""
    return get_success_data(api_client.activate_contract(contract_id, ADMIN))


# ---------------------------------------------------------------------------
# Tier 1/2: Plan + subscriber + contract base setup
# ---------------------------------------------------------------------------
def setup_plan_subscriber_contract(plan_overrides=None, email=None):
    """Create a plan, a subscriber, and a PENDING_ACTIVATION contract.
    Returns (plan, subscriber, contract). No clock set, no device."""
    plan = create_plan(**(plan_overrides or {}))
    sub = create_subscriber(email=email or unique_email())
    contract = create_contract(sub["id"], plan["id"])
    return plan, sub, contract


def setup_registered_device(plan_overrides=None, device_overrides=None, set_clock_to=None):
    """Plan + subscriber + contract + one REGISTERED device.
    Returns (plan, subscriber, contract, device)."""
    plan, sub, contract = setup_plan_subscriber_contract(plan_overrides)
    if set_clock_to:
        set_clock(set_clock_to)
    device = create_device(contract["id"], sub["id"], **(device_overrides or {}))
    return plan, sub, contract, device


# ---------------------------------------------------------------------------
# Tier 1/3: Activated contract with one ACTIVE device
# ---------------------------------------------------------------------------
def setup_active_contract_with_device(
    plan_overrides=None, device_overrides=None, clock=DEFAULT_CLOCK, test_battery=90,
):
    """Full path to an ACTIVE contract with one ACTIVE device:
    plan -> subscriber -> contract -> set clock -> register device -> PASS test -> enroll -> activate.
    Returns (plan, subscriber, contract, device) with contract & device freshly re-read post-activate."""
    plan, sub, contract = setup_plan_subscriber_contract(plan_overrides)
    set_clock(clock)
    device = create_device(contract["id"], sub["id"], **(device_overrides or {}))
    submit_test(device["id"], sub["id"], reported_battery_pct=test_battery, signal_ok=True)
    enroll_device(device["id"], sub["id"])
    contract = activate_contract(contract["id"])
    device = get_success_data(api_client.get_device(device["id"], ADMIN))
    return plan, sub, contract, device


def setup_active_contract_with_two_devices(plan_overrides=None, clock=DEFAULT_CLOCK):
    """ACTIVE contract with TWO ACTIVE devices. Returns (plan, subscriber, contract, dev_a, dev_b)."""
    plan, sub, contract = setup_plan_subscriber_contract(plan_overrides)
    set_clock(clock)
    dev_a = create_device(contract["id"], sub["id"], serial_number=unique_serial("SNa"))
    dev_b = create_device(contract["id"], sub["id"], serial_number=unique_serial("SNb"),
                          device_type="WRISTBAND")
    for d in (dev_a, dev_b):
        submit_test(d["id"], sub["id"], reported_battery_pct=90, signal_ok=True)
        enroll_device(d["id"], sub["id"])
    contract = activate_contract(contract["id"])
    dev_a = get_success_data(api_client.get_device(dev_a["id"], ADMIN))
    dev_b = get_success_data(api_client.get_device(dev_b["id"], ADMIN))
    return plan, sub, contract, dev_a, dev_b


# ---------------------------------------------------------------------------
# Suspension helpers
# ---------------------------------------------------------------------------
def drive_contract_to_suspended(contract_id, past_due_clock="2026-07-02T00:00:00Z"):
    """From an ACTIVE+CURRENT contract: advance clock past paid_through, mark-past-due, suspend.
    Returns the suspended contract dict."""
    set_clock(past_due_clock)
    get_success_data(api_client.mark_past_due(contract_id, ADMIN))
    return get_success_data(api_client.suspend_contract(contract_id, ADMIN))


def setup_suspended_contract_with_device(plan_overrides=None, device_overrides=None,
                                         clock=DEFAULT_CLOCK):
    """ACTIVE -> SUSPENDED contract with one (now SUSPENDED) device.
    Returns (plan, subscriber, contract, device)."""
    plan, sub, contract, device = setup_active_contract_with_device(
        plan_overrides, device_overrides, clock=clock)
    contract = drive_contract_to_suspended(contract["id"])
    device = get_success_data(api_client.get_device(device["id"], ADMIN))
    return plan, sub, contract, device


# ---------------------------------------------------------------------------
# Cancellation / equipment-return helpers
# ---------------------------------------------------------------------------
def request_cancellation_active(contract):
    """Request cancellation on an ACTIVE contract using its current version (STANDARD variant).
    Returns the updated contract dict."""
    return get_success_data(
        api_client.request_cancellation(
            contract["id"], {"expected_contract_version": contract["version"]},
            make_subscriber_headers(contract["subscriber_id"]),
        )
    )


def finalize_after_effective(contract_id, finalize_clock="2026-07-02T00:00:00Z"):
    """Advance clock past the standard effective date (paid_through) and finalize cancellation.
    Returns the cancelled contract dict."""
    set_clock(finalize_clock)
    return get_success_data(api_client.finalize_cancellation(contract_id, ADMIN))


def cancel_via_suspended_and_finalize(contract_id, suspend_clock="2026-07-02T00:00:00Z"):
    """Drive an ACTIVE contract all the way to CANCELLED (finalized).

    Per PRD 3.7 finalization is blocked while any device is still ACTIVE or NEEDS_TEST;
    the only PRD path that moves devices out of ACTIVE without finalizing is suspension
    (ACTIVE -> SUSPENDED, PRD 3.4). So a finalizable cancellation is reached by:
    suspend (devices -> SUSPENDED), request cancellation from SUSPENDED (IMMEDIATE variant,
    cancellation_effective_at = current instant), then finalize at that same instant.

    suspend_clock must be strictly after the contract's paid_through_at so mark-past-due
    is permitted; the default 2026-07-02 is one day past the standard 2026-07-01 paid_through
    of a contract activated on 2026-06-01, and finalize then stamps due_back_at at
    suspend_clock + 14 days. Returns the cancelled contract dict."""
    drive_contract_to_suspended(contract_id, past_due_clock=suspend_clock)
    contract = get_success_data(api_client.get_contract(contract_id, ADMIN))
    contract = get_success_data(
        api_client.request_cancellation(
            contract_id, {"expected_contract_version": contract["version"]},
            make_subscriber_headers(contract["subscriber_id"]),
        )
    )
    # Clock is already at suspend_clock (== cancellation_effective_at for the IMMEDIATE
    # variant), so finalization's temporal gate is satisfied.
    return get_success_data(api_client.finalize_cancellation(contract_id, ADMIN))


def get_first_equipment_return(contract_id):
    """Return the first EquipmentReturn opened under a contract (re-read fresh)."""
    returns, _ = _list(api_client.list_contract_equipment_returns(contract_id, ADMIN))
    assert returns, "Setup step failed: no equipment returns under contract"
    return returns[0]


def setup_received_equipment_return(device_type="PENDANT", clock=DEFAULT_CLOCK):
    """Full path to a RECEIVED EquipmentReturn ready to inspect:
    activate contract (BASIC, ETF 0) -> suspend -> cancel -> finalize -> send kit -> mark received.
    Cancellation goes through SUSPENDED (PRD 3.4) because PRD 3.7 blocks finalization while a
    device is still ACTIVE/NEEDS_TEST; suspension is the only PRD path that moves the device
    out of ACTIVE without finalizing. Returns (contract, device, equipment_return)."""
    plan, sub, contract, device = setup_active_contract_with_device(
        plan_overrides=create_plan_payload(),  # BASIC, ETF 0, min_commitment 0
        device_overrides={"device_type": device_type, "serial_number": unique_serial("SNr")},
        clock=clock,
    )
    contract = cancel_via_suspended_and_finalize(contract["id"])
    ret = get_first_equipment_return(contract["id"])
    get_success_data(api_client.send_kit(ret["id"], ADMIN))
    ret = get_success_data(api_client.mark_received(ret["id"], ADMIN))
    device = get_success_data(api_client.get_device(device["id"], ADMIN))
    return contract, device, ret


def setup_finalized_contract_with_return(device_type="WRISTBAND", clock=DEFAULT_CLOCK):
    """Activate a BASIC contract, suspend, cancel, finalize so an INITIATED EquipmentReturn exists.
    Cancellation goes through SUSPENDED (PRD 3.4) because PRD 3.7 blocks finalization while a
    device is still ACTIVE/NEEDS_TEST. Returns (contract, device, equipment_return)."""
    plan, sub, contract, device = setup_active_contract_with_device(
        plan_overrides=create_plan_payload(),
        device_overrides={"device_type": device_type, "serial_number": unique_serial("SNf")},
        clock=clock,
    )
    contract = cancel_via_suspended_and_finalize(contract["id"])
    ret = get_first_equipment_return(contract["id"])
    device = get_success_data(api_client.get_device(device["id"], ADMIN))
    return contract, device, ret


# ---------------------------------------------------------------------------
# Alarm / agent / dispatch helpers
# ---------------------------------------------------------------------------
def create_shift(agent_user_id, starts_at, ends_at):
    """Create a SCHEDULED AgentShift. Returns the shift dict."""
    return get_success_data(
        api_client.create_shift(create_shift_payload(agent_user_id, starts_at, ends_at), ADMIN)
    )


def raise_alarm(device_id, subscriber_id, signal_type="MANUAL_BUTTON"):
    """Raise an alarm on a device as the owning subscriber. Returns the alarm dict."""
    headers = make_subscriber_headers(subscriber_id)
    return get_success_data(api_client.raise_alarm(device_id, create_alarm_payload(signal_type), headers))


def assign_alarm(alarm_id, agent_user_id):
    """Assign an alarm to a covering agent. Returns the alarm dict."""
    return get_success_data(api_client.assign_alarm(alarm_id, make_agent_headers(agent_user_id)))


def dispatch(alarm_id, agent_user_id, action_type, outcome, target_contact_id=None):
    """Record a dispatch action as the assigned agent. Returns the DispatchAction dict."""
    payload = create_dispatch_payload(action_type, outcome)
    if target_contact_id is not None:
        payload["target_contact_id"] = target_contact_id
    return get_success_data(
        api_client.create_dispatch_action(alarm_id, payload, make_agent_headers(agent_user_id))
    )


def setup_assigned_alarm(
    agent_user_id="agent-1", signal_type="MANUAL_BUTTON", device_overrides=None,
    plan_overrides=None, clock=DEFAULT_CLOCK, shift_end="2026-06-01T12:00:00Z",
):
    """ACTIVE device + agent shift + raised alarm + assigned to agent.
    Returns (subscriber, contract, device, alarm). Agent shift covers [clock, shift_end)."""
    plan, sub, contract, device = setup_active_contract_with_device(
        plan_overrides=plan_overrides, device_overrides=device_overrides, clock=clock)
    create_shift(agent_user_id, clock, shift_end)
    alarm = raise_alarm(device["id"], sub["id"], signal_type=signal_type)
    alarm = assign_alarm(alarm["id"], agent_user_id)
    return sub, contract, device, alarm


def setup_contacting_subscriber_alarm(
    agent_user_id="agent-1", signal_type="MANUAL_BUTTON", device_overrides=None,
    plan_overrides=None, clock=DEFAULT_CLOCK,
):
    """Alarm driven to CONTACTING_SUBSCRIBER (CALL_SUBSCRIBER ANSWERED).
    Returns (subscriber, contract, device, alarm)."""
    sub, contract, device, alarm = setup_assigned_alarm(
        agent_user_id=agent_user_id, signal_type=signal_type,
        device_overrides=device_overrides, plan_overrides=plan_overrides, clock=clock)
    dispatch(alarm["id"], agent_user_id, "CALL_SUBSCRIBER", "ANSWERED")
    alarm = get_success_data(api_client.get_alarm(alarm["id"], ADMIN))
    return sub, contract, device, alarm


def create_contact(subscriber_id, priority_rank, **overrides):
    """Create an EmergencyContact for the subscriber. Returns the contact dict."""
    headers = make_subscriber_headers(subscriber_id)
    return get_success_data(
        api_client.create_contact(create_contact_payload(subscriber_id, priority_rank, **overrides), headers)
    )


def setup_escalating_alarm_two_contacts(agent_user_id="agent-1", clock=DEFAULT_CLOCK,
                                        c1_can_authorize=False):
    """ACTIVE non-fall device; two active contacts (rank1 escalates_to rank2); alarm assigned;
    subscriber NO_ANSWER -> ESCALATING at rank 1.
    Returns (subscriber, contract, device, alarm, c1, c2)."""
    plan, sub, contract, device = setup_active_contract_with_device(
        device_overrides={"fall_detection_enabled": False}, clock=clock)
    # rank 2 first so rank 1 can escalate to it
    c2 = create_contact(sub["id"], 2, name="C2", phone="555-2222", relationship="FAMILY")
    c1 = create_contact(sub["id"], 1, name="C1", phone="555-1111", relationship="CAREGIVER",
                        escalates_to_contact_id=c2["id"], can_authorize_911=c1_can_authorize)
    create_shift(agent_user_id, clock, "2026-06-02T00:00:00Z")
    alarm = raise_alarm(device["id"], sub["id"], signal_type="MANUAL_BUTTON")
    alarm = assign_alarm(alarm["id"], agent_user_id)
    dispatch(alarm["id"], agent_user_id, "CALL_SUBSCRIBER", "ANSWERED")
    dispatch(alarm["id"], agent_user_id, "CALL_SUBSCRIBER", "NO_ANSWER")
    alarm = get_success_data(api_client.get_alarm(alarm["id"], ADMIN))
    return sub, contract, device, alarm, c1, c2


# ---------------------------------------------------------------------------
# Listing helper
# ---------------------------------------------------------------------------
def _list(response):
    """Unwrap a paginated list response into (data, meta) leniently for setup use."""
    body = response.json()
    return body.get("data", []), body.get("meta", {})
