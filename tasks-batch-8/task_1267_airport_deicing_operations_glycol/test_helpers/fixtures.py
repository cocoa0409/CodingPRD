"""Composite setup helpers for PRD-specific test scenarios.

Every fixture builds its preconditions from scratch using only PRD-declared
endpoints. The test harness restarts the server before every test, so no
state carries over between tests.
"""
from typing import Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    DEFAULTS,
    assign_request_payload,
    complete_operation_payload,
    create_airline_payload,
    create_deice_request_payload,
    create_discharge_permit_payload,
    create_fluid_tank_payload,
    create_inspection_payload,
    create_invoice_payload,
    create_pad_payload,
    create_recycling_contract_payload,
    create_spill_report_payload,
    create_station_payload,
    create_weather_event_payload,
    escalate_payload,
    record_shipment_payload,
    replenish_payload,
    start_operation_payload,
)
from .test_users import (
    TEST_USERS,
    make_airline_rep_headers,
    make_environmental_officer_headers,
    make_inspector_headers,
)


# ---------------------------------------------------------------------------
# Tier 1: single-entity creators (no cross-entity wiring)
# ---------------------------------------------------------------------------

def create_station(**overrides) -> dict:
    """Create a station. Returns the created station."""
    payload = create_station_payload(**overrides)
    resp = api_client.create_station(payload, TEST_USERS["station_admin_headers"])
    return get_success_data(resp)


def create_station_with_permit(
    permit_overrides: Optional[dict] = None,
    **station_overrides,
) -> Tuple[dict, dict]:
    """Create a station and an ACTIVE permit. Returns (station, permit)."""
    station = create_station(**station_overrides)
    permit_payload = create_discharge_permit_payload(
        station["id"], expected_station_version=station["version"]
    )
    if permit_overrides:
        permit_payload.update(permit_overrides)
    resp = api_client.create_discharge_permit(
        permit_payload, TEST_USERS["station_admin_headers"]
    )
    permit = get_success_data(resp)
    return station, permit


def create_pad(station_id: str, **overrides) -> dict:
    payload = create_pad_payload(station_id, **overrides)
    resp = api_client.create_pad(payload, TEST_USERS["station_admin_headers"])
    return get_success_data(resp)


def create_fluid_tank(station_id: str, **overrides) -> dict:
    payload = create_fluid_tank_payload(station_id, **overrides)
    resp = api_client.create_fluid_tank(payload, TEST_USERS["station_admin_headers"])
    return get_success_data(resp)


def create_airline(**overrides) -> dict:
    payload = create_airline_payload(**overrides)
    resp = api_client.create_airline(payload, TEST_USERS["station_admin_headers"])
    return get_success_data(resp)


def create_weather_event(station_id: str, **overrides) -> dict:
    payload = create_weather_event_payload(station_id, **overrides)
    resp = api_client.create_weather_event(payload, TEST_USERS["station_admin_headers"])
    return get_success_data(resp)


def create_and_activate_weather_event(station_id: str, **overrides) -> dict:
    """Create a FORECASTED weather event and activate it. Returns the event."""
    event = create_weather_event(station_id, **overrides)
    resp = api_client.activate_weather_event(
        event["id"], TEST_USERS["station_admin_headers"]
    )
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 2: base operational scenario (station + permit + tank + pad + airline)
# ---------------------------------------------------------------------------

def setup_operational_base(
    station_overrides: Optional[dict] = None,
    tank_overrides: Optional[dict] = None,
    pad_overrides: Optional[dict] = None,
    airline_overrides: Optional[dict] = None,
) -> Tuple[dict, dict, dict, dict, dict]:
    """Create station + ACTIVE permit + tank + pad + airline.

    Returns (station, permit, tank, pad, airline).
    """
    st_kw = station_overrides or {}
    station = create_station(**st_kw)
    permit_payload = create_discharge_permit_payload(
        station["id"], expected_station_version=station["version"]
    )
    resp = api_client.create_discharge_permit(
        permit_payload, TEST_USERS["station_admin_headers"]
    )
    permit = get_success_data(resp)

    tk_kw = tank_overrides or {}
    tank = create_fluid_tank(station["id"], **tk_kw)

    pd_kw = pad_overrides or {}
    pad = create_pad(station["id"], **pd_kw)

    al_kw = airline_overrides or {}
    airline = create_airline(**al_kw)

    return station, permit, tank, pad, airline


# ---------------------------------------------------------------------------
# Tier 3: request + assignment + operation lifecycle
# ---------------------------------------------------------------------------

def create_reserved_request(
    airline: dict,
    station: dict,
    tank: dict,
    size_class: str = "MEDIUM",
    **request_overrides,
) -> dict:
    """Create a deice request that successfully reserves fluid from `tank`.
    Returns the created request."""
    payload = create_deice_request_payload(
        airline["id"], station["id"], size_class=size_class, **request_overrides
    )
    resp = api_client.create_deice_request(
        payload, make_airline_rep_headers(airline["id"])
    )
    return get_success_data(resp)


def assign_request_to_pad(
    request: dict,
    pad: dict,
    window_start: str = DEFAULTS["WINDOW_START"],
    window_end: str = DEFAULTS["WINDOW_END"],
) -> dict:
    """Assign a QUEUED request to a pad. Returns the updated request."""
    payload = assign_request_payload(
        pad["id"], window_start=window_start, window_end=window_end
    )
    resp = api_client.assign_deice_request(
        request["id"], payload, TEST_USERS["pad_operator_headers"]
    )
    return get_success_data(resp)


def get_operation_for_request(request_id: str) -> dict:
    """Fetch the single operation created for a request."""
    resp = api_client.list_deice_operations(
        TEST_USERS["pad_operator_headers"], params={"request_id": request_id}
    )
    data = get_success_data(resp)
    assert isinstance(data, list) and len(data) == 1, (
        f"expected exactly one operation for request {request_id}"
    )
    return data[0]


def record_acceptance_inspection(operation_id: str, inspector_id: str = "insp-1") -> dict:
    """Record an ACCEPTANCE PASS inspection. Returns the inspection."""
    payload = create_inspection_payload(
        operation_id, kind="ACCEPTANCE", result="PASS"
    )
    resp = api_client.create_inspection(
        payload, make_inspector_headers(inspector_id)
    )
    return get_success_data(resp)


def record_post_treatment_inspection(
    operation_id: str,
    result: str = "PASS",
    inspector_id: str = "insp-2",
    findings: str = "",
) -> dict:
    """Record a POST_TREATMENT inspection. Returns the inspection."""
    payload = create_inspection_payload(
        operation_id, kind="POST_TREATMENT", result=result, findings=findings
    )
    resp = api_client.create_inspection(
        payload, make_inspector_headers(inspector_id)
    )
    return get_success_data(resp)


def start_operation(operation_id: str, oat_celsius: float = 0) -> dict:
    """Start spraying (PLANNED → SPRAYING). Returns the updated operation."""
    payload = start_operation_payload(oat_celsius)
    resp = api_client.start_deice_operation(
        operation_id, payload, TEST_USERS["pad_operator_headers"]
    )
    return get_success_data(resp)


def complete_operation(
    operation_id: str, actual_liters: float, collected_liters: float
) -> dict:
    """Complete spraying (SPRAYING → AWAITING_INSPECTION). Returns the updated operation."""
    payload = complete_operation_payload(actual_liters, collected_liters)
    resp = api_client.complete_deice_operation(
        operation_id, payload, TEST_USERS["pad_operator_headers"]
    )
    return get_success_data(resp)


def void_operation(operation_id: str) -> dict:
    """Void a CLEARED operation. Returns the updated operation."""
    resp = api_client.void_deice_operation(
        operation_id, TEST_USERS["pad_operator_headers"]
    )
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 4: full lifecycle shortcuts
# ---------------------------------------------------------------------------

def setup_request_assigned(
    station_overrides: Optional[dict] = None,
    tank_overrides: Optional[dict] = None,
    pad_overrides: Optional[dict] = None,
    airline_overrides: Optional[dict] = None,
    request_overrides: Optional[dict] = None,
    size_class: str = "MEDIUM",
    window_start: str = DEFAULTS["WINDOW_START"],
    window_end: str = DEFAULTS["WINDOW_END"],
) -> Tuple[dict, dict, dict, dict, dict, dict, dict]:
    """Full setup through assign: station + permit + tank + pad + airline +
    RESERVED request + ASSIGNED + PLANNED operation.

    Returns (station, permit, tank, pad, airline, request, operation).
    """
    station, permit, tank, pad, airline = setup_operational_base(
        station_overrides=station_overrides,
        tank_overrides=tank_overrides,
        pad_overrides=pad_overrides,
        airline_overrides=airline_overrides,
    )
    rq_kw = request_overrides or {}
    request = create_reserved_request(
        airline, station, tank, size_class=size_class, **rq_kw
    )
    assign_request_to_pad(request, pad, window_start=window_start, window_end=window_end)
    operation = get_operation_for_request(request["id"])
    return station, permit, tank, pad, airline, request, operation


def setup_operation_spraying(
    station_overrides: Optional[dict] = None,
    tank_overrides: Optional[dict] = None,
    pad_overrides: Optional[dict] = None,
    airline_overrides: Optional[dict] = None,
    request_overrides: Optional[dict] = None,
    size_class: str = "MEDIUM",
    oat_celsius: float = 0,
) -> Tuple[dict, dict, dict, dict, dict, dict, dict]:
    """Full setup through start: request ASSIGNED, acceptance PASS, operation
    SPRAYING. Returns (station, permit, tank, pad, airline, request, operation)."""
    station, permit, tank, pad, airline, request, operation = setup_request_assigned(
        station_overrides=station_overrides,
        tank_overrides=tank_overrides,
        pad_overrides=pad_overrides,
        airline_overrides=airline_overrides,
        request_overrides=request_overrides,
        size_class=size_class,
    )
    record_acceptance_inspection(operation["id"], inspector_id="insp-1")
    operation = start_operation(operation["id"], oat_celsius=oat_celsius)
    return station, permit, tank, pad, airline, request, operation


def setup_operation_awaiting_inspection(
    actual_liters: float,
    collected_liters: float,
    station_overrides: Optional[dict] = None,
    tank_overrides: Optional[dict] = None,
    pad_overrides: Optional[dict] = None,
    airline_overrides: Optional[dict] = None,
    request_overrides: Optional[dict] = None,
    size_class: str = "MEDIUM",
    oat_celsius: float = 0,
) -> Tuple[dict, dict, dict, dict, dict, dict, dict]:
    """Full setup through complete: operation AWAITING_INSPECTION.
    Returns (station, permit, tank, pad, airline, request, operation)."""
    station, permit, tank, pad, airline, request, operation = setup_operation_spraying(
        station_overrides=station_overrides,
        tank_overrides=tank_overrides,
        pad_overrides=pad_overrides,
        airline_overrides=airline_overrides,
        request_overrides=request_overrides,
        size_class=size_class,
        oat_celsius=oat_celsius,
    )
    operation = complete_operation(operation["id"], actual_liters, collected_liters)
    return station, permit, tank, pad, airline, request, operation


def setup_operation_cleared(
    actual_liters: float,
    collected_liters: float,
    station_overrides: Optional[dict] = None,
    tank_overrides: Optional[dict] = None,
    pad_overrides: Optional[dict] = None,
    airline_overrides: Optional[dict] = None,
    request_overrides: Optional[dict] = None,
    size_class: str = "MEDIUM",
    oat_celsius: float = 0,
) -> Tuple[dict, dict, dict, dict, dict, dict, dict]:
    """Full setup through post-treatment PASS: operation CLEARED, request
    COMPLETED, pad AVAILABLE, collected pool credited.
    Returns (station, permit, tank, pad, airline, request, operation)."""
    station, permit, tank, pad, airline, request, operation = setup_operation_awaiting_inspection(
        actual_liters=actual_liters,
        collected_liters=collected_liters,
        station_overrides=station_overrides,
        tank_overrides=tank_overrides,
        pad_overrides=pad_overrides,
        airline_overrides=airline_overrides,
        request_overrides=request_overrides,
        size_class=size_class,
        oat_celsius=oat_celsius,
    )
    record_post_treatment_inspection(operation["id"], result="PASS", inspector_id="insp-2")
    operation = get_operation_for_request(request["id"])
    # Re-fetch request to get terminal state
    resp = api_client.get_deice_request(
        request["id"], TEST_USERS["pad_operator_headers"]
    )
    request = get_success_data(resp)
    return station, permit, tank, pad, airline, request, operation


# ---------------------------------------------------------------------------
# Tier 5: billing / invoice fixtures
# ---------------------------------------------------------------------------

def setup_invoice_for_cleared_operation(
    actual_liters: float,
    collected_liters: float,
    station_overrides: Optional[dict] = None,
    tank_overrides: Optional[dict] = None,
    pad_overrides: Optional[dict] = None,
    airline_overrides: Optional[dict] = None,
    request_overrides: Optional[dict] = None,
    size_class: str = "MEDIUM",
) -> Tuple[dict, dict, dict, dict, dict, dict, dict, dict]:
    """Full setup through invoice creation (DRAFT).
    Returns (station, permit, tank, pad, airline, request, operation, invoice)."""
    station, permit, tank, pad, airline, request, operation = setup_operation_cleared(
        actual_liters=actual_liters,
        collected_liters=collected_liters,
        station_overrides=station_overrides,
        tank_overrides=tank_overrides,
        pad_overrides=pad_overrides,
        airline_overrides=airline_overrides,
        request_overrides=request_overrides,
        size_class=size_class,
    )
    # Re-read airline to get current version for OCC
    resp = api_client.get_airline(
        airline["id"], TEST_USERS["billing_clerk_headers"]
    )
    airline = get_success_data(resp)
    invoice_payload = create_invoice_payload(
        operation["id"], expected_airline_version=airline["version"]
    )
    resp = api_client.create_invoice(
        invoice_payload, TEST_USERS["billing_clerk_headers"]
    )
    invoice = get_success_data(resp)
    return station, permit, tank, pad, airline, request, operation, invoice


def setup_invoice_issued(
    actual_liters: float,
    collected_liters: float,
    station_overrides: Optional[dict] = None,
    tank_overrides: Optional[dict] = None,
    pad_overrides: Optional[dict] = None,
    airline_overrides: Optional[dict] = None,
    request_overrides: Optional[dict] = None,
    size_class: str = "MEDIUM",
) -> Tuple[dict, dict, dict, dict, dict, dict, dict, dict]:
    """Full setup through invoice ISSUED.
    Returns (station, permit, tank, pad, airline, request, operation, invoice)."""
    station, permit, tank, pad, airline, request, operation, invoice = (
        setup_invoice_for_cleared_operation(
            actual_liters=actual_liters,
            collected_liters=collected_liters,
            station_overrides=station_overrides,
            tank_overrides=tank_overrides,
            pad_overrides=pad_overrides,
            airline_overrides=airline_overrides,
            request_overrides=request_overrides,
            size_class=size_class,
        )
    )
    resp = api_client.issue_invoice(
        invoice["id"], TEST_USERS["billing_clerk_headers"]
    )
    invoice = get_success_data(resp)
    # Re-read airline to get updated balances
    resp = api_client.get_airline(
        airline["id"], TEST_USERS["billing_clerk_headers"]
    )
    airline = get_success_data(resp)
    return station, permit, tank, pad, airline, request, operation, invoice


# ---------------------------------------------------------------------------
# Tier 6: spill / recycling / weather fixtures
# ---------------------------------------------------------------------------

def setup_spill_report(
    quantity_liters: float,
    station_overrides: Optional[dict] = None,
    tank_overrides: Optional[dict] = None,
    reporter_id: str = "eo-1",
) -> Tuple[dict, dict, dict]:
    """Station + tank + spill report in REPORTED status.
    Returns (station, tank, spill_report)."""
    station = create_station(**(station_overrides or {}))
    tank = create_fluid_tank(station["id"], **(tank_overrides or {}))
    payload = create_spill_report_payload(
        station["id"], tank["id"], quantity_liters=quantity_liters
    )
    resp = api_client.create_spill_report(
        payload, make_environmental_officer_headers(reporter_id)
    )
    spill = get_success_data(resp)
    return station, tank, spill


def setup_spill_confirmed(
    quantity_liters: float,
    station_overrides: Optional[dict] = None,
    tank_overrides: Optional[dict] = None,
    reporter_id: str = "eo-1",
    confirmer_id: str = "eo-2",
) -> Tuple[dict, dict, dict]:
    """Station + tank + spill report in CONFIRMED status.
    Returns (station, tank, spill_report)."""
    station, tank, spill = setup_spill_report(
        quantity_liters=quantity_liters,
        station_overrides=station_overrides,
        tank_overrides=tank_overrides,
        reporter_id=reporter_id,
    )
    resp = api_client.confirm_spill_report(
        spill["id"], make_environmental_officer_headers(confirmer_id)
    )
    spill = get_success_data(resp)
    return station, tank, spill


def setup_recycling_contract_with_pool(
    pool_liters: float = 400,
    actual_liters: float = 600,
    contract_overrides: Optional[dict] = None,
) -> Tuple[dict, dict, dict, dict, dict, dict, dict, dict]:
    """Station + permit + tank + pad + airline + CLEARED operation contributing
    `pool_liters` to the collected pool + ACTIVE recycling contract.

    Returns (station, permit, tank, pad, airline, request, operation, contract).
    """
    station, permit, tank, pad, airline, request, operation = setup_operation_cleared(
        actual_liters=actual_liters,
        collected_liters=pool_liters,
        size_class="MEDIUM",
    )
    contract_payload = create_recycling_contract_payload(station["id"])
    if contract_overrides:
        contract_payload.update(contract_overrides)
    resp = api_client.create_recycling_contract(
        contract_payload, TEST_USERS["station_admin_headers"]
    )
    contract = get_success_data(resp)
    return station, permit, tank, pad, airline, request, operation, contract


def setup_weather_event_escalated(
    severity: str,
    assigned_crew_count: int,
    station_overrides: Optional[dict] = None,
) -> Tuple[dict, dict]:
    """Station + weather event escalated to a crew count.
    Returns (station, weather_event)."""
    station = create_station(**(station_overrides or {}))
    event = create_weather_event(
        station["id"],
        precip_type="FREEZING_RAIN",
        precip_rate="MODERATE",
        severity=severity,
    )
    resp = api_client.escalate_weather_event(
        event["id"],
        escalate_payload(assigned_crew_count),
        TEST_USERS["station_admin_headers"],
    )
    event = get_success_data(resp)
    return station, event
