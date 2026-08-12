"""Composite setup helpers: multi-step scenario builders shared by tests.

Every helper builds preconditions from scratch via PRD-declared endpoints and
uses the lenient get_success_data() validator so setup failures surface as
clear errors rather than confusing assertion failures.

Identity threading: after creating a Caregiver / Senior / Installer, any
ownership-gated call uses make_<role>_headers(entity["id"]) — never the shared
TEST_USERS fallback constants.
"""
from typing import Dict, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from . import factories
from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_caregiver_headers,
    make_installer_headers,
    make_senior_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
AGENT = TEST_USERS["monitoring_agent_headers"]
HUB = TEST_USERS["device_hub_headers"]

DEFAULT_WINDOW = ("2026-05-01T09:00:00Z", "2026-05-01T10:00:00Z")
DEFAULT_COMPLETE_AT = "2026-05-01T09:30:00Z"


# ---------------------------------------------------------------------------
# Tier 1: single-resource builders
# ---------------------------------------------------------------------------

def create_plan(**overrides) -> dict:
    """Create a subscription plan. Returns the plan resource."""
    return get_success_data(
        api_client.create_subscription_plan(
            factories.create_subscription_plan_payload(**overrides), ADMIN
        )
    )


def create_senior(**overrides) -> dict:
    """Register a senior. Returns the senior resource."""
    return get_success_data(
        api_client.create_senior(factories.create_senior_payload(**overrides), ADMIN)
    )


def create_subscription(senior_id: str, plan_id: str) -> dict:
    """Create a PROVISIONING/CURRENT subscription. Returns the subscription."""
    return get_success_data(
        api_client.create_subscription(
            factories.create_subscription_payload(senior_id, plan_id), ADMIN
        )
    )


def order_kit(senior_id: str, motion_sensor_count: Optional[int] = None) -> dict:
    """Order a sensor kit (ORDERED, devices PROVISIONED). Returns the kit."""
    overrides = {}
    if motion_sensor_count is not None:
        overrides["motion_sensor_count"] = motion_sensor_count
    return get_success_data(
        api_client.create_sensor_kit(
            factories.create_sensor_kit_payload(senior_id, **overrides), ADMIN
        )
    )


def ship_kit(kit_id: str) -> dict:
    return get_success_data(api_client.ship_sensor_kit(kit_id, ADMIN))


def deliver_kit(kit_id: str) -> dict:
    return get_success_data(api_client.mark_sensor_kit_delivered(kit_id, ADMIN))


def create_installer(**overrides) -> dict:
    return get_success_data(
        api_client.create_installer(
            factories.create_installer_payload(**overrides), ADMIN
        )
    )


def schedule_appointment(
    senior_id: str,
    kit_id: str,
    installer_id: str,
    window_start: str = DEFAULT_WINDOW[0],
    window_end: str = DEFAULT_WINDOW[1],
) -> dict:
    return get_success_data(
        api_client.create_install_appointment(
            factories.create_install_appointment_payload(
                senior_id,
                kit_id,
                installer_id,
                window_start=window_start,
                window_end=window_end,
            ),
            ADMIN,
        )
    )


def set_clock(to_iso8601: str) -> dict:
    return get_success_data(
        api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN)
    )


# ---------------------------------------------------------------------------
# Tier 2/3: installation pipeline and activation
# ---------------------------------------------------------------------------

def confirm_and_complete_appointment(
    appointment_id: str, installer_id: str, complete_at: str = DEFAULT_COMPLETE_AT
) -> dict:
    """Confirm as the assigned installer, move the clock inside the window,
    then complete. Returns the COMPLETED appointment."""
    installer_headers = make_installer_headers(installer_id)
    get_success_data(
        api_client.confirm_install_appointment(appointment_id, installer_headers)
    )
    set_clock(complete_at)
    return get_success_data(
        api_client.complete_install_appointment(appointment_id, installer_headers)
    )


def install_kit(
    senior_id: str,
    kit_id: str,
    installer: Optional[dict] = None,
    window_start: str = DEFAULT_WINDOW[0],
    window_end: str = DEFAULT_WINDOW[1],
    complete_at: str = DEFAULT_COMPLETE_AT,
) -> Tuple[dict, dict]:
    """Drive a kit to INSTALLED via the appointment pipeline.

    Returns (installer, appointment)."""
    if installer is None:
        installer = create_installer()
    appointment = schedule_appointment(
        senior_id, kit_id, installer["id"], window_start, window_end
    )
    confirm_and_complete_appointment(appointment["id"], installer["id"], complete_at)
    return installer, appointment


def get_kit_devices(kit_id: str) -> Dict[str, object]:
    """Return {'gateway': device, 'wearable': device, 'motions': [device, ...]}."""
    devices, _meta = _list_devices(kit_id)
    gateway = next(d for d in devices if d["device_type"] == "GATEWAY")
    wearable = next(d for d in devices if d["device_type"] == "WEARABLE")
    motions = [d for d in devices if d["device_type"] == "MOTION"]
    return {"gateway": gateway, "wearable": wearable, "motions": motions}


def _list_devices(kit_id: str):
    from prd_bench_local_runner.testing import validate_paginated

    return validate_paginated(api_client.list_devices(ADMIN, params={"kit_id": kit_id}))


def setup_senior_with_subscription(
    plan_overrides: Optional[dict] = None,
    senior_overrides: Optional[dict] = None,
) -> dict:
    """Plan + senior + PROVISIONING subscription. Returns a context dict."""
    plan = create_plan(**(plan_overrides or {}))
    senior = create_senior(**(senior_overrides or {}))
    subscription = create_subscription(senior["id"], plan["id"])
    return {"plan": plan, "senior": senior, "subscription": subscription}


def setup_installed_senior(
    plan_overrides: Optional[dict] = None,
    senior_overrides: Optional[dict] = None,
    motion_sensor_count: Optional[int] = None,
    window_start: str = DEFAULT_WINDOW[0],
    window_end: str = DEFAULT_WINDOW[1],
    complete_at: str = DEFAULT_COMPLETE_AT,
) -> dict:
    """Plan + senior + subscription + kit driven to INSTALLED (devices INSTALLED).

    Subscription remains PROVISIONING. Returns a context dict."""
    ctx = setup_senior_with_subscription(plan_overrides, senior_overrides)
    kit = order_kit(ctx["senior"]["id"], motion_sensor_count)
    ship_kit(kit["id"])
    deliver_kit(kit["id"])
    installer, appointment = install_kit(
        ctx["senior"]["id"],
        kit["id"],
        window_start=window_start,
        window_end=window_end,
        complete_at=complete_at,
    )
    ctx.update(
        {
            "kit": get_success_data(api_client.get_sensor_kit(kit["id"], ADMIN)),
            "installer": installer,
            "appointment": appointment,
            "devices": get_kit_devices(kit["id"]),
        }
    )
    return ctx


def setup_active_senior(
    plan_overrides: Optional[dict] = None,
    senior_overrides: Optional[dict] = None,
    motion_sensor_count: Optional[int] = None,
    window_start: str = DEFAULT_WINDOW[0],
    window_end: str = DEFAULT_WINDOW[1],
    complete_at: str = DEFAULT_COMPLETE_AT,
) -> dict:
    """Full onboarding: installed kit + ACTIVE subscription (posture ACTIVE).

    Returns a context dict with plan/senior/subscription/kit/installer/
    appointment/devices keys."""
    ctx = setup_installed_senior(
        plan_overrides=plan_overrides,
        senior_overrides=senior_overrides,
        motion_sensor_count=motion_sensor_count,
        window_start=window_start,
        window_end=window_end,
        complete_at=complete_at,
    )
    subscription = get_success_data(
        api_client.activate_subscription(ctx["subscription"]["id"], ADMIN)
    )
    ctx["subscription"] = subscription
    ctx["kit"] = get_success_data(api_client.get_sensor_kit(ctx["kit"]["id"], ADMIN))
    return ctx


def setup_two_active_seniors_one_installer(
    plan_overrides: Optional[dict] = None,
) -> Tuple[dict, dict]:
    """Two seniors on the same plan, each with a kit installed by one shared
    installer (back-to-back windows 09:00-10:00 and 10:30-11:30, completed at
    09:30 and 11:00), both subscriptions activated at clock 2026-05-01T11:00Z.

    Returns (ctx_a, ctx_b)."""
    plan = create_plan(**(plan_overrides or {}))
    installer = create_installer()
    contexts = []
    windows = (
        ("2026-05-01T09:00:00Z", "2026-05-01T10:00:00Z", "2026-05-01T09:30:00Z"),
        ("2026-05-01T10:30:00Z", "2026-05-01T11:30:00Z", "2026-05-01T11:00:00Z"),
    )
    for index, (ws, we, complete_at) in enumerate(windows):
        senior = create_senior(
            full_name=f"Shared Senior {index + 1}",
            address=f"{index + 1} Shared St",
        )
        subscription = create_subscription(senior["id"], plan["id"])
        kit = order_kit(senior["id"])
        ship_kit(kit["id"])
        deliver_kit(kit["id"])
        appointment = schedule_appointment(senior["id"], kit["id"], installer["id"], ws, we)
        confirm_and_complete_appointment(
            appointment["id"], installer["id"], complete_at
        )
        contexts.append(
            {
                "plan": plan,
                "senior": senior,
                "subscription": subscription,
                "kit": kit,
                "installer": installer,
                "appointment": appointment,
            }
        )
    for ctx in contexts:
        ctx["subscription"] = get_success_data(
            api_client.activate_subscription(ctx["subscription"]["id"], ADMIN)
        )
    return contexts[0], contexts[1]


# ---------------------------------------------------------------------------
# Tier 2: caregivers, contact tree, alerts
# ---------------------------------------------------------------------------

def add_caregiver(senior_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_caregiver(
            factories.create_caregiver_payload(senior_id, **overrides), ADMIN
        )
    )


def add_contact_entry(
    senior_id: str,
    caregiver_id: str,
    priority_rank: int = 1,
    min_severity: str = "LOW",
    response_timeout_seconds: int = 3600,
) -> dict:
    return get_success_data(
        api_client.create_contact_tree_entry(
            factories.create_contact_tree_entry_payload(
                senior_id,
                caregiver_id,
                priority_rank=priority_rank,
                min_severity=min_severity,
                response_timeout_seconds=response_timeout_seconds,
            ),
            ADMIN,
        )
    )


def add_caregiver_with_contact(
    senior_id: str,
    priority_rank: int = 1,
    min_severity: str = "LOW",
    response_timeout_seconds: int = 3600,
    **caregiver_overrides,
) -> Tuple[dict, dict]:
    """Caregiver serving the senior + one ACTIVE contact-tree entry.

    Returns (caregiver, entry)."""
    caregiver = add_caregiver(senior_id, **caregiver_overrides)
    entry = add_contact_entry(
        senior_id,
        caregiver["id"],
        priority_rank=priority_rank,
        min_severity=min_severity,
        response_timeout_seconds=response_timeout_seconds,
    )
    return caregiver, entry


def raise_manual_alert(senior_id: str, severity: str = "MEDIUM", **overrides) -> dict:
    """MonitoringAgent raises a MANUAL alert. Returns the alert."""
    return get_success_data(
        api_client.create_alert(
            factories.create_alert_payload(senior_id, severity, **overrides), AGENT
        )
    )


# ---------------------------------------------------------------------------
# Tier 3: telemetry
# ---------------------------------------------------------------------------

def ingest_event(
    device_id: str,
    event_type: str,
    observed_at: str,
    battery_percent: Optional[int] = None,
    note: Optional[str] = None,
) -> dict:
    """DeviceHub pushes one sensor event. Returns the stored event."""
    overrides = {}
    if battery_percent is not None:
        overrides["battery_percent"] = battery_percent
    if note is not None:
        overrides["note"] = note
    return get_success_data(
        api_client.ingest_telemetry(
            factories.create_telemetry_payload(
                device_id, event_type, observed_at, **overrides
            ),
            HUB,
        )
    )


def bring_device_online(device_id: str, observed_at: str) -> dict:
    """First telemetry event flips INSTALLED -> ONLINE."""
    return ingest_event(device_id, "HEARTBEAT", observed_at)


# ---------------------------------------------------------------------------
# Tier 3/4: medication schedules and doses
# ---------------------------------------------------------------------------

def create_med_schedule(
    senior_id: str,
    medication_name: str = "Aspirin",
    times_of_day=("20:00",),
    window_minutes: int = 60,
    criticality: str = "ROUTINE",
    start_date: str = "2026-05-01",
    as_caregiver_id: Optional[str] = None,
) -> dict:
    """Create a schedule with a fresh expected_senior_version (OCC).

    PlatformAdmin by default; pass as_caregiver_id to act as the caregiver."""
    senior = get_success_data(api_client.get_senior(senior_id, ADMIN))
    headers = (
        make_caregiver_headers(as_caregiver_id) if as_caregiver_id else ADMIN
    )
    return get_success_data(
        api_client.create_medication_schedule(
            factories.create_medication_schedule_payload(
                senior_id,
                expected_senior_version=senior["version"],
                medication_name=medication_name,
                times_of_day=list(times_of_day),
                window_minutes=window_minutes,
                criticality=criticality,
                start_date=start_date,
            ),
            headers,
        )
    )


def list_doses(schedule_id: str) -> list:
    from prd_bench_local_runner.testing import validate_paginated

    data, _meta = validate_paginated(
        api_client.list_dose_events(ADMIN, params={"schedule_id": schedule_id})
    )
    return data


def confirm_dose_as_senior(dose_id: str, senior_id: str) -> dict:
    return get_success_data(
        api_client.confirm_dose_event(dose_id, make_senior_headers(senior_id))
    )


# ---------------------------------------------------------------------------
# Tier 3: alert lifecycle
# ---------------------------------------------------------------------------

def caregiver_acknowledge(alert_id: str, caregiver_id: str) -> dict:
    return get_success_data(
        api_client.acknowledge_alert(alert_id, make_caregiver_headers(caregiver_id))
    )


def caregiver_resolve(alert_id: str, caregiver_id: str, note: str = "handled") -> dict:
    return get_success_data(
        api_client.resolve_alert(
            alert_id, {"note": note}, make_caregiver_headers(caregiver_id)
        )
    )


def list_notifications(**params) -> list:
    from prd_bench_local_runner.testing import validate_paginated

    data, _meta = validate_paginated(
        api_client.list_alert_notifications(ADMIN, params=params)
    )
    return data


def list_alerts(**params) -> list:
    from prd_bench_local_runner.testing import validate_paginated

    data, _meta = validate_paginated(api_client.list_alerts(ADMIN, params=params))
    return data


def get_senior(senior_id: str) -> dict:
    return get_success_data(api_client.get_senior(senior_id, ADMIN))
