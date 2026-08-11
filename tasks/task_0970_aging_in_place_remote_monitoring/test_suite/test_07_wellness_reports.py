"""Wellness report scoring: PROVISIONAL vs FINAL variants, the fall cap,
vacuous adherence, duplicate-FINAL rejection, and regenerate OCC."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    factories,
    fixtures,
    get_success_data,
    set_clock,
    setup_active_senior,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
HUB = TEST_USERS["device_hub_headers"]

PREMIUM_PLAN = {
    "tier": "PREMIUM",
    "monthly_fee_cents": 9000,
    "included_motion_sensors": 2,
    "extra_sensor_fee_cents": 199,
    "max_contacts": 8,
    "checkin_interval_hours": 24,
    "medication_reminders_enabled": True,
    "wellness_report_enabled": True,
    "wellness_report_cadence": "WEEKLY",
}

PERIOD_START = "2026-05-01T00:00:00Z"
PERIOD_END = "2026-05-05T00:00:00Z"


def _motion_burst(device_id: str, day_prefix: str, times):
    for t in times:
        fixtures.ingest_event(device_id, "MOTION", f"{day_prefix}T{t}:00Z")


def _setup_provisional_vs_final():
    """ACTIVE senior with gateway + one motion device ONLINE; ROUTINE schedule
    at 20:00 (window 60, start 2026-05-01); dose 05-01 TAKEN punctual, dose
    05-02 TAKEN late, dose 05-03 MISSED, dose 05-04 PENDING-due at provisional
    time; 2 active motion days (05-01, 05-02); clock at 2026-05-04T20:10Z."""
    ctx = setup_active_senior(plan_overrides=dict(PREMIUM_PLAN))
    senior_id = ctx["senior"]["id"]
    gateway = ctx["devices"]["gateway"]
    motion = ctx["devices"]["motions"][0]
    schedule = fixtures.create_med_schedule(
        senior_id,
        medication_name="Vitamin D",
        times_of_day=("20:00",),
        window_minutes=60,
        criticality="ROUTINE",
        start_date="2026-05-01",
    )
    fixtures.bring_device_online(gateway["id"], "2026-05-01T09:30:00Z")
    fixtures.bring_device_online(motion["id"], "2026-05-01T09:30:00Z")
    _motion_burst(motion["id"], "2026-05-01", ["09:28", "09:29", "09:30"])

    doses = fixtures.list_doses(schedule["id"])
    dose1, dose2 = doses[0], doses[1]
    set_clock("2026-05-01T20:10:00Z")
    fixtures.confirm_dose_as_senior(dose1["id"], senior_id)  # punctual
    set_clock("2026-05-02T20:40:00Z")
    fixtures.confirm_dose_as_senior(dose2["id"], senior_id)  # late (40 min)
    _motion_burst(motion["id"], "2026-05-02", ["08:00", "09:00", "10:00"])
    # 05-03 dose misses its window during this advance.
    set_clock("2026-05-03T21:30:00Z")
    set_clock("2026-05-04T20:10:00Z")
    fixtures.bring_device_online(gateway["id"], "2026-05-04T20:10:00Z")
    fixtures.bring_device_online(motion["id"], "2026-05-04T20:10:00Z")
    ctx["schedule"] = schedule
    return ctx


class TestProvisionalVsFinal:
    def test_wellness_provisional_scores(self, api):
        """PRD 3.8: "A `PROVISIONAL` report adds every still-`PENDING` dose
        already due by the current clock, each counted at full weight 1.0."
        PRD 3.8: "for a `PROVISIONAL` report the divisor is instead the number
        of whole days elapsed since `period_start`, clamped to at least one so
        a same-day preview never divides by zero."

        Design: Difficulty/dual_variant_calc/wellness_index_provisional_vs_final
        """
        ctx = _setup_provisional_vs_final()
        report = get_success_data(
            api.create_wellness_report(
                factories.create_wellness_report_payload(
                    ctx["senior"]["id"], PERIOD_START, PERIOD_END, "PROVISIONAL"
                ),
                ADMIN,
            )
        )
        # 2 active days / 3 elapsed days -> 66.7.
        assert report["activity_score"] == pytest.approx(66.7, abs=0.01)
        # weights 1.0 (punctual) + 0.5 (late) + 0.0 (missed) + 1.0 (due PENDING).
        assert report["adherence_pct"] == pytest.approx(62.5, abs=0.01)
        # 0.40*66.7 + 0.35*62.5 + 0.25*100 = 73.555 -> 73.6 (no penalty).
        assert report["wellness_index"] == pytest.approx(73.6, abs=0.01)

    def test_wellness_final_scores_differ_from_provisional(self, api):
        """PRD 3.8: "The due set for a `FINAL` report is the senior's doses
        scheduled inside the period with status `TAKEN` or `MISSED`; `SKIPPED`
        doses are excluded entirely."
        PRD 3.8: "The `wellness_index` blends the three: forty percent of the
        activity score, thirty-five percent of adherence, and twenty-five
        percent of device health. The evaluation order is pinned — weighting
        first, penalty second, cap third, rounding last. If adherence falls
        below 60, the blended value is multiplied by 0.8."

        Design: Difficulty/dual_variant_calc/wellness_index_provisional_vs_final
        """
        ctx = _setup_provisional_vs_final()
        provisional = get_success_data(
            api.create_wellness_report(
                factories.create_wellness_report_payload(
                    ctx["senior"]["id"], PERIOD_START, PERIOD_END, "PROVISIONAL"
                ),
                ADMIN,
            )
        )
        # Close the period; the sweep marks the 05-04 dose MISSED.
        set_clock("2026-05-05T00:01:00Z")
        fixtures.bring_device_online(
            ctx["devices"]["gateway"]["id"], "2026-05-05T00:01:00Z"
        )
        fixtures.bring_device_online(
            ctx["devices"]["motions"][0]["id"], "2026-05-05T00:01:00Z"
        )
        final = get_success_data(
            api.create_wellness_report(
                factories.create_wellness_report_payload(
                    ctx["senior"]["id"], PERIOD_START, PERIOD_END, "FINAL"
                ),
                ADMIN,
            )
        )
        # 2 active days / 4 period days -> 50.0.
        assert final["activity_score"] == pytest.approx(50.0, abs=0.01)
        # terminal doses: 1.0 + 0.5 + 0.0 + 0.0 over 4 -> 37.5.
        assert final["adherence_pct"] == pytest.approx(37.5, abs=0.01)
        # raw = 0.40*50 + 0.35*37.5 + 0.25*100 = 58.125; adherence < 60 ->
        # 58.125 * 0.8 = 46.5.
        assert final["wellness_index"] == pytest.approx(46.5, abs=0.01)
        assert final["wellness_index"] != provisional["wellness_index"], (
            "the two modes must diverge on the same underlying period data"
        )


class TestFallCap:
    def _setup(self):
        """ACTIVE senior, no schedules (vacuous adherence), 2 active motion
        days, one FALL_DETECTED (CRITICAL FALL alert, no contact tree -> RAISED),
        clock at 2026-05-03T00:01Z with devices ONLINE."""
        ctx = setup_active_senior(plan_overrides=dict(PREMIUM_PLAN))
        gateway = ctx["devices"]["gateway"]
        wearable = ctx["devices"]["wearable"]
        motion = ctx["devices"]["motions"][0]
        fixtures.bring_device_online(gateway["id"], "2026-05-01T09:30:00Z")
        fixtures.bring_device_online(motion["id"], "2026-05-01T09:30:00Z")
        _motion_burst(motion["id"], "2026-05-01", ["09:28", "09:29", "09:30"])
        set_clock("2026-05-02T10:00:00Z")
        _motion_burst(motion["id"], "2026-05-02", ["08:00", "09:00", "09:30"])
        fixtures.ingest_event(
            wearable["id"], "FALL_DETECTED", "2026-05-02T09:45:00Z"
        )
        set_clock("2026-05-03T00:01:00Z")
        fixtures.bring_device_online(gateway["id"], "2026-05-03T00:01:00Z")
        fixtures.bring_device_online(motion["id"], "2026-05-03T00:01:00Z")
        return ctx

    def test_wellness_index_fall_cap_applies(self, api):
        """PRD 3.8: "Then, if any `FALL` alert of the senior was opened inside
        the period and does not stand in `FALSE_ALARM` status, the value is
        capped at 59 and the report's `fall_cap_applied` flag is set true."
        PRD 3.8: "The `wellness_index` blends the three: forty percent of the
        activity score, thirty-five percent of adherence, and twenty-five
        percent of device health."

        Design: Difficulty/combinatorial_formula/wellness_index_weighted_sum_with_fall_cap
        """
        ctx = self._setup()
        report = get_success_data(
            api.create_wellness_report(
                factories.create_wellness_report_payload(
                    ctx["senior"]["id"],
                    "2026-05-01T00:00:00Z",
                    "2026-05-03T00:00:00Z",
                    "FINAL",
                ),
                ADMIN,
            )
        )
        # The uncapped blend sits well above 59 (perfect activity, vacuous
        # adherence); the open FALL alert must cap the index at 59.
        assert report["wellness_index"] == pytest.approx(59.0, abs=0.01)

    def test_wellness_index_fall_cap_flag_and_vacuous_adherence(self, api):
        """PRD 3.8: "Then, if any `FALL` alert of the senior was opened inside
        the period and does not stand in `FALSE_ALARM` status, the value is
        capped at 59 and the report's `fall_cap_applied` flag is set true."
        PRD 3.8: "When the due set is empty, adherence is defined as 100.0;
        otherwise it is one hundred times the summed weights divided by the
        due-set size, rounded half up to one decimal."

        Design: Difficulty/combinatorial_formula/wellness_index_weighted_sum_with_fall_cap
        """
        ctx = self._setup()
        report = get_success_data(
            api.create_wellness_report(
                factories.create_wellness_report_payload(
                    ctx["senior"]["id"],
                    "2026-05-01T00:00:00Z",
                    "2026-05-03T00:00:00Z",
                    "FINAL",
                ),
                ADMIN,
            )
        )
        assert report["fall_cap_applied"] is True
        assert report["activity_score"] == pytest.approx(100.0, abs=0.01)
        assert report["adherence_pct"] == pytest.approx(100.0, abs=0.01)


class TestVacuousAdherence:
    def _setup(self):
        """ACTIVE senior, no schedules, no telemetry (devices INSTALLED, never
        ONLINE); clock at 2026-05-02T00:01Z."""
        ctx = setup_active_senior(
            plan_overrides={
                "tier": "PREMIUM",
                "monthly_fee_cents": 9000,
                "included_motion_sensors": 2,
                "extra_sensor_fee_cents": 199,
                "max_contacts": 8,
                "checkin_interval_hours": 48,
                "medication_reminders_enabled": True,
                "wellness_report_enabled": True,
                "wellness_report_cadence": "WEEKLY",
            }
        )
        set_clock("2026-05-02T00:01:00Z")
        return ctx

    def test_adherence_empty_dose_set_is_100(self, api):
        """PRD 3.8: "When the due set is empty, adherence is defined as 100.0;
        otherwise it is one hundred times the summed weights divided by the
        due-set size, rounded half up to one decimal."

        Design: Difficulty/boundary_precision_check/adherence_empty_dose_set_is_vacuous_100
        """
        ctx = self._setup()
        report = get_success_data(
            api.create_wellness_report(
                factories.create_wellness_report_payload(
                    ctx["senior"]["id"],
                    "2026-05-01T00:00:00Z",
                    "2026-05-02T00:00:00Z",
                    "FINAL",
                ),
                ADMIN,
            )
        )
        assert report["adherence_pct"] == pytest.approx(100.0, abs=0.01), (
            "an empty due set must yield vacuous adherence 100.0"
        )

    def test_empty_period_wellness_index_60(self, api):
        """PRD 3.8: "When the due set is empty, adherence is defined as 100.0;
        otherwise it is one hundred times the summed weights divided by the
        due-set size, rounded half up to one decimal."
        PRD 3.8: "The `wellness_index` blends the three: forty percent of the
        activity score, thirty-five percent of adherence, and twenty-five
        percent of device health. The evaluation order is pinned — weighting
        first, penalty second, cap third, rounding last."
        PRD 3.8: "The `device_health_pct` starts at 100 and deducts per
        non-`DECOMMISSIONED` device of the senior: 10 points if the device is
        `OFFLINE` at evaluation time, and 5 points if its `battery_percent` is
        at or below 20 at evaluation time. A device `INSTALLED` but never yet
        `ONLINE` draws no deduction, and the total never drops below 0; the
        value is carried to one decimal place, though it is integral in
        practice."

        Design: Difficulty/boundary_precision_check/adherence_empty_dose_set_is_vacuous_100
        """
        ctx = self._setup()
        report = get_success_data(
            api.create_wellness_report(
                factories.create_wellness_report_payload(
                    ctx["senior"]["id"],
                    "2026-05-01T00:00:00Z",
                    "2026-05-02T00:00:00Z",
                    "FINAL",
                ),
                ADMIN,
            )
        )
        assert report["activity_score"] == pytest.approx(0.0, abs=0.01), (
            "no MOTION events means zero active days"
        )
        assert report["device_health_pct"] == pytest.approx(100.0, abs=0.01)
        # 0.40*0 + 0.35*100 + 0.25*100 = 60.0; no penalty (100 >= 60); no cap.
        assert report["wellness_index"] == pytest.approx(60.0, abs=0.01)
        assert report["fall_cap_applied"] is False


class TestDuplicateFinalReport:
    def test_duplicate_final_report_rejected(self, api):
        """PRD 3.8: "Four gates guard creation, in this order: the subscription
        must be `ACTIVE` (else `ERR_SUBSCRIPTION_NOT_ACTIVE`); a `FINAL` report
        must not already exist for the same senior and an overlapping period
        (else `ERR_DUPLICATE_REPORT`); the period must be temporally legal —
        `FINAL` requires the clock to have passed `period_end`, while
        `PROVISIONAL` requires the clock to lie within the period from
        `period_start` through `period_end` inclusive (else
        `ERR_PERIOD_NOT_CLOSED`); and the plan's `wellness_report_enabled` flag
        must be on (else `ERR_FEATURE_GATED`)."

        Design: Corner/validations/duplicate_final_report_rejected
        """
        ctx = setup_active_senior(
            plan_overrides={
                "tier": "PREMIUM",
                "checkin_interval_hours": 48,
                "wellness_report_enabled": True,
            }
        )
        set_clock("2026-05-02T00:01:00Z")
        payload = factories.create_wellness_report_payload(
            ctx["senior"]["id"],
            "2026-05-01T00:00:00Z",
            "2026-05-02T00:00:00Z",
            "FINAL",
        )
        get_success_data(api.create_wellness_report(payload, ADMIN))
        resp = api.create_wellness_report(dict(payload), ADMIN)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_REPORT)


class TestReportRegenerateOCC:
    def test_occ_report_regenerate_stale_version_rejected(self, api):
        """PRD 2.8: "Regenerating a wellness report similarly requires
        `expected_report_version` matching the target `WellnessReport`'s
        current `version`. A mismatch is rejected with `ERR_STALE_VERSION`
        (HTTP 412), so a client never silently discards another writer's
        regeneration."
        PRD 3.8: "Regeneration, restricted to `PlatformAdmin`, recomputes every
        metric in place at the current clock under the report's existing `mode`
        and increments the report's `version`; it is governed by the
        optimistic-concurrency rule of §2.8 — `expected_report_version` must
        match or the request fails with `ERR_STALE_VERSION` — and a report no
        longer `READY` yields `ERR_INVALID_STATE`."

        Design: Corner/cross_cutting_complexity_layers/occ_report_regenerate_stale_version_rejected
        """
        ctx = setup_active_senior(
            plan_overrides={
                "tier": "PREMIUM",
                "checkin_interval_hours": 48,
                "wellness_report_enabled": True,
            }
        )
        set_clock("2026-05-02T00:01:00Z")
        report = get_success_data(
            api.create_wellness_report(
                factories.create_wellness_report_payload(
                    ctx["senior"]["id"],
                    "2026-05-01T00:00:00Z",
                    "2026-05-02T00:00:00Z",
                    "FINAL",
                ),
                ADMIN,
            )
        )
        observed_version = report["version"]
        regenerated = get_success_data(
            api.regenerate_wellness_report(
                report["id"], {"expected_report_version": observed_version}, ADMIN
            )
        )
        assert regenerated["version"] == observed_version + 1, (
            "a fresh expected version must succeed and increment the version"
        )
        resp = api.regenerate_wellness_report(
            report["id"], {"expected_report_version": observed_version}, ADMIN
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
