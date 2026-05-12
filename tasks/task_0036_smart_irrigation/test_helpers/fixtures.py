"""Composite setup helpers for the Smart Irrigation test suite.

The PRD's lifecycle has many interlocking phases — Tenant → Plot → Sensor
ingest → IrrigationPlan (DRAFT → ACTIVE → SUSPENDED → ACTIVE → DRAFT
revision → COMPLETED) → ValveGroup → ControlCommand (PENDING → DISPATCHING
→ EXECUTING → EXECUTED|FAILED, plus PENDING → OFFLINE_LOCAL → EXECUTED) →
WaterQuota (parallel usage_state and approval_state dimensions) → Alert
(cyclic RESOLVED → REOPENED) → WaterBill (DRAFT → ISSUED → PAID|DISPUTED
→ CANCELLED). Most interesting tests need the system in a non-initial
state, sometimes 5–15 API calls deep.

Identity threading (PRD §2.1):

- Tenant is entity-backed: ownership-gated calls (POST /water-bills/{id}/
  dispute, POST /water-bills/{id}/payments by Tenant, GET /water-bills/{id}
  scoped to own tenant, etc.) MUST use make_tenant_headers(tenant['id']).

Setup calls use get_success_data (lenient validator) so broken
preconditions surface as obvious errors, not confusing assertion failures.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    approve_override_payload,
    create_control_command_payload,
    create_plan_payload,
    create_plot_payload,
    create_reading_payload,
    create_sensor_payload,
    create_tenant_payload,
    create_valve_group_payload,
    create_water_bill_payload,
    create_water_quota_payload,
    dispute_payload,
    dispute_resolve_payload,
    feedback_payload,
    payment_payload,
    request_override_payload,
    unique_name,
    unique_pump_id,
    unique_valve_id,
)
from .test_users import (
    TEST_USERS,
    make_platform_admin_headers,
    make_tenant_headers,
    make_water_admin_headers,
)


# ===========================================================================
# Time helpers (PRD §2.4 — ISO 8601 UTC with three fractional digits)
# ===========================================================================
def iso_z(dt: datetime) -> str:
    """Format a datetime as ISO 8601 UTC with exactly three fractional digits."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    millis = int(dt.microsecond / 1000)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{millis:03d}Z"


def parse_iso(s: str) -> datetime:
    s2 = s.replace("Z", "+00:00")
    return datetime.fromisoformat(s2)


def add_seconds(s: str, n: float) -> str:
    return iso_z(parse_iso(s) + timedelta(seconds=n))


def add_minutes(s: str, n: float) -> str:
    return iso_z(parse_iso(s) + timedelta(minutes=n))


def add_hours(s: str, n: float) -> str:
    return iso_z(parse_iso(s) + timedelta(hours=n))


def add_days(s: str, n: float) -> str:
    return iso_z(parse_iso(s) + timedelta(days=n))


# Default base instant — picked so window arithmetic stays in 2026.
DEFAULT_NOW_ISO = "2026-06-01T00:00:00.000Z"


# ===========================================================================
# Test-driving wrappers (PRD §3.8 / §4)
# ===========================================================================
_last_known_clock_iso: Optional[str] = None


def advance_clock(to_iso: str) -> Dict[str, Any]:
    """POST /_clock/advance. PRD §4 mounts this as a PlatformAdmin-only
    test driver. The simulated clock is shared across tests; if the
    requested time is at or before the last known clock, this helper
    silently NO-OPs (forward-only)."""
    global _last_known_clock_iso
    if (
        _last_known_clock_iso is not None
        and parse_iso(to_iso) <= parse_iso(_last_known_clock_iso)
    ):
        return {}
    headers = TEST_USERS["platform_admin_headers"]
    res = api_client.advance_clock(to_iso, headers)
    data = get_success_data(res)
    _last_known_clock_iso = to_iso
    return data


def current_clock_iso() -> str:
    return _last_known_clock_iso or DEFAULT_NOW_ISO


def run_sweep() -> Dict[str, Any]:
    """POST /_sweep/run as PlatformAdmin (PRD §3.8)."""
    headers = TEST_USERS["platform_admin_headers"]
    return get_success_data(api_client.run_sweep(headers))


def emit_event(event_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """POST /_events/emit as PlatformAdmin (PRD §3.8)."""
    headers = TEST_USERS["platform_admin_headers"]
    return get_success_data(api_client.emit_event(event_type, payload, headers))


# ===========================================================================
# Tier 1 — single-entity creation
# ===========================================================================
def create_tenant(*, name: Optional[str] = None,
                  contact_email: Optional[str] = None,
                  status: Optional[str] = None,
                  **overrides: Any) -> Dict[str, Any]:
    """Register a Tenant via PlatformAdmin. PRD §2.1 / §4 declare
    POST /tenants is PlatformAdmin-only."""
    payload = create_tenant_payload(
        name=name, contact_email=contact_email, **overrides
    )
    res = api_client.create_tenant(
        payload, TEST_USERS["platform_admin_headers"]
    )
    tenant = get_success_data(res)
    # If a test wanted SUSPENDED tenant (PRD §3.6 punitive multiplier),
    # they'd need a backdoor. PRD doesn't expose one, so we honour status
    # as-default-ACTIVE. Tests requiring SUSPENDED tenant must accept that
    # default. (We don't fabricate.)
    return tenant


def create_plot(
    tenant_id: str,
    *,
    area_hectares: float = 10.0,
    crop_type: str = "CORN",
    crop_stage: str = "VEGETATIVE",
    pump_id: Optional[str] = None,
    name: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = create_plot_payload(
        tenant_id=tenant_id,
        area_hectares=area_hectares,
        crop_type=crop_type,
        crop_stage=crop_stage,
        pump_id=pump_id,
        name=name,
        **overrides,
    )
    res = api_client.create_plot(
        payload, TEST_USERS["water_admin_headers"]
    )
    return get_success_data(res)


def create_sensor(
    plot_id: str,
    *,
    sensor_type: str = "SOIL_MOISTURE",
    poll_interval_seconds: int = 300,
    min_valid_value: float = 10.0,
    max_valid_value: float = 90.0,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = create_sensor_payload(
        plot_id=plot_id,
        sensor_type=sensor_type,
        poll_interval_seconds=poll_interval_seconds,
        min_valid_value=min_valid_value,
        max_valid_value=max_valid_value,
        **overrides,
    )
    res = api_client.create_sensor(
        payload, TEST_USERS["water_admin_headers"]
    )
    return get_success_data(res)


def ingest_reading(
    sensor_id: str,
    *,
    value: float,
    reading_timestamp: str,
) -> Dict[str, Any]:
    payload = create_reading_payload(
        value=value, reading_timestamp=reading_timestamp
    )
    res = api_client.ingest_reading(
        sensor_id, payload, TEST_USERS["water_admin_headers"]
    )
    return get_success_data(res)


def create_valve_group(
    tenant_id: str,
    *,
    pump_id: str,
    valve_ids: Optional[List[str]] = None,
    control_mode: str = "SEQUENTIAL",
    max_parallel_valves: int = 1,
    name: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = create_valve_group_payload(
        tenant_id=tenant_id,
        pump_id=pump_id,
        valve_ids=valve_ids,
        control_mode=control_mode,
        max_parallel_valves=max_parallel_valves,
        name=name,
        **overrides,
    )
    res = api_client.create_valve_group(
        payload, TEST_USERS["water_admin_headers"]
    )
    return get_success_data(res)


def create_water_quota(
    plot_id: str,
    *,
    period_start: str,
    period_end: str,
    allocated_liters: float = 10000.0,
    warning_threshold_pct: Optional[float] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = create_water_quota_payload(
        plot_id=plot_id,
        period_start=period_start,
        period_end=period_end,
        allocated_liters=allocated_liters,
        warning_threshold_pct=warning_threshold_pct,
        **overrides,
    )
    res = api_client.create_water_quota(
        payload, TEST_USERS["water_admin_headers"]
    )
    return get_success_data(res)


def create_plan(
    plot_id: str,
    *,
    window_start: str,
    window_end: str,
    source: Optional[str] = None,
    planned_volume_liters: Optional[float] = None,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = create_plan_payload(
        window_start=window_start,
        window_end=window_end,
        source=source,
        planned_volume_liters=planned_volume_liters,
        **overrides,
    )
    res = api_client.create_irrigation_plan(
        plot_id, payload, headers or TEST_USERS["water_admin_headers"]
    )
    return get_success_data(res)


def activate_plan(plot_id: str, plan_id: str) -> Dict[str, Any]:
    res = api_client.activate_plan(
        plot_id, plan_id, TEST_USERS["water_admin_headers"]
    )
    return get_success_data(res)


def suspend_plan(plot_id: str, plan_id: str) -> Dict[str, Any]:
    res = api_client.suspend_plan(
        plot_id, plan_id, TEST_USERS["water_admin_headers"]
    )
    return get_success_data(res)


def resume_plan(plot_id: str, plan_id: str) -> Dict[str, Any]:
    res = api_client.resume_plan(
        plot_id, plan_id, TEST_USERS["water_admin_headers"]
    )
    return get_success_data(res)


def create_control_command(
    *,
    plan_id: str,
    valve_group_id: str,
    requested_volume_liters: float,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    payload = create_control_command_payload(
        plan_id=plan_id,
        valve_group_id=valve_group_id,
        requested_volume_liters=requested_volume_liters,
    )
    res = api_client.create_control_command(
        payload, headers or TEST_USERS["water_admin_headers"]
    )
    return get_success_data(res)


def dispatch_command(
    command_id: str,
    *,
    offline: bool = False,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /control-commands/{id}/dispatch.

    PRD §3.4: 'when a caller attaches the X-Device-Mode: OFFLINE header
    to the dispatch request, the command transitions instead from PENDING
    to OFFLINE_LOCAL'.
    """
    base_headers = dict(headers or TEST_USERS["water_admin_headers"])
    if offline:
        base_headers["X-Device-Mode"] = "OFFLINE"
    res = api_client.dispatch_command(command_id, base_headers)
    return get_success_data(res)


def feedback(
    command_id: str,
    *,
    phase: str,
    actual_volume_liters: Optional[float] = None,
    failure_reason: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    payload = feedback_payload(
        phase=phase,
        actual_volume_liters=actual_volume_liters,
        failure_reason=failure_reason,
    )
    res = api_client.feedback_command(
        command_id, payload, headers or TEST_USERS["water_admin_headers"]
    )
    return get_success_data(res)


def request_override(quota_id: str, *, reason: str = "Drought response"
                     ) -> Dict[str, Any]:
    """PRD §3.5: 'An Operator may post an override request' — exclusive
    to Operator role per §1.7."""
    payload = request_override_payload(reason=reason)
    res = api_client.request_quota_override(
        quota_id, payload, TEST_USERS["operator_headers"]
    )
    return get_success_data(res)


def approve_override(quota_id: str, *, extra_liters: float
                     ) -> Dict[str, Any]:
    payload = approve_override_payload(extra_liters=extra_liters)
    res = api_client.approve_quota_override(
        quota_id, payload, TEST_USERS["water_admin_headers"]
    )
    return get_success_data(res)


def reject_override(quota_id: str, *, reason: Optional[str] = None
                    ) -> Dict[str, Any]:
    body: Dict[str, Any] = {} if reason is None else {"reason": reason}
    res = api_client.reject_quota_override(
        quota_id, body, TEST_USERS["water_admin_headers"]
    )
    return get_success_data(res)


def get_quota(quota_id: str) -> Dict[str, Any]:
    res = api_client.get_water_quota(
        quota_id, TEST_USERS["water_admin_headers"]
    )
    return get_success_data(res)


def get_plan(plot_id: str, plan_id: str) -> Dict[str, Any]:
    """Fetch via list — PRD §4 doesn't expose a singular plan GET, but
    the list-by-plot does. Tests should refresh state via the active
    plan returned by activate/suspend/resume."""
    res = api_client.list_plans(
        plot_id, TEST_USERS["water_admin_headers"]
    )
    data = get_success_data(res)
    items = data if isinstance(data, list) else data.get("items", [])
    for plan in items:
        if plan.get("id") == plan_id:
            return plan
    raise AssertionError(f"Plan {plan_id} not found under plot {plot_id}")


def get_command(command_id: str) -> Dict[str, Any]:
    res = api_client.get_control_command(
        command_id, TEST_USERS["water_admin_headers"]
    )
    return get_success_data(res)


def get_alert(alert_id: str) -> Dict[str, Any]:
    res = api_client.get_alert(
        alert_id, TEST_USERS["water_admin_headers"]
    )
    return get_success_data(res)


def get_plot(plot_id: str) -> Dict[str, Any]:
    res = api_client.get_plot(
        plot_id, TEST_USERS["water_admin_headers"]
    )
    return get_success_data(res)


def get_sensor(sensor_id: str) -> Dict[str, Any]:
    res = api_client.get_sensor(
        sensor_id, TEST_USERS["water_admin_headers"]
    )
    return get_success_data(res)


def get_bill(bill_id: str,
             headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    res = api_client.get_water_bill(
        bill_id, headers or TEST_USERS["water_admin_headers"]
    )
    return get_success_data(res)


def list_alerts(*, params: Optional[Dict[str, Any]] = None
                ) -> List[Dict[str, Any]]:
    res = api_client.list_alerts(
        TEST_USERS["water_admin_headers"], params=params
    )
    data = get_success_data(res)
    return data if isinstance(data, list) else data.get("items", [])


def list_audit_logs(*, params: Optional[Dict[str, Any]] = None
                    ) -> List[Dict[str, Any]]:
    res = api_client.list_audit_logs(
        TEST_USERS["water_admin_headers"], params=params
    )
    data = get_success_data(res)
    return data if isinstance(data, list) else data.get("items", [])


def list_commands(*, params: Optional[Dict[str, Any]] = None
                  ) -> List[Dict[str, Any]]:
    res = api_client.list_control_commands(
        TEST_USERS["water_admin_headers"], params=params
    )
    data = get_success_data(res)
    return data if isinstance(data, list) else data.get("items", [])


# ===========================================================================
# Tier 2 — entity hierarchy
# ===========================================================================
def setup_tenant_plot_quota(
    *,
    period_start: Optional[str] = None,
    period_end: Optional[str] = None,
    allocated_liters: float = 10000.0,
    warning_threshold_pct: Optional[float] = None,
    crop_type: str = "CORN",
    crop_stage: str = "VEGETATIVE",
    area_hectares: float = 10.0,
    pump_id: Optional[str] = None,
    add_online_sensor: bool = True,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Optional[Dict[str, Any]]]:
    """Tenant + Plot + WaterQuota covering [period_start, period_end).

    Optionally registers one ONLINE SOIL_MOISTURE sensor — needed because
    PRD §3.2 requires 'at least one Sensor on the plot has Sensor.status
    is ONLINE' for activation.

    If period_start is omitted, anchors to the next-day midnight after
    the current simulated clock — guarantees the plan window is
    strictly in the future of any prior test's clock advance, so
    plans don't auto-COMPLETE before tests can exercise them.

    Returns (tenant, plot, quota, sensor_or_None).
    """
    if period_start is None:
        now_dt = parse_iso(current_clock_iso())
        period_start = iso_z(
            (now_dt + timedelta(days=1)).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
        )
    period_end = period_end or add_days(period_start, 30)
    pump = pump_id or unique_pump_id("pump")
    tenant = create_tenant()
    plot = create_plot(
        tenant["id"],
        crop_type=crop_type,
        crop_stage=crop_stage,
        area_hectares=area_hectares,
        pump_id=pump,
    )
    quota = create_water_quota(
        plot["id"],
        period_start=period_start,
        period_end=period_end,
        allocated_liters=allocated_liters,
        warning_threshold_pct=warning_threshold_pct,
    )
    sensor = None
    if add_online_sensor:
        sensor = create_sensor(plot["id"], sensor_type="SOIL_MOISTURE")
    return tenant, plot, quota, sensor


def setup_active_plan(
    *,
    plot: Dict[str, Any],
    valve_group: Dict[str, Any],
    quota: Dict[str, Any],
    plan_window_start: Optional[str] = None,
    plan_window_end: Optional[str] = None,
    planned_volume_liters: float = 1000.0,
) -> Dict[str, Any]:
    """Create a plan with MANUAL_OVERRIDE source (so the test pins
    planned_volume_liters), then activate it. Returns the activated plan."""
    ws = plan_window_start or quota["period_start"]
    we = plan_window_end or add_days(ws, 1)
    plan = create_plan(
        plot["id"],
        window_start=ws,
        window_end=we,
        source="MANUAL_OVERRIDE",
        planned_volume_liters=planned_volume_liters,
    )
    activated = activate_plan(plot["id"], plan["id"])
    return activated


def setup_full_active_scenario(
    *,
    allocated_liters: float = 10000.0,
    warning_threshold_pct: Optional[float] = None,
    plan_volume_liters: float = 1000.0,
    period_start: Optional[str] = None,
    period_end: Optional[str] = None,
    crop_type: str = "CORN",
    crop_stage: str = "VEGETATIVE",
    area_hectares: float = 10.0,
    valve_control_mode: str = "SEQUENTIAL",
    valve_max_parallel: int = 1,
    plan_window_days: int = 28,
) -> Dict[str, Any]:
    """The most-common composite: Tenant + Plot (with 1 ONLINE sensor) +
    ValveGroup on the same pump + WaterQuota + ACTIVE IrrigationPlan.

    Plan window defaults to 28 days inside the quota period — wide
    enough to absorb advance_clock calls inside threshold/billing tests
    without auto-COMPLETing the plan (PRD §3.2: 'when the system clock
    advances past a plan's window_end and no ControlCommand for the
    plan remains in PENDING, DISPATCHING, or EXECUTING, the system
    transitions the plan from ACTIVE to COMPLETED').

    Returns dict with keys: tenant, plot, sensor, quota, valve_group, plan.
    """
    tenant, plot, quota, sensor = setup_tenant_plot_quota(
        period_start=period_start,
        period_end=period_end,
        allocated_liters=allocated_liters,
        warning_threshold_pct=warning_threshold_pct,
        crop_type=crop_type,
        crop_stage=crop_stage,
        area_hectares=area_hectares,
        add_online_sensor=True,
    )
    valve_group = create_valve_group(
        tenant["id"],
        pump_id=plot["pump_id"],
        valve_ids=[unique_valve_id("v")],
        control_mode=valve_control_mode,
        max_parallel_valves=valve_max_parallel,
    )
    plan = setup_active_plan(
        plot=plot,
        valve_group=valve_group,
        quota=quota,
        plan_window_start=quota["period_start"],
        plan_window_end=add_days(quota["period_start"], plan_window_days),
        planned_volume_liters=plan_volume_liters,
    )
    # PRD §3.5 quota aggregations (provisional_used_liters,
    # final_used_liters) filter ControlCommand records by
    # created_at / feedback_received_at falling inside
    # [period_start, period_end). Advance the simulated clock to one
    # hour past period_start so any subsequent command operations issued
    # by this fixture's caller land inside the quota window — keeps
    # quota math consistent with the PRD-faithful implementation.
    advance_clock(add_hours(quota["period_start"], 1))
    return {
        "tenant": tenant,
        "plot": plot,
        "sensor": sensor,
        "quota": quota,
        "valve_group": valve_group,
        "plan": plan,
    }


# ===========================================================================
# Tier 3 — full lifecycle shortcuts
# ===========================================================================
def create_and_dispatch_command(
    *,
    plan_id: str,
    valve_group_id: str,
    requested_volume_liters: float,
    offline: bool = False,
) -> Dict[str, Any]:
    """Create a ControlCommand and dispatch it.

    PRD §3.4: 'A successful creation reserves the volume and stores the
    command in PENDING.' Then dispatch flips PENDING → DISPATCHING (or
    OFFLINE_LOCAL with the offline header).
    """
    cmd = create_control_command(
        plan_id=plan_id,
        valve_group_id=valve_group_id,
        requested_volume_liters=requested_volume_liters,
    )
    return dispatch_command(cmd["id"], offline=offline)


def drive_command_to_executed(
    *,
    plan_id: str,
    valve_group_id: str,
    requested_volume_liters: float,
    actual_volume_liters: Optional[float] = None,
) -> Dict[str, Any]:
    """Full happy-path: create → dispatch → STARTED → COMPLETED.

    Returns the final ControlCommand snapshot in EXECUTED state.
    """
    if actual_volume_liters is None:
        actual_volume_liters = requested_volume_liters
    cmd = create_control_command(
        plan_id=plan_id,
        valve_group_id=valve_group_id,
        requested_volume_liters=requested_volume_liters,
    )
    dispatch_command(cmd["id"])
    feedback(cmd["id"], phase="STARTED")
    return feedback(
        cmd["id"], phase="COMPLETED",
        actual_volume_liters=actual_volume_liters,
    )


def drive_command_to_executing(
    *,
    plan_id: str,
    valve_group_id: str,
    requested_volume_liters: float,
) -> Dict[str, Any]:
    """create → dispatch → STARTED. Returns command in EXECUTING state."""
    cmd = create_control_command(
        plan_id=plan_id,
        valve_group_id=valve_group_id,
        requested_volume_liters=requested_volume_liters,
    )
    dispatch_command(cmd["id"])
    return feedback(cmd["id"], phase="STARTED")


def drive_command_to_dispatching(
    *,
    plan_id: str,
    valve_group_id: str,
    requested_volume_liters: float,
) -> Dict[str, Any]:
    """create → dispatch. Returns command in DISPATCHING state."""
    cmd = create_control_command(
        plan_id=plan_id,
        valve_group_id=valve_group_id,
        requested_volume_liters=requested_volume_liters,
    )
    return dispatch_command(cmd["id"])


# ===========================================================================
# Tier 4 — accumulation / threshold targeting (difficulty-design-driven)
# ===========================================================================
def setup_quota_at_usage(
    *,
    target_final_used_liters: float,
    allocated_liters: float = 10000.0,
    warning_threshold_pct: Optional[float] = None,
    period_start: Optional[str] = None,
    period_end: Optional[str] = None,
    crop_type: str = "CORN",
) -> Dict[str, Any]:
    """Drive a quota to a precise final_used_liters value by sending a
    single COMPLETED feedback. Used for boundary-precision tests around
    the warning_threshold_pct.

    Strategy: keep the command's requested_volume_liters strictly inside
    quota so the §3.4 quota guard at create-time passes; let the device
    over-deliver via actual_volume_liters at feedback time.

    Returns dict with: tenant, plot, quota, valve_group, plan, command,
    quota_after (refreshed).
    """
    period_end = period_end or (
        add_days(period_start, 30) if period_start else None
    )
    # Keep the in-flight provisional reservation strictly below the
    # allocation so neither the activation precondition nor the
    # command-create quota guard fires. The feedback step is then free
    # to over-deliver to land final_used_liters at the target.
    safe_request = min(
        max(target_final_used_liters, 1.0),
        max(allocated_liters * 0.5, 1.0),
    )
    ctx = setup_full_active_scenario(
        allocated_liters=allocated_liters,
        warning_threshold_pct=warning_threshold_pct,
        plan_volume_liters=safe_request,
        period_start=period_start,
        period_end=period_end,
        crop_type=crop_type,
        valve_control_mode="PARALLEL",
        valve_max_parallel=4,
    )
    # PRD §3.5: final_used_liters sums EXECUTED commands whose
    # feedback_received_at lies inside [period_start, period_end). The
    # virtual clock starts on wall-clock unless advanced; advance it to
    # an instant strictly inside the quota period so the command's
    # feedback timestamp lands in-window and counts toward the quota.
    advance_clock(add_hours(ctx["quota"]["period_start"], 1))
    cmd = drive_command_to_executed(
        plan_id=ctx["plan"]["id"],
        valve_group_id=ctx["valve_group"]["id"],
        requested_volume_liters=safe_request,
        actual_volume_liters=target_final_used_liters,
    )
    quota_after = get_quota(ctx["quota"]["id"])
    return {**ctx, "command": cmd, "quota_after": quota_after}


def setup_with_executed_volume_at_hours(
    *,
    consumption_pairs: List[Tuple[float, int]],
    allocated_liters: float = 1_000_000.0,
    period_start: Optional[str] = None,
    period_end: Optional[str] = None,
) -> Dict[str, Any]:
    """For tiered_water_fee tests. consumption_pairs is a list of
    (actual_volume_liters, hour_of_day) — the helper drives one EXECUTED
    command for each pair, with feedback_received_at landing inside the
    intended hour-of-day so the bill partitions PEAK vs OFFPEAK correctly.

    PRD §3.6 PEAK_HOURS = {6, 7, 8, 9, 18, 19, 20, 21}. Caller picks
    hours.

    Period is computed dynamically so each call gets a fresh
    [period_start, period_end) window past the simulated clock. This
    avoids forward-only clock collisions across tests.

    Returns ctx dict with tenant/plot/quota/valve_group/plan and the
    list of (cmd, target_iso) tuples.
    """
    # Anchor the period to the current clock advanced ahead by 1 day so
    # we have a clean day-aligned start strictly in the future of any
    # prior test's simulated clock.
    now_iso = current_clock_iso()
    now_dt = parse_iso(now_iso)
    # Start the period on the next-day midnight after now.
    base_day = (now_dt + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    period_start = period_start or iso_z(base_day)
    period_end = period_end or add_days(period_start, 30)
    total_planned = sum(v for v, _ in consumption_pairs) + 1.0
    ctx = setup_full_active_scenario(
        allocated_liters=allocated_liters,
        plan_volume_liters=total_planned,
        period_start=period_start,
        period_end=period_end,
        valve_control_mode="PARALLEL",
        valve_max_parallel=4,
    )
    commands: List[Dict[str, Any]] = []
    period_base = parse_iso(period_start).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    for offset_idx, (volume, hour) in enumerate(consumption_pairs):
        # Anchor each EXECUTED command at a unique target hour inside
        # the period. We advance the simulated clock to that hour so
        # feedback_received_at = current clock = target hour-of-day.
        target_dt = period_base + timedelta(days=1 + offset_idx, hours=hour)
        target_iso = iso_z(target_dt)
        advance_clock(target_iso)
        cmd = drive_command_to_executed(
            plan_id=ctx["plan"]["id"],
            valve_group_id=ctx["valve_group"]["id"],
            requested_volume_liters=volume,
            actual_volume_liters=volume,
        )
        commands.append({"command": cmd, "target_iso": target_iso,
                         "hour": hour, "volume": volume})
    return {**ctx, "commands": commands}


# ===========================================================================
# Difficulty-design-driven composite fixtures
# (Pre-named for the specific instances in SCAFFOLD_DIFFICULTY_DESIGN.yaml)
# ===========================================================================
def setup_quota_and_pending_command(
    *,
    allocated_liters: float = 10000.0,
    warning_threshold_pct: float = 80.0,
    requested_volume_liters: float = 7900.0,
    period_start: Optional[str] = None,
    period_end: Optional[str] = None,
) -> Dict[str, Any]:
    """For difficulty: dual_variant_calc/water_quota_provisional_vs_final_usage.

    Tenant + Plot + Quota + ValveGroup + ACTIVE plan + a freshly created
    PENDING ControlCommand. Returns dict with tenant/plot/quota/valve_group/
    plan/command.
    """
    if period_start is None:
        # Anchor the period strictly in the future of any prior test's
        # simulated clock — advance_clock is forward-only, so a fixed
        # DEFAULT_NOW_ISO can fall behind the live clock once another
        # test has advanced it. PRD §3.5 quota aggregations filter by
        # [period_start, period_end), so the command's created_at /
        # feedback_received_at must land inside the period.
        now_dt = parse_iso(current_clock_iso())
        period_start = iso_z(
            (now_dt + timedelta(days=1)).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
        )
    period_end = period_end or add_days(period_start, 30)
    ctx = setup_full_active_scenario(
        allocated_liters=allocated_liters,
        warning_threshold_pct=warning_threshold_pct,
        plan_volume_liters=max(requested_volume_liters, 1.0),
        period_start=period_start,
        period_end=period_end,
    )
    cmd = create_control_command(
        plan_id=ctx["plan"]["id"],
        valve_group_id=ctx["valve_group"]["id"],
        requested_volume_liters=requested_volume_liters,
    )
    return {**ctx, "command": cmd}


def setup_alert_with_abnormal_readings(
    *,
    sensor_min: float = 10.0,
    sensor_max: float = 90.0,
) -> Dict[str, Any]:
    """For difficulty: dual_variant_calc/alert_severity_provisional_vs_reconciled.

    PRD §3.1: 'If the same sensor produces three consecutive
    OUT_OF_RANGE readings, the third reading's validity is reclassified
    to ABNORMAL_FILTERED and an ABNORMAL_FLOW Alert is emitted with
    subject_type SENSOR.'

    Wait — for the difficulty-design test, the recipe says rule=ABNORMAL_FLOW
    on subject_type=PLOT. PRD §3.5 emits ABNORMAL_FLOW + subject_type=PLOT
    when a quota's usage_state crosses to WARNING. The difficulty-design
    instance is about the SAME alert object's severity recomputing
    pre/post sweep. We provide the building blocks; tests pick the path.

    Builds: Tenant + Plot + 1 SOIL_MOISTURE sensor with valid range
    [sensor_min, sensor_max]. Caller drives the readings.
    """
    tenant = create_tenant()
    plot = create_plot(tenant["id"], crop_type="CORN")
    sensor = create_sensor(
        plot["id"],
        sensor_type="SOIL_MOISTURE",
        min_valid_value=sensor_min,
        max_valid_value=sensor_max,
    )
    return {"tenant": tenant, "plot": plot, "sensor": sensor}


def setup_three_out_of_range_readings(
    *,
    sensor_min: float = 10.0,
    sensor_max: float = 90.0,
    values: Optional[List[float]] = None,
) -> Dict[str, Any]:
    """Builds a sensor and ingests three consecutive OUT_OF_RANGE
    readings, the third of which triggers ABNORMAL_FILTERED and an
    Alert per PRD §3.1.

    Returns dict with tenant/plot/sensor and the alert (looked up from
    /alerts list by rule_code + subject_id, without relying on
    server-side filtering)."""
    if values is None:
        values = [120.0, 130.0, 140.0]
    assert len(values) == 3
    base = setup_alert_with_abnormal_readings(
        sensor_min=sensor_min, sensor_max=sensor_max
    )
    sensor = base["sensor"]
    base_iso = DEFAULT_NOW_ISO
    for i, v in enumerate(values):
        ingest_reading(
            sensor["id"], value=v, reading_timestamp=add_minutes(base_iso, i)
        )
    # Page through /alerts looking for our sensor's ABNORMAL_FLOW alert.
    alert: Optional[Dict[str, Any]] = None
    offset = 0
    while True:
        alerts = list_alerts(params={"limit": 100, "offset": offset})
        if not alerts:
            break
        for a in alerts:
            if (
                a.get("subject_id") == sensor["id"]
                and a.get("rule_code") == "ABNORMAL_FLOW"
            ):
                alert = a
                break
        if alert is not None or len(alerts) < 100:
            break
        offset += 100
    return {**base, "alert": alert}


def setup_billing_period_with_quota(
    *,
    allocated_liters: float = 1_000_000.0,
    period_start: Optional[str] = None,
    period_end: Optional[str] = None,
) -> Dict[str, Any]:
    """Tenant + Plot + WaterQuota covering [period_start, period_end) with
    a generous allocation so EXECUTED commands inside the window don't trip
    quota guards. For tiered-fee / settlement tests."""
    period_start = period_start or DEFAULT_NOW_ISO
    period_end = period_end or add_days(period_start, 30)
    tenant, plot, quota, sensor = setup_tenant_plot_quota(
        period_start=period_start,
        period_end=period_end,
        allocated_liters=allocated_liters,
        add_online_sensor=True,
    )
    return {
        "tenant": tenant,
        "plot": plot,
        "quota": quota,
        "sensor": sensor,
    }


def setup_overlap_plans(
    *,
    plan1_offset_hours_from_period_start: int = 24,
    plan1_duration_hours: int = 24,
    plan1_window_start: Optional[str] = None,
    plan1_window_end: Optional[str] = None,
) -> Dict[str, Any]:
    """For difficulty: resource_temporal_overlap/irrigation_plan_window_half_open_overlap.

    Tenant + Plot (1 ONLINE sensor) + ValveGroup + Quota + ACTIVE plan1.
    Caller creates plan2 to test adjacency vs overlap behaviour.

    Plan windows are pinned RELATIVE to the quota.period_start so they
    stay inside the quota window even if the simulated clock has
    advanced from a previous test. The two explicit kwargs
    plan1_window_start / plan1_window_end (back-compat) override the
    relative offsets when provided.
    """
    tenant, plot, quota, sensor = setup_tenant_plot_quota(
        allocated_liters=100000.0,
        add_online_sensor=True,
    )
    if plan1_window_start is None:
        plan1_window_start = add_hours(
            quota["period_start"], plan1_offset_hours_from_period_start
        )
    if plan1_window_end is None:
        plan1_window_end = add_hours(
            plan1_window_start, plan1_duration_hours
        )
    valve_group = create_valve_group(
        tenant["id"],
        pump_id=plot["pump_id"],
        control_mode="SEQUENTIAL",
        max_parallel_valves=1,
    )
    plan1 = create_plan(
        plot["id"],
        window_start=plan1_window_start,
        window_end=plan1_window_end,
        source="MANUAL_OVERRIDE",
        planned_volume_liters=500.0,
    )
    activated = activate_plan(plot["id"], plan1["id"])
    return {
        "tenant": tenant,
        "plot": plot,
        "sensor": sensor,
        "quota": quota,
        "valve_group": valve_group,
        "plan": activated,
    }


def setup_pump_with_two_valve_groups(
    *,
    vg1_mode: str = "SEQUENTIAL",
    vg1_max: int = 1,
    vg2_mode: str = "SEQUENTIAL",
    vg2_max: int = 1,
    extra_vgs: Optional[List[Tuple[str, int]]] = None,
    allocated_liters: float = 1_000_000.0,
) -> Dict[str, Any]:
    """For pump-and-valve interlock tests (Rule 7 / Rule 8).

    Tenant + Plot + 1 ONLINE sensor + ACTIVE plan +
    two ValveGroups on the SAME pump (matching Plot.pump_id), plus
    optional additional vgs."""
    ctx = setup_full_active_scenario(
        allocated_liters=allocated_liters,
        plan_volume_liters=1000.0,
        valve_control_mode=vg1_mode,
        valve_max_parallel=vg1_max,
    )
    tenant = ctx["tenant"]
    plot = ctx["plot"]
    vg1 = ctx["valve_group"]
    vg2 = create_valve_group(
        tenant["id"],
        pump_id=plot["pump_id"],
        control_mode=vg2_mode,
        max_parallel_valves=vg2_max,
    )
    extras: List[Dict[str, Any]] = []
    if extra_vgs:
        for mode, mx in extra_vgs:
            extras.append(create_valve_group(
                tenant["id"],
                pump_id=plot["pump_id"],
                control_mode=mode,
                max_parallel_valves=mx,
            ))
    return {**ctx, "valve_group_2": vg2, "extra_valve_groups": extras}


def setup_quota_at_warning_for_override_priority(
    *,
    allocated_liters: float = 10000.0,
    warning_threshold_pct: float = 80.0,
) -> Dict[str, Any]:
    """For Rule 5 priority pair tests. Drive the quota to WARNING via
    EXECUTED command, then SUSPEND the plan to set up the
    state-vs-business_fiscal precedence test.

    Plan reservation is kept conservatively low; the EXECUTED command
    requests + delivers enough to push final usage to ~85% of
    allocation (above the 80% warning threshold but below 100%)."""
    ctx = setup_full_active_scenario(
        allocated_liters=allocated_liters,
        warning_threshold_pct=warning_threshold_pct,
        plan_volume_liters=allocated_liters * 0.5,
        valve_control_mode="PARALLEL",
        valve_max_parallel=4,
    )
    # Advance clock into quota window so feedback_received_at lands
    # inside [period_start, period_end) — required for final_used_liters
    # accumulation per PRD §3.5.
    advance_clock(add_hours(ctx["quota"]["period_start"], 1))
    drive_command_to_executed(
        plan_id=ctx["plan"]["id"],
        valve_group_id=ctx["valve_group"]["id"],
        requested_volume_liters=allocated_liters * 0.4,
        actual_volume_liters=allocated_liters * 0.85,
    )
    suspend_plan(ctx["plot"]["id"], ctx["plan"]["id"])
    return ctx


def setup_issued_bill_with_payment(
    *,
    bill_total_floor_cents: int = 100_000,
    partial_payment_cents: int = 30_000,
) -> Dict[str, Any]:
    """For difficulty: compensating_invariant/bill_money_invariant_on_dispute_accept_cancel.

    Build a Tenant + Plot + Quota covering a billing period, drive enough
    EXECUTED consumption to make the bill non-trivial, create a draft
    bill, issue it, and post a partial payment. Returns the ISSUED bill
    in dict.
    """
    # Anchor the billing period strictly in the future of any prior
    # test's simulated clock to avoid forward-only-clock collisions.
    now_dt = parse_iso(current_clock_iso())
    period_start = iso_z(
        (now_dt + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
    )
    period_end = add_days(period_start, 30)
    base = setup_billing_period_with_quota(
        allocated_liters=1_000_000.0,
        period_start=period_start,
        period_end=period_end,
    )
    valve_group = create_valve_group(
        base["tenant"]["id"],
        pump_id=base["plot"]["pump_id"],
        control_mode="PARALLEL",
        max_parallel_valves=4,
    )
    plan = setup_active_plan(
        plot=base["plot"],
        valve_group=valve_group,
        quota=base["quota"],
        plan_window_start=period_start,
        plan_window_end=add_days(period_start, 1),
        planned_volume_liters=200_000.0,
    )
    # Drive a sizeable EXECUTED command at peak hour (06:00) on the
    # FIRST day inside the billing period to ensure the bill total
    # clears the floor.
    advance_clock(add_hours(period_start, 6))
    drive_command_to_executed(
        plan_id=plan["id"],
        valve_group_id=valve_group["id"],
        requested_volume_liters=80_000.0,
        actual_volume_liters=80_000.0,
    )
    bill_payload = create_water_bill_payload(
        tenant_id=base["tenant"]["id"],
        plot_id=base["plot"]["id"],
        period_start=period_start,
        period_end=period_end,
    )
    res = api_client.create_water_bill(
        bill_payload, TEST_USERS["water_admin_headers"]
    )
    bill = get_success_data(res)
    assert bill["total_amount_cents"] >= bill_total_floor_cents, (
        f"Bill total {bill['total_amount_cents']} below floor "
        f"{bill_total_floor_cents}; recipe needs more EXECUTED volume"
    )
    res = api_client.issue_bill(bill["id"], TEST_USERS["water_admin_headers"])
    bill = get_success_data(res)
    # Tenant ownership-gated payment — use make_tenant_headers per PRD §2.1.
    tenant_headers = make_tenant_headers(base["tenant"]["id"])
    res = api_client.pay_bill(
        bill["id"],
        payment_payload(amount_cents=partial_payment_cents),
        tenant_headers,
    )
    bill = get_success_data(res)
    return {**base, "valve_group": valve_group, "plan": plan, "bill": bill}


def setup_quota_in_pending_approval(
    *,
    allocated_liters: float = 10000.0,
    warning_threshold_pct: float = 80.0,
) -> Dict[str, Any]:
    """Drive quota to OVER (via device over-delivery — request stays
    inside quota, actual exceeds) then post a PENDING_APPROVAL request.

    PRD §3.4 quota guard at CREATE inspects projected usage_state, so
    the requested_volume must stay within effective_allocation. The
    feedback's actual_volume_liters is unconstrained (PRD §3.4 only
    requires it be ≥ 0), so device over-delivery legally pushes
    final_used_liters past allocation and flips usage_state to OVER.

    Used for approve/reject override race tests."""
    ctx = setup_full_active_scenario(
        allocated_liters=allocated_liters,
        warning_threshold_pct=warning_threshold_pct,
        # Plan reservation must also stay below allocation so activation
        # doesn't overshoot the (provisional-based or final-based) guard.
        plan_volume_liters=allocated_liters * 0.5,
        valve_control_mode="PARALLEL",
        valve_max_parallel=4,
    )
    # PRD §3.5: final_used_liters sums EXECUTED commands whose
    # feedback_received_at lies inside [period_start, period_end). Advance
    # the clock into the quota window so the over-delivery flips
    # usage_state to OVER (a precondition for a request_override call).
    advance_clock(add_hours(ctx["quota"]["period_start"], 1))
    # Request stays inside quota; actual overshoots.
    drive_command_to_executed(
        plan_id=ctx["plan"]["id"],
        valve_group_id=ctx["valve_group"]["id"],
        requested_volume_liters=allocated_liters * 0.4,
        actual_volume_liters=allocated_liters + 100,
    )
    request_override(ctx["quota"]["id"], reason="drought response")
    return ctx


def setup_resolved_alert(
    *,
    sensor_min: float = 10.0,
    sensor_max: float = 90.0,
) -> Dict[str, Any]:
    """For Alert reopen-cycle tests. Builds a sensor + abnormal readings
    that emit an ABNORMAL_FLOW alert, then acknowledges and resolves it.

    Returns dict with tenant/plot/sensor/alert (in RESOLVED state)."""
    ctx = setup_three_out_of_range_readings(
        sensor_min=sensor_min, sensor_max=sensor_max
    )
    alert = ctx["alert"]
    assert alert is not None, (
        "ABNORMAL_FLOW alert not emitted by 3rd OUT_OF_RANGE reading"
    )
    res = api_client.acknowledge_alert(
        alert["id"], TEST_USERS["water_admin_headers"]
    )
    get_success_data(res)
    res = api_client.resolve_alert(
        alert["id"], TEST_USERS["water_admin_headers"]
    )
    resolved = get_success_data(res)
    return {**ctx, "alert": resolved}


__all__ = [
    "iso_z",
    "parse_iso",
    "add_seconds",
    "add_minutes",
    "add_hours",
    "add_days",
    "DEFAULT_NOW_ISO",
    "advance_clock",
    "current_clock_iso",
    "run_sweep",
    "emit_event",
    # Tier 1
    "create_tenant",
    "create_plot",
    "create_sensor",
    "ingest_reading",
    "create_valve_group",
    "create_water_quota",
    "create_plan",
    "activate_plan",
    "suspend_plan",
    "resume_plan",
    "create_control_command",
    "dispatch_command",
    "feedback",
    "request_override",
    "approve_override",
    "reject_override",
    "get_quota",
    "get_plan",
    "get_command",
    "get_alert",
    "get_plot",
    "get_sensor",
    "get_bill",
    "list_alerts",
    "list_audit_logs",
    "list_commands",
    # Tier 2
    "setup_tenant_plot_quota",
    "setup_active_plan",
    "setup_full_active_scenario",
    # Tier 3
    "create_and_dispatch_command",
    "drive_command_to_executed",
    "drive_command_to_executing",
    "drive_command_to_dispatching",
    # Tier 4 / difficulty-design
    "setup_quota_at_usage",
    "setup_with_executed_volume_at_hours",
    "setup_quota_and_pending_command",
    "setup_alert_with_abnormal_readings",
    "setup_three_out_of_range_readings",
    "setup_billing_period_with_quota",
    "setup_overlap_plans",
    "setup_pump_with_two_valve_groups",
    "setup_quota_at_warning_for_override_priority",
    "setup_issued_bill_with_payment",
    "setup_quota_in_pending_approval",
    "setup_resolved_alert",
]
