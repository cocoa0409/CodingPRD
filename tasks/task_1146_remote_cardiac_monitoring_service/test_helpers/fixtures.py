"""Composite setup helpers for the cardiac-monitoring domain.

Every fixture builds its preconditions from scratch through PRD-declared
endpoints (the harness restarts the server before each test, so every test
starts against an empty database with the logical clock at its startup
default). Setup calls use the lenient get_success_data validator so failures
surface as clear "Setup step failed" errors.

Identity threading: Physician and MonitoringTechnician are entity-backed roles,
so ownership/assignment-gated calls always use make_*_headers(entity["id"]).
"""
from datetime import datetime, timedelta, timezone

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_START
from .factories import (
    create_alert_payload,
    create_device_payload,
    create_enrollment_payload,
    create_order_payload,
    create_patient_payload,
    create_physician_payload,
    create_report_payload,
    create_technician_payload,
    create_transmission_payload,
)
from .test_users import (
    TEST_USERS,
    make_physician_headers,
    make_technician_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
COORDINATOR = TEST_USERS["enrollment_coordinator_headers"]
BILLING_1 = TEST_USERS["billing_specialist_headers"]
INVENTORY = TEST_USERS["inventory_manager_headers"]
GATEWAY = TEST_USERS["device_gateway_headers"]


# ---------------------------------------------------------------------------
# Clock / sweep
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str):
    get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def run_sweep():
    get_success_data(api_client.run_daily_sweep(ADMIN))


def plus_days(iso: str, days: int) -> str:
    dt = datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    return (dt + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Registry registrations
# ---------------------------------------------------------------------------

def register_patient(**overrides) -> dict:
    return get_success_data(api_client.create_patient(create_patient_payload(**overrides), COORDINATOR))


def register_physician(**overrides) -> dict:
    return get_success_data(api_client.create_physician(create_physician_payload(**overrides), ADMIN))


def register_technician(capacity: int = 5, **overrides) -> dict:
    return get_success_data(
        api_client.create_technician(create_technician_payload(shift_capacity=capacity, **overrides), ADMIN)
    )


def register_device(model: str = "EVENT", **overrides) -> dict:
    return get_success_data(api_client.create_device(create_device_payload(model=model, **overrides), INVENTORY))


# ---------------------------------------------------------------------------
# Reads (any role may read; coordinator used by default)
# ---------------------------------------------------------------------------

def read_patient(patient_id: str) -> dict:
    return get_success_data(api_client.get_patient(patient_id, COORDINATOR))


def read_device(device_id: str) -> dict:
    return get_success_data(api_client.get_device(device_id, COORDINATOR))


def read_order(order_id: str) -> dict:
    return get_success_data(api_client.get_order(order_id, COORDINATOR))


def read_enrollment(enrollment_id: str) -> dict:
    return get_success_data(api_client.get_enrollment(enrollment_id, COORDINATOR))


def read_episode(episode_id: str) -> dict:
    return get_success_data(api_client.get_episode(episode_id, COORDINATOR))


def read_technician(technician_id: str) -> dict:
    return get_success_data(api_client.get_technician(technician_id, COORDINATOR))


def read_alert(alert_id: str) -> dict:
    return get_success_data(api_client.get_alert(alert_id, COORDINATOR))


def read_report(report_id: str) -> dict:
    return get_success_data(api_client.get_report(report_id, COORDINATOR))


def read_billing_period(period_id: str) -> dict:
    return get_success_data(api_client.get_billing_period(period_id, COORDINATOR))


def read_shipment(shipment_id: str) -> dict:
    return get_success_data(api_client.get_return_shipment(shipment_id, COORDINATOR))


def list_open_gap_events(episode_id: str) -> list:
    return get_success_data(
        api_client.list_compliance_events(
            COORDINATOR,
            params={"episode_id": episode_id, "status": "OPEN", "event_type": "TRANSMISSION_GAP"},
        )
    )


# ---------------------------------------------------------------------------
# Tier 1/2: order + enrollment chains
# ---------------------------------------------------------------------------

def create_order_for(patient_id: str, physician_id: str, prescribed_days: int = 30,
                     monitor_type: str = "EVENT", **overrides) -> dict:
    """Create a monitoring order; ordering_physician_id comes from X-User-ID."""
    headers = make_physician_headers(physician_id)
    return get_success_data(
        api_client.create_order(
            create_order_payload(patient_id, monitor_type=monitor_type,
                                 prescribed_days=prescribed_days, **overrides),
            headers,
        )
    )


def create_enrollment_for(order: dict, device_id: str) -> dict:
    """Create an enrollment with the OCC field pinned to the order's version."""
    payload = create_enrollment_payload(device_id, order["version"])
    return get_success_data(api_client.create_enrollment(order["id"], payload, COORDINATOR))


def setup_open_order(prescribed_days: int = 30, monitor_type: str = "EVENT",
                     clock: str = None, patient_over: dict = None,
                     physician_over: dict = None, device_over: dict = None) -> dict:
    """Patient + physician + device + OPEN order. Returns the context dict."""
    patient = register_patient(**(patient_over or {}))
    physician = register_physician(**(physician_over or {}))
    device = register_device(model=monitor_type, **(device_over or {}))
    if clock is not None:
        set_clock(clock)
    order = create_order_for(patient["id"], physician["id"],
                             prescribed_days=prescribed_days, monitor_type=monitor_type)
    return {"patient": patient, "physician": physician, "device": device, "order": order}


def setup_educated_enrollment(prescribed_days: int = 30, monitor_type: str = "EVENT",
                              clock: str = None, education_method: str = "VIDEO",
                              **kwargs) -> dict:
    """Open order + enrollment INITIATED + complete-education -> EDUCATED."""
    ctx = setup_open_order(prescribed_days=prescribed_days, monitor_type=monitor_type,
                           clock=clock, **kwargs)
    enrollment = create_enrollment_for(ctx["order"], ctx["device"]["id"])
    enrollment = get_success_data(
        api_client.complete_education(enrollment["id"], {"education_method": education_method}, COORDINATOR)
    )
    ctx["enrollment"] = enrollment
    return ctx


def setup_monitoring_episode(prescribed_days: int = 30, monitor_type: str = "EVENT",
                             start_clock: str = None, baseline_signal_quality: int = 90,
                             education_method: str = "VIDEO", **kwargs) -> dict:
    """Full chain through activation. Returns context with episode_id set."""
    ctx = setup_educated_enrollment(prescribed_days=prescribed_days, monitor_type=monitor_type,
                                    clock=start_clock, education_method=education_method, **kwargs)
    enrollment = get_success_data(
        api_client.activate_enrollment(
            ctx["enrollment"]["id"], {"baseline_signal_quality": baseline_signal_quality}, COORDINATOR
        )
    )
    ctx["enrollment"] = enrollment
    ctx["episode_id"] = enrollment["episode_id"]
    ctx["episode"] = read_episode(enrollment["episode_id"])
    return ctx


def setup_completed_episode(prescribed_days: int = 10, complete_clock: str = None,
                            transmissions: int = 0, **kwargs) -> dict:
    """Monitoring episode driven to clinical_status COMPLETED (no sweeps run,
    so no gap strikes). complete_clock defaults to start + prescribed_days."""
    ctx = setup_monitoring_episode(prescribed_days=prescribed_days, **kwargs)
    episode_id = ctx["episode_id"]
    for seq in range(1, transmissions + 1):
        get_success_data(
            api_client.ingest_transmission(
                episode_id, create_transmission_payload(seq_no=seq), GATEWAY
            )
        )
    if complete_clock is None:
        started = ctx["episode"]["started_at"][:19] + "Z"
        complete_clock = plus_days(started, prescribed_days)
    set_clock(complete_clock)
    ctx["episode"] = get_success_data(
        api_client.complete_episode(episode_id, {"reason": "COMPLETED"}, COORDINATOR)
    )
    return ctx


# ---------------------------------------------------------------------------
# Tier 4: strike accumulation (transmission-gap cascade)
# ---------------------------------------------------------------------------

def record_gap_strikes(episode_id: str, count: int, resolve_last: bool = True,
                       anchor_clock: str = CLOCK_START, step_days: int = 2) -> list:
    """Drive `count` TRANSMISSION_GAP strikes via clock advance + daily sweep.

    Each sweep runs step_days (default 2 = the 48h gap threshold) after the
    previous event's creation, so each sweep fires exactly one new gap event.
    Intermediate events are resolved (an OPEN gap event blocks the next
    detection); the final event is resolved only when resolve_last is true.
    Returns the created event ids in order.
    """
    event_ids = []
    last = anchor_clock
    for i in range(count):
        last = plus_days(last, step_days)
        set_clock(last)
        run_sweep()
        open_events = list_open_gap_events(episode_id)
        assert open_events, f"Setup: expected an OPEN TRANSMISSION_GAP event after sweep at {last}"
        event_id = open_events[0]["id"]
        event_ids.append(event_id)
        if i < count - 1 or resolve_last:
            get_success_data(
                api_client.resolve_compliance_event(
                    event_id, {"resolution_action": "CONTACTED_PATIENT"}, COORDINATOR
                )
            )
    return event_ids


# ---------------------------------------------------------------------------
# Tier 3/5: billing pipelines
# ---------------------------------------------------------------------------

def generate_billing(episode_id: str) -> list:
    data = get_success_data(api_client.generate_billing_periods(episode_id, BILLING_1))
    assert isinstance(data, list) and data, "Setup: billing generate must return a non-empty array"
    return data


def create_and_finalize_report(episode_id: str, physician_id: str,
                               report_type: str = "INTERIM", **overrides) -> dict:
    headers = make_physician_headers(physician_id)
    report = get_success_data(
        api_client.create_report(
            episode_id, create_report_payload(report_type=report_type, **overrides), headers
        )
    )
    return get_success_data(api_client.finalize_report(report["id"], headers))


def setup_ready_billing_period(prescribed_days: int = 10, **kwargs) -> dict:
    """Completed episode -> billing generated -> INTERIM report FINALIZED ->
    sweep matures the window to READY. Returns context with bp_id set."""
    ctx = setup_completed_episode(prescribed_days=prescribed_days, **kwargs)
    periods = generate_billing(ctx["episode_id"])
    ctx["billing_periods"] = periods
    ctx["bp_id"] = periods[0]["id"]
    ctx["report"] = create_and_finalize_report(ctx["episode_id"], ctx["physician"]["id"])
    run_sweep()
    ctx["billing_period"] = read_billing_period(ctx["bp_id"])
    return ctx


def setup_submitted_billing_period(prescribed_days: int = 10,
                                   submitter: str = "billing-1", **kwargs) -> dict:
    """READY period submitted by `submitter`. Returns context with the
    SUBMITTED billing period."""
    from .test_users import make_billing_specialist_headers

    ctx = setup_ready_billing_period(prescribed_days=prescribed_days, **kwargs)
    ctx["billing_period"] = get_success_data(
        api_client.submit_billing_period(
            ctx["bp_id"], make_billing_specialist_headers(submitter)
        )
    )
    return ctx


# ---------------------------------------------------------------------------
# Tier 3: alert pipelines
# ---------------------------------------------------------------------------

def raise_alert(episode_id: str, severity: str = "ROUTINE", arrhythmia_type: str = "AFIB") -> dict:
    return get_success_data(
        api_client.raise_alert(
            episode_id,
            create_alert_payload(severity=severity, arrhythmia_type=arrhythmia_type),
            GATEWAY,
        )
    )


def setup_alert_scenario(severity: str = "ROUTINE", arrhythmia_type: str = "AFIB",
                         alert_clock: str = None, technician_capacity: int = 5,
                         prescribed_days: int = 30, **kwargs) -> dict:
    """Monitoring episode + technician + one alert in NEW. Context carries
    technician and alert in addition to the episode chain."""
    ctx = setup_monitoring_episode(prescribed_days=prescribed_days, **kwargs)
    ctx["technician"] = register_technician(capacity=technician_capacity)
    if alert_clock is not None:
        set_clock(alert_clock)
    ctx["alert"] = raise_alert(ctx["episode_id"], severity=severity, arrhythmia_type=arrhythmia_type)
    return ctx


def acknowledge_alert(alert_id: str, technician_id: str) -> dict:
    return get_success_data(
        api_client.acknowledge_alert(alert_id, make_technician_headers(technician_id))
    )


def setup_acknowledged_alert(**kwargs) -> dict:
    """Alert scenario with the alert ACKNOWLEDGED by the technician."""
    ctx = setup_alert_scenario(**kwargs)
    ctx["alert"] = acknowledge_alert(ctx["alert"]["id"], ctx["technician"]["id"])
    return ctx


def setup_notified_alert(severity: str = "URGENT", alert_clock: str = "2026-05-01T10:00:00Z",
                         **kwargs) -> dict:
    """Alert carried NEW -> ACKNOWLEDGED -> TRIAGED -> NOTIFIED; the created
    NotificationAttempt (PENDING) is in ctx['attempt']."""
    ctx = setup_acknowledged_alert(severity=severity, alert_clock=alert_clock, **kwargs)
    tech_headers = make_technician_headers(ctx["technician"]["id"])
    ctx["alert"] = get_success_data(api_client.triage_alert(ctx["alert"]["id"], {}, tech_headers))
    ctx["attempt"] = get_success_data(api_client.notify_alert(ctx["alert"]["id"], tech_headers))
    ctx["alert"] = read_alert(ctx["alert"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 5: device return pipeline
# ---------------------------------------------------------------------------

def setup_returned_device(prescribed_days: int = 7, return_clock: str = None, **kwargs) -> dict:
    """Completed episode -> return shipment created -> marked received.
    Context carries shipment and the device now in REFURBISHING."""
    ctx = setup_completed_episode(prescribed_days=prescribed_days, **kwargs)
    if return_clock is not None:
        set_clock(return_clock)
    shipment = get_success_data(api_client.create_return_shipment(ctx["episode_id"], INVENTORY))
    ctx["shipment"] = get_success_data(api_client.mark_shipment_received(shipment["id"], INVENTORY))
    ctx["device"] = read_device(ctx["device"]["id"])
    return ctx
