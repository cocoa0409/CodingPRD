"""Kit provisioning defaults, append-only sensor events, telemetry validation,
battery alert thresholds, device offline detection, and kit state machine."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    confirm_and_complete_appointment,
    create_installer,
    create_senior,
    create_subscription,
    deliver_kit,
    fixtures,
    get_success_data,
    ingest_event,
    order_kit,
    schedule_appointment,
    set_clock,
    setup_active_senior,
    setup_installed_senior,
    setup_senior_with_subscription,
    ship_kit,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
HUB = TEST_USERS["device_hub_headers"]


class TestKitProvisioning:
    def test_kit_create_applies_plan_default_motion_sensor_count(self, api):
        """PRD 3.3: "Ordering a sensor kit for a senior is a `PlatformAdmin`
        action taking the `senior_id` and an optional `motion_sensor_count`;
        when the count is omitted it defaults to the subscribed plan's
        `included_motion_sensors`."
        PRD 3.3: "The kit is created in `ORDERED` status, and provisioning
        happens immediately: exactly one device whose `device_type` is
        `GATEWAY`, exactly one whose `device_type` is `WEARABLE`, and one
        `MOTION` device per requested motion sensor, each created in
        `PROVISIONED` status with a system-minted, unique `serial` of the form
        kit-sequence, device-type, and index joined by hyphens."

        Design: Corner/entities/kit_create_applies_plan_default_motion_sensor_count
        """
        ctx = setup_senior_with_subscription(
            plan_overrides={"included_motion_sensors": 2}
        )
        kit = validate_success(
            api.create_sensor_kit({"senior_id": ctx["senior"]["id"]}, ADMIN), 201
        )
        assert kit["motion_sensor_count"] == 2, (
            f"motion_sensor_count must default to the plan's 2, got "
            f"{kit['motion_sensor_count']}"
        )
        assert kit["status"] == "ORDERED"

        devices, meta = validate_paginated(
            api.list_devices(ADMIN, params={"kit_id": kit["id"]})
        )
        assert len(devices) == 4, f"expected 4 devices, got {len(devices)}"
        by_type = {}
        for device in devices:
            by_type.setdefault(device["device_type"], []).append(device)
        assert len(by_type.get("GATEWAY", [])) == 1
        assert len(by_type.get("WEARABLE", [])) == 1
        assert len(by_type.get("MOTION", [])) == 2
        for device in devices:
            assert device["status"] == "PROVISIONED"
            assert device["battery_percent"] == 100


class TestKitStateMachine:
    def test_kit_ship_from_shipped_rejected_invalid_state(self, api):
        """PRD 3.3: "A `PlatformAdmin` marks an `ORDERED` kit `SHIPPED`, and a
        `SHIPPED` kit `DELIVERED`; attempting either step from the wrong state
        is rejected with `ERR_INVALID_STATE`, and each step refreshes the kit's
        `updated_at` and increments its `version`."

        Design: Corner/state_machines/kit_ship_from_shipped_rejected_invalid_state
        """
        ctx = setup_senior_with_subscription()
        kit = order_kit(ctx["senior"]["id"])
        ship_kit(kit["id"])
        resp = api.ship_sensor_kit(kit["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        kit_after = get_success_data(api.get_sensor_kit(kit["id"], ADMIN))
        assert kit_after["status"] == "SHIPPED", (
            f"kit must remain SHIPPED, got {kit_after['status']}"
        )


class TestSensorEventShape:
    def test_sensor_event_immutable_common_fields_false(self, api):
        """PRD 2.5: "Four event-like resources are deliberately lighter:
        `SensorEvent`, `AlertNotification`, `DoseEvent`, and `CheckIn` carry
        only `id` and `created_at`. Both `updated_at` and `version` are absent
        on these four, and no endpoint mutates them after creation."

        Design: Corner/entities/sensor_event_immutable_common_fields_false
        """
        ctx = setup_installed_senior()
        device = ctx["devices"]["gateway"]
        event = ingest_event(
            device["id"], "HEARTBEAT", "2026-05-01T09:30:00Z"
        )
        fetched = get_success_data(api.get_sensor_event(event["id"], ADMIN))
        for field in ("id", "created_at", "device_id", "event_type", "observed_at"):
            assert field in fetched, f"sensor event must carry {field}"
        assert "version" not in fetched, "append-only event must not carry version"
        assert "updated_at" not in fetched, (
            "append-only event must not carry updated_at"
        )


class TestTelemetryValidation:
    def test_telemetry_with_future_observed_at_rejected(self, api):
        """PRD 2.4: "Every device event also carries its own `observed_at`
        timestamp, which must not be later than the current logical clock; an
        event from the future is rejected with `ERR_INVALID_REQUEST`."

        Design: Corner/errors/telemetry_with_future_observed_at_rejected
        """
        ctx = setup_installed_senior()
        device = ctx["devices"]["gateway"]
        # Clock is at 2026-05-01T09:30:00Z after installation.
        resp = api.ingest_telemetry(
            {
                "device_id": device["id"],
                "event_type": "HEARTBEAT",
                "observed_at": "2026-05-01T10:00:00Z",
            },
            HUB,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        events, _meta = validate_paginated(
            api.list_sensor_events(ADMIN, params={"device_id": device["id"]})
        )
        assert events == [], "no SensorEvent may be persisted for a future observed_at"


class TestBatteryAlertThresholds:
    """Boundary precision on the inclusive battery thresholds (PRD 3.4)."""

    def _setup(self):
        ctx = setup_active_senior()
        # Advance the clock so the battery readings are not future events.
        set_clock("2026-05-01T10:30:00Z")
        return ctx

    def test_battery_reading_21_creates_no_alert(self, api):
        """PRD 3.4: "When a reading lands at or below 20 percent and no open
        `LOW_BATTERY` alert exists for the device, one is created — severity
        `HIGH` if the reading is at or below 10 percent, `MEDIUM` otherwise."
        PRD 3.4: "The boundaries are exact: 20 triggers, 21 does not; 10 is
        `HIGH`, 11 is `MEDIUM`."

        Design: Difficulty/boundary_precision_check/battery_alert_threshold_inclusive_at_20
        """
        ctx = self._setup()
        gateway = ctx["devices"]["gateway"]
        ingest_event(
            gateway["id"], "HEARTBEAT", "2026-05-01T10:30:00Z", battery_percent=21
        )
        alerts = fixtures.list_alerts(device_id=gateway["id"])
        assert alerts == [], (
            f"21 percent is above the inclusive threshold; got {len(alerts)} alerts"
        )

    def test_battery_reading_20_creates_medium_low_battery_alert(self, api):
        """PRD 3.4: "When a reading lands at or below 20 percent and no open
        `LOW_BATTERY` alert exists for the device, one is created — severity
        `HIGH` if the reading is at or below 10 percent, `MEDIUM` otherwise."
        PRD 3.4: "The boundaries are exact: 20 triggers, 21 does not; 10 is
        `HIGH`, 11 is `MEDIUM`."

        Design: Difficulty/boundary_precision_check/battery_alert_threshold_inclusive_at_20
        """
        ctx = self._setup()
        motion = ctx["devices"]["motions"][0]
        ingest_event(
            motion["id"], "HEARTBEAT", "2026-05-01T10:30:00Z", battery_percent=20
        )
        alerts = fixtures.list_alerts(device_id=motion["id"])
        assert len(alerts) == 1, f"20 percent must trigger exactly one alert"
        assert alerts[0]["alert_type"] == "LOW_BATTERY"
        assert alerts[0]["severity"] == "MEDIUM"
        senior = fixtures.get_senior(ctx["senior"]["id"])
        assert senior["open_alert_count"] == 1


class TestDeviceOfflineDetection:
    def test_device_offline_auto_transition_and_alert(self, api):
        """PRD 3.4: "The offline detector, which runs first in the pinned sweep
        order, moves any `ONLINE` device whose `last_seen_at` is more than 90
        minutes behind the current clock to `OFFLINE` and creates a `MEDIUM`
        `DEVICE_OFFLINE` alert — unless an open `DEVICE_OFFLINE` alert already
        exists for that device."

        Design: Corner/state_machines/device_offline_auto_transition_and_alert
        """
        ctx = setup_active_senior()
        gateway = ctx["devices"]["gateway"]
        fixtures.bring_device_online(gateway["id"], "2026-05-01T09:30:00Z")

        # 150 minutes of silence -> OFFLINE + one DEVICE_OFFLINE alert.
        set_clock("2026-05-01T12:00:00Z")
        device = get_success_data(api.get_device(gateway["id"], ADMIN))
        assert device["status"] == "OFFLINE", (
            f"device must be OFFLINE after 150 min of silence, got {device['status']}"
        )
        alerts = fixtures.list_alerts(
            device_id=gateway["id"], alert_type="DEVICE_OFFLINE"
        )
        assert len(alerts) == 1
        assert alerts[0]["severity"] == "MEDIUM"

        # A second sweep must not create a duplicate while one is open.
        set_clock("2026-05-01T13:00:00Z")
        alerts = fixtures.list_alerts(
            device_id=gateway["id"], alert_type="DEVICE_OFFLINE"
        )
        assert len(alerts) == 1, "no duplicate DEVICE_OFFLINE alert on second sweep"
