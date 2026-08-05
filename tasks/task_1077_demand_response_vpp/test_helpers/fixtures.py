"""Composite setup helpers.

The test harness restarts the API server (empty DB, clock reset to
2026-05-01T00:00:00Z) before every test, so every fixture builds its
preconditions from scratch using only PRD-declared endpoints. Setup calls use
get_success_data() (lenient) so a broken precondition surfaces as a clear
"Setup failed" rather than a confusing assertion error.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_aggregator_headers,
    make_customer_headers,
)
from .factories import (
    create_program_payload,
    create_aggregator_payload,
    create_customer_payload,
    create_device_payload,
    create_enrollment_payload,
    create_dispatch_event_payload,
    create_meter_reading_payload,
    create_settlement_payload,
)

OP1 = TEST_USERS["program_operator_headers"]   # opaque operator id "op1" (dispatcher)
OP2 = TEST_USERS["second_operator_headers"]    # opaque operator id "op2" (approver)

# Default event window / clock choreography reused across settlement fixtures.
DEFAULT_WINDOW_START = "2026-06-01T14:00:00Z"
DEFAULT_WINDOW_END = "2026-06-01T16:00:00Z"
DEFAULT_NOTIFY_CLOCK = "2026-06-01T12:00:00Z"

# Baseline readings live on distinct pre-season days, 14:00-15:00 UTC.
_BASELINE_DAYS = ("2026-05-20", "2026-05-21", "2026-05-22", "2026-05-23", "2026-05-24")


# --------------------------------------------------------------------------- #
# Primitives
# --------------------------------------------------------------------------- #
def onboard_aggregator(name="VPP Aggregator", email="agg@example.com") -> dict:
    resp = api_client.create_aggregator(create_aggregator_payload(name=name, contact_email=email), OP1)
    return get_success_data(resp)


def onboard_customer(**overrides) -> dict:
    resp = api_client.create_customer(create_customer_payload(**overrides), OP1)
    return get_success_data(resp)


def create_program(active=True, **overrides) -> dict:
    resp = api_client.create_program(create_program_payload(**overrides), OP1)
    prog = get_success_data(resp)
    if active:
        prog = get_success_data(api_client.activate_program(prog["id"], OP1))
    return prog


def register_device(aggregator_id, customer_id, **overrides) -> dict:
    resp = api_client.create_device(
        create_device_payload(customer_id, **overrides), make_aggregator_headers(aggregator_id)
    )
    return get_success_data(resp)


def add_baseline_readings(device_id, aggregator_id, loads=(10, 9, 8)) -> list:
    headers = make_aggregator_headers(aggregator_id)
    out = []
    for i, load in enumerate(loads):
        day = _BASELINE_DAYS[i]
        payload = create_meter_reading_payload(
            interval_start=f"{day}T14:00:00Z",
            interval_end=f"{day}T15:00:00Z",
            kw_load=load,
            reading_type="BASELINE_WINDOW",
        )
        out.append(get_success_data(api_client.create_meter_reading(device_id, payload, headers)))
    return out


def enroll_active(device_id, program_id, aggregator_id, committed_kw=5) -> dict:
    headers = make_aggregator_headers(aggregator_id)
    enr = get_success_data(
        api_client.create_enrollment(create_enrollment_payload(device_id, program_id, committed_kw), headers)
    )
    enr = get_success_data(api_client.activate_enrollment(enr["id"], headers))
    return enr


def create_event(program_id, window_start=DEFAULT_WINDOW_START, window_end=DEFAULT_WINDOW_END,
                 target_reduction_kw=5) -> dict:
    resp = api_client.create_dispatch_event(
        create_dispatch_event_payload(program_id, window_start, window_end, target_reduction_kw), OP1
    )
    return get_success_data(resp)


def set_clock(iso8601) -> None:
    get_success_data(api_client.set_clock(iso8601, OP1))


def notify_event(event_id, operator_headers=OP1) -> dict:
    return get_success_data(api_client.notify_dispatch_event(event_id, operator_headers))


def start_event(event_id) -> dict:
    return get_success_data(api_client.start_dispatch_event(event_id, OP1))


def complete_event(event_id) -> dict:
    return get_success_data(api_client.complete_dispatch_event(event_id, OP1))


def add_event_reading(device_id, aggregator_id, event_id, kw_load,
                      interval_start, interval_end) -> dict:
    payload = create_meter_reading_payload(
        interval_start=interval_start,
        interval_end=interval_end,
        kw_load=kw_load,
        reading_type="EVENT_WINDOW",
        dispatch_event_id=event_id,
    )
    return get_success_data(
        api_client.create_meter_reading(device_id, payload, make_aggregator_headers(aggregator_id))
    )


def event_dispatches(event_id) -> list:
    resp = api_client.list_event_dispatches(event_id, OP1)
    return get_success_data(resp)


# --------------------------------------------------------------------------- #
# Composite: notified event with fanned-out dispatches (no measurement yet)
# --------------------------------------------------------------------------- #
def setup_notified_event(committed_kw=5, device_type="BATTERY", target_reduction_kw=5,
                         window_start=DEFAULT_WINDOW_START, window_end=DEFAULT_WINDOW_END,
                         notify_clock=DEFAULT_NOTIFY_CLOCK, with_baseline=False,
                         baseline_loads=(10, 9, 8), **program_overrides) -> dict:
    """Active program + one active enrollment + a NOTIFIED event that has fanned
    out one PENDING dispatch. Returns ids plus the first dispatch (disp/disp_id).
    """
    agg = onboard_aggregator()
    cust = onboard_customer()
    device_kwargs = {"device_type": device_type}
    if device_type == "THERMOSTAT":
        device_kwargs["capacity_kwh"] = None
    prog = create_program(active=True, **program_overrides)
    dev = register_device(agg["id"], cust["id"], **device_kwargs)
    if with_baseline:
        add_baseline_readings(dev["id"], agg["id"], baseline_loads)
    enr = enroll_active(dev["id"], prog["id"], agg["id"], committed_kw)
    evt = create_event(prog["id"], window_start, window_end, target_reduction_kw)
    set_clock(notify_clock)
    notify_event(evt["id"], OP1)
    dispatches = event_dispatches(evt["id"])
    disp = dispatches[0]
    return {
        "agg_id": agg["id"], "cust_id": cust["id"], "prog_id": prog["id"],
        "dev_id": dev["id"], "enr_id": enr["id"], "evt_id": evt["id"],
        "disp_id": disp["id"], "disp": disp, "dispatches": dispatches,
        "window_start": window_start, "window_end": window_end,
    }


# --------------------------------------------------------------------------- #
# Composite: single-device COMPLETED event (full measurement cascade run)
# --------------------------------------------------------------------------- #
def setup_completed_single_device_event(
    baseline_method="TEN_OF_TEN",
    settlement_method="PAY_FOR_PERFORMANCE",
    performance_floor_pct=None,
    committed_kw=5,
    baseline_loads=(10, 9, 8),
    event_load=4.0,
    window_start=DEFAULT_WINDOW_START,
    window_end=DEFAULT_WINDOW_END,
    notify_clock=DEFAULT_NOTIFY_CLOCK,
    target_reduction_kw=5,
) -> dict:
    """Drive one enrolled device all the way through event COMPLETED, so the
    dispatch carries computed baseline_kw / delivered_kwh / performance_ratio.
    Returns ids plus the completed dispatch (disp)."""
    agg = onboard_aggregator()
    cust = onboard_customer()
    prog_overrides = {"baseline_method": baseline_method, "settlement_method": settlement_method}
    if performance_floor_pct is not None:
        prog_overrides["performance_floor_pct"] = performance_floor_pct
    prog = create_program(active=True, **prog_overrides)
    dev = register_device(agg["id"], cust["id"], device_type="BATTERY", capacity_kwh=20)
    add_baseline_readings(dev["id"], agg["id"], baseline_loads)
    enr = enroll_active(dev["id"], prog["id"], agg["id"], committed_kw)
    evt = create_event(prog["id"], window_start, window_end, target_reduction_kw)
    set_clock(notify_clock)
    notify_event(evt["id"], OP1)
    set_clock(window_start)
    start_event(evt["id"])
    add_event_reading(dev["id"], agg["id"], evt["id"], event_load, window_start, window_end)
    set_clock(window_end)
    complete_event(evt["id"])
    dispatches = event_dispatches(evt["id"])
    return {
        "agg_id": agg["id"], "cust_id": cust["id"], "prog_id": prog["id"],
        "dev_id": dev["id"], "enr_id": enr["id"], "evt_id": evt["id"],
        "disp": dispatches[0], "dispatches": dispatches,
        "window_start": window_start, "window_end": window_end,
    }


# --------------------------------------------------------------------------- #
# Composite: two-device COMPLETED event (round-per-line-then-sum pinning)
# --------------------------------------------------------------------------- #
def setup_two_device_completed_event(
    committed_kw=1.0,
    baseline_load=6.01,
    event_load=5.00,
    window_start="2026-06-01T14:00:00Z",
    window_end="2026-06-01T15:00:00Z",
    notify_clock=DEFAULT_NOTIFY_CLOCK,
    target_reduction_kw=2,
) -> dict:
    """Two devices of one aggregator/customer, each enrolled and completed under
    a PAY_FOR_PERFORMANCE program. Both dispatches share the same measured line.
    Returns ids plus the list of completed dispatches."""
    agg = onboard_aggregator()
    cust = onboard_customer()
    prog = create_program(active=True, baseline_method="TEN_OF_TEN",
                          settlement_method="PAY_FOR_PERFORMANCE")
    loads = (baseline_load, baseline_load, baseline_load)
    dev1 = register_device(agg["id"], cust["id"], capacity_kwh=20)
    dev2 = register_device(agg["id"], cust["id"], capacity_kwh=20)
    add_baseline_readings(dev1["id"], agg["id"], loads)
    add_baseline_readings(dev2["id"], agg["id"], loads)
    enroll_active(dev1["id"], prog["id"], agg["id"], committed_kw)
    enroll_active(dev2["id"], prog["id"], agg["id"], committed_kw)
    evt = create_event(prog["id"], window_start, window_end, target_reduction_kw)
    set_clock(notify_clock)
    notify_event(evt["id"], OP1)
    set_clock(window_start)
    start_event(evt["id"])
    add_event_reading(dev1["id"], agg["id"], evt["id"], event_load, window_start, window_end)
    add_event_reading(dev2["id"], agg["id"], evt["id"], event_load, window_start, window_end)
    set_clock(window_end)
    complete_event(evt["id"])
    dispatches = event_dispatches(evt["id"])
    return {
        "agg_id": agg["id"], "cust_id": cust["id"], "prog_id": prog["id"],
        "dev1_id": dev1["id"], "dev2_id": dev2["id"], "evt_id": evt["id"],
        "dispatches": dispatches,
    }


# --------------------------------------------------------------------------- #
# Composite: settlement in SUBMITTED / APPROVED states
# --------------------------------------------------------------------------- #
def setup_submitted_settlement(**kwargs) -> dict:
    """Completed single-device event with a settlement created and submitted
    (PENDING_APPROVAL). Adds set_id and the submitted settlement (settlement)."""
    ctx = setup_completed_single_device_event(**kwargs)
    settle = get_success_data(api_client.create_settlement(create_settlement_payload(ctx["evt_id"]), OP1))
    submitted = get_success_data(api_client.submit_settlement(settle["id"], OP1))
    ctx["set_id"] = settle["id"]
    ctx["settlement"] = submitted
    return ctx


def setup_approved_settlement(approver=OP2, **kwargs) -> dict:
    """Submitted settlement approved by a distinct operator (op2 by default) so
    an ISSUED Payment exists. Adds the approved settlement (settlement)."""
    ctx = setup_submitted_settlement(**kwargs)
    approved = get_success_data(api_client.approve_settlement(ctx["set_id"], approver))
    ctx["settlement"] = approved
    return ctx

