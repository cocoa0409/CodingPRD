"""Arrhythmia triage lifecycle, notification SLA, and alarm fatigue (PRD §3.5)."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    acknowledge_alert,
    assert_iso_prefix,
    make_physician_headers,
    make_technician_headers,
    raise_alert,
    read_alert,
    read_technician,
    register_physician,
    register_technician,
    set_clock,
    setup_acknowledged_alert,
    setup_alert_scenario,
    setup_monitoring_episode,
    setup_notified_alert,
    validate_error,
    validate_paginated,
    validate_success,
)

COORD = TEST_USERS["enrollment_coordinator_headers"]


class TestAlertInvalidTransitions:
    def test_close_from_new_rejected(self, api):
        """PRD §3.5: "Closing an alert depends on how far it traveled. From
        `ACKNOWLEDGED`, the assignee closes with `outcome` `FALSE_POSITIVE`."
        PRD §2.8: "5. **State-machine preconditions** — from-state and guard
        checks: generic failures yield `ERR_INVALID_STATE` (409); a device
        already committed elsewhere yields `ERR_DEVICE_NOT_IN_STOCK` (409);
        activation before education yields `ERR_EDUCATION_INCOMPLETE` (422); a
        stale order version yields `ERR_STALE_VERSION` (412)."

        Design: Corner/state_machines/alert_close_from_new_rejected
        """
        ctx = setup_alert_scenario(severity="ROUTINE")
        tech_headers = make_technician_headers(ctx["technician"]["id"])
        resp = api.close_alert(ctx["alert"]["id"], {"outcome": "FALSE_POSITIVE"}, tech_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert read_alert(ctx["alert"]["id"])["status"] == "NEW"

    def test_notify_requires_triaged_or_escalated(self, api):
        """PRD §3.5: "From `TRIAGED`, the notifying technician must be the
        assignee; from `ESCALATED`, the same notify action is not gated on
        assignment, and it likewise produces a preference-channel attempt."
        PRD §2.8: "5. **State-machine preconditions** — from-state and guard
        checks: generic failures yield `ERR_INVALID_STATE` (409); a device
        already committed elsewhere yields `ERR_DEVICE_NOT_IN_STOCK` (409);
        activation before education yields `ERR_EDUCATION_INCOMPLETE` (422); a
        stale order version yields `ERR_STALE_VERSION` (412)."

        Design: Corner/state_machines/notify_requires_triaged_or_escalated
        """
        ctx = setup_acknowledged_alert(severity="URGENT", alert_clock="2026-05-01T10:00:00Z")
        tech_headers = make_technician_headers(ctx["technician"]["id"])
        resp = api.notify_alert(ctx["alert"]["id"], tech_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        attempts, meta = validate_paginated(
            api.list_notification_attempts(COORD, params={"alert_id": ctx["alert"]["id"]})
        )
        assert meta["total_count"] == 0, "rejected notify must not create a NotificationAttempt"


class TestNotificationCloseGate:
    def test_close_resolved_requires_acknowledged_notification(self, api):
        """PRD §3.5: "From `NOTIFIED`, closing with `outcome` `RESOLVED`
        additionally requires that at least one notification attempt for the
        alert has been acknowledged by the physician; without one, the close is
        rejected with `ERR_NOTIFICATION_NOT_ACKNOWLEDGED` (HTTP 422)."
        PRD §3.5: "Either close records `closed_outcome`, moves the alert to
        its terminal `CLOSED` state, decrements the holding technician's
        `open_alert_load`, and — for `CRITICAL` alerts — decrements the
        episode's `unacknowledged_critical_count`."
        PRD §3.5: "At that moment `within_sla` is computed: true when the
        acknowledgement happened at or before the alert's `sla_deadline`, false
        otherwise."

        Design: Corner/state_machines/close_resolved_requires_acknowledged_notification
        """
        ctx = setup_notified_alert(severity="URGENT", alert_clock="2026-05-01T10:00:00Z")
        tech_headers = make_technician_headers(ctx["technician"]["id"])
        alert_id = ctx["alert"]["id"]

        resp = api.close_alert(alert_id, {"outcome": "RESOLVED"}, tech_headers)
        validate_error(resp, ApiErrorId.ERR_NOTIFICATION_NOT_ACKNOWLEDGED)

        attempt = validate_success(
            api.acknowledge_notification_attempt(
                ctx["attempt"]["id"], make_physician_headers(ctx["physician"]["id"])
            )
        )
        assert attempt["status"] == "ACKNOWLEDGED"
        assert attempt["within_sla"] is True, (
            "URGENT raised at 10:00 has sla_deadline 11:00; ack at 10:00 is within SLA"
        )

        closed = validate_success(api.close_alert(alert_id, {"outcome": "RESOLVED"}, tech_headers))
        assert closed["status"] == "CLOSED"
        assert closed["closed_outcome"] == "RESOLVED"
        assert read_technician(ctx["technician"]["id"])["open_alert_load"] == 0


class TestEscalation:
    def test_manual_escalation_creates_escalation_attempt(self, api):
        """PRD §3.5: "A technician may manually escalate a `TRIAGED` alert, and
        the sweep's third stage escalates any alert still in `NEW`,
        `ACKNOWLEDGED`, or `TRIAGED` whose `sla_deadline` has passed."
        PRD §3.5: "Either way the alert lands in `ESCALATED` and a
        `NotificationAttempt` with `channel` `ESCALATION` is created, counted
        like any other."
        PRD §3.5: "The attempt's `physician_id` is resolved by walking the
        episode's enrollment back to the order's `ordering_physician_id` — the
        ordering physician is always the one notified — and its `channel` is
        that physician's `notification_preference`."

        Design: Corner/state_machines/escalation_creates_escalation_attempt
        """
        ctx = setup_acknowledged_alert(severity="CRITICAL", alert_clock="2026-05-01T10:00:00Z")
        tech_headers = make_technician_headers(ctx["technician"]["id"])
        validate_success(api.triage_alert(ctx["alert"]["id"], {}, tech_headers))

        escalated = validate_success(api.escalate_alert(ctx["alert"]["id"], tech_headers))
        assert escalated["status"] == "ESCALATED"
        assert escalated["notification_attempt_count"] == 1

        attempts, meta = validate_paginated(
            api.list_notification_attempts(COORD, params={"alert_id": ctx["alert"]["id"]})
        )
        assert meta["total_count"] == 1
        assert attempts[0]["channel"] == "ESCALATION"
        assert attempts[0]["physician_id"] == ctx["physician"]["id"]


class TestFatigueGating:
    def test_fatigued_technician_blocked_from_acknowledge(self, api):
        """PRD §3.5: "The load ratio `fatigue_index` is the technician's
        `open_alert_load` divided by `shift_capacity`, rounded half up to two
        decimal places; a value of 0.80 or higher marks the technician
        `FATIGUED`, a value of 0.60 or higher but below 0.80 marks `AT_RISK`,
        and anything lower is `NORMAL`."
        PRD §3.5: "A `MonitoringTechnician` acknowledges a `NEW` alert — from
        any other state the action fails generically with `ERR_INVALID_STATE` —
        and three conditions are enforced together, any of which rejects the
        call with `ERR_TECHNICIAN_UNAVAILABLE` (HTTP 422): the caller's
        `on_shift` flag must be true, the caller's `open_alert_load` must be
        below their `shift_capacity`, and the caller's `fatigue_status` must
        not be `FATIGUED`."

        Design: Corner/calculations/fatigued_technician_blocked_from_acknowledge
        """
        ctx = setup_alert_scenario(severity="ROUTINE", alert_clock="2026-05-01T10:00:00Z")
        tech_id = ctx["technician"]["id"]  # capacity 5
        episode_id = ctx["episode_id"]
        alerts = [ctx["alert"]] + [
            raise_alert(episode_id, severity="ROUTINE", arrhythmia_type="AFIB") for _ in range(3)
        ]
        fifth = raise_alert(episode_id, severity="ROUTINE", arrhythmia_type="PAUSE")
        for a in alerts:
            acknowledge_alert(a["id"], tech_id)

        tech = read_technician(tech_id)
        assert tech["open_alert_load"] == 4
        assert tech["fatigue_index"] == pytest.approx(0.80, abs=0.001)
        assert tech["fatigue_status"] == "FATIGUED", "0.80 is inclusive FATIGUED"

        resp = api.acknowledge_alert(fifth["id"], make_technician_headers(tech_id))
        validate_error(resp, ApiErrorId.ERR_TECHNICIAN_UNAVAILABLE)
        assert read_alert(fifth["id"])["status"] == "NEW"

    def test_technician_at_capacity_unavailable(self, api):
        """PRD §3.5: "A `MonitoringTechnician` acknowledges a `NEW` alert —
        from any other state the action fails generically with
        `ERR_INVALID_STATE` — and three conditions are enforced together, any
        of which rejects the call with `ERR_TECHNICIAN_UNAVAILABLE` (HTTP 422):
        the caller's `on_shift` flag must be true, the caller's
        `open_alert_load` must be below their `shift_capacity`, and the
        caller's `fatigue_status` must not be `FATIGUED`."

        Design: Corner/errors/technician_at_capacity_unavailable
        """
        ctx = setup_alert_scenario(
            severity="ROUTINE", alert_clock="2026-05-01T10:00:00Z", technician_capacity=1
        )
        tech_id = ctx["technician"]["id"]
        acknowledge_alert(ctx["alert"]["id"], tech_id)
        second = raise_alert(ctx["episode_id"], severity="ROUTINE", arrhythmia_type="AFIB")

        resp = api.acknowledge_alert(second["id"], make_technician_headers(tech_id))
        validate_error(resp, ApiErrorId.ERR_TECHNICIAN_UNAVAILABLE)


class TestThroughputVsLoadRatio:
    def test_throughput_vs_load_ratio_divergence(self, api):
        """PRD §3.5: "The load ratio `fatigue_index` is the technician's
        `open_alert_load` divided by `shift_capacity`, rounded half up to two
        decimal places; a value of 0.80 or higher marks the technician
        `FATIGUED`, a value of 0.60 or higher but below 0.80 marks `AT_RISK`,
        and anything lower is `NORMAL`."
        PRD §3.5: "The `throughput_index` is the cumulative companion: the sum
        of `alerts_acknowledged_total` and `open_alert_load`, divided by
        `shift_capacity` multiplied by the number of full days between the
        technician's `created_at` and the current time — that day count treated
        as at least one — rounded half up to two decimal places."

        Design: Corner/calculations/throughput_vs_load_ratio_divergence
        """
        ctx = setup_alert_scenario(severity="ROUTINE", alert_clock=None)
        tech_id = ctx["technician"]["id"]  # capacity 5, created at clock start
        episode_id = ctx["episode_id"]
        alerts = [ctx["alert"]] + [
            raise_alert(episode_id, severity="ROUTINE", arrhythmia_type="AFIB") for _ in range(5)
        ]
        tech_headers = make_technician_headers(tech_id)
        for a in alerts:
            acknowledge_alert(a["id"], tech_id)
            validate_success(api.close_alert(a["id"], {"outcome": "FALSE_POSITIVE"}, tech_headers))

        set_clock("2026-05-03T00:00:00Z")
        tech = read_technician(tech_id)
        assert tech["alerts_acknowledged_total"] == 6
        assert tech["open_alert_load"] == 0
        assert tech["fatigue_index"] == pytest.approx(0.0, abs=0.001)
        assert tech["fatigue_status"] == "NORMAL"
        # (6 + 0) / (5 * 2 full days) = 0.60 — the throughput variant diverges.
        assert tech["throughput_index"] == pytest.approx(0.60, abs=0.001)


class TestNotificationAttemptOwnership:
    def test_notification_ack_wrong_physician_forbidden(self, api):
        """PRD §3.5: "The physician side of the loop is a single act: the
        addressed physician — the caller's id must equal the attempt's
        `physician_id`, else `ERR_FORBIDDEN_ROLE` — acknowledges a `PENDING`
        attempt, moving it to its terminal `ACKNOWLEDGED` status."

        Design: Corner/errors/notification_ack_wrong_physician_forbidden
        """
        ctx = setup_notified_alert(severity="URGENT", alert_clock="2026-05-01T10:00:00Z")
        other_physician = register_physician()
        resp = api.acknowledge_notification_attempt(
            ctx["attempt"]["id"], make_physician_headers(other_physician["id"])
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
        attempt = validate_success(
            api.get_notification_attempt(ctx["attempt"]["id"], COORD)
        )
        assert attempt["status"] == "PENDING"


class TestAcknowledgeReleaseCycle:
    def test_acknowledge_assigns_and_increments_load(self, api):
        """PRD §3.5: "On success the alert moves from `NEW` to `ACKNOWLEDGED`
        with `assigned_technician_id` set to the caller and `acknowledged_at`
        stamped; the cascade then runs two links into the technician record —
        `open_alert_load` increments by one, `alerts_acknowledged_total`
        increments by one (a lifetime counter that is never decremented), and
        the fatigue figures are recomputed as described below, which may flip
        `fatigue_status` from `NORMAL` to `AT_RISK` or `FATIGUED`."

        Design: Difficulty/non_linear_state_machine/alert_acknowledge_release_cycle
        """
        ctx = setup_alert_scenario(severity="CRITICAL")
        t1 = ctx["technician"]
        t2 = register_technician()

        acked = acknowledge_alert(ctx["alert"]["id"], t1["id"])
        assert acked["status"] == "ACKNOWLEDGED"
        assert acked["assigned_technician_id"] == t1["id"]
        assert read_technician(t1["id"])["open_alert_load"] == 1

        # continue the cycle so the instance's full loop is exercised
        released = validate_success(
            api.release_alert(ctx["alert"]["id"], make_technician_headers(t1["id"]))
        )
        assert released["status"] == "NEW"
        acked2 = acknowledge_alert(ctx["alert"]["id"], t2["id"])
        assert acked2["assigned_technician_id"] == t2["id"]

    def test_release_returns_to_new_and_decrements_load(self, api):
        """PRD §3.5: "Releasing an alert — permitted only to the technician
        whose id equals `assigned_technician_id` — returns it from
        `ACKNOWLEDGED` to `NEW`, clears the assignment, decrements the
        technician's `open_alert_load`, and recomputes fatigue."

        Design: Difficulty/non_linear_state_machine/alert_acknowledge_release_cycle
        """
        ctx = setup_alert_scenario(severity="CRITICAL")
        t1 = ctx["technician"]
        t2 = register_technician()

        acknowledge_alert(ctx["alert"]["id"], t1["id"])
        released = validate_success(
            api.release_alert(ctx["alert"]["id"], make_technician_headers(t1["id"]))
        )
        assert released["status"] == "NEW"
        assert released["assigned_technician_id"] is None
        assert read_technician(t1["id"])["open_alert_load"] == 0, "release must not leak load"

        acked2 = acknowledge_alert(ctx["alert"]["id"], t2["id"])
        assert acked2["status"] == "ACKNOWLEDGED"
        assert acked2["assigned_technician_id"] == t2["id"]
        assert read_technician(t2["id"])["open_alert_load"] == 1


class TestAcknowledgeFatigueCascade:
    def _setup_two_acked(self):
        ctx = setup_alert_scenario(severity="ROUTINE")
        tech_id = ctx["technician"]["id"]  # capacity 5
        a2 = raise_alert(ctx["episode_id"], severity="ROUTINE", arrhythmia_type="AFIB")
        a3 = raise_alert(ctx["episode_id"], severity="ROUTINE", arrhythmia_type="PAUSE")
        acknowledge_alert(ctx["alert"]["id"], tech_id)
        acknowledge_alert(a2["id"], tech_id)
        return ctx, a3

    def test_third_acknowledge_updates_assignment_and_load(self, api):
        """PRD §3.5: "On success the alert moves from `NEW` to `ACKNOWLEDGED`
        with `assigned_technician_id` set to the caller and `acknowledged_at`
        stamped; the cascade then runs two links into the technician record —
        `open_alert_load` increments by one, `alerts_acknowledged_total`
        increments by one (a lifetime counter that is never decremented), and
        the fatigue figures are recomputed as described below, which may flip
        `fatigue_status` from `NORMAL` to `AT_RISK` or `FATIGUED`."

        Design: Difficulty/transitive_cascade/acknowledge_fatigue_cascade
        """
        ctx, a3 = self._setup_two_acked()
        tech_id = ctx["technician"]["id"]
        acked = acknowledge_alert(a3["id"], tech_id)
        assert acked["status"] == "ACKNOWLEDGED"
        assert acked["assigned_technician_id"] == tech_id
        assert read_technician(tech_id)["open_alert_load"] == 3

    def test_third_acknowledge_flips_fatigue_at_risk_boundary(self, api):
        """PRD §3.5: "The load ratio `fatigue_index` is the technician's
        `open_alert_load` divided by `shift_capacity`, rounded half up to two
        decimal places; a value of 0.80 or higher marks the technician
        `FATIGUED`, a value of 0.60 or higher but below 0.80 marks `AT_RISK`,
        and anything lower is `NORMAL`."

        Design: Difficulty/transitive_cascade/acknowledge_fatigue_cascade
        """
        ctx, a3 = self._setup_two_acked()
        tech_id = ctx["technician"]["id"]
        tech_before = read_technician(tech_id)
        assert tech_before["fatigue_index"] == pytest.approx(0.40, abs=0.001)
        assert tech_before["fatigue_status"] == "NORMAL"

        acknowledge_alert(a3["id"], tech_id)
        tech = read_technician(tech_id)
        assert tech["open_alert_load"] == 3
        assert tech["fatigue_index"] == pytest.approx(0.60, abs=0.001)
        assert tech["fatigue_status"] == "AT_RISK", "0.60 is inclusive AT_RISK"


class TestNotificationSlaBusinessHours:
    def test_urgent_out_of_hours_deadline_uses_business_hours_variant(self, api):
        """PRD §3.5: "An `URGENT` alert detected within business hours carries
        a deadline sixty minutes after detection; detected outside business
        hours, its deadline is thirty minutes past the next 08:00 UTC."
        PRD §3.5: "The notification SLA is pinned to the BUSINESS_HOURS
        variant."

        Design: Difficulty/dual_variant_calc/business_hours_vs_wall_clock_sla
        """
        ctx = setup_monitoring_episode(prescribed_days=30)
        set_clock("2026-05-01T21:30:00Z")
        alert = raise_alert(ctx["episode_id"], severity="URGENT", arrhythmia_type="AFIB")
        assert_iso_prefix(alert["detected_at"], "2026-05-01T21:30:00", "detected_at")
        assert_iso_prefix(alert["sla_deadline"], "2026-05-02T08:30:00", "sla_deadline")

    def test_urgent_out_of_hours_deadline_is_not_wall_clock(self, api):
        """PRD §3.5: "A wall-clock reading of the same rule — deadline equals
        `detected_at` plus the base minutes regardless of hour — is a
        documented alternative interpretation only and is never what gets
        stored."
        PRD §3.5: "Business hours run from 08:00 UTC up to but not including
        20:00 UTC, every day of the week."

        Design: Difficulty/dual_variant_calc/business_hours_vs_wall_clock_sla
        """
        ctx = setup_monitoring_episode(prescribed_days=30)
        set_clock("2026-05-01T21:30:00Z")
        alert = raise_alert(ctx["episode_id"], severity="URGENT", arrhythmia_type="AFIB")
        assert not alert["sla_deadline"].startswith("2026-05-01T22:30:00"), (
            "WALL_CLOCK variant (detected_at + 60min) must not be stored"
        )
        assert_iso_prefix(alert["sla_deadline"], "2026-05-02T08:30:00", "sla_deadline")


class TestNotificationSlaPiecewise:
    def _raise_three(self):
        ctx = setup_monitoring_episode(prescribed_days=30)
        set_clock("2026-05-01T21:30:00Z")
        crit = raise_alert(ctx["episode_id"], severity="CRITICAL", arrhythmia_type="VTACH")
        set_clock("2026-05-02T10:00:00Z")
        urg = raise_alert(ctx["episode_id"], severity="URGENT", arrhythmia_type="AFIB")
        set_clock("2026-05-03T07:30:00Z")
        rout = raise_alert(ctx["episode_id"], severity="ROUTINE", arrhythmia_type="PAUSE")
        return crit, urg, rout

    def test_critical_and_urgent_branches(self, api):
        """PRD §3.5: "A `CRITICAL` alert's deadline is always fifteen minutes
        after `detected_at`, regardless of the hour."
        PRD §3.5: "An `URGENT` alert detected within business hours carries a
        deadline sixty minutes after detection; detected outside business
        hours, its deadline is thirty minutes past the next 08:00 UTC."

        Design: Difficulty/combinatorial_formula/notification_sla_piecewise_multi_input
        """
        crit, urg, _ = self._raise_three()
        assert_iso_prefix(crit["sla_deadline"], "2026-05-01T21:45:00", "critical sla_deadline")
        assert_iso_prefix(urg["sla_deadline"], "2026-05-02T11:00:00", "urgent sla_deadline")

    def test_routine_out_of_hours_branch(self, api):
        """PRD §3.5: "A `ROUTINE` alert detected within business hours carries
        1,440 minutes — a full day; detected outside business hours, its
        deadline is 120 minutes past the next 08:00 UTC."
        PRD §3.5: "A wall-clock reading of the same rule — deadline equals
        `detected_at` plus the base minutes regardless of hour — is a
        documented alternative interpretation only and is never what gets
        stored."

        Design: Difficulty/combinatorial_formula/notification_sla_piecewise_multi_input
        """
        _, _, rout = self._raise_three()
        assert_iso_prefix(rout["detected_at"], "2026-05-03T07:30:00", "detected_at")
        assert_iso_prefix(rout["sla_deadline"], "2026-05-03T10:00:00", "routine sla_deadline")
        assert not rout["sla_deadline"].startswith("2026-05-04T07:30:00"), (
            "WALL_CLOCK variant (detected_at + 1440min) must not be stored"
        )
