"""Composite setup helpers for multi-step test prerequisites.

Most interesting claims require the system to be in a specific cross-entity
state that takes several API calls to reach. These helpers encapsulate the
common preambles so tests focus on assertions. They use get_success_data()
(lenient 2xx validator) so a broken setup surfaces as a clear "Setup failed".

Identity threading: the Subscriber role is entity_backed:Account, so every
ownership-gated call (arm/disarm) uses make_subscriber_headers(account_id)
with the real owning account id — never the shared subscriber constant.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_monitoring_plan_payload,
    create_account_payload,
    create_system_payload,
    create_sensor_payload,
    create_alarm_event_payload,
    create_permit_payload,
    change_plan_payload,
    arm_payload,
    resolve_payload,
)
from .test_users import TEST_USERS, make_subscriber_headers


_ADMIN = TEST_USERS["admin_headers"]
_OPERATOR = TEST_USERS["operator_headers"]

# Standard plan payloads matching the design-index fee values.
PLAN_BASIC = dict(tier="BASIC", monthly_fee_cents=1500, police_dispatch_included=False,
                  max_sensors=8, cellular_backup_included=False)
PLAN_PLUS = dict(tier="PLUS", monthly_fee_cents=3100, police_dispatch_included=True,
                 max_sensors=16, cellular_backup_included=True)
PLAN_PRO = dict(tier="PRO", monthly_fee_cents=6200, police_dispatch_included=True,
                max_sensors=32, cellular_backup_included=True)


# ─── Clock control ────────────────────────────────────────────────────

def set_clock(now_utc: str):
    """Set the server logical clock to an ISO 8601 instant."""
    return get_success_data(api_client.set_clock(now_utc, _ADMIN))


# ─── Tier 0: Bare creation primitives ─────────────────────────────────

def create_plan(**overrides):
    """Create one monitoring plan. Returns the plan object."""
    res = api_client.create_monitoring_plan(create_monitoring_plan_payload(**overrides), _ADMIN)
    return get_success_data(res)


def create_account(plan_id, **overrides):
    """Create one PENDING account on a plan. Returns the account object."""
    res = api_client.create_account(create_account_payload(plan_id, **overrides), _ADMIN)
    return get_success_data(res)


def create_system(account_id, **overrides):
    """Register one security system on an account. Returns the system object."""
    res = api_client.create_system(create_system_payload(account_id, **overrides), _ADMIN)
    return get_success_data(res)


def create_sensor(system_id, **overrides):
    """Enroll one sensor on a system. Returns the sensor object."""
    res = api_client.create_sensor(create_sensor_payload(system_id, **overrides), _ADMIN)
    return get_success_data(res)


def issue_permit(account_id, permit_number, **overrides):
    """Issue one ACTIVE permit on an account. Returns the permit object."""
    res = api_client.create_permit(
        create_permit_payload(account_id, permit_number, **overrides), _ADMIN)
    return get_success_data(res)


# ─── Tier 1: Plan + account + system + sensor (pre-activation) ────────

def setup_account_with_system(plan_overrides=None, account_overrides=None,
                              system_overrides=None, sensor_overrides=None,
                              with_sensor=True):
    """Create plan -> account (PENDING) -> system -> one sensor.

    Returns dict(plan, account, system, sensor). The account is still PENDING;
    it is NOT activated here. This is the shared preamble for nearly every
    scenario.
    """
    plan = create_plan(**(plan_overrides or {}))
    account = create_account(plan["id"], **(account_overrides or {}))
    system = create_system(account["id"], **(system_overrides or {}))
    sensor = None
    if with_sensor:
        sensor = create_sensor(system["id"], **(sensor_overrides or {}))
    return {"plan": plan, "account": account, "system": system, "sensor": sensor}


# ─── Tier 1b: Activated account ───────────────────────────────────────

def setup_activated_account(plan_overrides=None, account_overrides=None,
                            system_overrides=None, sensor_overrides=None):
    """Plan -> account -> system -> sensor -> activate.

    Returns dict(plan, account, system, sensor, version) where `account` is the
    activated account object (contract_status ACTIVE) and `version` is its
    post-activation version.
    """
    ctx = setup_account_with_system(
        plan_overrides=plan_overrides, account_overrides=account_overrides,
        system_overrides=system_overrides, sensor_overrides=sensor_overrides)
    activated = get_success_data(api_client.activate_account(ctx["account"]["id"], _ADMIN))
    ctx["account"] = activated
    ctx["version"] = activated["version"]
    return ctx


def setup_activated_armed_account(plan_overrides=None, account_overrides=None,
                                  system_overrides=None, sensor_overrides=None,
                                  mode="ARMED_AWAY"):
    """Activated account whose system is then armed (ARMED_AWAY by default).

    Uses make_subscriber_headers(account_id) for the ownership-gated arm.
    Returns dict(plan, account, system, sensor, version) with the system in
    the armed state.
    """
    ctx = setup_activated_account(
        plan_overrides=plan_overrides, account_overrides=account_overrides,
        system_overrides=system_overrides, sensor_overrides=sensor_overrides)
    sub = make_subscriber_headers(ctx["account"]["id"])
    armed = get_success_data(
        api_client.arm_system(ctx["system"]["id"], arm_payload(mode=mode), sub))
    ctx["system"] = armed
    return ctx


# ─── Tier 3: Alarm-event lifecycle shortcuts ──────────────────────────

def ingest_event(system_id, sensor_id, signal_type="BURGLARY"):
    """Ingest one alarm event. Returns the event object."""
    res = api_client.create_alarm_event(
        create_alarm_event_payload(system_id, sensor_id, signal_type=signal_type), _OPERATOR)
    return get_success_data(res)


def ingest_route_dispatch(system_id, sensor_id, signal_type="BURGLARY"):
    """Ingest -> route -> dispatch one event. Returns the DISPATCHED event object.

    Requires the owning account to be ACTIVE and the system armed/not-test-mode
    (so the event is not auto-suppressed and routing is permitted).
    """
    ev = ingest_event(system_id, sensor_id, signal_type=signal_type)
    get_success_data(api_client.route_alarm_event(ev["id"], _OPERATOR))
    dispatched = get_success_data(api_client.dispatch_alarm_event(ev["id"], _OPERATOR))
    return dispatched


def resolve_false_alarm(event_id):
    """Resolve a DISPATCHED event as FALSE_ALARM. Returns the resolved event."""
    res = api_client.resolve_alarm_event(event_id, resolve_payload("FALSE_ALARM"), _OPERATOR)
    return get_success_data(res)


def resolve_real(event_id):
    """Resolve a DISPATCHED event as REAL. Returns the resolved event."""
    res = api_client.resolve_alarm_event(event_id, resolve_payload("REAL"), _OPERATOR)
    return get_success_data(res)


def fine_for_event(event_id):
    """Return the Fine object whose alarm_event_id == event_id (or None)."""
    data, _meta = _list(api_client.list_fines(_ADMIN, params={"alarm_event_id": event_id}))
    return data[0] if data else None


def dispatch_for_event(event_id):
    """Return the Dispatch object for an alarm event (or None)."""
    data, _meta = _list(api_client.list_dispatches(_ADMIN, params={"alarm_event_id": event_id}))
    return data[0] if data else None


def _list(response):
    """Return (data, meta) from a paginated list response, leniently."""
    body = response.json()
    return body.get("data", []), body.get("meta", {})


# ─── Tier 4: Cumulative false-alarm sequences ─────────────────────────

def setup_false_alarm_sequence(num_events, plan_overrides=None, with_permit=False,
                               permit_number="P-SEQ", base_time="2026-06-01T00:00:00Z",
                               spacing_minutes=10, sensor_type="MOTION"):
    """Activate a PRO account (armed), then ingest/route/dispatch/resolve-FALSE
    `num_events` burglary false alarms spaced `spacing_minutes` apart.

    Returns dict(plan, account, system, sensor, events) where `events` is the
    list of resolved FALSE_ALARM event objects in chronological order. Each
    event's clock is advanced before ingest so debounce never collides.
    Optionally issues one ACTIVE permit before the sequence.
    """
    set_clock(base_time)
    ctx = setup_activated_armed_account(
        plan_overrides=plan_overrides or PLAN_PRO,
        system_overrides={"primary_path": "CELLULAR"},
        sensor_overrides={"sensor_type": sensor_type})
    if with_permit:
        issue_permit(ctx["account"]["id"], permit_number, filed_days_late=0)

    events = []
    base_minute = 0
    # base_time minute is 0; advance by spacing for each event
    from datetime import datetime, timedelta
    base_dt = datetime.fromisoformat(base_time.replace("Z", "+00:00"))
    for i in range(num_events):
        ts = (base_dt + timedelta(minutes=base_minute + i * spacing_minutes))
        set_clock(ts.strftime("%Y-%m-%dT%H:%M:%SZ"))
        dispatched = ingest_route_dispatch(
            ctx["system"]["id"], ctx["sensor"]["id"], signal_type="BURGLARY")
        resolved = resolve_false_alarm(dispatched["id"])
        events.append(resolved)
    ctx["events"] = events
    return ctx


# ─── Tier 1c: Account in CANCELLATION_REQUESTED ───────────────────────

def setup_cancellation_requested_account(plan_overrides=None, account_overrides=None,
                                         system_overrides=None, sensor_overrides=None,
                                         base_time="2026-06-01T00:00:00Z"):
    """Activated account driven to CANCELLATION_REQUESTED via request-cancellation.

    Returns dict(plan, account, system, sensor, version) where `account` is the
    object returned by request-cancellation (contract_status
    CANCELLATION_REQUESTED) and `version` is its current version.
    """
    set_clock(base_time)
    ctx = setup_activated_account(
        plan_overrides=plan_overrides, account_overrides=account_overrides,
        system_overrides=system_overrides, sensor_overrides=sensor_overrides)
    requested = get_success_data(
        api_client.request_cancellation(ctx["account"]["id"], _ADMIN))
    ctx["account"] = requested
    ctx["version"] = requested["version"]
    return ctx


# ─── Tier 2: Plan + activated account ready for change-plan ───────────

def setup_two_plans_activated_account(base_plan=None, alt_plan=None,
                                      base_time="2026-06-01T00:00:00Z"):
    """Create base + alternate plans, then an activated account on the base plan.

    Returns dict(base_plan, alt_plan, account, system, sensor, version).
    Defaults: BASIC base, PLUS alt.
    """
    set_clock(base_time)
    bp = create_plan(**(base_plan or PLAN_BASIC))
    ap = create_plan(**(alt_plan or PLAN_PLUS))
    account = create_account(bp["id"])
    system = create_system(account["id"], primary_path="BROADBAND")
    sensor = create_sensor(system["id"], sensor_type="DOOR")
    activated = get_success_data(api_client.activate_account(account["id"], _ADMIN))
    return {"base_plan": bp, "alt_plan": ap, "account": activated,
            "system": system, "sensor": sensor, "version": activated["version"]}
