"""Composite setup helpers.

Every helper here builds its preconditions from scratch through PRD-declared
endpoints only, because each test runs against an empty database.  Setup calls
use the lenient success validator so a broken precondition surfaces as a setup
failure rather than a confusing assertion failure.
"""
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    claim_line_item,
    create_charging_port_payload,
    create_customer_complaint_payload,
    create_host_site_payload,
    create_maintenance_dispatch_payload,
    create_outage_event_payload,
    create_part_reservation_payload,
    create_spare_part_payload,
    create_station_payload,
    create_uptime_report_payload,
    triage_payload,
)
from .test_users import (
    AUDITOR_1,
    OPERATOR_1,
    PROGRAM_ADMIN_1,
    SUPPORT_AGENT_1,
    TECHNICIAN_1,
    make_compliance_auditor_headers,
    make_customer_support_agent_headers,
    make_field_technician_headers,
    make_network_operator_headers,
    make_program_administrator_headers,
)

# ---------------------------------------------------------------------------
# Canonical port specifications
# ---------------------------------------------------------------------------
#: A dispenser with all three interoperability flags true, a roaming-compliant
#: OCPI version and a CERTIFIED payment terminal — the configuration that scores
#: 100.00 on its own.
FULLY_COMPLIANT_PORT: Dict[str, Any] = {
    "contactless_enabled": True,
    "plug_and_charge_enabled": True,
    "price_display_verified": True,
    "roaming_ocpi_version": "V2_2_1",
    "certify": "CERTIFIED",
}

DEFAULT_RATED_POWER_KW = {"L2_19": 19.20, "DCFC_150": 150.00, "DCFC_350": 350.00}


# ---------------------------------------------------------------------------
# Tier 0 — primitives
# ---------------------------------------------------------------------------
def set_clock(current_utc: str, headers: Optional[Dict[str, str]] = None) -> dict:
    """Drive the logical clock to a fixed instant.  Any role may do this."""
    headers = headers or make_network_operator_headers(OPERATOR_1)
    return get_success_data(api_client.set_clock(current_utc, headers))


def register_host_site(
    site_code: str = "HS-1",
    committed_service_capacity_kw: float = 400.00,
    operator_user_id: str = OPERATOR_1,
    **overrides,
) -> dict:
    payload = create_host_site_payload(
        site_code,
        committed_service_capacity_kw=committed_service_capacity_kw,
        **overrides,
    )
    return get_success_data(
        api_client.create_host_site(payload, make_network_operator_headers(operator_user_id))
    )


def register_commissionable_host_site(
    site_code: str = "HS-1",
    committed_service_capacity_kw: float = 400.00,
    operator_user_id: str = OPERATOR_1,
    **overrides,
) -> dict:
    """A host site whose agreement, power and parking gates all already pass."""
    defaults = {
        "agreement_status": "EXECUTED",
        "power_upgrade_status": "ENERGIZED",
        "parking_enforcement_mode": "TOWING_ENFORCED",
    }
    defaults.update(overrides)
    return register_host_site(
        site_code,
        committed_service_capacity_kw=committed_service_capacity_kw,
        operator_user_id=operator_user_id,
        **defaults,
    )


def create_station(
    host_site_id: str,
    station_code: str = "ST-1",
    power_class: str = "DCFC_150",
    declared_port_count: int = 1,
    corridor_designated: bool = False,
    operator_user_id: str = OPERATOR_1,
    **overrides,
) -> dict:
    payload = create_station_payload(
        host_site_id,
        station_code,
        power_class=power_class,
        declared_port_count=declared_port_count,
        corridor_designated=corridor_designated,
        **overrides,
    )
    return get_success_data(
        api_client.create_station(payload, make_network_operator_headers(operator_user_id))
    )


def install_charging_port(
    station_id: str,
    dispenser_serial: str = "DS-1",
    rated_power_kw: float = 150.00,
    operator_user_id: str = OPERATOR_1,
    **overrides,
) -> dict:
    payload = create_charging_port_payload(
        station_id, dispenser_serial, rated_power_kw=rated_power_kw, **overrides
    )
    return get_success_data(
        api_client.create_charging_port(payload, make_network_operator_headers(operator_user_id))
    )


def certify_terminal(
    port_id: str, certification_status: str = "CERTIFIED", auditor_user_id: str = AUDITOR_1
) -> dict:
    return get_success_data(
        api_client.record_terminal_certification(
            port_id, certification_status, make_compliance_auditor_headers(auditor_user_id)
        )
    )


def move_station_status(
    station_id: str, target_status: str, operator_user_id: str = OPERATOR_1
) -> dict:
    return get_success_data(
        api_client.transition_station_status(
            station_id, target_status, make_network_operator_headers(operator_user_id)
        )
    )


def commission_station(station_id: str, operator_user_id: str = OPERATOR_1) -> dict:
    return get_success_data(
        api_client.commission_station(station_id, make_network_operator_headers(operator_user_id))
    )


def read_station(station_id: str) -> dict:
    return get_success_data(
        api_client.get_station(station_id, make_network_operator_headers(OPERATOR_1))
    )


def read_charging_port(port_id: str) -> dict:
    return get_success_data(
        api_client.get_charging_port(port_id, make_network_operator_headers(OPERATOR_1))
    )


def read_outage_event(outage_event_id: str) -> dict:
    return get_success_data(
        api_client.get_outage_event(outage_event_id, make_network_operator_headers(OPERATOR_1))
    )


def read_dispatch(dispatch_id: str) -> dict:
    return get_success_data(
        api_client.get_maintenance_dispatch(
            dispatch_id, make_network_operator_headers(OPERATOR_1)
        )
    )


def read_spare_part(spare_part_id: str) -> dict:
    return get_success_data(
        api_client.get_spare_part(spare_part_id, make_network_operator_headers(OPERATOR_1))
    )


def read_part_reservation(reservation_id: str) -> dict:
    return get_success_data(
        api_client.get_part_reservation(reservation_id, make_network_operator_headers(OPERATOR_1))
    )


def read_host_site(host_site_id: str) -> dict:
    return get_success_data(
        api_client.get_host_site(host_site_id, make_network_operator_headers(OPERATOR_1))
    )


def read_uptime_report(uptime_report_id: str) -> dict:
    return get_success_data(
        api_client.get_uptime_report(uptime_report_id, make_network_operator_headers(OPERATOR_1))
    )


def read_claim(claim_id: str) -> dict:
    return get_success_data(
        api_client.get_reimbursement_claim(claim_id, make_network_operator_headers(OPERATOR_1))
    )


def read_complaint(complaint_id: str) -> dict:
    return get_success_data(
        api_client.get_customer_complaint(
            complaint_id, make_customer_support_agent_headers(SUPPORT_AGENT_1)
        )
    )


# ---------------------------------------------------------------------------
# Tier 1/2 — the station bootstrap every workflow sits on
# ---------------------------------------------------------------------------
def setup_station(
    clock: Optional[str] = None,
    site_code: str = "HS-1",
    station_code: str = "ST-1",
    committed_service_capacity_kw: float = 400.00,
    power_class: str = "DCFC_150",
    declared_port_count: int = 1,
    corridor_designated: bool = False,
    host_site_overrides: Optional[Dict[str, Any]] = None,
    ports: Optional[List[Dict[str, Any]]] = None,
    stop_at: str = "OPERATIONAL",
    operator_user_id: str = OPERATOR_1,
    auditor_user_id: str = AUDITOR_1,
) -> Dict[str, Any]:
    """Build a host site, a station and its dispensers, then walk the station's
    lifecycle as far as `stop_at` (``DRAFT``, ``COMMISSIONING`` or
    ``OPERATIONAL``).

    `ports` is a list of per-dispenser specifications.  Each entry may carry any
    charging-port input field plus a ``certify`` key holding ``"CERTIFIED"``,
    ``"REVOKED"`` or ``None``.  The default is a single fully compliant
    dispenser, which scores 100.00 on its own.

    Returns ``{"host_site", "station", "ports"}`` with the freshly read station.
    """
    if clock is not None:
        set_clock(clock)

    host_site_overrides = dict(host_site_overrides or {})
    host_site = register_commissionable_host_site(
        site_code,
        committed_service_capacity_kw=committed_service_capacity_kw,
        operator_user_id=operator_user_id,
        **host_site_overrides,
    )

    station = create_station(
        host_site["id"],
        station_code,
        power_class=power_class,
        declared_port_count=declared_port_count,
        corridor_designated=corridor_designated,
        operator_user_id=operator_user_id,
    )

    if ports is None:
        ports = [dict(FULLY_COMPLIANT_PORT)]

    installed: List[dict] = []
    for index, spec in enumerate(ports, start=1):
        spec = dict(spec)
        certify = spec.pop("certify", None)
        dispenser_serial = spec.pop(
            "dispenser_serial", f"DS-{station_code}-{index}"
        )
        rated_power_kw = spec.pop(
            "rated_power_kw", DEFAULT_RATED_POWER_KW.get(power_class, 150.00)
        )
        port = install_charging_port(
            station["id"],
            dispenser_serial,
            rated_power_kw=rated_power_kw,
            operator_user_id=operator_user_id,
            **spec,
        )
        if certify:
            port = certify_terminal(port["id"], certify, auditor_user_id=auditor_user_id)
        installed.append(port)

    if stop_at in ("COMMISSIONING", "OPERATIONAL"):
        station = move_station_status(
            station["id"], "COMMISSIONING", operator_user_id=operator_user_id
        )
    if stop_at == "OPERATIONAL":
        station = commission_station(station["id"], operator_user_id=operator_user_id)

    return {"host_site": host_site, "station": station, "ports": installed}


def setup_operational_station(
    clock: Optional[str] = None,
    site_code: str = "HS-1",
    station_code: str = "ST-1",
    power_class: str = "DCFC_150",
    port_count: int = 1,
    committed_service_capacity_kw: float = 400.00,
    corridor_designated: bool = False,
    host_site_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """An OPERATIONAL station carrying `port_count` fully compliant dispensers."""
    return setup_station(
        clock=clock,
        site_code=site_code,
        station_code=station_code,
        committed_service_capacity_kw=committed_service_capacity_kw,
        power_class=power_class,
        declared_port_count=port_count,
        corridor_designated=corridor_designated,
        host_site_overrides=host_site_overrides,
        ports=[dict(FULLY_COMPLIANT_PORT) for _ in range(port_count)],
        stop_at="OPERATIONAL",
    )


# ---------------------------------------------------------------------------
# Tier 3 — the fault / dispatch / repair chain
# ---------------------------------------------------------------------------
def ingest_outage(
    port_id: str,
    detected_at: str,
    fault_class: str = "MAJOR",
    fault_code: str = "OCPP-GEN-01",
    operator_user_id: str = OPERATOR_1,
    **overrides,
) -> dict:
    payload = create_outage_event_payload(
        port_id, detected_at, fault_class=fault_class, fault_code=fault_code, **overrides
    )
    return get_success_data(
        api_client.create_outage_event(payload, make_network_operator_headers(operator_user_id))
    )


def classify_outage(
    outage_event_id: str,
    fault_class: str = "MAJOR",
    operator_user_id: str = OPERATOR_1,
    **overrides,
) -> dict:
    payload: Dict[str, Any] = {"fault_class": fault_class}
    payload.update(overrides)
    return get_success_data(
        api_client.classify_outage_event(
            outage_event_id, payload, make_network_operator_headers(operator_user_id)
        )
    )


def ingest_and_classify_outage(
    port_id: str,
    detected_at: str,
    fault_class: str = "MAJOR",
    fault_code: str = "OCPP-GEN-01",
    operator_user_id: str = OPERATOR_1,
    **overrides,
) -> dict:
    outage = ingest_outage(
        port_id,
        detected_at,
        fault_class=fault_class,
        fault_code=fault_code,
        operator_user_id=operator_user_id,
        **overrides,
    )
    return classify_outage(
        outage["id"], fault_class=fault_class, operator_user_id=operator_user_id
    )


def create_dispatch(
    outage_event_id: str,
    port_id: str,
    window_start_at: str,
    window_end_at: str,
    technician_user_id: str = TECHNICIAN_1,
    technician_certification_class: str = "DCFC_BASIC",
    operator_user_id: str = OPERATOR_1,
    **overrides,
) -> dict:
    payload = create_maintenance_dispatch_payload(
        outage_event_id,
        port_id,
        technician_user_id,
        window_start_at,
        window_end_at,
        technician_certification_class=technician_certification_class,
        **overrides,
    )
    return get_success_data(
        api_client.create_maintenance_dispatch(
            payload, make_network_operator_headers(operator_user_id)
        )
    )


def post_progress(dispatch_id: str, event: str, technician_user_id: str = TECHNICIAN_1) -> dict:
    return get_success_data(
        api_client.post_dispatch_progress(
            dispatch_id, event, make_field_technician_headers(technician_user_id)
        )
    )


def drive_dispatch_to_on_site(dispatch_id: str, technician_user_id: str = TECHNICIAN_1) -> dict:
    post_progress(dispatch_id, "EN_ROUTE", technician_user_id)
    return post_progress(dispatch_id, "ARRIVE", technician_user_id)


def complete_dispatch(dispatch_id: str, technician_user_id: str = TECHNICIAN_1) -> dict:
    return get_success_data(
        api_client.complete_dispatch(
            dispatch_id, make_field_technician_headers(technician_user_id)
        )
    )


def run_repair_cycle(
    port_id: str,
    detected_at: str,
    window_start_at: str,
    window_end_at: str,
    completed_at: Optional[str] = None,
    fault_class: str = "MAJOR",
    fault_code: str = "OCPP-GEN-01",
    technician_user_id: str = TECHNICIAN_1,
    technician_certification_class: str = "DCFC_BASIC",
    operator_user_id: str = OPERATOR_1,
    excluded_cause_claim: Optional[str] = None,
) -> Dict[str, Any]:
    """Ingest a fault, classify it, dispatch a technician, arrive, and — when
    `completed_at` is supplied — advance the clock to that instant and close the
    repair out.  Returns ``{"outage", "dispatch"}`` as last observed.
    """
    extra: Dict[str, Any] = {}
    if excluded_cause_claim is not None:
        extra["excluded_cause_claim"] = excluded_cause_claim

    outage = ingest_outage(
        port_id,
        detected_at,
        fault_class=fault_class,
        fault_code=fault_code,
        operator_user_id=operator_user_id,
        **extra,
    )
    outage = classify_outage(
        outage["id"], fault_class=fault_class, operator_user_id=operator_user_id
    )
    dispatch = create_dispatch(
        outage["id"],
        port_id,
        window_start_at,
        window_end_at,
        technician_user_id=technician_user_id,
        technician_certification_class=technician_certification_class,
        operator_user_id=operator_user_id,
    )
    dispatch = drive_dispatch_to_on_site(dispatch["id"], technician_user_id)
    if completed_at is not None:
        set_clock(completed_at)
        dispatch = complete_dispatch(dispatch["id"], technician_user_id)
    return {"outage": read_outage_event(outage["id"]), "dispatch": dispatch}


def request_exclusion(
    outage_event_id: str,
    excluded_cause_claim: Optional[str] = None,
    operator_user_id: str = OPERATOR_1,
) -> dict:
    payload: Dict[str, Any] = {"action": "REQUEST"}
    if excluded_cause_claim is not None:
        payload["excluded_cause_claim"] = excluded_cause_claim
    return get_success_data(
        api_client.submit_exclusion_action(
            outage_event_id, payload, make_network_operator_headers(operator_user_id)
        )
    )


def adjudicate_exclusion(
    outage_event_id: str, action: str, auditor_user_id: str = AUDITOR_1
) -> dict:
    return get_success_data(
        api_client.submit_exclusion_action(
            outage_event_id, {"action": action}, make_compliance_auditor_headers(auditor_user_id)
        )
    )


def approve_exclusion(
    outage_event_id: str,
    excluded_cause_claim: Optional[str] = None,
    operator_user_id: str = OPERATOR_1,
    auditor_user_id: str = AUDITOR_1,
) -> dict:
    """REQUEST as the operator, then APPROVE as the auditor."""
    request_exclusion(
        outage_event_id, excluded_cause_claim, operator_user_id=operator_user_id
    )
    return adjudicate_exclusion(outage_event_id, "APPROVE", auditor_user_id=auditor_user_id)


# ---------------------------------------------------------------------------
# Tier 3 — the depot chain
# ---------------------------------------------------------------------------
def setup_spare_part_with_stock(
    part_number: str = "SP-1",
    part_class: str = "DISPENSER",
    lead_time_days: int = 3,
    on_hand_qty: int = 10,
    operator_user_id: str = OPERATOR_1,
) -> dict:
    """Create a depot part and restock it.  Returns the part as last observed,
    so ``part["version"]`` is the value a reservation must pin."""
    part = get_success_data(
        api_client.create_spare_part(
            create_spare_part_payload(
                part_number, part_class=part_class, lead_time_days=lead_time_days
            ),
            make_network_operator_headers(operator_user_id),
        )
    )
    if on_hand_qty:
        part = get_success_data(
            api_client.restock_spare_part(
                part["id"], on_hand_qty, make_network_operator_headers(operator_user_id)
            )
        )
    return part


def reserve_parts(
    dispatch_id: str,
    spare_part_id: str,
    qty: int,
    expected_spare_part_version: int,
    operator_user_id: str = OPERATOR_1,
) -> dict:
    return get_success_data(
        api_client.create_part_reservation(
            create_part_reservation_payload(
                dispatch_id, spare_part_id, qty, expected_spare_part_version
            ),
            make_network_operator_headers(operator_user_id),
        )
    )


# ---------------------------------------------------------------------------
# Tier 4/5 — the uptime reporting and claim chain
# ---------------------------------------------------------------------------
def declare_reporting_period(
    station_id: str, period_start: str, period_end: str, operator_user_id: str = OPERATOR_1
) -> dict:
    return get_success_data(
        api_client.create_uptime_report(
            create_uptime_report_payload(station_id, period_start, period_end),
            make_network_operator_headers(operator_user_id),
        )
    )


def compute_provisional(uptime_report_id: str, operator_user_id: str = OPERATOR_1) -> dict:
    return get_success_data(
        api_client.compute_provisional_uptime(
            uptime_report_id, make_network_operator_headers(operator_user_id)
        )
    )


def finalize_report(uptime_report_id: str, auditor_user_id: str = AUDITOR_1) -> dict:
    return get_success_data(
        api_client.finalize_uptime_report(
            uptime_report_id, make_compliance_auditor_headers(auditor_user_id)
        )
    )


def submit_report(uptime_report_id: str, operator_user_id: str = OPERATOR_1) -> dict:
    return get_success_data(
        api_client.submit_uptime_report(
            uptime_report_id, make_network_operator_headers(operator_user_id)
        )
    )


def program_review(
    uptime_report_id: str, outcome: str, program_admin_user_id: str = PROGRAM_ADMIN_1
) -> dict:
    return get_success_data(
        api_client.program_review_uptime_report(
            uptime_report_id, outcome, make_program_administrator_headers(program_admin_user_id)
        )
    )


def setup_accepted_report(
    station_id: str,
    period_start: str,
    period_end: str,
    operator_user_id: str = OPERATOR_1,
    auditor_user_id: str = AUDITOR_1,
    program_admin_user_id: str = PROGRAM_ADMIN_1,
) -> dict:
    """Declare a period and walk it DRAFT → PROVISIONAL → FINAL → SUBMITTED →
    ACCEPTED.  The returned report carries the `version` a claim must pin."""
    report = declare_reporting_period(
        station_id, period_start, period_end, operator_user_id=operator_user_id
    )
    compute_provisional(report["id"], operator_user_id=operator_user_id)
    finalize_report(report["id"], auditor_user_id=auditor_user_id)
    submit_report(report["id"], operator_user_id=operator_user_id)
    return program_review(
        report["id"], "ACCEPT", program_admin_user_id=program_admin_user_id
    )


def setup_submitted_report(
    station_id: str,
    period_start: str,
    period_end: str,
    operator_user_id: str = OPERATOR_1,
    auditor_user_id: str = AUDITOR_1,
) -> dict:
    """Walk a period only as far as SUBMITTED, leaving it unclaimable."""
    report = declare_reporting_period(
        station_id, period_start, period_end, operator_user_id=operator_user_id
    )
    compute_provisional(report["id"], operator_user_id=operator_user_id)
    finalize_report(report["id"], auditor_user_id=auditor_user_id)
    return submit_report(report["id"], operator_user_id=operator_user_id)


def file_claim(
    uptime_report_id: str,
    line_items: List[dict],
    expected_uptime_report_version: int,
    operator_user_id: str = OPERATOR_1,
) -> dict:
    return get_success_data(
        api_client.create_reimbursement_claim(
            {
                "uptime_report_id": uptime_report_id,
                "line_items": line_items,
                "expected_uptime_report_version": expected_uptime_report_version,
            },
            make_network_operator_headers(operator_user_id),
        )
    )


def open_claim_review(claim_id: str, program_admin_user_id: str = PROGRAM_ADMIN_1) -> dict:
    return get_success_data(
        api_client.review_reimbursement_claim(
            claim_id, make_program_administrator_headers(program_admin_user_id)
        )
    )


def setup_claim_in_review(
    station_id: str,
    port_id: str,
    period_start: str,
    period_end: str,
    amounts_cents: Optional[List[int]] = None,
    category: str = "OANDM",
    operator_user_id: str = OPERATOR_1,
    auditor_user_id: str = AUDITOR_1,
    program_admin_user_id: str = PROGRAM_ADMIN_1,
) -> Dict[str, Any]:
    """Full money chain: accepted report → filed claim → claim opened for
    adjudication.  Returns ``{"report", "claim"}`` with the claim in REVIEW and
    its snapshot written."""
    report = setup_accepted_report(
        station_id,
        period_start,
        period_end,
        operator_user_id=operator_user_id,
        auditor_user_id=auditor_user_id,
        program_admin_user_id=program_admin_user_id,
    )
    line_items = [
        claim_line_item(port_id, amount, category)
        for amount in (amounts_cents or [1000])
    ]
    claim = file_claim(
        report["id"], line_items, report["version"], operator_user_id=operator_user_id
    )
    claim = open_claim_review(claim["id"], program_admin_user_id=program_admin_user_id)
    return {"report": read_uptime_report(report["id"]), "claim": claim}


# ---------------------------------------------------------------------------
# Tier 3 — the complaint / refund chain
# ---------------------------------------------------------------------------
def intake_complaint(
    station_id: str,
    port_id: str,
    session_started_at: str,
    session_ended_at: str,
    session_energy_kwh: float,
    session_price_per_kwh_cents: int,
    session_charged_cents: int,
    support_agent_user_id: str = SUPPORT_AGENT_1,
    **overrides,
) -> dict:
    payload = create_customer_complaint_payload(
        station_id,
        port_id,
        session_started_at,
        session_ended_at,
        session_energy_kwh,
        session_price_per_kwh_cents,
        session_charged_cents,
        **overrides,
    )
    return get_success_data(
        api_client.create_customer_complaint(
            payload, make_customer_support_agent_headers(support_agent_user_id)
        )
    )


def triage_complaint(
    complaint_id: str,
    disposition: str = "LINK_OUTAGE",
    linked_outage_event_id: Optional[str] = None,
    support_agent_user_id: str = SUPPORT_AGENT_1,
) -> dict:
    return get_success_data(
        api_client.triage_customer_complaint(
            complaint_id,
            triage_payload(disposition, linked_outage_event_id),
            make_customer_support_agent_headers(support_agent_user_id),
        )
    )


def request_refund(
    complaint_id: str, refund_basis: str, support_agent_user_id: str = SUPPORT_AGENT_1
) -> dict:
    return get_success_data(
        api_client.request_session_refund(
            complaint_id, refund_basis, make_customer_support_agent_headers(support_agent_user_id)
        )
    )


def decide_refund(complaint_id: str, decision: str, auditor_user_id: str = AUDITOR_1) -> dict:
    return get_success_data(
        api_client.decide_session_refund(
            complaint_id, decision, make_compliance_auditor_headers(auditor_user_id)
        )
    )


def act_on_refund_ledger(
    complaint_id: str,
    action: str,
    support_agent_user_id: str = SUPPORT_AGENT_1,
    auditor_user_id: str = AUDITOR_1,
) -> dict:
    """SETTLE is the support agent's action; REVERSE is the auditor's."""
    if action == "SETTLE":
        headers = make_customer_support_agent_headers(support_agent_user_id)
    else:
        headers = make_compliance_auditor_headers(auditor_user_id)
    return get_success_data(api_client.act_on_refund_ledger(complaint_id, action, headers))


def setup_triaged_complaint_on_open_fault(
    clock: str,
    outage_detected_at: str,
    session_started_at: str,
    session_ended_at: str,
    session_energy_kwh: float,
    session_price_per_kwh_cents: int,
    session_charged_cents: int,
    session_idle_fee_cents: int = 0,
    fault_class: str = "CRITICAL",
    fault_code: str = "EVSE-CRIT-02",
    site_code: str = "HS-RF-1",
    station_code: str = "ST-RF-1",
    station_clock: Optional[str] = None,
    complaint_count: int = 1,
) -> Dict[str, Any]:
    """An OPERATIONAL station carrying one dispenser, one still-open fault on
    that dispenser, and `complaint_count` byte-identical complaints already
    triaged onto that fault.

    Returns ``{"host_site", "station", "port", "outage", "complaints"}``.
    """
    scenario = setup_operational_station(
        clock=station_clock or clock,
        site_code=site_code,
        station_code=station_code,
        port_count=1,
    )
    port = scenario["ports"][0]

    set_clock(clock)
    outage = ingest_outage(
        port["id"], outage_detected_at, fault_class=fault_class, fault_code=fault_code
    )

    complaints = []
    for _ in range(complaint_count):
        complaint = intake_complaint(
            scenario["station"]["id"],
            port["id"],
            session_started_at,
            session_ended_at,
            session_energy_kwh,
            session_price_per_kwh_cents,
            session_charged_cents,
            session_idle_fee_cents=session_idle_fee_cents,
        )
        complaint = triage_complaint(
            complaint["id"], "LINK_OUTAGE", linked_outage_event_id=outage["id"]
        )
        complaints.append(complaint)

    return {
        "host_site": scenario["host_site"],
        "station": read_station(scenario["station"]["id"]),
        "port": read_charging_port(port["id"]),
        "outage": read_outage_event(outage["id"]),
        "complaints": complaints,
    }
