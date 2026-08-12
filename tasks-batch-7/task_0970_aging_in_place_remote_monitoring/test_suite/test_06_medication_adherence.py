"""Medication schedules: OCC, feature gating, dose horizon materialization,
miss cascades, dose confirmation lockdown, check-in gating, and the dashboard's
today-scope adherence."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    factories,
    fixtures,
    get_success_data,
    make_caregiver_headers,
    make_senior_headers,
    set_clock,
    setup_active_senior,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]


class TestDoseMissCascade:
    """Depth-3 cascade: dose sweep -> missed_streak -> alert -> notification."""

    def _setup(self):
        """ACTIVE senior, contact rank 1 (LOW, 3600s), CRITICAL schedule at
        20:00 with window 60 starting 2026-05-01; clock at activation time."""
        ctx = setup_active_senior(
            plan_overrides={"tier": "PLUS", "checkin_interval_hours": 48}
        )
        caregiver, entry = fixtures.add_caregiver_with_contact(
            ctx["senior"]["id"], priority_rank=1, min_severity="LOW",
            response_timeout_seconds=3600,
        )
        schedule = fixtures.create_med_schedule(
            ctx["senior"]["id"],
            medication_name="Warfarin",
            times_of_day=("20:00",),
            window_minutes=60,
            criticality="CRITICAL",
            start_date="2026-05-01",
        )
        ctx.update({"caregiver": caregiver, "entry": entry, "schedule": schedule})
        return ctx

    def test_critical_dose_misses_create_streak_and_alert(self, api):
        """PRD 3.6: "The third sweep step closes expired windows: a `PENDING`
        dose whose deadline has passed becomes `MISSED`, its schedule's
        `missed_streak` increments by one, and streaks trigger escalation — a
        `CRITICAL` schedule reaching a streak of 2, or a `ROUTINE` schedule
        reaching 3, creates a `MISSED_MEDICATION` alert for the senior (`HIGH`
        severity for `CRITICAL` schedules, `MEDIUM` for `ROUTINE`) provided no
        such alert is already open, increments `open_alert_count`, and
        immediately runs the notification step of §3.5."
        PRD 2.6: "A third derived field, `risk_tier`, reads `ELEVATED` when the
        senior has any open `CRITICAL` alert or any `ACTIVE` `CRITICAL`
        medication schedule whose `missed_streak` has reached 3, and `STANDARD`
        otherwise."

        Design: Difficulty/transitive_cascade/dose_miss_streak_alert_notification_chain
        """
        ctx = self._setup()
        # Both the 05-01 and 05-02 doses miss their 60-minute windows.
        set_clock("2026-05-02T21:30:00Z")

        missed, _meta = validate_paginated(
            api.list_dose_events(
                ADMIN, params={"schedule_id": ctx["schedule"]["id"], "status": "MISSED"}
            )
        )
        assert len(missed) == 2, f"both doses must be MISSED, got {len(missed)}"

        schedule = get_success_data(
            api.get_medication_schedule(ctx["schedule"]["id"], ADMIN)
        )
        assert schedule["missed_streak"] == 2

        alerts = fixtures.list_alerts(
            senior_id=ctx["senior"]["id"], alert_type="MISSED_MEDICATION"
        )
        assert len(alerts) == 1
        assert alerts[0]["severity"] == "HIGH"
        assert alerts[0]["status"] == "NOTIFYING"

        senior = fixtures.get_senior(ctx["senior"]["id"])
        assert senior["open_alert_count"] == 1
        assert senior["risk_tier"] == "STANDARD", (
            "streak 2 is below the CRITICAL-schedule threshold of 3"
        )

    def test_missed_medication_alert_fires_notification_level_one(self, api):
        """PRD 3.6: "The third sweep step closes expired windows: a `PENDING`
        dose whose deadline has passed becomes `MISSED`, its schedule's
        `missed_streak` increments by one, and streaks trigger escalation — a
        `CRITICAL` schedule reaching a streak of 2, or a `ROUTINE` schedule
        reaching 3, creates a `MISSED_MEDICATION` alert for the senior (`HIGH`
        severity for `CRITICAL` schedules, `MEDIUM` for `ROUTINE`) provided no
        such alert is already open, increments `open_alert_count`, and
        immediately runs the notification step of §3.5."
        PRD 3.5: "When at least one eligible contact exists, the alert moves
        `RAISED` → `NOTIFYING`, an `AlertNotification` is created for the
        first-ranked contact at `level` 1 in `SENT` status with `sent_at`
        stamped from the logical clock, and the alert's `escalation_level`
        becomes 1. When no eligible contact exists, the alert simply stays
        `RAISED` in the monitoring-center queue."

        Design: Difficulty/transitive_cascade/dose_miss_streak_alert_notification_chain
        """
        ctx = self._setup()
        set_clock("2026-05-02T21:30:00Z")
        notifications = fixtures.list_notifications(
            caregiver_id=ctx["caregiver"]["id"]
        )
        assert len(notifications) == 1, (
            "the cascade's alert must immediately notify the first contact"
        )
        assert notifications[0]["level"] == 1
        assert notifications[0]["status"] == "SENT"


class TestDoseConfirmationLockdown:
    def test_dose_confirm_after_window_returns_not_pending(self, api):
        """PRD 3.6: "The senior themself or their caregiver may confirm a dose;
        the caller must own the dose's senior (else `ERR_OWNERSHIP_MISMATCH`),
        the dose must still be `PENDING` (else `ERR_DOSE_NOT_PENDING`), and
        confirmation must arrive no later than `scheduled_at` plus
        `window_minutes` — after that the sweep has already marked it missed."

        Design: Corner/state_machines/dose_confirm_after_window_returns_not_pending
        """
        ctx = setup_active_senior()
        schedule = fixtures.create_med_schedule(
            ctx["senior"]["id"],
            medication_name="Aspirin",
            times_of_day=("20:00",),
            window_minutes=60,
            criticality="ROUTINE",
            start_date="2026-05-01",
        )
        # Sweep past the 20:00 + 60-minute deadline.
        set_clock("2026-05-01T21:30:00Z")
        doses = fixtures.list_doses(schedule["id"])
        assert doses[0]["status"] == "MISSED", (
            "the sweep must mark the dose MISSED before the confirm attempt"
        )
        resp = api.confirm_dose_event(
            doses[0]["id"], make_senior_headers(ctx["senior"]["id"])
        )
        validate_error(resp, ApiErrorId.ERR_DOSE_NOT_PENDING)


class TestDoseHorizonExtension:
    def test_dose_horizon_extension_materializes_future_doses(self, api):
        """PRD 3.6: "The new schedule starts `ACTIVE` with `missed_streak` at
        zero, and its dose events are materialized immediately for the window
        from the current clock through the next 48 hours; each clock advance
        extends that horizon by the same 48-hour look-ahead, which is the
        second step of the pinned sweep."

        Design: Corner/cross_cutting_complexity_layers/dose_horizon_extension_materializes_future_doses
        """
        ctx = setup_active_senior()
        schedule = fixtures.create_med_schedule(
            ctx["senior"]["id"],
            medication_name="Aspirin",
            times_of_day=("20:00",),
            window_minutes=60,
            criticality="ROUTINE",
            start_date="2026-05-01",
        )
        # Created at clock 2026-05-01T09:30Z: horizon covers 05-01 and 05-02.
        doses_before = fixtures.list_doses(schedule["id"])
        assert len(doses_before) == 2, (
            f"only doses within [now, now+48h) may be materialized; got "
            f"{len(doses_before)}"
        )

        set_clock("2026-05-02T09:30:00Z")
        doses_after = fixtures.list_doses(schedule["id"])
        assert len(doses_after) == 3, (
            "the clock advance must materialize the 05-03 dose without any "
            "further client writes"
        )
        new_doses = [d for d in doses_after if d["scheduled_at"] >= "2026-05-03"]
        assert len(new_doses) == 1
        assert new_doses[0]["status"] == "PENDING"


class TestMedicationScheduleOCC:
    def test_occ_med_schedule_stale_version_rejected(self, api):
        """PRD 2.8: "Creating a medication schedule requires the request to
        carry `expected_senior_version`, holding the `version` of the target
        `Senior` as the client last observed it. If the senior's current
        `version` no longer matches — for instance because another writer has
        since created a schedule for the same medication, legitimately
        superseding the prior `ACTIVE` one — the creation is rejected with
        `ERR_STALE_VERSION` (HTTP 412), preventing the client from acting on a
        view of the senior it has not re-read."
        PRD 3.6: "Creation increments the senior's `version` by one — which is
        precisely what a concurrent creator's `expected_senior_version` check
        observes — and enforces a uniqueness-by-replacement rule: if an
        `ACTIVE` schedule already exists for the same senior and
        `medication_name`, the newcomer supersedes it, ending the old schedule
        and marking its `PENDING` doses `SKIPPED`."

        Design: Corner/cross_cutting_complexity_layers/occ_med_schedule_stale_version_rejected
        """
        ctx = setup_active_senior()
        senior_id = ctx["senior"]["id"]
        senior = fixtures.get_senior(senior_id)
        observed_version = senior["version"]

        first = get_success_data(
            api.create_medication_schedule(
                factories.create_medication_schedule_payload(
                    senior_id,
                    expected_senior_version=observed_version,
                    medication_name="Warfarin",
                    times_of_day=["20:00"],
                    window_minutes=60,
                    criticality="CRITICAL",
                    start_date="2026-05-01",
                ),
                ADMIN,
            )
        )

        # The first create bumped Senior.version; replaying the stale version
        # must be rejected even though the payload is otherwise valid.
        resp = api.create_medication_schedule(
            factories.create_medication_schedule_payload(
                senior_id,
                expected_senior_version=observed_version,
                medication_name="Warfarin",
                times_of_day=["08:00"],
                window_minutes=30,
                criticality="CRITICAL",
                start_date="2026-05-02",
            ),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        schedules, _meta = validate_paginated(
            api.list_medication_schedules(
                ADMIN, params={"senior_id": senior_id, "status": "ACTIVE"}
            )
        )
        assert len(schedules) == 1, (
            "the rejected create must not supersede the existing schedule"
        )
        assert schedules[0]["id"] == first["id"]


class TestFeatureGatesAndSubscriptionGates:
    def test_feature_gate_blocks_med_schedule_on_basic_plan(self, api):
        """PRD 3.6: "A medication schedule is created for a senior by a
        `PlatformAdmin` or by that senior's caregiver, and only while the
        senior's subscription has `service_status` of `ACTIVE` (else
        `ERR_SUBSCRIPTION_NOT_ACTIVE`) and the plan's
        `medication_reminders_enabled` flag is on (else `ERR_FEATURE_GATED`)."

        Design: Corner/validations/feature_gate_blocks_med_schedule_on_basic_plan
        """
        ctx = setup_active_senior(
            plan_overrides={
                "tier": "ESSENTIAL",
                "medication_reminders_enabled": False,
                "wellness_report_enabled": False,
                "wellness_report_cadence": "NONE",
            }
        )
        senior = fixtures.get_senior(ctx["senior"]["id"])
        resp = api.create_medication_schedule(
            factories.create_medication_schedule_payload(
                ctx["senior"]["id"],
                expected_senior_version=senior["version"],
                medication_name="Aspirin",
                times_of_day=["08:00"],
                window_minutes=60,
                criticality="ROUTINE",
                start_date="2026-05-01",
            ),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_FEATURE_GATED)


class TestCheckInGating:
    """Check-in creation requires the subscription's service to be ACTIVE."""

    def _setup_suspended(self, api):
        ctx = setup_active_senior()
        caregiver = fixtures.add_caregiver(ctx["senior"]["id"], full_name="Cg Ci")
        sub_id = ctx["subscription"]["id"]
        get_success_data(api.record_payment(sub_id, {"outcome": "FAILED"}, ADMIN))
        suspended = get_success_data(
            api.record_payment(sub_id, {"outcome": "FAILED"}, ADMIN)
        )
        assert suspended["service_status"] == "SUSPENDED"
        ctx["caregiver"] = caregiver
        return ctx

    def test_checkin_on_suspended_subscription_rejected(self, api):
        """PRD 3.7: "Recording a check-in requires the senior's subscription to
        be `ACTIVE`, else `ERR_SUBSCRIPTION_NOT_ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/checkin_requires_active_subscription_rejected
        """
        ctx = self._setup_suspended(api)
        resp = api.create_check_in(
            factories.create_check_in_payload(
                ctx["senior"]["id"], "CALL", note="weekly call"
            ),
            make_caregiver_headers(ctx["caregiver"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SUBSCRIPTION_NOT_ACTIVE)

    def test_checkin_rejection_creates_no_checkin(self, api):
        """PRD 3.7: "Recording a check-in requires the senior's subscription to
        be `ACTIVE`, else `ERR_SUBSCRIPTION_NOT_ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/checkin_requires_active_subscription_rejected
        """
        ctx = self._setup_suspended(api)
        validate_error(
            api.create_check_in(
                factories.create_check_in_payload(
                    ctx["senior"]["id"], "CALL", note="weekly call"
                ),
                make_caregiver_headers(ctx["caregiver"]["id"]),
            ),
            ApiErrorId.ERR_SUBSCRIPTION_NOT_ACTIVE,
        )
        checkins, _meta = validate_paginated(
            api.list_check_ins(ADMIN, params={"senior_id": ctx["senior"]["id"]})
        )
        assert checkins == [], "a rejected check-in must not persist a row"


class TestDashboardAdherence:
    def test_dashboard_adherence_today_weighted_literal(self, api):
        """PRD 3.7: "The caregiver dashboard aggregates a senior's current
        situation into a single read: the `monitoring_posture`,
        `open_alert_count`, and `risk_tier` of §2.6; `adherence_today_pct`, the
        adherence percentage (§3.8's weighting rules) computed over doses
        scheduled from midnight UTC today through the current clock, counting
        only terminal doses; `devices_online` and `devices_total` summarizing
        the fleet; the `last_checkin_at` timestamp; and the
        `next_dose_scheduled_at` instant of the next pending dose."
        PRD 3.8: "The `adherence_pct` weighs terminal doses: a dose confirmed
        `TAKEN` with `punctual` true counts 1.0, `TAKEN` but late counts 0.5,
        and `MISSED` counts 0.0."

        Design: Corner/calculations/dashboard_adherence_today_weighted_literal
        """
        ctx = setup_active_senior(
            window_start="2026-05-01T07:00:00Z",
            window_end="2026-05-01T08:00:00Z",
            complete_at="2026-05-01T07:30:00Z",
        )
        senior_id = ctx["senior"]["id"]
        schedule = fixtures.create_med_schedule(
            senior_id,
            medication_name="Metformin",
            times_of_day=("08:00", "09:00"),
            window_minutes=60,
            criticality="ROUTINE",
            start_date="2026-05-01",
        )
        set_clock("2026-05-01T08:10:00Z")
        doses = fixtures.list_doses(schedule["id"])
        dose_0800 = next(d for d in doses if "T08:00" in d["scheduled_at"])
        dose_0900 = next(d for d in doses if "T09:00" in d["scheduled_at"])
        # Punctual confirmation (within 15 minutes of the scheduled time).
        fixtures.confirm_dose_as_senior(dose_0800["id"], senior_id)
        # Late confirmation: 40 minutes after 09:00, inside the 60-minute window.
        set_clock("2026-05-01T09:40:00Z")
        fixtures.confirm_dose_as_senior(dose_0900["id"], senior_id)

        dashboard = get_success_data(api.get_senior_dashboard(senior_id, ADMIN))
        assert dashboard["adherence_today_pct"] == pytest.approx(75.0, abs=0.01), (
            "one punctual (1.0) plus one late (0.5) terminal dose must yield "
            f"75.0, got {dashboard['adherence_today_pct']}"
        )
        assert dashboard["monitoring_posture"] == "ACTIVE"
