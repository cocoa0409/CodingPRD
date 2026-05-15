"""Performance endpoint calculations and station-status recomputation
on full cascade chains (PRD §3.1, §3.2)."""
from __future__ import annotations

import pytest

from test_helpers import (
    REFERENCE_IRRADIANCE_W_M2,
    advance_clock_to,
    api_client,
    ingest_alarm,
    register_alarm_code_map,
    setup_performance_window_with_alarm,
    setup_station_with_inverters,
    TEST_USERS,
    validate_success,
)


class TestPerformanceWithoutDowntime:
    """PRD §3.2 expected and actual calculations on a clean window."""

    def test_expected_kwh_uses_irradiance_ratio(self, api, admin_headers):
        """PRD §3.2: "For each reading the contribution is the
        irradiance ratio (the reading's irradiance_w_m2 divided by
        the reference one-sun figure of 1000 watts per square metre)
        multiplied by the station's installed_capacity_kw and by one
        sixtieth of an hour..."

        Claim: 60 readings at irradiance=800 on a 100-kW station yield
        expected_generation_kwh = 60 * (800/1000) * 100 * (1/60) = 80.000.
        """
        info = setup_performance_window_with_alarm(
            minutes=60, irradiance=800.0, dc_power=72.0, ac_power=70.0,
            installed_capacity_kw=100.0, ac_capacity_kw=100.0,
            base_hour_start="2026-01-01T00:00:00.000Z",
            place_alarm=False,
        )
        station = info["station"]
        resp = api.get_station_performance(
            station["id"], admin_headers,
            params={
                "window_start": "2026-01-01T00:00:00.000Z",
                "window_end": "2026-01-01T01:00:00.000Z",
            },
        )
        data = validate_success(resp)
        assert data["expected_generation_kwh"] == pytest.approx(
            80.000, abs=0.001,
        )

    def test_actual_kwh_no_downtime_uses_ac_power(
        self, api, admin_headers,
    ):
        """PRD §3.2: "Otherwise, the slice contributes the reading's
        ac_power_kw multiplied by one sixtieth of an hour. The sum
        across the window is rounded half-up to three decimal places."

        Claim: with no MAJOR/CRITICAL alarm, actual = sum over slices
        of (ac_power * 1/60). 60 slices @ 70 kW = 70.000.
        """
        info = setup_performance_window_with_alarm(
            minutes=60, irradiance=800.0, ac_power=70.0,
            installed_capacity_kw=100.0, ac_capacity_kw=100.0,
            base_hour_start="2026-01-01T00:00:00.000Z",
            place_alarm=False,
        )
        station = info["station"]
        resp = api.get_station_performance(
            station["id"], admin_headers,
            params={
                "window_start": "2026-01-01T00:00:00.000Z",
                "window_end": "2026-01-01T01:00:00.000Z",
            },
        )
        data = validate_success(resp)
        assert data["actual_generation_kwh"] == pytest.approx(
            70.000, abs=0.001,
        )

    def test_performance_ratio_zero_expected_returns_zero(
        self, api, admin_headers,
    ):
        """PRD §3.2: "The performance_ratio is the actual divided by
        the expected when the expected is strictly positive, and zero
        otherwise..."

        Claim: with no readings in the window (expected = 0), PR is 0.
        """
        station, _supp, _invs = setup_station_with_inverters(
            inverter_count=1,
        )
        resp = api.get_station_performance(
            station["id"], admin_headers,
            params={
                "window_start": "2026-01-01T00:00:00.000Z",
                "window_end": "2026-01-01T01:00:00.000Z",
            },
        )
        data = validate_success(resp)
        assert data["expected_generation_kwh"] == pytest.approx(0.000)
        assert data["performance_ratio"] == pytest.approx(0.0)


class TestPerformanceInfoAlarmDoesNotExclude:
    """PRD §3.2: only MAJOR/CRITICAL alarms exclude slices."""

    def test_info_alarm_does_not_zero_slices(self, api, admin_headers,
                                              om_headers):
        """PRD §3.2: "INFO-severity and WARN-severity alarms do not
        exclude slices; only the two highest severities do."

        Claim: an INFO alarm covering the full window leaves actual
        unchanged (= 70.000 for 60 readings @ ac=70).
        """
        info = setup_performance_window_with_alarm(
            minutes=60, irradiance=800.0, ac_power=70.0,
            installed_capacity_kw=100.0, ac_capacity_kw=100.0,
            base_hour_start="2026-01-01T00:00:00.000Z",
            alarm_severity="INFO",
            place_alarm=False,  # we'll place an INFO alarm manually
        )
        station = info["station"]
        inverter = info["inverter"]
        # Register the INFO mapping and ingest an alarm covering the
        # window. Don't ack — but INFO can only be archived from OPEN,
        # so the alarm stays OPEN inside the window. Per PRD, OPEN +
        # INFO does not exclude any slice.
        register_alarm_code_map(severity="INFO")
        ingest_alarm(
            inverter["id"], first_seen_at="2026-01-01T00:00:00.000Z",
        )
        resp = api.get_station_performance(
            station["id"], admin_headers,
            params={
                "window_start": "2026-01-01T00:00:00.000Z",
                "window_end": "2026-01-01T01:00:00.000Z",
            },
        )
        data = validate_success(resp)
        assert data["actual_generation_kwh"] == pytest.approx(
            70.000, abs=0.001,
        ), "PRD §3.2: INFO alarms do not exclude slices"


class TestCapacityFactor:
    """PRD §3.2 capacity_factor."""

    def test_capacity_factor_uses_ac_capacity_and_hours(
        self, api, admin_headers,
    ):
        """PRD §3.2: "The capacity_factor is the actual divided by the
        product of the station's ac_capacity_kw and the number of
        hours between window_start and window_end, also rounded
        half-up to four decimal places."

        Claim: 60 slices @ ac=70 over a 1-hour window on a 100-kW
        station → cf = 70.000 / (100*1) = 0.7000.
        """
        info = setup_performance_window_with_alarm(
            minutes=60, irradiance=800.0, ac_power=70.0,
            installed_capacity_kw=100.0, ac_capacity_kw=100.0,
            base_hour_start="2026-01-01T00:00:00.000Z",
            place_alarm=False,
        )
        station = info["station"]
        resp = api.get_station_performance(
            station["id"], admin_headers,
            params={
                "window_start": "2026-01-01T00:00:00.000Z",
                "window_end": "2026-01-01T01:00:00.000Z",
            },
        )
        data = validate_success(resp)
        assert data["capacity_factor"] == pytest.approx(0.7000, abs=0.0001)
