"""Composite setup helpers used by test_suite/.

Each fixture encapsulates a multi-step preamble that more than one test
needs. Setup calls go through get_success_data() (the lenient validator)
so any unexpected status surfaces as a clear "Setup failed" rather than as
an assertion deep inside a test.

PRD §2.1 ownership threading: although every role is opaque, technician
ownership is enforced by field equality against the opaque X-User-ID
stored on WorkOrder.assigned_technician_id. These fixtures always thread
the SAME opaque ID into both the assign-payload and any subsequent
technician-role header, so ownership checks succeed by construction.

PRD §2.1 SoD: TopologyApprover acting on a TopologyVersion MUST differ
from submitted_by; MaintenanceSupervisor verifying a WorkOrder MUST
differ from assigned_technician_id. Fixtures use distinct opaque IDs
(`USER_IDS['topology_engineer']` vs `USER_IDS['topology_approver']`,
`USER_IDS['technician']` vs `USER_IDS['supervisor']`) so the happy paths
satisfy SoD by construction.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import ApiClient, api_client
from .factories import (
    advance_clock_payload,
    assign_work_order_payload,
    complete_work_order_payload,
    create_device_payload,
    create_dma_payload,
    create_network_payload,
    create_node_payload,
    create_segment_payload,
    create_topology_version_payload,
    create_work_order_payload,
    dispatch_investigation_payload,
    iso_from_epoch_ms,
    iso_z,
    post_reading_payload,
    request_parts_payload,
    resolve_alert_payload,
    suppress_alert_payload,
    unique_code,
    unique_suffix,
    verify_work_order_payload,
    water_balance_report_payload,
)
from .test_users import TEST_USERS, USER_IDS, make_technician_headers


# ---------------------------------------------------------------------------
# Header shortcuts — convenience aliases used throughout fixtures.
# ---------------------------------------------------------------------------
TE = TEST_USERS["topology_engineer_headers"]
TE_ALT = TEST_USERS["topology_engineer_headers_alt"]
TA = TEST_USERS["topology_approver_headers"]
TA_ALT = TEST_USERS["topology_approver_headers_alt"]
CO = TEST_USERS["control_operator_headers"]
CO_ALT = TEST_USERS["control_operator_headers_alt"]
SUP = TEST_USERS["supervisor_headers"]
SUP_ALT = TEST_USERS["supervisor_headers_alt"]
TECH = TEST_USERS["technician_headers"]
TECH_ALT = TEST_USERS["technician_headers_alt"]
TECH_3 = TEST_USERS["technician_headers_third"]
AUD = TEST_USERS["auditor_headers"]


TECH_USER_ID = USER_IDS["technician"]
TECH_USER_ID_ALT = USER_IDS["technician_alt"]
TECH_USER_ID_3 = USER_IDS["technician_third"]
SUP_USER_ID = USER_IDS["supervisor"]
SUP_USER_ID_ALT = USER_IDS["supervisor_alt"]
TE_USER_ID = USER_IDS["topology_engineer"]
TE_USER_ID_ALT = USER_IDS["topology_engineer_alt"]
TA_USER_ID = USER_IDS["topology_approver"]
TA_USER_ID_ALT = USER_IDS["topology_approver_alt"]
CO_USER_ID = USER_IDS["control_operator"]


# ===========================================================================
# Network / clock helpers
# ===========================================================================
def create_network(api: ApiClient = api_client,
                   **overrides: Any) -> Dict[str, Any]:
    """PRD §3.1 creation — returns the Network resource with clock_epoch_ms
    initialized to server wall-clock time at creation."""
    resp = api.create_network(create_network_payload(**overrides), TA)
    return get_success_data(resp)


def advance_clock(api: ApiClient, network_id: str,
                  advance_ms: int) -> Dict[str, Any]:
    """PRD §3.1: 'A ControlOperator invokes an admin-only test-driving
    capability on the network with an advance_ms body parameter, which
    must be strictly greater than zero.'"""
    resp = api.advance_clock(network_id,
                             advance_clock_payload(advance_ms), CO)
    return get_success_data(resp)


def get_network(api: ApiClient, network_id: str) -> Dict[str, Any]:
    resp = api.get_network(network_id, TA)
    return get_success_data(resp)


def clock_now_iso(network: Dict[str, Any]) -> str:
    """Return ISO 8601 UTC string corresponding to Network.clock_epoch_ms."""
    return iso_from_epoch_ms(network["clock_epoch_ms"])


# ===========================================================================
# Topology helpers — DRAFT → UNDER_REVIEW → PUBLISHED
# ===========================================================================
def create_draft_topology(api: ApiClient, network_id: str,
                          parent_version_id: Optional[str] = None
                          ) -> Dict[str, Any]:
    resp = api.create_topology_version(
        network_id,
        create_topology_version_payload(parent_version_id=parent_version_id),
        TE,
    )
    return get_success_data(resp)


def add_node(api: ApiClient, network_id: str, version_id: str,
             **overrides: Any) -> Dict[str, Any]:
    resp = api.create_node(network_id, version_id,
                           create_node_payload(**overrides), TE)
    return get_success_data(resp)


def add_segment(api: ApiClient, network_id: str, version_id: str,
                **overrides: Any) -> Dict[str, Any]:
    resp = api.create_segment(network_id, version_id,
                              create_segment_payload(**overrides), TE)
    return get_success_data(resp)


def submit_topology(api: ApiClient, network_id: str,
                    version_id: str) -> Dict[str, Any]:
    resp = api.submit_topology_version(network_id, version_id, TE)
    return get_success_data(resp)


def approve_topology(api: ApiClient, network_id: str,
                     version_id: str) -> Dict[str, Any]:
    """Approve a version with TA — distinct from TE which submitted it
    (PRD §2.1 SoD)."""
    resp = api.approve_topology_version(network_id, version_id, TA)
    return get_success_data(resp)


def create_dma(api: ApiClient, network_id: str,
               **overrides: Any) -> Dict[str, Any]:
    resp = api.create_dma(network_id,
                          create_dma_payload(**overrides), TE)
    return get_success_data(resp)


def get_dma(api: ApiClient, network_id: str,
            dma_id: str) -> Dict[str, Any]:
    resp = api.get_dma(network_id, dma_id, CO)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier-2 setup: a network with an initial published topology and one DMA
# containing two junction nodes connected by a segment.
# ---------------------------------------------------------------------------
def setup_published_network_with_one_segment(
    api: ApiClient = api_client,
    segment_length_m: float = 100.0,
    segment_diameter_mm: int = 200,
    segment_material: str = "PVC",
    inlet_elevation_m: float = 10.0,
    outlet_elevation_m: float = 10.0,
) -> Dict[str, Any]:
    """Most-common preamble.

    Builds: Network → DMA (with inlet_node_codes=[node_from]) → DRAFT
    TopologyVersion with two JUNCTION nodes (in DMA) and one segment
    between them → submit → approve → PUBLISHED. Returns a dict with
    named handles to every resource.

    PRD §3.3 calls inlet_node_codes the nodes whose sensors "count toward
    input reconciliation", and PRD §3.9 says input_volume is integrated
    "over the DMA's inlet devices". Tests that produce water-balance
    reports therefore expect at least one inlet to be registered on the
    DMA, so this base fixture pre-mints stable node_codes and registers
    node_from as the DMA inlet (and node_to as the outlet).
    """
    network = create_network(api)
    # Pre-mint stable node_codes so the DMA can reference the inlet.
    inlet_node_code = unique_code("BN")
    outlet_node_code = unique_code("BN")

    dma = create_dma(api, network["id"],
                     inlet_node_codes=[inlet_node_code],
                     outlet_node_codes=[outlet_node_code])
    version = create_draft_topology(api, network["id"])

    node_from = add_node(api, network["id"], version["id"],
                         node_code=inlet_node_code,
                         dma_id=dma["id"], kind="JUNCTION",
                         elevation_m=inlet_elevation_m)
    node_to = add_node(api, network["id"], version["id"],
                       node_code=outlet_node_code,
                       dma_id=dma["id"], kind="JUNCTION",
                       elevation_m=outlet_elevation_m)

    segment = add_segment(api, network["id"], version["id"],
                          from_node_code=node_from["node_code"],
                          to_node_code=node_to["node_code"],
                          length_m=segment_length_m,
                          diameter_mm=segment_diameter_mm,
                          material=segment_material)

    submit_topology(api, network["id"], version["id"])
    approve_topology(api, network["id"], version["id"])

    return {
        "network": get_network(api, network["id"]),
        "dma": get_dma(api, network["id"], dma["id"]),
        "version": version,
        "node_from": node_from,
        "node_to": node_to,
        "segment": segment,
    }


# ---------------------------------------------------------------------------
# Tier-2 setup: a network with a published topology containing a configurable
# set of node_codes/segments. Useful for difficulty tests that need a richer
# graph (e.g., 120 CUSTOMER_TAP descendants downstream of a segment).
# ---------------------------------------------------------------------------
def setup_published_network_with_customer_taps(
    api: ApiClient,
    num_customer_taps: int = 120,
) -> Dict[str, Any]:
    """Build network → DMA → topology with one JUNCTION 'J_from', one
    JUNCTION 'J_to', the segment S1 between them, and a chain of
    CUSTOMER_TAP nodes downstream of J_to. PRD §3.8 priority calc counts
    CUSTOMER_TAP descendants reachable downstream of target_segment_code.
    """
    network = create_network(api)
    dma = create_dma(api, network["id"])
    version = create_draft_topology(api, network["id"])

    j_from = add_node(api, network["id"], version["id"],
                      dma_id=dma["id"], kind="JUNCTION", elevation_m=20.0)
    j_to = add_node(api, network["id"], version["id"],
                    dma_id=dma["id"], kind="JUNCTION", elevation_m=10.0)
    segment = add_segment(api, network["id"], version["id"],
                          from_node_code=j_from["node_code"],
                          to_node_code=j_to["node_code"],
                          length_m=100.0,
                          diameter_mm=200,
                          material="PVC")

    taps: List[Dict[str, Any]] = []
    tap_segments: List[Dict[str, Any]] = []
    upstream_code = j_to["node_code"]
    for i in range(num_customer_taps):
        tap = add_node(api, network["id"], version["id"],
                       dma_id=dma["id"], kind="CUSTOMER_TAP",
                       elevation_m=5.0)
        taps.append(tap)
        seg = add_segment(api, network["id"], version["id"],
                          from_node_code=upstream_code,
                          to_node_code=tap["node_code"],
                          length_m=10.0,
                          diameter_mm=50,
                          material="PVC")
        tap_segments.append(seg)
        # Note: chain them off j_to (star topology) so every tap is
        # downstream of S1; an implementer that builds a tree of taps off
        # j_to is equally valid because each is reachable downstream.
        upstream_code = j_to["node_code"]

    submit_topology(api, network["id"], version["id"])
    approve_topology(api, network["id"], version["id"])

    return {
        "network": get_network(api, network["id"]),
        "dma": get_dma(api, network["id"], dma["id"]),
        "version": version,
        "node_from": j_from,
        "node_to": j_to,
        "segment": segment,
        "customer_taps": taps,
        "tap_segments": tap_segments,
    }


# ===========================================================================
# Device helpers
# ===========================================================================
def create_device(api: ApiClient, network_id: str,
                  **overrides: Any) -> Dict[str, Any]:
    resp = api.create_device(network_id,
                             create_device_payload(**overrides), CO)
    return get_success_data(resp)


def activate_device(api: ApiClient, network_id: str,
                    device_id: str) -> Dict[str, Any]:
    resp = api.activate_device(network_id, device_id, CO)
    return get_success_data(resp)


def get_device(api: ApiClient, network_id: str,
               device_id: str) -> Dict[str, Any]:
    resp = api.get_device(network_id, device_id, CO)
    return get_success_data(resp)


def create_and_activate_pressure_device(
    api: ApiClient,
    network_id: str,
    mounted_on_node_code: str,
    valid_range_min: float = 200.0,
    valid_range_max: float = 600.0,
    polling_interval_s: int = 3600,
) -> Dict[str, Any]:
    """Create a PRESSURE device, then activate it. Used by tests that need
    to push readings against a device with a known static baseline (the
    midpoint of valid_range)."""
    device = create_device(api, network_id,
                           mounted_on_node_code=mounted_on_node_code,
                           sensor_kind="PRESSURE",
                           valid_range_min=valid_range_min,
                           valid_range_max=valid_range_max,
                           polling_interval_s=polling_interval_s)
    return activate_device(api, network_id, device["id"])


def create_and_activate_flow_device(
    api: ApiClient,
    network_id: str,
    mounted_on_node_code: str,
    valid_range_min: float = 0.0,
    valid_range_max: float = 100.0,
    polling_interval_s: int = 3600,
) -> Dict[str, Any]:
    device = create_device(api, network_id,
                           mounted_on_node_code=mounted_on_node_code,
                           sensor_kind="FLOW",
                           valid_range_min=valid_range_min,
                           valid_range_max=valid_range_max,
                           polling_interval_s=polling_interval_s)
    return activate_device(api, network_id, device["id"])


def create_and_activate_meter_device(
    api: ApiClient,
    network_id: str,
    mounted_on_node_code: str,
    valid_range_min: float = 0.0,
    valid_range_max: float = 1_000_000.0,
    polling_interval_s: int = 3600,
) -> Dict[str, Any]:
    device = create_device(api, network_id,
                           mounted_on_node_code=mounted_on_node_code,
                           sensor_kind="METER",
                           valid_range_min=valid_range_min,
                           valid_range_max=valid_range_max,
                           polling_interval_s=polling_interval_s)
    return activate_device(api, network_id, device["id"])


def post_reading(api: ApiClient, network_id: str, device_id: str,
                 observed_at: str, raw_value: float,
                 idempotency_key: Optional[str] = None,
                 strict_mode: Optional[bool] = None,
                 expect_status: Optional[int] = None
                 ) -> Dict[str, Any]:
    params: Optional[Dict[str, Any]] = None
    if strict_mode is not None:
        params = {"strict_mode": str(strict_mode).lower()}
    payload = post_reading_payload(observed_at, raw_value, idempotency_key)
    resp = api.post_reading(network_id, device_id, payload, CO, params=params)
    return get_success_data(resp)


# ===========================================================================
# Alert helpers
# ===========================================================================
def list_alerts(api: ApiClient, network_id: str,
                **params: Any) -> List[Dict[str, Any]]:
    resp = api.list_alerts(network_id, CO, params=params or None)
    body = resp.json()
    return body["data"]


def get_latest_alert_for_device(api: ApiClient, network_id: str,
                                device_id: str) -> Optional[Dict[str, Any]]:
    """Return the most-recent alert whose trigger_device_id matches.

    PRD §3.5 says newly-opened alerts are queryable via GET /alerts; this
    helper short-circuits the test's listing pattern."""
    alerts = list_alerts(api, network_id)
    matches = [a for a in alerts if a.get("trigger_device_id") == device_id]
    if not matches:
        return None
    # PRD §2.3: list endpoints sort by created_at ascending.
    return matches[-1]


def acknowledge_alert(api: ApiClient, network_id: str,
                      alert_id: str) -> Dict[str, Any]:
    resp = api.acknowledge_alert(network_id, alert_id, CO)
    return get_success_data(resp)


def resolve_alert(api: ApiClient, network_id: str, alert_id: str,
                  note: str = "ok") -> Dict[str, Any]:
    resp = api.resolve_alert(network_id, alert_id,
                             resolve_alert_payload(note), CO)
    return get_success_data(resp)


def suppress_alert(api: ApiClient, network_id: str, alert_id: str,
                   note: str = "false positive") -> Dict[str, Any]:
    resp = api.suppress_alert(network_id, alert_id,
                              suppress_alert_payload(note), CO)
    return get_success_data(resp)


def open_investigation_from_alert(api: ApiClient, network_id: str,
                                  alert_id: str) -> Dict[str, Any]:
    """Acknowledge alert (if not already), then open investigation. PRD
    §3.6: 'From ACKNOWLEDGED, the operator may either resolve the alert
    directly ... or open a LeakInvestigation.'
    """
    alert_resp = api.get_alert(network_id, alert_id, CO)
    alert = get_success_data(alert_resp)
    if alert["status"] == "OPEN":
        acknowledge_alert(api, network_id, alert_id)
    resp = api.create_investigation(network_id, alert_id, CO)
    return get_success_data(resp)


# ===========================================================================
# WorkOrder helpers
# ===========================================================================
def create_work_order(api: ApiClient, network_id: str,
                      target_segment_code: str,
                      origin: str = "INSPECTION_FINDING",
                      alert_id: Optional[str] = None,
                      investigation_id: Optional[str] = None,
                      ) -> Dict[str, Any]:
    payload = create_work_order_payload(
        origin=origin,
        target_segment_code=target_segment_code,
        alert_id=alert_id,
        investigation_id=investigation_id,
    )
    resp = api.create_work_order(network_id, payload, SUP)
    return get_success_data(resp)


def assign_work_order(api: ApiClient, network_id: str,
                      work_order_id: str,
                      technician_user_id: str = TECH_USER_ID
                      ) -> Dict[str, Any]:
    """Assign work-order to a technician identified by opaque user_id.

    PRD §2.1: technician ownership is field equality between Technician's
    X-User-ID and WorkOrder.assigned_technician_id, so the same opaque ID
    must be threaded into every later Technician-role call on this work
    order. The default TECH_USER_ID matches the default TECH header in
    this module.
    """
    resp = api.assign_work_order(network_id, work_order_id,
                                 assign_work_order_payload(technician_user_id),
                                 SUP)
    return get_success_data(resp)


def start_work_order(api: ApiClient, network_id: str,
                     work_order_id: str,
                     technician_headers: Dict[str, str] = TECH
                     ) -> Dict[str, Any]:
    resp = api.start_work_order(network_id, work_order_id,
                                technician_headers)
    return get_success_data(resp)


def complete_work_order(api: ApiClient, network_id: str,
                        work_order_id: str,
                        leak_class: str = "LEAK_CONFIRMED",
                        technician_headers: Dict[str, str] = TECH
                        ) -> Dict[str, Any]:
    resp = api.complete_work_order(network_id, work_order_id,
                                   complete_work_order_payload(leak_class),
                                   technician_headers)
    return get_success_data(resp)


def verify_work_order(api: ApiClient, network_id: str,
                      work_order_id: str,
                      outcome: str = "PASS",
                      supervisor_headers: Dict[str, str] = SUP_ALT
                      ) -> Dict[str, Any]:
    """Verify a work order.

    PRD §2.1 SoD: supervisor performing verify MUST differ from
    assigned_technician_id. Default supervisor (SUP_ALT) is a distinct
    opaque ID from the default technician.
    """
    resp = api.verify_work_order(network_id, work_order_id,
                                 verify_work_order_payload(outcome),
                                 supervisor_headers)
    return get_success_data(resp)


# ===========================================================================
# Tier-3 fixture: a published network + active pressure device on the
# upstream node of the test segment. Used by all alert-classification tests.
# ===========================================================================
def setup_published_with_active_pressure_device(
    api: ApiClient = api_client,
    valid_range_min: float = 200.0,
    valid_range_max: float = 600.0,
    polling_interval_s: int = 3600,
) -> Dict[str, Any]:
    """Returns dict with keys: network, dma, version, node_from, node_to,
    segment, device. Device is mounted on node_from."""
    base = setup_published_network_with_one_segment(api)
    device = create_and_activate_pressure_device(
        api, base["network"]["id"],
        mounted_on_node_code=base["node_from"]["node_code"],
        valid_range_min=valid_range_min,
        valid_range_max=valid_range_max,
        polling_interval_s=polling_interval_s,
    )
    base["device"] = device
    return base


# ===========================================================================
# Tier-4 fixture: setup with cumulative usage / inlet flow readings for
# water-balance tests. Builds an inlet FLOW device + METER device, pushes
# readings whose integral over the window equals a known input_volume_m3,
# and returns the env so a test can call POST /water-balance-reports.
# ===========================================================================
def setup_dma_with_inlet_flow_and_meter(
    api: ApiClient = api_client,
    inlet_flow_lps: float = 5.0,
    billed_meter_first: float = 0.0,
    billed_meter_last: float = 300.0,
    window_seconds: int = 86400,
) -> Dict[str, Any]:
    """Build a fully-published network with one DMA (with node_from as
    inlet), a FLOW inlet device, and a billed METER device. Push two
    readings on each device so the integration window has well-defined
    input_volume_m3 and billed_consumption_m3.

    Returns the resources plus the window_start / window_end ISO strings
    the test should pass to POST /water-balance-reports.
    """
    base = setup_published_network_with_one_segment(api)
    network = base["network"]
    network_id = network["id"]
    inlet_node_code = base["node_from"]["node_code"]
    outlet_node_code = base["node_to"]["node_code"]

    flow_dev = create_and_activate_flow_device(
        api, network_id, mounted_on_node_code=inlet_node_code,
        valid_range_min=0.0, valid_range_max=100.0,
        polling_interval_s=3600,
    )
    # PRD §3.9: "METER devices in the DMA tagged with billed_flag true"
    # contribute to billed_consumption_m3, so flag the meter accordingly.
    meter_dev_raw = create_device(
        api, network_id,
        mounted_on_node_code=outlet_node_code,
        sensor_kind="METER",
        valid_range_min=0.0, valid_range_max=1_000_000.0,
        polling_interval_s=3600,
        billed_flag=True,
        authorized=True,
    )
    meter_dev = activate_device(api, network_id, meter_dev_raw["id"])

    # Pick window aligned to the current clock to satisfy the backdate
    # check (PRD §3.4 backdate window is 7 days).
    network = get_network(api, network_id)
    clock_now_ms = network["clock_epoch_ms"]
    window_start_ms = clock_now_ms - window_seconds * 1000
    window_end_ms = clock_now_ms
    window_start = iso_from_epoch_ms(window_start_ms)
    window_end = iso_from_epoch_ms(window_end_ms)

    # Push two flow readings, both with the same constant value, so the
    # piecewise-constant integration yields flow_lps * window_seconds
    # liters across the window (= flow_lps * window_seconds / 1000 m^3).
    post_reading(api, network_id, flow_dev["id"], window_start,
                 inlet_flow_lps)
    post_reading(api, network_id, flow_dev["id"],
                 iso_from_epoch_ms(window_start_ms + window_seconds * 500),
                 inlet_flow_lps)

    # Push first/last meter readings inside the window.
    post_reading(api, network_id, meter_dev["id"],
                 iso_from_epoch_ms(window_start_ms + 1000),
                 billed_meter_first)
    post_reading(api, network_id, meter_dev["id"],
                 iso_from_epoch_ms(window_end_ms - 1000),
                 billed_meter_last)

    return {
        **base,
        "inlet_device": flow_dev,
        "meter_device": meter_dev,
        "window_start": window_start,
        "window_end": window_end,
        "window_seconds": window_seconds,
        "expected_input_volume_lps": inlet_flow_lps,
    }


# ===========================================================================
# Tier-3 fixture: end-to-end work order in AWAITING_VERIFICATION with a
# post-completion ACCEPTED reading on the repaired segment's device — i.e.,
# the supervisor can call /verify outcome=PASS.
# ===========================================================================
def setup_work_order_awaiting_verification(
    api: ApiClient = api_client,
    technician_user_id: str = TECH_USER_ID,
    technician_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Build base scenario, create a WO, assign-start-complete it, then
    push one ACCEPTED reading on the repaired segment's device after
    completed_at so PRD §3.8 verify-precondition is satisfied.
    """
    if technician_headers is None:
        technician_headers = make_technician_headers(technician_user_id)

    base = setup_published_with_active_pressure_device(api)
    network_id = base["network"]["id"]

    wo = create_work_order(api, network_id,
                           target_segment_code=base["segment"]["segment_code"],
                           origin="INSPECTION_FINDING")
    assign_work_order(api, network_id, wo["id"],
                      technician_user_id=technician_user_id)
    start_work_order(api, network_id, wo["id"], technician_headers)
    complete_work_order(api, network_id, wo["id"],
                        technician_headers=technician_headers)

    # Push one ACCEPTED reading after completed_at — PRD §3.8: 'at least
    # one ACCEPTED Reading has been ingested after completed_at from a
    # Device mounted on the repaired segment.' Advance the logical clock
    # by 1 ms before ingest so the reading's ingested_at is strictly
    # greater than the completed_at stamp (which is also taken from the
    # logical clock).
    advance_clock(api, network_id, 1)
    network = get_network(api, network_id)
    observed_at = iso_from_epoch_ms(network["clock_epoch_ms"])
    post_reading(api, network_id, base["device"]["id"],
                 observed_at, 400.0)  # mid-range = ACCEPTED

    base["work_order"] = wo
    base["technician_user_id"] = technician_user_id
    base["technician_headers"] = technician_headers
    return base


# ===========================================================================
# Tier-4 fixture: setup with N CRITICAL alerts on a DMA. Used to drive the
# DMA posture cascade (OPEN → RESTRICTED → FROZEN) and the work_order_priority
# DMA-score test.
# ===========================================================================
def setup_dma_with_n_critical_alerts(
    api: ApiClient = api_client,
    n_critical: int = 3,
) -> Dict[str, Any]:
    """Open N CRITICAL alerts on a fresh DMA by pushing N out-of-range
    readings on N distinct pressure devices (different alert_kinds /
    devices so dedup does not merge them).

    Returns the base scenario plus the list of opened alert IDs and the
    refreshed DMA whose open_critical_alert_count == n_critical.
    """
    base = setup_published_network_with_one_segment(api)
    network_id = base["network"]["id"]

    # Need N distinct trigger devices to avoid dedup-merge (PRD §3.5
    # dedups by (trigger_device_id, alert_kind)).
    alerts: List[Dict[str, Any]] = []
    for i in range(n_critical):
        # Add a JUNCTION node to host each device.
        # Re-using base topology — we cannot mutate PUBLISHED topology, so
        # create a fresh draft version.
        # Simpler: just create devices mounted on existing node_from.
        # Each device needs its own (device_code) — but they'll share
        # alert_kind=PRESSURE_HIGH. Dedup is (trigger_device_id,
        # alert_kind), so distinct devices produce distinct alerts.
        dev = create_and_activate_pressure_device(
            api, network_id,
            mounted_on_node_code=base["node_from"]["node_code"],
            valid_range_min=200.0, valid_range_max=600.0,
            polling_interval_s=3600,
        )
        network = get_network(api, network_id)
        observed_at = iso_from_epoch_ms(network["clock_epoch_ms"] - 1000)
        # Raw 520 → deviation_pct = |520 - 400| / 400 * 100 = 30.0 → CRITICAL.
        post_reading(api, network_id, dev["id"], observed_at, 520.0)
        alert = get_latest_alert_for_device(api, network_id, dev["id"])
        assert alert is not None, \
            "Setup failed: post_reading at raw=520 did not open an Alert"
        alerts.append(alert)

    base["critical_alerts"] = alerts
    base["dma"] = get_dma(api, network_id, base["dma"]["id"])
    return base


# ===========================================================================
# Tier-2: setup a TopologyVersion in UNDER_REVIEW (so subsequent
# approve/reject tests have a target).
# ===========================================================================
def setup_under_review_version(
    api: ApiClient = api_client,
) -> Dict[str, Any]:
    """Create network → DMA → DRAFT with one node + one segment → submit.

    Returns the base resources; version.status == 'UNDER_REVIEW'.
    Submitter is TE (USER_IDS['topology_engineer']) — approver in tests
    should use TA (different opaque ID) to satisfy SoD.
    """
    network = create_network(api)
    dma = create_dma(api, network["id"])
    version = create_draft_topology(api, network["id"])
    j_from = add_node(api, network["id"], version["id"],
                      dma_id=dma["id"], kind="JUNCTION")
    j_to = add_node(api, network["id"], version["id"],
                    dma_id=dma["id"], kind="JUNCTION")
    segment = add_segment(api, network["id"], version["id"],
                          from_node_code=j_from["node_code"],
                          to_node_code=j_to["node_code"])
    submitted = submit_topology(api, network["id"], version["id"])
    return {
        "network": network, "dma": dma,
        "version": submitted,
        "node_from": j_from, "node_to": j_to,
        "segment": segment,
    }


# ===========================================================================
# Difficulty-design specific composite fixtures
# ===========================================================================
def setup_two_published_versions(
    api: ApiClient = api_client,
) -> Dict[str, Any]:
    """For topology_version_cycle_rollback / topology_rollback_preserves_*.

    Setup: V1 published (with node J1 + segment S1) → V2 published (which
    auto-supersedes V1). Returns network, dma, v1, v2, and segment refs.
    """
    base = setup_published_network_with_one_segment(api)
    network_id = base["network"]["id"]
    v1_id = base["version"]["id"]

    # Build V2 (child of V1) with completely fresh node_codes / segment.
    v2 = create_draft_topology(api, network_id, parent_version_id=v1_id)
    j_from = add_node(api, network_id, v2["id"],
                      dma_id=base["dma"]["id"], kind="JUNCTION",
                      elevation_m=10.0)
    j_to = add_node(api, network_id, v2["id"],
                    dma_id=base["dma"]["id"], kind="JUNCTION",
                    elevation_m=10.0)
    seg2 = add_segment(api, network_id, v2["id"],
                       from_node_code=j_from["node_code"],
                       to_node_code=j_to["node_code"])
    submit_topology(api, network_id, v2["id"])
    approve_topology(api, network_id, v2["id"])
    v2_resp = api.get_topology_version(network_id, v2["id"], TA)
    v2_final = get_success_data(v2_resp)

    v1_resp = api.get_topology_version(network_id, v1_id, TA)
    v1_final = get_success_data(v1_resp)

    return {
        "network": get_network(api, network_id),
        "dma": base["dma"],
        "v1": v1_final,
        "v2": v2_final,
        "v1_segment_code": base["segment"]["segment_code"],
        "v2_segment_code": seg2["segment_code"],
        "v2_node_from": j_from,
        "v2_node_to": j_to,
    }


def setup_v2_removes_node_with_device_and_alert(
    api: ApiClient = api_client,
) -> Dict[str, Any]:
    """For topology_approval_three_hop_cascade.

    V1 published with node J1 in DMA D1 + segment S1; Device DV1
    ACTIVE mounted on J1; one open Alert A1 with trigger_device_id=DV1.
    V2 drafted *removing* J1 and S1 (V2 has only J2 / no J1).

    Returns: network, dma, v1, v2 (UNDER_REVIEW), device, alert.
    """
    base = setup_published_network_with_one_segment(api)
    network_id = base["network"]["id"]
    j1 = base["node_from"]
    j2_old = base["node_to"]

    # Create + activate device on J1.
    device = create_and_activate_pressure_device(
        api, network_id, mounted_on_node_code=j1["node_code"],
        valid_range_min=200.0, valid_range_max=600.0,
        polling_interval_s=3600,
    )

    # Push reading that opens a CRITICAL alert.
    network = get_network(api, network_id)
    observed_at = iso_from_epoch_ms(network["clock_epoch_ms"] - 1000)
    post_reading(api, network_id, device["id"], observed_at, 520.0)
    alert = get_latest_alert_for_device(api, network_id, device["id"])

    # Build V2 *without* J1 — V2 has only one new junction + one fresh
    # segment, so when V2 publishes, DV1 will have no mount and A1 will
    # be on a removed segment.
    v2 = create_draft_topology(api, network_id,
                               parent_version_id=base["version"]["id"])
    new_from = add_node(api, network_id, v2["id"],
                        dma_id=base["dma"]["id"], kind="JUNCTION")
    new_to = add_node(api, network_id, v2["id"],
                      dma_id=base["dma"]["id"], kind="JUNCTION")
    add_segment(api, network_id, v2["id"],
                from_node_code=new_from["node_code"],
                to_node_code=new_to["node_code"])
    submit_topology(api, network_id, v2["id"])

    return {
        "network": get_network(api, network_id),
        "dma": base["dma"],
        "v1": base["version"],
        "v2": get_success_data(
            api.get_topology_version(network_id, v2["id"], TA)
        ),
        "j1": j1,
        "old_j2": j2_old,
        "device": device,
        "alert": alert,
        "segment_v1": base["segment"],
    }


def setup_alert_critical_on_open_dma(
    api: ApiClient = api_client,
) -> Dict[str, Any]:
    """For critical_alert_dma_freeze_cascade.

    Build a published network, an ACTIVE pressure device in DMA D1, and a
    pre-created NEW WorkOrder targeting the segment. Returns these
    handles so the test can post a CRITICAL reading and observe the
    cascade.
    """
    base = setup_published_with_active_pressure_device(api)
    network_id = base["network"]["id"]

    wo = create_work_order(
        api, network_id,
        target_segment_code=base["segment"]["segment_code"],
        origin="INSPECTION_FINDING",
    )
    base["work_order"] = wo
    return base


__all__ = [
    # Header aliases
    "TE", "TE_ALT", "TA", "TA_ALT", "CO", "CO_ALT",
    "SUP", "SUP_ALT", "TECH", "TECH_ALT", "TECH_3", "AUD",
    "TECH_USER_ID", "TECH_USER_ID_ALT", "TECH_USER_ID_3",
    "SUP_USER_ID", "SUP_USER_ID_ALT", "TE_USER_ID", "TE_USER_ID_ALT",
    "TA_USER_ID", "TA_USER_ID_ALT", "CO_USER_ID",
    # Network / clock
    "create_network", "advance_clock", "get_network", "clock_now_iso",
    # Topology
    "create_draft_topology", "add_node", "add_segment",
    "submit_topology", "approve_topology",
    # DMA
    "create_dma", "get_dma",
    # Composite (Tier-2)
    "setup_published_network_with_one_segment",
    "setup_published_network_with_customer_taps",
    "setup_under_review_version",
    # Device
    "create_device", "activate_device", "get_device",
    "create_and_activate_pressure_device",
    "create_and_activate_flow_device",
    "create_and_activate_meter_device",
    "post_reading",
    # Composite (Tier-3)
    "setup_published_with_active_pressure_device",
    # Alerts
    "list_alerts", "get_latest_alert_for_device",
    "acknowledge_alert", "resolve_alert", "suppress_alert",
    "open_investigation_from_alert",
    # WorkOrders
    "create_work_order", "assign_work_order", "start_work_order",
    "complete_work_order", "verify_work_order",
    "setup_work_order_awaiting_verification",
    # Composite (Tier-4)
    "setup_dma_with_inlet_flow_and_meter",
    "setup_dma_with_n_critical_alerts",
    # Difficulty-design composites
    "setup_two_published_versions",
    "setup_v2_removes_node_with_device_and_alert",
    "setup_alert_critical_on_open_dma",
]
