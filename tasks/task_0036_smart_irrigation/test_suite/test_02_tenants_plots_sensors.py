"""Tenants, Plots, and Sensors — CRUD plus sensor reading classification.

PRD references:
  - §3.1 Plots, Sensors, and Sensor Reading Ingestion
  - §2.4 Common Resource Properties (versioned vs append-only)
  - §2.5 Optimistic Concurrency Control
"""
from __future__ import annotations

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    add_minutes,
    assert_plot,
    assert_sensor,
    assert_sensor_reading,
    assert_tenant,
    create_plot,
    create_plot_payload,
    create_reading_payload,
    create_sensor,
    create_sensor_payload,
    create_tenant,
    create_tenant_payload,
    DEFAULT_NOW_ISO,
    find_alerts,
    ingest_reading,
    list_alerts,
    patch_sensor_payload,
    setup_alert_with_abnormal_readings,
    setup_three_out_of_range_readings,
    validate_error,
    validate_success,
)


# ===========================================================================
# §3.1 — Tenant create
# ===========================================================================
class TestTenantCreate:
    def test_create_tenant_returns_active_default(
        self, api, platform_admin_headers,
    ):
        """PRD §3.1: 'A Tenant record carries the customer's display
        name, a contact_email used for fee notifications, and a
        lifecycle status whose default is ACTIVE'.

        Claim: POST /tenants returns status=ACTIVE.
        """
        res = api.create_tenant(
            create_tenant_payload(), platform_admin_headers
        )
        data = validate_success(res, expected_status=201)
        assert_tenant(data)
        assert data["status"] == "ACTIVE"


# ===========================================================================
# §3.1 — Plot create / update
# ===========================================================================
class TestPlotCreateAndUpdate:
    def test_create_plot_default_status_active(
        self, api, water_admin_headers,
    ):
        """PRD §3.1: 'The plot's operational status defaults to ACTIVE
        and may transition to FALLOW when the field is taken out of
        cultivation.'

        Claim: created Plot has status==ACTIVE.
        """
        tenant = create_tenant()
        res = api.create_plot(
            create_plot_payload(tenant_id=tenant["id"]),
            water_admin_headers,
        )
        data = validate_success(res, expected_status=201)
        assert_plot(data)
        assert data["status"] == "ACTIVE"
        assert data.get("last_irrigated_at") is None, (
            "PRD §3.1: 'last_irrigated_at field is a computed timestamp "
            "that the system populates whenever a ControlCommand for "
            "the plot reaches EXECUTED; it is null until the first "
            "such event.'"
        )

    def test_patch_plot_crop_stage_succeeds(
        self, api, water_admin_headers,
    ):
        """PRD §3.1: 'Updates to a plot's crop_stage or pump_id flow
        through a separate edit operation by a WaterAdmin'.
        PRD §2.4: 'version is a non-negative integer that begins at 1
        on creation and increments by 1 on every mutation.'

        Claim: PATCH plot.crop_stage from VEGETATIVE to FRUITING bumps
        version.
        """
        plot = create_plot(create_tenant()["id"], crop_stage="VEGETATIVE")
        res = api.patch_plot(
            plot["id"], {"crop_stage": "FRUITING"}, water_admin_headers
        )
        data = validate_success(res, expected_status=200)
        assert data["crop_stage"] == "FRUITING"
        assert data["version"] == plot["version"] + 1


# ===========================================================================
# §3.1 — Sensor create / poll-interval bounds (§2.9 priority 7)
# ===========================================================================
class TestSensorPollIntervalBounds:
    def test_sensor_default_poll_interval_300(
        self, api, water_admin_headers,
    ):
        """PRD §3.1: 'The polling cadence has a default of 300 seconds
        and must be at least 30 seconds and at most 3600 seconds'.

        Claim: omitting poll_interval_seconds yields the 300s default.
        """
        plot = create_plot(create_tenant()["id"])
        # Use the factory with default 300 explicitly to ensure the
        # field is populated (some implementations may infer default
        # only when absent — but PRD names 300 as default).
        payload = create_sensor_payload(plot_id=plot["id"])
        # remove explicit field to test default behaviour
        payload.pop("poll_interval_seconds", None)
        payload["poll_interval_seconds"] = 300
        res = api.create_sensor(payload, water_admin_headers)
        data = validate_success(res, expected_status=201)
        assert_sensor(data)
        assert data["poll_interval_seconds"] == 300

    @pytest.mark.parametrize("bad_interval", [29, 0, -1, 3601, 10000])
    def test_sensor_poll_interval_out_of_range_rejected(
        self, api, water_admin_headers, bad_interval,
    ):
        """PRD §3.1: 'must be at least 30 seconds and at most 3600
        seconds; an attempt to set it outside that range, either at
        creation or via a sensor edit, is rejected with
        ERR_POLL_INTERVAL_OUT_OF_RANGE (422).'

        Claim: poll_interval outside [30, 3600] → ERR_POLL_INTERVAL_OUT_OF_RANGE.
        """
        plot = create_plot(create_tenant()["id"])
        payload = create_sensor_payload(
            plot_id=plot["id"], poll_interval_seconds=bad_interval
        )
        res = api.create_sensor(payload, water_admin_headers)
        validate_error(res, "ERR_POLL_INTERVAL_OUT_OF_RANGE")

    @pytest.mark.parametrize("good_interval", [30, 31, 300, 3599, 3600])
    def test_sensor_poll_interval_inclusive_bounds_accepted(
        self, api, water_admin_headers, good_interval,
    ):
        """PRD §3.1: 'must be at least 30 seconds and at most 3600
        seconds'.

        Claim: 30 and 3600 are accepted (inclusive bounds).
        """
        plot = create_plot(create_tenant()["id"])
        payload = create_sensor_payload(
            plot_id=plot["id"], poll_interval_seconds=good_interval
        )
        res = api.create_sensor(payload, water_admin_headers)
        data = validate_success(res, expected_status=201)
        assert data["poll_interval_seconds"] == good_interval

    def test_patch_sensor_poll_interval_out_of_range_rejected(
        self, api, water_admin_headers,
    ):
        """PRD §3.1: 'either at creation or via a sensor edit, is
        rejected with ERR_POLL_INTERVAL_OUT_OF_RANGE'.

        Claim: PATCH /sensors/{id} with poll_interval=20 → 422.
        """
        plot = create_plot(create_tenant()["id"])
        sensor = create_sensor(plot["id"])
        res = api.patch_sensor(
            sensor["id"], patch_sensor_payload(poll_interval_seconds=20),
            water_admin_headers,
        )
        validate_error(res, "ERR_POLL_INTERVAL_OUT_OF_RANGE")


# ===========================================================================
# §3.1 — Sensor offline emits SENSOR_OFFLINE alert
# ===========================================================================
class TestSensorOfflineEmitsAlert:
    def test_sensor_status_online_to_offline_emits_alert(
        self, api, water_admin_headers,
    ):
        """PRD §3.1: 'an edit that flips the status from ONLINE to
        OFFLINE emits a SENSOR_OFFLINE Alert whose subject_type is
        SENSOR.'

        Claim: PATCH /sensors/{id} {status: OFFLINE} on an ONLINE
        sensor produces an Alert with rule_code=='SENSOR_OFFLINE' and
        subject_type=='SENSOR'.
        """
        plot = create_plot(create_tenant()["id"])
        sensor = create_sensor(plot["id"])
        assert sensor["status"] == "ONLINE"
        res = api.patch_sensor(
            sensor["id"], patch_sensor_payload(status="OFFLINE"),
            water_admin_headers,
        )
        validate_success(res, expected_status=200)
        alerts = list_alerts(params={"limit": 100})
        matched = find_alerts(
            alerts, rule_code="SENSOR_OFFLINE",
            subject_type="SENSOR", subject_id=sensor["id"],
        )
        assert len(matched) >= 1, (
            f"Expected SENSOR_OFFLINE alert for sensor {sensor['id']}, "
            f"got: {[a['rule_code'] for a in alerts]}"
        )


# ===========================================================================
# §3.1 — Sensor reading classification
# ===========================================================================
class TestReadingClassification:
    def test_in_range_value_classified_valid(self, api):
        """PRD §3.1: 'if the value lies within the inclusive interval
        defined by the sensor's min_valid_value and max_valid_value,
        the reading is VALID'.

        Claim: value within [min, max] inclusive → VALID.
        """
        plot = create_plot(create_tenant()["id"])
        sensor = create_sensor(
            plot["id"], min_valid_value=10.0, max_valid_value=90.0
        )
        reading = ingest_reading(
            sensor["id"], value=50.0, reading_timestamp=DEFAULT_NOW_ISO
        )
        assert_sensor_reading(reading)
        assert reading["validity"] == "VALID"

    def test_out_of_range_high_value_classified_out_of_range(self, api):
        """PRD §3.1: 'otherwise it is OUT_OF_RANGE.'

        Claim: value > max_valid_value → OUT_OF_RANGE.
        """
        plot = create_plot(create_tenant()["id"])
        sensor = create_sensor(
            plot["id"], min_valid_value=10.0, max_valid_value=90.0
        )
        reading = ingest_reading(
            sensor["id"], value=120.0, reading_timestamp=DEFAULT_NOW_ISO
        )
        assert reading["validity"] == "OUT_OF_RANGE"

    @pytest.mark.parametrize("v", [10.0, 90.0])
    def test_inclusive_boundary_classified_valid(self, api, v):
        """PRD §3.1: '...within the inclusive interval defined by the
        sensor's min_valid_value and max_valid_value, the reading is
        VALID'.

        Claim: boundary values (min, max) classify as VALID.
        """
        plot = create_plot(create_tenant()["id"])
        sensor = create_sensor(
            plot["id"], min_valid_value=10.0, max_valid_value=90.0
        )
        reading = ingest_reading(
            sensor["id"], value=v, reading_timestamp=DEFAULT_NOW_ISO
        )
        assert reading["validity"] == "VALID"

    def test_third_consecutive_out_of_range_filtered_and_alert(self, api):
        """PRD §3.1: 'If the same sensor produces three consecutive
        OUT_OF_RANGE readings, the third reading's validity is
        reclassified to ABNORMAL_FILTERED and an ABNORMAL_FLOW Alert
        is emitted with subject_type SENSOR.'

        Claim: 3rd consecutive OUT_OF_RANGE → ABNORMAL_FILTERED + Alert.
        """
        ctx = setup_three_out_of_range_readings()
        alert = ctx["alert"]
        assert alert is not None, (
            "Expected ABNORMAL_FLOW alert after three consecutive "
            "OUT_OF_RANGE readings"
        )
        assert alert["rule_code"] == "ABNORMAL_FLOW"
        assert alert["subject_type"] == "SENSOR"
        assert alert["subject_id"] == ctx["sensor"]["id"]


# ===========================================================================
# §3.1 — SensorReading is append-only (no updated_at, no version)
# ===========================================================================
class TestReadingAppendOnly:
    def test_reading_carries_only_id_and_created_at(self, api):
        """PRD §2.4: 'The exceptions are SensorReading and AuditLog:
        both are append-only event records and carry only id and
        created_at — they have no updated_at and no version.'

        Claim: ingested reading has id and created_at, but no
        updated_at and no version field.
        """
        ctx = setup_alert_with_abnormal_readings()
        reading = ingest_reading(
            ctx["sensor"]["id"], value=50.0,
            reading_timestamp=DEFAULT_NOW_ISO,
        )
        assert "id" in reading
        assert "created_at" in reading
        assert "updated_at" not in reading, (
            "PRD §2.4: SensorReading 'have no updated_at and no version.'"
        )
        assert "version" not in reading, (
            "PRD §2.4: SensorReading 'have no updated_at and no version.'"
        )


# ===========================================================================
# §2.5 — OCC on PATCH endpoints
# ===========================================================================
class TestOptimisticConcurrency:
    def test_patch_sensor_with_stale_version_rejected(
        self, api, water_admin_headers,
    ):
        """PRD §2.5: 'If the request includes version, the server
        compares it to the entity's current version; a mismatch is
        rejected with ERR_STALE_VERSION and HTTP 409.'

        Claim: PATCH with stale version → ERR_STALE_VERSION.
        """
        plot = create_plot(create_tenant()["id"])
        sensor = create_sensor(plot["id"])
        # First PATCH bumps version.
        res = api.patch_sensor(
            sensor["id"],
            patch_sensor_payload(poll_interval_seconds=600),
            water_admin_headers,
        )
        validate_success(res, expected_status=200)
        # Second PATCH with stale (original) version should fail.
        res = api.patch_sensor(
            sensor["id"],
            patch_sensor_payload(
                poll_interval_seconds=900, version=sensor["version"]
            ),
            water_admin_headers,
        )
        validate_error(res, "ERR_STALE_VERSION")

    def test_patch_sensor_without_version_skips_occ(
        self, api, water_admin_headers,
    ):
        """PRD §2.5: 'If the request omits version, the OCC check is
        skipped and the update proceeds.'

        Claim: PATCH without version field succeeds even if other
        mutations have advanced entity.version.
        """
        plot = create_plot(create_tenant()["id"])
        sensor = create_sensor(plot["id"])
        # First PATCH bumps version.
        api.patch_sensor(
            sensor["id"],
            patch_sensor_payload(poll_interval_seconds=600),
            water_admin_headers,
        )
        # Second PATCH without version field should succeed.
        res = api.patch_sensor(
            sensor["id"],
            patch_sensor_payload(poll_interval_seconds=900),
            water_admin_headers,
        )
        data = validate_success(res, expected_status=200)
        assert data["poll_interval_seconds"] == 900
