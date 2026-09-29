"""Composite state builders.

The service under test starts every test from an empty store, so each builder
here reconstructs the state it needs purely through the documented endpoints:
move the logical clock, register a carrier, provision circuits, wire them into
application paths, then drive alarms, incidents, tickets, claims, windows,
failover verifications and upgrade orders through their documented transitions.

Builders are ordinary functions, not pytest fixtures, so a single test can build
two independent topologies. Each returns a plain dict of the identifiers and
records a test needs, and each accepts keyword overrides that are forwarded to
the underlying payload factory.
"""

from typing import Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .test_users import (
    ADMIN_HEADERS,
    ANALYST_HEADERS,
    CAPACITY_PLANNER_HEADERS,
    SHIFT_LEAD_HEADERS,
    VENDOR_MANAGER_HEADERS,
    make_carrier_liaison_headers,
    make_shift_lead_headers,
)

# ===========================================================================
# Tier 1 — single-call primitives
# ===========================================================================


def advance_clock(api, to_iso8601: str) -> dict:
    """Move the service's logical clock forward to the supplied instant."""
    return get_success_data(
        api.set_clock(f.clock_payload(to_iso8601), ADMIN_HEADERS)
    )


def create_carrier(api, **overrides) -> dict:
    return get_success_data(
        api.create_carrier(f.carrier_payload(**overrides), ADMIN_HEADERS)
    )


def create_circuit(api, carrier_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_circuit(f.circuit_payload(carrier_id, **overrides), ADMIN_HEADERS)
    )


def create_device(api, **overrides) -> dict:
    return get_success_data(
        api.create_device(f.device_payload(**overrides), ADMIN_HEADERS)
    )


def create_path(api, **overrides) -> dict:
    return get_success_data(
        api.create_application_path(
            f.application_path_payload(**overrides), ADMIN_HEADERS
        )
    )


def add_segment(api, path_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_path_segment(
            f.path_segment_payload(path_id, **overrides), ADMIN_HEADERS
        )
    )


def raise_alarm(api, raised_at: str, headers: Optional[dict] = None, **overrides) -> dict:
    """Ingest an alarm; the response already carries its correlation outcome."""
    return get_success_data(
        api.create_alarm(
            f.alarm_payload(raised_at, **overrides), headers or ANALYST_HEADERS
        )
    )


def clear_alarm(api, alarm_id: str, cleared_at: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(
        api.clear_alarm(
            alarm_id, f.alarm_clear_payload(cleared_at), headers or ANALYST_HEADERS
        )
    )


def read_carrier(api, carrier_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api.get_carrier(carrier_id, headers or ADMIN_HEADERS))


def read_circuit(api, circuit_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api.get_circuit(circuit_id, headers or ADMIN_HEADERS))


def read_path(api, path_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(
        api.get_application_path(path_id, headers or ADMIN_HEADERS)
    )


def read_incident(api, incident_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api.get_incident(incident_id, headers or ANALYST_HEADERS))


def read_ticket(api, ticket_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(
        api.get_carrier_ticket(ticket_id, headers or SHIFT_LEAD_HEADERS)
    )


def read_claim(api, claim_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(
        api.get_sla_credit_claim(claim_id, headers or VENDOR_MANAGER_HEADERS)
    )


def read_window(api, window_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(
        api.get_maintenance_window(window_id, headers or SHIFT_LEAD_HEADERS)
    )


def read_segment(api, segment_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(
        api.get_path_segment(segment_id, headers or SHIFT_LEAD_HEADERS)
    )


# ===========================================================================
# Tier 2 — carrier and path topologies
# ===========================================================================


def build_pft_single_leg(
    api,
    clock: str,
    circuit_identifier: str = "PFT-CKT-9001",
    site_z_code: str = "MSP01",
    bandwidth_mbps: int = 500,
    mrc_cents: int = 275000,
    path_name: str = "Guest",
    service_tier: str = "BRONZE",
    protection_scheme: str = "UNPROTECTED",
    with_segment: bool = True,
    alarm_raised_at: Optional[str] = None,
    **carrier_overrides,
) -> dict:
    """A single monitored circuit carrying one single-leg application path.

    This is the smallest topology that still produces a real incident: the one
    leg is the whole path, so a critical alarm on the circuit takes the path
    down and the incident is classified against exactly one service tier.
    """
    advance_clock(api, clock)
    carrier = create_carrier(api, **carrier_overrides)
    circuit = create_circuit(
        api,
        carrier["id"],
        carrier_circuit_identifier=circuit_identifier,
        site_z_code=site_z_code,
        bandwidth_mbps=bandwidth_mbps,
        mrc_cents=mrc_cents,
        monitoring_state="MONITORED",
    )
    path = create_path(
        api,
        name=path_name,
        service_tier=service_tier,
        protection_scheme=protection_scheme,
        min_surviving_legs=1,
    )
    state = {
        "carrier": carrier,
        "carrier_id": carrier["id"],
        "circuit": circuit,
        "circuit_id": circuit["id"],
        "path": path,
        "path_id": path["id"],
        "liaison_headers": make_carrier_liaison_headers(carrier["id"]),
    }
    if with_segment:
        segment = add_segment(api, path["id"], circuit_id=circuit["id"])
        state["segment"] = segment
        state["segment_id"] = segment["id"]
    if alarm_raised_at is not None:
        alarm = raise_alarm(api, alarm_raised_at, source_circuit_id=circuit["id"])
        state["alarm"] = alarm
        state["alarm_id"] = alarm["id"]
        state["incident_id"] = alarm["incident_id"]
    return state


def build_pft_capacity_circuit(
    api,
    clock: str,
    circuit_identifier: str = "PFT-CKT-9005",
    bandwidth_mbps: int = 100,
    mrc_cents: int = 90000,
    **carrier_overrides,
) -> dict:
    """A monitored circuit on the lowest bandwidth rung, with no path wiring.

    Capacity pressure is a property of the circuit alone, so this topology
    deliberately leaves the circuit out of every application path.
    """
    advance_clock(api, clock)
    carrier = create_carrier(api, **carrier_overrides)
    circuit = create_circuit(
        api,
        carrier["id"],
        carrier_circuit_identifier=circuit_identifier,
        site_z_code="OMA01",
        bandwidth_mbps=bandwidth_mbps,
        mrc_cents=mrc_cents,
        monitoring_state="MONITORED",
    )
    return {
        "carrier": carrier,
        "carrier_id": carrier["id"],
        "circuit": circuit,
        "circuit_id": circuit["id"],
        "circuit_version": circuit["version"],
        "liaison_headers": make_carrier_liaison_headers(carrier["id"]),
    }


def build_nlc_four_path(
    api,
    clock: str,
    ticket_reference: Optional[str] = None,
    ticket_opened_at: Optional[str] = None,
    **carrier_overrides,
) -> dict:
    """One critical circuit carried by four application paths of three tiers.

    The circuit is the sole hop of a gold path, two silver paths and a bronze
    path, so a critical alarm on it makes all four paths affected at once. That
    is what makes the impact score exercise every one of its weighted terms and
    what gives the credit calculation four separately rounded path lines.
    """
    advance_clock(api, clock)
    carrier = create_carrier(
        api,
        name="NorthLink Communications",
        carrier_code="NLC",
        **carrier_overrides,
    )
    circuit = create_circuit(
        api,
        carrier["id"],
        carrier_circuit_identifier="NLC-CKT-1001",
        site_a_code="NYC01",
        site_z_code="BOS01",
        bandwidth_mbps=200,
        mrc_cents=920000,
        monitoring_state="MONITORED",
    )
    path_specs = [
        ("trading", "Trading Gateway", "GOLD", "ACTIVE_STANDBY"),
        ("claims", "Claims Portal", "SILVER", "ACTIVE_STANDBY"),
        ("payroll", "Payroll Feed", "SILVER", "ACTIVE_STANDBY"),
        ("guest", "Guest WiFi", "BRONZE", "UNPROTECTED"),
    ]
    paths = {}
    for key, name, tier, scheme in path_specs:
        path = create_path(
            api,
            name=name,
            service_tier=tier,
            protection_scheme=scheme,
            min_surviving_legs=1,
        )
        add_segment(api, path["id"], circuit_id=circuit["id"])
        paths[key] = path

    alarm = raise_alarm(api, clock, source_circuit_id=circuit["id"])
    state = {
        "carrier": carrier,
        "carrier_id": carrier["id"],
        "circuit": circuit,
        "circuit_id": circuit["id"],
        "paths": paths,
        "path_ids": {key: path["id"] for key, path in paths.items()},
        "alarm": alarm,
        "alarm_id": alarm["id"],
        "incident_id": alarm["incident_id"],
        "liaison_headers": make_carrier_liaison_headers(carrier["id"]),
    }
    if ticket_reference is not None:
        opened_at = ticket_opened_at or _plus_thirty_minutes(clock)
        advance_clock(api, opened_at)
        ticket = open_carrier_ticket(
            api, alarm["incident_id"], circuit["id"], ticket_reference
        )
        state["ticket"] = ticket
        state["ticket_id"] = ticket["id"]
        state["ticket_opened_at"] = opened_at
    return state


def build_nlc_single_gold(
    api,
    clock: str,
    ticket_reference: Optional[str] = None,
    ticket_opened_at: Optional[str] = None,
    **carrier_overrides,
) -> dict:
    """One critical circuit carried by a single unprotected gold path.

    With one gold line the credit is a single un-split share of the monthly
    charge, which isolates the breach arithmetic from the per-line rounding.
    """
    advance_clock(api, clock)
    carrier = create_carrier(
        api,
        name="NorthLink Communications",
        carrier_code="NLC",
        **carrier_overrides,
    )
    circuit = create_circuit(
        api,
        carrier["id"],
        carrier_circuit_identifier="NLC-CKT-1001",
        site_a_code="NYC01",
        site_z_code="BOS01",
        bandwidth_mbps=200,
        mrc_cents=920000,
        monitoring_state="MONITORED",
    )
    path = create_path(
        api,
        name="Trading Gateway",
        service_tier="GOLD",
        protection_scheme="UNPROTECTED",
        min_surviving_legs=1,
    )
    segment = add_segment(api, path["id"], circuit_id=circuit["id"])
    alarm = raise_alarm(api, clock, source_circuit_id=circuit["id"])
    state = {
        "carrier": carrier,
        "carrier_id": carrier["id"],
        "circuit": circuit,
        "circuit_id": circuit["id"],
        "path": path,
        "path_id": path["id"],
        "segment_id": segment["id"],
        "alarm": alarm,
        "alarm_id": alarm["id"],
        "incident_id": alarm["incident_id"],
        "liaison_headers": make_carrier_liaison_headers(carrier["id"]),
    }
    if ticket_reference is not None:
        opened_at = ticket_opened_at or _plus_thirty_minutes(clock)
        advance_clock(api, opened_at)
        ticket = open_carrier_ticket(
            api, alarm["incident_id"], circuit["id"], ticket_reference
        )
        state["ticket"] = ticket
        state["ticket_id"] = ticket["id"]
        state["ticket_opened_at"] = opened_at
    return state


def build_ewt_two_leg(api, clock: str, **carrier_overrides) -> dict:
    """Two monitored circuits on two legs of one gold active-active path.

    Two legs with a minimum of one surviving leg is the smallest topology in
    which redundancy can be lost without the path going down, which is what the
    degraded-without-redundancy posture and the single-point-of-failure flag on
    the sibling leg both depend on.
    """
    advance_clock(api, clock)
    carrier = create_carrier(
        api, name="Eastward Telecom", carrier_code="EWT", **carrier_overrides
    )
    circuit_a = create_circuit(
        api,
        carrier["id"],
        carrier_circuit_identifier="EWT-CKT-2001",
        site_a_code="NYC01",
        site_z_code="PHL01",
        bandwidth_mbps=1000,
        mrc_cents=500000,
        monitoring_state="MONITORED",
    )
    circuit_b = create_circuit(
        api,
        carrier["id"],
        carrier_circuit_identifier="EWT-CKT-2002",
        site_a_code="NYC01",
        site_z_code="PHL01",
        bandwidth_mbps=1000,
        mrc_cents=500000,
        monitoring_state="MONITORED",
    )
    path = create_path(
        api,
        name="Core Voice Path",
        service_tier="GOLD",
        protection_scheme="ACTIVE_ACTIVE",
        min_surviving_legs=1,
    )
    segment_a = add_segment(
        api, path["id"], leg_group="LEG_A", sequence_index=1, circuit_id=circuit_a["id"]
    )
    segment_b = add_segment(
        api, path["id"], leg_group="LEG_B", sequence_index=1, circuit_id=circuit_b["id"]
    )
    return {
        "carrier": carrier,
        "carrier_id": carrier["id"],
        "circuit_a": circuit_a,
        "circuit_a_id": circuit_a["id"],
        "circuit_b": circuit_b,
        "circuit_b_id": circuit_b["id"],
        "path": path,
        "path_id": path["id"],
        "segment_a_id": segment_a["id"],
        "segment_b_id": segment_b["id"],
        "liaison_headers": make_carrier_liaison_headers(carrier["id"]),
    }


def build_srg_single_gold(
    api, clock: str, alarm_raised_at: Optional[str] = None, **carrier_overrides
) -> dict:
    """One monitored circuit as the only leg of an unprotected gold path."""
    advance_clock(api, clock)
    carrier = create_carrier(
        api, name="Southridge Networks", carrier_code="SRG", **carrier_overrides
    )
    circuit = create_circuit(
        api,
        carrier["id"],
        carrier_circuit_identifier="SRG-CKT-3001",
        site_a_code="ATL01",
        site_z_code="MIA01",
        bandwidth_mbps=500,
        mrc_cents=400000,
        monitoring_state="MONITORED",
    )
    path = create_path(
        api,
        name="Card Auth Path",
        service_tier="GOLD",
        protection_scheme="UNPROTECTED",
        min_surviving_legs=1,
    )
    segment = add_segment(api, path["id"], circuit_id=circuit["id"])
    state = {
        "carrier": carrier,
        "carrier_id": carrier["id"],
        "circuit": circuit,
        "circuit_id": circuit["id"],
        "path": path,
        "path_id": path["id"],
        "segment_id": segment["id"],
        "liaison_headers": make_carrier_liaison_headers(carrier["id"]),
    }
    if alarm_raised_at is not None:
        alarm = raise_alarm(api, alarm_raised_at, source_circuit_id=circuit["id"])
        state["alarm"] = alarm
        state["alarm_id"] = alarm["id"]
        state["incident_id"] = alarm["incident_id"]
    return state


def build_wbf_circuit(
    api,
    clock: str,
    circuit_identifier: str = "WBF-CKT-4001",
    site_z_code: str = "SLC01",
    bandwidth_mbps: int = 100,
    mrc_cents: int = 300000,
    **carrier_overrides,
) -> dict:
    """A monitored circuit with no path wiring, used for capacity and change work."""
    advance_clock(api, clock)
    carrier = create_carrier(
        api, name="Westbound Fiber", carrier_code="WBF", **carrier_overrides
    )
    circuit = create_circuit(
        api,
        carrier["id"],
        carrier_circuit_identifier=circuit_identifier,
        site_a_code="DEN01",
        site_z_code=site_z_code,
        bandwidth_mbps=bandwidth_mbps,
        mrc_cents=mrc_cents,
        monitoring_state="MONITORED",
    )
    return {
        "carrier": carrier,
        "carrier_id": carrier["id"],
        "circuit": circuit,
        "circuit_id": circuit["id"],
        "circuit_version": circuit["version"],
        "liaison_headers": make_carrier_liaison_headers(carrier["id"]),
    }


# ===========================================================================
# Tier 3 — lifecycle shortcuts
# ===========================================================================


def open_carrier_ticket(
    api,
    incident_id: str,
    circuit_id: str,
    carrier_reference: str,
    headers: Optional[dict] = None,
) -> dict:
    return get_success_data(
        api.create_carrier_ticket(
            f.carrier_ticket_payload(incident_id, circuit_id, carrier_reference),
            headers or ANALYST_HEADERS,
        )
    )


def advance_incident(
    api,
    incident_id: str,
    target_response_state: str,
    note: Optional[str] = None,
    headers: Optional[dict] = None,
) -> dict:
    return get_success_data(
        api.advance_incident_response(
            incident_id,
            f.incident_response_payload(target_response_state, note),
            headers or ANALYST_HEADERS,
        )
    )


def walk_incident_to_mitigated(api, incident_id: str) -> dict:
    """Take an incident from detected through triaged to mitigated."""
    advance_incident(api, incident_id, "TRIAGED")
    return advance_incident(api, incident_id, "MITIGATED")


def resolve_incident(
    api,
    incident_id: str,
    resolution_note: Optional[str] = None,
    user_id: Optional[str] = None,
) -> dict:
    headers = make_shift_lead_headers(user_id) if user_id else SHIFT_LEAD_HEADERS
    return get_success_data(
        api.resolve_incident(
            incident_id, f.incident_resolve_payload(resolution_note), headers
        )
    )


def run_fault_cycle(
    api,
    circuit_id: str,
    raised_at: str,
    cleared_at: str,
    resolution_note: str = "fault cleared",
) -> dict:
    """Raise, clear, triage, mitigate and resolve one complete fault.

    A resolved incident is the only thing that advances the circuit's fault
    count, so repeating this cycle is how a circuit is walked up the chronic
    ladder.
    """
    advance_clock(api, raised_at)
    alarm = raise_alarm(api, raised_at, source_circuit_id=circuit_id)
    incident_id = alarm["incident_id"]
    advance_clock(api, cleared_at)
    clear_alarm(api, alarm["id"], cleared_at)
    walk_incident_to_mitigated(api, incident_id)
    incident = resolve_incident(api, incident_id, resolution_note)
    return {
        "alarm_id": alarm["id"],
        "incident_id": incident_id,
        "incident": incident,
    }


def file_test_result(
    api,
    ticket_id: str,
    test_type: str = "BERT",
    outcome: str = "FAIL",
    notes: Optional[str] = None,
    headers: Optional[dict] = None,
) -> dict:
    return get_success_data(
        api.create_test_result(
            ticket_id,
            f.test_result_payload(test_type, outcome, notes),
            headers or ANALYST_HEADERS,
        )
    )


def carrier_reports_restored(
    api, ticket_id: str, carrier_id: str, restored_at: str
) -> dict:
    """The carrier's own claim that service is back, filed by its liaison."""
    return get_success_data(
        api.carrier_update_ticket(
            ticket_id,
            f.carrier_update_payload("RESTORED", restored_at),
            make_carrier_liaison_headers(carrier_id),
        )
    )


def confirm_restoration(
    api,
    ticket_id: str,
    soak_passed: bool = True,
    user_id: Optional[str] = None,
) -> dict:
    headers = make_shift_lead_headers(user_id) if user_id else SHIFT_LEAD_HEADERS
    return get_success_data(
        api.confirm_restoration(
            ticket_id, f.confirm_restoration_payload(soak_passed), headers
        )
    )


def restore_and_confirm(
    api,
    ticket_id: str,
    carrier_id: str,
    alarm_id: str,
    restored_at: str,
    confirmed_at: str,
    confirmer_user_id: Optional[str] = None,
) -> dict:
    """Walk a ticket to closed-restored: report, clear, soak, then confirm.

    The confirmation is what closes the ticket and, when the service target was
    missed, drafts the credit claim, so this is the shortest route to a carrier
    holding real credit exposure.
    """
    advance_clock(api, restored_at)
    carrier_reports_restored(api, ticket_id, carrier_id, restored_at)
    clear_alarm(api, alarm_id, restored_at)
    advance_clock(api, confirmed_at)
    return confirm_restoration(api, ticket_id, True, confirmer_user_id)


def find_auto_drafted_claim(api, ticket_id: str) -> Optional[dict]:
    """Return the claim automatically drafted for a ticket, if one exists."""
    body = api.list_sla_credit_claims(
        VENDOR_MANAGER_HEADERS, params={"carrier_ticket_id": ticket_id}
    ).json()
    rows = body["data"]
    return rows[0] if rows else None


def count_claims_for_ticket(api, ticket_id: str) -> int:
    body = api.list_sla_credit_claims(
        VENDOR_MANAGER_HEADERS, params={"carrier_ticket_id": ticket_id}
    ).json()
    return body["meta"]["total_count"]


# ===========================================================================
# Tier 4 — accumulation and threshold targeting
# ===========================================================================


def record_reading(
    api,
    circuit_id: str,
    sample_at: str,
    utilization_pct: float,
    direction: str = "INGRESS",
) -> dict:
    return get_success_data(
        api.create_capacity_reading(
            circuit_id,
            f.capacity_reading_payload(sample_at, utilization_pct, direction),
            CAPACITY_PLANNER_HEADERS,
        )
    )


def record_readings(api, circuit_id: str, samples: list) -> list:
    """Record a run of samples given as (sample_at, utilization_pct) pairs.

    Samples must arrive in strictly increasing sample order, which is exactly
    the constraint the endpoint itself enforces.
    """
    recorded = []
    for sample_at, utilization_pct in samples:
        recorded.append(record_reading(api, circuit_id, sample_at, utilization_pct))
    return recorded


def create_manual_upgrade_order(
    api,
    circuit_id: str,
    target_bandwidth_mbps: int,
    expected_circuit_version: int,
    expedite: Optional[bool] = None,
    user_id: Optional[str] = None,
) -> dict:
    from .test_users import make_capacity_planner_headers

    headers = (
        make_capacity_planner_headers(user_id) if user_id else CAPACITY_PLANNER_HEADERS
    )
    return get_success_data(
        api.create_upgrade_order(
            f.upgrade_order_payload(
                circuit_id, target_bandwidth_mbps, expected_circuit_version, expedite
            ),
            headers,
        )
    )


def submit_upgrade_order(api, order_id: str, user_id: Optional[str] = None) -> dict:
    from .test_users import make_capacity_planner_headers

    headers = (
        make_capacity_planner_headers(user_id) if user_id else CAPACITY_PLANNER_HEADERS
    )
    return get_success_data(api.submit_upgrade_order(order_id, {}, headers))


def approve_upgrade_order(api, order_id: str, user_id: Optional[str] = None) -> dict:
    from .test_users import make_vendor_manager_headers

    headers = (
        make_vendor_manager_headers(user_id) if user_id else VENDOR_MANAGER_HEADERS
    )
    return get_success_data(api.approve_upgrade_order(order_id, {}, headers))


def set_order_state(api, order_id: str, target_state: str) -> dict:
    return get_success_data(
        api.set_upgrade_order_state(
            order_id, f.order_state_payload(target_state), CAPACITY_PLANNER_HEADERS
        )
    )


# ===========================================================================
# Tier 5 — planned change, verification and review
# ===========================================================================


def propose_window(
    api,
    circuit_id: str,
    window_start: str,
    window_end: str,
    origin: str = "INTERNAL_CHANGE",
    suppresses_monitoring: Optional[bool] = None,
    headers: Optional[dict] = None,
    carrier_id: Optional[str] = None,
) -> dict:
    """Announce planned work. Carrier-notified windows must come from the liaison."""
    if headers is None:
        headers = (
            make_carrier_liaison_headers(carrier_id)
            if origin == "CARRIER_NOTIFIED" and carrier_id
            else ANALYST_HEADERS
        )
    return get_success_data(
        api.create_maintenance_window(
            f.maintenance_window_payload(
                circuit_id,
                window_start,
                window_end,
                origin=origin,
                suppresses_monitoring=suppresses_monitoring,
            ),
            headers,
        )
    )


def review_window(
    api,
    window_id: str,
    decision: str = "APPROVED",
    risk_acknowledged: Optional[bool] = None,
    user_id: Optional[str] = None,
) -> dict:
    headers = make_shift_lead_headers(user_id) if user_id else SHIFT_LEAD_HEADERS
    return get_success_data(
        api.review_maintenance_window(
            window_id, f.window_review_payload(decision, risk_acknowledged), headers
        )
    )


def set_window_state(api, window_id: str, target_state: str) -> dict:
    return get_success_data(
        api.set_maintenance_window_state(
            window_id, f.window_state_payload(target_state), SHIFT_LEAD_HEADERS
        )
    )


def build_approved_carrier_window(
    api,
    circuit_id: str,
    carrier_id: str,
    window_start: str,
    window_end: str,
    suppresses_monitoring: bool = False,
    risk_acknowledged: bool = True,
) -> dict:
    """A carrier-notified window, filed by the liaison and approved by the lead.

    Only approved or in-progress carrier-notified windows contribute excluded
    minutes to the carrier's restoration clock, so this pair of calls is the
    prerequisite for any exclusion arithmetic.
    """
    window = propose_window(
        api,
        circuit_id,
        window_start,
        window_end,
        origin="CARRIER_NOTIFIED",
        suppresses_monitoring=suppresses_monitoring,
        carrier_id=carrier_id,
    )
    approved = review_window(
        api, window["id"], "APPROVED", risk_acknowledged=risk_acknowledged
    )
    return {"window_id": window["id"], "window": approved}


def schedule_failover_test(
    api,
    path_id: str,
    tested_leg_group: str,
    scheduled_start: str,
    scheduled_end: str,
    user_id: Optional[str] = None,
) -> dict:
    headers = make_shift_lead_headers(user_id) if user_id else SHIFT_LEAD_HEADERS
    return get_success_data(
        api.create_failover_test(
            f.failover_test_payload(
                path_id, tested_leg_group, scheduled_start, scheduled_end
            ),
            headers,
        )
    )


def start_failover_test(api, test_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(
        api.start_failover_test(test_id, {}, headers or ANALYST_HEADERS)
    )


def record_failover_result(
    api,
    test_id: str,
    outcome: str,
    surviving_leg_count: Optional[int] = None,
    user_id: Optional[str] = None,
) -> dict:
    headers = make_shift_lead_headers(user_id) if user_id else SHIFT_LEAD_HEADERS
    return get_success_data(
        api.record_failover_result(
            test_id,
            f.failover_result_payload(outcome, surviving_leg_count),
            headers,
        )
    )


def create_vendor_review(
    api, carrier_id: str, period_start: str, period_end: str
) -> dict:
    return get_success_data(
        api.create_vendor_review(
            f.vendor_review_payload(carrier_id, period_start, period_end),
            VENDOR_MANAGER_HEADERS,
        )
    )


def decide_vendor_review(
    api, review_id: str, decision: str, justification: Optional[str] = None
) -> dict:
    return get_success_data(
        api.decide_vendor_review(
            review_id,
            f.review_decide_payload(decision, justification),
            VENDOR_MANAGER_HEADERS,
        )
    )


# ===========================================================================
# Small instant helpers
# ===========================================================================


def _plus_thirty_minutes(instant: str) -> str:
    """Return the instant thirty minutes later, in the same rendering."""
    from datetime import datetime, timedelta, timezone

    parsed = datetime.strptime(instant, "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=timezone.utc
    )
    return (parsed + timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ")


def at(day: str, hhmm: str) -> str:
    """Compose a request instant from a calendar day and an `HH:MM` time."""
    return f"{day}T{hhmm}:00Z"


def stamped(day: str, hhmm: str) -> str:
    """Compose the instant as the service renders it, with milliseconds."""
    return f"{day}T{hhmm}:00.000Z"
