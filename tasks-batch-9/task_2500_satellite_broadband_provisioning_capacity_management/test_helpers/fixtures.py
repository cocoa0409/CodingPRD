"""Composite setup helpers.

Every test starts against an empty database, so each fixture builds its whole
precondition chain from PRD-declared endpoints. The canonical chain that most
scenarios share is:

    set the logical clock -> file a licence -> coordinate it (GRANTED)
    -> create a beam -> create a coverage cell -> publish a plan
    -> open a subscriber account -> file a service order (lands RESERVED)
    -> ship a terminal -> deliver it -> record a sky survey -> install it
    -> read the cell's version -> activate the subscription
    -> acknowledge the consumer disclosure -> grant network authorisation

Setup calls use the lenient validator so a broken precondition reports as a
setup failure rather than as a confusing assertion failure.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_EPOCH
from .factories import (
    authorize_payload,
    capacity_policy_payload,
    coordination_payload,
    create_beam_payload,
    create_outage_event_payload,
    create_roaming_authorization_payload,
    create_service_cell_payload,
    create_service_order_payload,
    create_service_plan_payload,
    create_spectrum_license_payload,
    create_subscriber_payload,
    create_subscription_payload,
    create_terminal_payload,
    credit_decision_payload,
    disclosure_acknowledgement_payload,
    enforcement_action_payload,
    obstruction_scan_payload,
    plan_change_payload,
    resolve_outage_payload,
    set_clock_payload,
    suspend_payload,
    terminate_payload,
    usage_record_payload,
    warranty_replacement_payload,
)
from .test_users import TEST_USERS, make_subscriber_headers

AGENT = TEST_USERS["provisioning_agent_headers"]
NETOPS = TEST_USERS["network_ops_engineer_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
COMPLIANCE_2 = TEST_USERS["compliance_officer_2_headers"]
LOGISTICS = TEST_USERS["logistics_coordinator_headers"]


# ───────────────────────── instant arithmetic ────────────────────────

def iso_shift(base_iso: str, days: int = 0, hours: int = 0, minutes: int = 0) -> str:
    """Return `base_iso` moved by the given offset, formatted as ISO 8601 UTC."""
    cleaned = base_iso.replace("Z", "+00:00")
    moment = datetime.fromisoformat(cleaned).astimezone(timezone.utc)
    moment = moment + timedelta(days=days, hours=hours, minutes=minutes)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


# ─────────────────────────── logical clock ───────────────────────────

def set_clock(to_iso8601: str, headers: Optional[dict] = None) -> dict:
    """Move the logical clock. Inert with respect to business state."""
    return get_success_data(
        api_client.set_clock(set_clock_payload(to_iso8601), headers or NETOPS)
    )


def reset_clock_to_epoch() -> dict:
    """Pin the clock at the instant it starts from, making a test explicit about it."""
    return set_clock(CLOCK_EPOCH)


# ──────────────────────── spectrum licences ──────────────────────────

def create_license(**overrides) -> dict:
    """File a licence. Lands in PENDING_COORDINATION / UNCOORDINATED."""
    return get_success_data(
        api_client.create_spectrum_license(
            create_spectrum_license_payload(**overrides), COMPLIANCE
        )
    )


def coordinate_license(
    license_id: str,
    outcome: str = "GRANTED",
    coordination_note: str = "no neighbour objection",
) -> dict:
    return get_success_data(
        api_client.record_coordination(
            license_id,
            coordination_payload(outcome=outcome, coordination_note=coordination_note),
            COMPLIANCE,
        )
    )


def create_active_license(**overrides) -> dict:
    """File a licence and coordinate it GRANTED so it is both live and coordinated."""
    license_record = create_license(**overrides)
    return coordinate_license(license_record["id"], outcome="GRANTED")


def create_provisional_license(**overrides) -> dict:
    """File a licence and grant it provisionally: ACTIVE but still UNCOORDINATED."""
    license_record = create_license(**overrides)
    return coordinate_license(license_record["id"], outcome="GRANTED_PROVISIONAL")


def suspend_license(license_id: str, reason: str = "interference investigation") -> dict:
    return get_success_data(
        api_client.enforcement_action(
            license_id, enforcement_action_payload("SUSPEND", reason=reason), COMPLIANCE
        )
    )


def reinstate_license(license_id: str, reason: str = "investigation closed") -> dict:
    return get_success_data(
        api_client.enforcement_action(
            license_id, enforcement_action_payload("REINSTATE", reason=reason), COMPLIANCE
        )
    )


def get_license(license_id: str) -> dict:
    return get_success_data(api_client.get_spectrum_license(license_id, COMPLIANCE))


# ───────────────────────────── topology ──────────────────────────────

def create_beam(spectrum_license_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_beam(
            create_beam_payload(spectrum_license_id=spectrum_license_id, **overrides), NETOPS
        )
    )


def create_cell(beam_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_service_cell(
            create_service_cell_payload(beam_id=beam_id, **overrides), NETOPS
        )
    )


def create_plan(**overrides) -> dict:
    return get_success_data(
        api_client.create_service_plan(create_service_plan_payload(**overrides), AGENT)
    )


def get_beam(beam_id: str) -> dict:
    return get_success_data(api_client.get_beam(beam_id, NETOPS))


def get_beam_version(beam_id: str) -> int:
    return get_beam(beam_id)["version"]


def get_cell(cell_id: str) -> dict:
    return get_success_data(api_client.get_service_cell(cell_id, AGENT))


def get_cell_version(cell_id: str) -> int:
    return get_cell(cell_id)["version"]


def write_capacity_policy(
    beam_id: str,
    oversubscription_limit: float = 4.0,
    deprioritization_grace_gb: int = 0,
    expected_beam_version: Optional[int] = None,
) -> dict:
    if expected_beam_version is None:
        expected_beam_version = get_beam_version(beam_id)
    return get_success_data(
        api_client.write_capacity_policy(
            beam_id,
            capacity_policy_payload(
                expected_beam_version=expected_beam_version,
                oversubscription_limit=oversubscription_limit,
                deprioritization_grace_gb=deprioritization_grace_gb,
            ),
            NETOPS,
        )
    )


def close_billing_cycle(beam_id: str) -> dict:
    return get_success_data(api_client.close_billing_cycle(beam_id, NETOPS))


def setup_topology(
    max_active_terminals: int = 1,
    forward_capacity_mbps: float = 100,
    oversubscription_limit: float = 4.0,
    committed_rate_mbps: float = 200,
    priority_tier: str = "PRIORITY_1",
    monthly_fee_cents: int = 9900,
    priority_data_gb: int = 100,
    jurisdiction_code: str = "US-CA",
    in_motion_permitted: bool = True,
    roaming_allowed: bool = True,
    in_motion_allowed: bool = True,
    clock: str = CLOCK_EPOCH,
    license_overrides: Optional[dict] = None,
    beam_overrides: Optional[dict] = None,
    cell_overrides: Optional[dict] = None,
    plan_overrides: Optional[dict] = None,
) -> dict:
    """Clock at a known instant, a live coordinated licence, one beam, one cell,
    one plan. Returns {"license", "beam", "cell", "plan"}."""
    set_clock(clock)
    license_record = create_active_license(
        jurisdiction_code=jurisdiction_code,
        in_motion_permitted=in_motion_permitted,
        **(license_overrides or {}),
    )
    beam = create_beam(
        license_record["id"],
        forward_capacity_mbps=forward_capacity_mbps,
        oversubscription_limit=oversubscription_limit,
        **(beam_overrides or {}),
    )
    cell = create_cell(
        beam["id"],
        jurisdiction_code=jurisdiction_code,
        max_active_terminals=max_active_terminals,
        **(cell_overrides or {}),
    )
    plan = create_plan(
        committed_rate_mbps=committed_rate_mbps,
        priority_tier=priority_tier,
        monthly_fee_cents=monthly_fee_cents,
        priority_data_gb=priority_data_gb,
        roaming_allowed=roaming_allowed,
        in_motion_allowed=in_motion_allowed,
        **(plan_overrides or {}),
    )
    return {"license": license_record, "beam": beam, "cell": cell, "plan": plan}


# ──────────────────────────── accounts ──────────────────────────────

def create_subscriber(index: int = 1, jurisdiction_code: str = "US-CA", **overrides) -> dict:
    payload = {
        "email": f"sub{index}@example.com",
        "full_name": f"Sub {index}",
        "jurisdiction_code": jurisdiction_code,
    }
    payload.update(overrides)
    return get_success_data(
        api_client.create_subscriber(create_subscriber_payload(**payload), AGENT)
    )


def get_subscriber(subscriber_id: str) -> dict:
    return get_success_data(api_client.get_subscriber(subscriber_id, AGENT))


# ───────────────────────── orders and waitlist ───────────────────────

def create_order(subscriber_id: str, service_cell_id: str, requested_plan_id: str) -> dict:
    return get_success_data(
        api_client.create_service_order(
            create_service_order_payload(
                subscriber_id=subscriber_id,
                service_cell_id=service_cell_id,
                requested_plan_id=requested_plan_id,
            ),
            AGENT,
        )
    )


def get_order(order_id: str) -> dict:
    return get_success_data(api_client.get_service_order(order_id, AGENT))


def cancel_order(order_id: str, cancel_reason: str = "customer changed their mind") -> dict:
    return get_success_data(
        api_client.cancel_service_order(order_id, {"cancel_reason": cancel_reason}, AGENT)
    )


# ──────────────────────────── hardware ──────────────────────────────

def ship_terminal(subscriber_id: str, index: int = 1, **overrides) -> dict:
    payload = {"serial_number": f"TRM-{index:04d}"}
    payload.update(overrides)
    return get_success_data(
        api_client.create_terminal(
            create_terminal_payload(subscriber_id=subscriber_id, **payload), LOGISTICS
        )
    )


def deliver_terminal(terminal_id: str) -> dict:
    return get_success_data(api_client.deliver_terminal(terminal_id, LOGISTICS))


def scan_terminal(
    terminal_id: str,
    subscriber_id: str,
    obstructed_sample_count: int = 1,
    total_sample_count: int = 200,
) -> dict:
    """Record a sky survey as the owning subscriber."""
    return get_success_data(
        api_client.create_obstruction_scan(
            terminal_id,
            obstruction_scan_payload(obstructed_sample_count, total_sample_count),
            make_subscriber_headers(subscriber_id),
        )
    )


def install_terminal(terminal_id: str, subscriber_id: str) -> dict:
    """Self-install as the owning subscriber."""
    return get_success_data(
        api_client.install_terminal(terminal_id, make_subscriber_headers(subscriber_id))
    )


def get_terminal(terminal_id: str) -> dict:
    return get_success_data(api_client.get_terminal(terminal_id, LOGISTICS))


def prepare_installed_terminal(
    subscriber_id: str,
    index: int = 1,
    obstructed_sample_count: int = 1,
    total_sample_count: int = 200,
    **terminal_overrides,
) -> dict:
    """Ship, deliver, survey and install one terminal. Returns the installed record."""
    terminal = ship_terminal(subscriber_id, index=index, **terminal_overrides)
    deliver_terminal(terminal["id"])
    scan_terminal(
        terminal["id"],
        subscriber_id,
        obstructed_sample_count=obstructed_sample_count,
        total_sample_count=total_sample_count,
    )
    return install_terminal(terminal["id"], subscriber_id)


def raise_warranty_replacement(
    terminal_id: str,
    replacement_serial_number: str = "TRM-0001-R",
    replacement_warranty_expires_at: str = "2029-08-01T00:00:00Z",
) -> dict:
    """Raise a warranty RMA. The response body is the new replacement terminal."""
    return get_success_data(
        api_client.warranty_replacement(
            terminal_id,
            warranty_replacement_payload(
                replacement_serial_number=replacement_serial_number,
                replacement_warranty_expires_at=replacement_warranty_expires_at,
            ),
            LOGISTICS,
        )
    )


# ───────────────────────── subscriptions ────────────────────────────

def activate_subscription(
    service_order_id: str,
    terminal_id: str,
    service_cell_id: Optional[str] = None,
    expected_service_cell_version: Optional[int] = None,
) -> dict:
    """Activate. Reads the cell's current version when one is not supplied."""
    if expected_service_cell_version is None:
        assert service_cell_id, "supply service_cell_id or expected_service_cell_version"
        expected_service_cell_version = get_cell_version(service_cell_id)
    return get_success_data(
        api_client.create_subscription(
            create_subscription_payload(
                service_order_id=service_order_id,
                terminal_id=terminal_id,
                expected_service_cell_version=expected_service_cell_version,
            ),
            AGENT,
        )
    )


def acknowledge_disclosure(
    subscription_id: str, subscriber_id: str, acknowledged_version: str = "CD-2026.1"
) -> dict:
    return get_success_data(
        api_client.acknowledge_disclosure(
            subscription_id,
            disclosure_acknowledgement_payload(acknowledged_version),
            make_subscriber_headers(subscriber_id),
        )
    )


def authorize_subscription(subscription_id: str, authorization_mode: str = "FIXED") -> dict:
    return get_success_data(
        api_client.authorize_subscription(
            subscription_id, authorize_payload(authorization_mode), AGENT
        )
    )


def get_subscription(subscription_id: str) -> dict:
    return get_success_data(api_client.get_subscription(subscription_id, AGENT))


def suspend_subscription(subscription_id: str, suspend_reason: str = "non-payment") -> dict:
    return get_success_data(
        api_client.suspend_subscription(subscription_id, suspend_payload(suspend_reason=suspend_reason), AGENT)
    )


def terminate_subscription(
    subscription_id: str, termination_reason: str = "customer cancelled service"
) -> dict:
    return get_success_data(
        api_client.terminate_subscription(
            subscription_id, terminate_payload(termination_reason=termination_reason), AGENT
        )
    )


def change_plan(
    subscription_id: str,
    new_service_plan_id: str,
    beam_id: Optional[str] = None,
    expected_beam_version: Optional[int] = None,
) -> dict:
    if expected_beam_version is None:
        assert beam_id, "supply beam_id or expected_beam_version"
        expected_beam_version = get_beam_version(beam_id)
    return get_success_data(
        api_client.change_plan(
            subscription_id,
            plan_change_payload(
                new_service_plan_id=new_service_plan_id,
                expected_beam_version=expected_beam_version,
            ),
            AGENT,
        )
    )


def ingest_usage(subscription_id: str, gb_used: float, billing_cycle_index: int = 0) -> dict:
    return get_success_data(
        api_client.create_usage_record(
            subscription_id, usage_record_payload(gb_used, billing_cycle_index), NETOPS
        )
    )


# ───────────────── composite subscription lifecycles ────────────────

def setup_reserved_order(
    env: Optional[dict] = None,
    subscriber_index: int = 1,
    terminal_index: int = 1,
    install_terminal_too: bool = True,
    obstructed_sample_count: int = 1,
    total_sample_count: int = 200,
    **topology_overrides,
) -> dict:
    """Topology + one account + one RESERVED order + one terminal.

    Returns the topology dict extended with "subscriber", "order" and "terminal".
    """
    env = dict(env) if env else setup_topology(**topology_overrides)
    subscriber = create_subscriber(
        index=subscriber_index, jurisdiction_code=env["cell"]["jurisdiction_code"]
    )
    order = create_order(subscriber["id"], env["cell"]["id"], env["plan"]["id"])
    if install_terminal_too:
        terminal = prepare_installed_terminal(
            subscriber["id"],
            index=terminal_index,
            obstructed_sample_count=obstructed_sample_count,
            total_sample_count=total_sample_count,
        )
    else:
        terminal = ship_terminal(subscriber["id"], index=terminal_index)
    env.update({"subscriber": subscriber, "order": order, "terminal": terminal})
    return env


def setup_pending_activation_subscription(
    env: Optional[dict] = None, **overrides
) -> dict:
    """Everything setup_reserved_order builds, plus the activated subscription.

    The subscription lands PENDING_ACTIVATION / UNAUTHORIZED / PRIORITY / PENDING_ACK.
    Returns the env extended with "subscription".
    """
    env = setup_reserved_order(env, **overrides)
    subscription = activate_subscription(
        env["order"]["id"], env["terminal"]["id"], service_cell_id=env["cell"]["id"]
    )
    env["subscription"] = subscription
    return env


def setup_acknowledged_subscription(env: Optional[dict] = None, **overrides) -> dict:
    """A PENDING_ACTIVATION subscription whose disclosure has been acknowledged."""
    env = setup_pending_activation_subscription(env, **overrides)
    env["subscription"] = acknowledge_disclosure(
        env["subscription"]["id"],
        env["subscriber"]["id"],
        env["license"]["consumer_disclosure_version"],
    )
    return env


def setup_active_subscription(
    env: Optional[dict] = None, authorization_mode: str = "FIXED", **overrides
) -> dict:
    """A live service: service_state ACTIVE, authorisation granted, disclosure
    acknowledged. Returns the env with the post-authorisation subscription."""
    env = setup_acknowledged_subscription(env, **overrides)
    env["subscription"] = authorize_subscription(
        env["subscription"]["id"], authorization_mode
    )
    return env


def add_active_subscription(
    env: dict, subscriber_index: int = 2, terminal_index: int = 2,
    authorization_mode: str = "FIXED",
) -> dict:
    """Add a second (third, ...) live service on the same cell and beam.

    Returns {"subscriber", "order", "terminal", "subscription"} for the new account,
    leaving `env`'s own records untouched.
    """
    subscriber = create_subscriber(
        index=subscriber_index, jurisdiction_code=env["cell"]["jurisdiction_code"]
    )
    order = create_order(subscriber["id"], env["cell"]["id"], env["plan"]["id"])
    terminal = prepare_installed_terminal(subscriber["id"], index=terminal_index)
    subscription = activate_subscription(
        order["id"], terminal["id"], service_cell_id=env["cell"]["id"]
    )
    subscription = acknowledge_disclosure(
        subscription["id"], subscriber["id"], env["license"]["consumer_disclosure_version"]
    )
    subscription = authorize_subscription(subscription["id"], authorization_mode)
    return {
        "subscriber": subscriber,
        "order": order,
        "terminal": terminal,
        "subscription": subscription,
    }


def setup_waitlisted_order(env: dict, subscriber_index: int) -> dict:
    """File one further order on a cell with no admitting slot, so it is WAITLISTED.

    Returns {"subscriber", "order"}.
    """
    subscriber = create_subscriber(
        index=subscriber_index, jurisdiction_code=env["cell"]["jurisdiction_code"]
    )
    order = create_order(subscriber["id"], env["cell"]["id"], env["plan"]["id"])
    return {"subscriber": subscriber, "order": order}


def setup_rma_in_flight(env: Optional[dict] = None, **overrides) -> dict:
    """A live service whose bound terminal has gone to RMA_PENDING, leaving the
    subscription SUSPENDED and a replacement terminal SHIPPED.

    Returns the env extended with "replacement_terminal".
    """
    env = setup_active_subscription(env, **overrides)
    replacement = raise_warranty_replacement(
        env["terminal"]["id"],
        replacement_serial_number=f"{env['terminal']['serial_number']}-R",
    )
    env["replacement_terminal"] = replacement
    return env


# ────────────────── impairment events and credits ───────────────────

def open_outage_event(
    beam_id: str,
    cause: str = "EQUIPMENT_FAILURE",
    severity: str = "FULL_OUTAGE",
    started_at: str = CLOCK_EPOCH,
) -> dict:
    return get_success_data(
        api_client.create_outage_event(
            create_outage_event_payload(
                beam_id=beam_id, cause=cause, severity=severity, started_at=started_at
            ),
            NETOPS,
        )
    )


def resolve_outage_event(event_id: str, ended_at: str) -> dict:
    return get_success_data(
        api_client.resolve_outage_event(event_id, resolve_outage_payload(ended_at), NETOPS)
    )


def list_credits_for_subscription(subscription_id: str) -> list:
    response = api_client.list_outage_credits(AGENT, params={"subscription_id": subscription_id})
    body = response.json()
    assert 200 <= response.status_code < 300, f"Setup step failed: {response.text}"
    return body["data"]


def setup_drafted_credit(
    env: Optional[dict] = None,
    cause: str = "EQUIPMENT_FAILURE",
    severity: str = "FULL_OUTAGE",
    started_at: str = CLOCK_EPOCH,
    ended_at: Optional[str] = None,
    **overrides,
) -> dict:
    """A live service impaired by a resolved event, leaving one DRAFT credit.

    Returns the env extended with "event" and "credit".
    """
    env = setup_active_subscription(env, **overrides)
    event = open_outage_event(
        env["beam"]["id"], cause=cause, severity=severity, started_at=started_at
    )
    resolve_at = ended_at or iso_shift(started_at, hours=1)
    set_clock(resolve_at)
    env["event"] = resolve_outage_event(event["id"], resolve_at)
    credits = list_credits_for_subscription(env["subscription"]["id"])
    env["credit"] = credits[0] if credits else None
    return env


def submit_credit(credit_id: str, submitter_headers: Optional[dict] = None) -> dict:
    return get_success_data(
        api_client.submit_outage_credit(credit_id, submitter_headers or AGENT)
    )


def setup_submitted_credit(env: Optional[dict] = None, **overrides) -> dict:
    """A DRAFT credit moved to SUBMITTED by a ProvisioningAgent."""
    env = setup_drafted_credit(env, **overrides)
    env["credit"] = submit_credit(env["credit"]["id"])
    return env


def decide_credit(
    credit_id: str,
    decision: str = "APPROVE",
    decision_reason: str = "impairment confirmed",
    decider_headers: Optional[dict] = None,
) -> dict:
    return get_success_data(
        api_client.decide_outage_credit(
            credit_id,
            credit_decision_payload(decision=decision, decision_reason=decision_reason),
            decider_headers or COMPLIANCE,
        )
    )


# ───────────────────── roaming authorisations ───────────────────────

def request_roaming(
    subscription_id: str,
    subscriber_id: Optional[str] = None,
    mode: str = "ROAM_TEMPORARY",
    target_jurisdiction_code: str = "US-NV",
    effective_from: str = "2026-09-01T00:00:00Z",
    effective_until: str = "2026-09-10T00:00:00Z",
    target_service_cell_id: Optional[str] = None,
) -> dict:
    """Raise a roaming request. Uses the owning subscriber when one is supplied."""
    headers = make_subscriber_headers(subscriber_id) if subscriber_id else AGENT
    return get_success_data(
        api_client.create_roaming_authorization(
            create_roaming_authorization_payload(
                subscription_id=subscription_id,
                mode=mode,
                target_jurisdiction_code=target_jurisdiction_code,
                effective_from=effective_from,
                effective_until=effective_until,
                target_service_cell_id=target_service_cell_id,
            ),
            headers,
        )
    )


def decide_roaming(
    authorization_id: str,
    decision: str = "APPROVE",
    decision_note: str = "evidence accepted",
) -> dict:
    return get_success_data(
        api_client.decide_roaming_authorization(
            authorization_id,
            {"decision": decision, "decision_note": decision_note},
            COMPLIANCE,
        )
    )


def request_roaming_info(
    authorization_id: str, info_request_note: str = "please supply the address of record"
) -> dict:
    return get_success_data(
        api_client.request_roaming_info(
            authorization_id, {"info_request_note": info_request_note}, COMPLIANCE
        )
    )


def resubmit_roaming(
    authorization_id: str,
    effective_from: str,
    effective_until: str,
    subscriber_id: Optional[str] = None,
) -> dict:
    headers = make_subscriber_headers(subscriber_id) if subscriber_id else AGENT
    return get_success_data(
        api_client.resubmit_roaming_authorization(
            authorization_id,
            {"effective_from": effective_from, "effective_until": effective_until},
            headers,
        )
    )


def setup_approved_roaming_window(
    env: Optional[dict] = None,
    mode: str = "ROAM_TEMPORARY",
    target_jurisdiction_code: str = "US-CA",
    effective_from: str = "2026-09-01T00:00:00Z",
    effective_until: str = "2026-09-10T00:00:00Z",
    **overrides,
) -> dict:
    """A live service carrying one APPROVED roaming window.

    Returns the env extended with "roaming".
    """
    env = setup_active_subscription(env, **overrides)
    request = request_roaming(
        env["subscription"]["id"],
        subscriber_id=env["subscriber"]["id"],
        mode=mode,
        target_jurisdiction_code=target_jurisdiction_code,
        effective_from=effective_from,
        effective_until=effective_until,
    )
    env["roaming"] = decide_roaming(request["id"], "APPROVE")
    return env
