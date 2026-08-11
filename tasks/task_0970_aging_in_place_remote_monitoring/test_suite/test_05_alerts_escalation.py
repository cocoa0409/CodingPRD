"""Alert lifecycle: raise-time notification, escalation timeouts, acknowledgement,
reopen cycles, false-alarm safety, listing filters, and the open-alert invariant."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    fixtures,
    get_success_data,
    make_caregiver_headers,
    make_senior_headers,
    raise_manual_alert,
    set_clock,
    setup_active_senior,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
AGENT = TEST_USERS["monitoring_agent_headers"]
HUB = TEST_USERS["device_hub_headers"]


def _active_senior_with_contact(timeout=3600, min_severity="LOW"):
    ctx = setup_active_senior()
    caregiver, entry = fixtures.add_caregiver_with_contact(
        ctx["senior"]["id"],
        priority_rank=1,
        min_severity=min_severity,
        response_timeout_seconds=timeout,
    )
    ctx["caregiver"] = caregiver
    ctx["entry"] = entry
    return ctx


class TestManualRaiseNotification:
    def test_manual_alert_raise_immediately_notifies(self, api):
        """PRD 3.5: "Every newly opened alert increments the senior's
        `open_alert_count` by one and immediately attempts its first
        notification: the eligible contacts are the senior's `ACTIVE` tree
        entries whose `min_severity` is at or below the alert's severity on the
        `LOW` < `MEDIUM` < `HIGH` < `CRITICAL` scale, ranked by `priority_rank`
        ascending with ties broken by `created_at` ascending."
        PRD 3.5: "When at least one eligible contact exists, the alert moves
        `RAISED` → `NOTIFYING`, an `AlertNotification` is created for the
        first-ranked contact at `level` 1 in `SENT` status with `sent_at`
        stamped from the logical clock, and the alert's `escalation_level`
        becomes 1. When no eligible contact exists, the alert simply stays
        `RAISED` in the monitoring-center queue."

        Design: Corner/endpoints/manual_alert_raise_immediately_notifies
        """
        ctx = _active_senior_with_contact()
        alert = raise_manual_alert(
            ctx["senior"]["id"], "HIGH", note="smell of smoke"
        )
        assert alert["status"] == "NOTIFYING"
        assert alert["escalation_level"] == 1
        notifications = fixtures.list_notifications(alert_id=alert["id"])
        assert len(notifications) == 1
        assert notifications[0]["level"] == 1
        assert notifications[0]["status"] == "SENT"
        assert notifications[0]["caregiver_id"] == ctx["caregiver"]["id"]


class TestEscalation:
    def test_escalation_timeout_walks_contact_tree(self, api):
        """PRD 3.5: "When the latest `SENT` notification has been outstanding
        longer than its contact's `response_timeout_seconds` and a further
        eligible contact exists, the current notification becomes `TIMED_OUT`,
        a new `SENT` notification is created for the next-ranked contact at the
        next `level`, `escalation_level` increments, and the alert sits in
        `ESCALATED`."
        PRD 3.5: "This continues level by level until the final eligible
        contact times out with nobody left: that notification becomes
        `TIMED_OUT`, the alert's `escalation_exhausted` flag is set true, and
        the alert remains in `NOTIFYING` or `ESCALATED` awaiting human action."

        Design: Corner/state_machines/escalation_timeout_walks_contact_tree
        """
        ctx = setup_active_senior(
            plan_overrides={"tier": "PREMIUM", "checkin_interval_hours": 24}
        )
        senior_id = ctx["senior"]["id"]
        cg1 = fixtures.add_caregiver(senior_id, full_name="Cg E1", phone="555-11")
        cg2 = fixtures.add_caregiver(senior_id, full_name="Cg E2", phone="555-12")
        cg3 = fixtures.add_caregiver(senior_id, full_name="Cg E3", phone="555-13")
        fixtures.add_contact_entry(senior_id, cg1["id"], 1, "LOW", 3600)
        fixtures.add_contact_entry(senior_id, cg2["id"], 2, "MEDIUM", 3600)
        fixtures.add_contact_entry(senior_id, cg3["id"], 3, "HIGH", 3600)

        alert = raise_manual_alert(senior_id, "MEDIUM")
        assert alert["status"] == "NOTIFYING"
        assert alert["escalation_level"] == 1

        # 61 minutes past level-1 timeout -> escalate to level 2.
        set_clock("2026-05-01T10:31:00Z")
        alert_now = get_success_data(api.get_alert(alert["id"], ADMIN))
        assert alert_now["status"] == "ESCALATED"
        assert alert_now["escalation_level"] == 2

        notifications = fixtures.list_notifications(alert_id=alert["id"])
        assert len(notifications) == 2, (
            "the min_severity HIGH entry must stay out of a MEDIUM alert's fan-out"
        )
        by_level = {n["level"]: n for n in notifications}
        assert by_level[1]["status"] == "TIMED_OUT"
        assert by_level[1]["caregiver_id"] == cg1["id"]
        assert by_level[2]["status"] == "SENT"
        assert by_level[2]["caregiver_id"] == cg2["id"]
        assert all(n["caregiver_id"] != cg3["id"] for n in notifications)

        # 61 minutes past level-2 timeout with nobody left -> exhaustion.
        set_clock("2026-05-01T11:32:00Z")
        alert_final = get_success_data(api.get_alert(alert["id"], ADMIN))
        assert alert_final["escalation_exhausted"] is True
        notifications = fixtures.list_notifications(alert_id=alert["id"])
        by_level = {n["level"]: n for n in notifications}
        assert by_level[2]["status"] == "TIMED_OUT"
        assert len(notifications) == 2

    def test_escalation_selector_empty_eligible_set_stays_raised(self, api):
        """PRD 3.5: "When at least one eligible contact exists, the alert moves
        `RAISED` → `NOTIFYING`, an `AlertNotification` is created for the
        first-ranked contact at `level` 1 in `SENT` status with `sent_at`
        stamped from the logical clock, and the alert's `escalation_level`
        becomes 1. When no eligible contact exists, the alert simply stays
        `RAISED` in the monitoring-center queue."
        PRD 2.6: "A second derived field, `open_alert_count`, tallies the
        senior's alerts currently in `RAISED`, `NOTIFYING`, `ESCALATED`, or
        `ACKNOWLEDGED` status; it increments when such an alert opens and
        decrements when one resolves or is marked a false alarm."

        Design: Corner/calculations/escalation_selector_empty_eligible_set_stays_raised
        """
        ctx = _active_senior_with_contact(min_severity="HIGH")
        alert = raise_manual_alert(ctx["senior"]["id"], "MEDIUM")
        assert alert["status"] == "RAISED", (
            "a MEDIUM alert with only a HIGH-min_severity contact must stay RAISED"
        )
        notifications = fixtures.list_notifications(alert_id=alert["id"])
        assert notifications == []
        senior = fixtures.get_senior(ctx["senior"]["id"])
        assert senior["open_alert_count"] == 1, "RAISED counts as open"


class TestAlertActionGates:
    def test_alert_resolve_from_notifying_returns_not_actionable(self, api):
        """PRD 3.5: "Both actions require `ACKNOWLEDGED` status, enforced by
        `ERR_ALERT_NOT_ACTIONABLE`."
        PRD 2.6: "A second derived field, `open_alert_count`, tallies the
        senior's alerts currently in `RAISED`, `NOTIFYING`, `ESCALATED`, or
        `ACKNOWLEDGED` status; it increments when such an alert opens and
        decrements when one resolves or is marked a false alarm."

        Design: Corner/state_machines/alert_resolve_from_notifying_returns_not_actionable
        """
        ctx = _active_senior_with_contact()
        alert = raise_manual_alert(ctx["senior"]["id"], "MEDIUM")
        assert alert["status"] == "NOTIFYING"
        resp = api.resolve_alert(
            alert["id"], {}, make_caregiver_headers(ctx["caregiver"]["id"])
        )
        validate_error(resp, ApiErrorId.ERR_ALERT_NOT_ACTIONABLE)
        alert_after = get_success_data(api.get_alert(alert["id"], ADMIN))
        assert alert_after["status"] == "NOTIFYING"
        senior = fixtures.get_senior(ctx["senior"]["id"])
        assert senior["open_alert_count"] == 1

    def test_senior_cannot_acknowledge_alert_forbidden_role(self, api):
        """PRD 2.1: "Once authenticated, the caller's role must appear in the
        endpoint's authorized role list; otherwise the request is rejected with
        `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD 4: the acknowledge endpoint authorizes Caregiver and
        MonitoringAgent only.

        Design: Corner/rbac/senior_cannot_acknowledge_alert_forbidden_role
        """
        ctx = _active_senior_with_contact(timeout=7200)
        alert = raise_manual_alert(ctx["senior"]["id"], "MEDIUM")
        resp = api.acknowledge_alert(
            alert["id"], make_senior_headers(ctx["senior"]["id"])
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
        alert_after = get_success_data(api.get_alert(alert["id"], ADMIN))
        assert alert_after["status"] == "NOTIFYING"

    def test_caregiver_cannot_ack_other_seniors_alert(self, api):
        """PRD 3.5: "A `Caregiver` may acknowledge only after passing, in order,
        the ownership check (the caregiver must serve the alert's senior, else
        `ERR_OWNERSHIP_MISMATCH`), the state check, and the notification check:
        a notification for this alert addressed to that caregiver must exist in
        `SENT` status, else `ERR_NOT_NOTIFIED_CONTACT`."

        Design: Corner/validations/caregiver_cannot_ack_other_seniors_alert
        """
        ctx1, ctx2 = fixtures.setup_two_active_seniors_one_installer()
        cg1 = fixtures.add_caregiver(ctx1["senior"]["id"], full_name="Cg O1")
        cg2, _entry2 = fixtures.add_caregiver_with_contact(
            ctx2["senior"]["id"], priority_rank=1, min_severity="LOW",
            response_timeout_seconds=7200,
        )
        alert = raise_manual_alert(ctx2["senior"]["id"], "MEDIUM")
        assert alert["status"] == "NOTIFYING"
        resp = api.acknowledge_alert(alert["id"], make_caregiver_headers(cg1["id"]))
        validate_error(resp, ApiErrorId.ERR_OWNERSHIP_MISMATCH)
        alert_after = get_success_data(api.get_alert(alert["id"], ADMIN))
        assert alert_after["status"] == "NOTIFYING"


class TestAcknowledgeConsistency:
    def test_acknowledge_mutation_visible_immediately(self, api):
        """PRD 3.5: "A caregiver acknowledgement marks that caregiver's
        notification `ACKED`, supersedes any other `SENT` notifications, and
        records `acknowledged_by_caregiver_id`."
        PRD 3.5: "Acknowledgement moves an alert from `RAISED`, `NOTIFYING`, or
        `ESCALATED` to `ACKNOWLEDGED`; any other starting state is rejected
        with `ERR_ALERT_NOT_ACTIONABLE`."

        Design: Corner/consistency_model/acknowledge_mutation_visible_immediately
        """
        ctx = _active_senior_with_contact(timeout=7200)
        alert = raise_manual_alert(ctx["senior"]["id"], "MEDIUM")
        acked = get_success_data(
            api.acknowledge_alert(
                alert["id"], make_caregiver_headers(ctx["caregiver"]["id"])
            )
        )
        assert acked["status"] == "ACKNOWLEDGED"
        assert acked["acknowledged_by_caregiver_id"] == ctx["caregiver"]["id"]

        fetched = get_success_data(api.get_alert(alert["id"], ADMIN))
        assert fetched["status"] == "ACKNOWLEDGED", (
            "a subsequent GET must reflect the acknowledged state immediately"
        )
        notifications = fixtures.list_notifications(alert_id=alert["id"])
        assert len(notifications) == 1
        assert notifications[0]["status"] == "ACKED"


class TestReopenCycle:
    """Alert's machine is cyclic: RESOLVED -> NOTIFYING via reopen (PRD 3.5)."""

    def _raise_and_resolve(self):
        ctx = _active_senior_with_contact(timeout=3600)
        alert = raise_manual_alert(
            ctx["senior"]["id"], "MEDIUM", note="welfare concern"
        )
        assert alert["status"] == "NOTIFYING"
        fixtures.caregiver_acknowledge(alert["id"], ctx["caregiver"]["id"])
        fixtures.caregiver_resolve(
            alert["id"], ctx["caregiver"]["id"], note="visited, all fine"
        )
        return ctx, alert

    def test_alert_reopen_reenters_notifying_with_fresh_notification(self, api):
        """PRD 3.5: "a `MonitoringAgent` may reopen an alert in `RESOLVED` or
        `FALSE_ALARM` (anything else yields `ERR_ALERT_NOT_ACTIONABLE`), which
        increments `reopen_count`, re-increments `open_alert_count`, and starts
        a fresh notification round — a new level-1 `SENT` notification and
        `escalation_level` reset to 1 when an eligible contact exists, or a
        quiet return to `RAISED` when none does."

        Design: Difficulty/non_linear_state_machine/alert_reopen_cycle_reenters_notifying
        """
        ctx, alert = self._raise_and_resolve()
        senior_mid = fixtures.get_senior(ctx["senior"]["id"])
        assert senior_mid["open_alert_count"] == 0

        reopened = get_success_data(api.reopen_alert(alert["id"], AGENT))
        assert reopened["status"] == "NOTIFYING", (
            "reopen must re-enter NOTIFYING when an eligible contact exists"
        )
        assert reopened["reopen_count"] == 1
        sent = fixtures.list_notifications(alert_id=alert["id"], status="SENT")
        assert len(sent) == 1
        assert sent[0]["level"] == 1, "reopen starts a fresh round at level 1"

    def test_alert_reopen_restores_open_alert_count(self, api):
        """PRD 3.5: "a `MonitoringAgent` may reopen an alert in `RESOLVED` or
        `FALSE_ALARM` (anything else yields `ERR_ALERT_NOT_ACTIONABLE`), which
        increments `reopen_count`, re-increments `open_alert_count`, and starts
        a fresh notification round — a new level-1 `SENT` notification and
        `escalation_level` reset to 1 when an eligible contact exists, or a
        quiet return to `RAISED` when none does."
        PRD 2.6: "A second derived field, `open_alert_count`, tallies the
        senior's alerts currently in `RAISED`, `NOTIFYING`, `ESCALATED`, or
        `ACKNOWLEDGED` status; it increments when such an alert opens and
        decrements when one resolves or is marked a false alarm."

        Design: Difficulty/non_linear_state_machine/alert_reopen_cycle_reenters_notifying
        """
        ctx, alert = self._raise_and_resolve()
        assert fixtures.get_senior(ctx["senior"]["id"])["open_alert_count"] == 0
        get_success_data(api.reopen_alert(alert["id"], AGENT))
        senior = fixtures.get_senior(ctx["senior"]["id"])
        assert senior["open_alert_count"] == 1, (
            "reopen must re-increment open_alert_count"
        )


class TestFalseAlarmSafety:
    def test_false_alarm_on_critical_alert_requires_agent(self, api):
        """PRD 3.5: "Marking it a false alarm does the same bookkeeping but
        carries one extra safeguard: for a `CRITICAL` alert the caller must be
        a `MonitoringAgent`, or the request fails with
        `ERR_SAFETY_AGENT_REQUIRED`."
        PRD 3.4: "A `FALL_DETECTED` event raises a `CRITICAL` `FALL` alert
        immediately, and because falls are `CRITICAL` they are created even
        when the senior's posture would suppress lesser alerts."

        Design: Corner/rbac/false_alarm_on_critical_alert_requires_agent
        """
        ctx = _active_senior_with_contact(timeout=7200)
        wearable = ctx["devices"]["wearable"]
        fixtures.ingest_event(
            wearable["id"], "FALL_DETECTED", "2026-05-01T09:30:00Z"
        )
        falls = fixtures.list_alerts(
            senior_id=ctx["senior"]["id"], alert_type="FALL"
        )
        assert len(falls) == 1
        alert = falls[0]
        assert alert["severity"] == "CRITICAL"
        assert alert["status"] == "NOTIFYING"

        fixtures.caregiver_acknowledge(alert["id"], ctx["caregiver"]["id"])

        resp = api.mark_false_alarm(
            alert["id"],
            {"note": "probably fine"},
            make_caregiver_headers(ctx["caregiver"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SAFETY_AGENT_REQUIRED)

        resolved = get_success_data(
            api.mark_false_alarm(
                alert["id"], {"note": "confirmed sensor test"}, AGENT
            )
        )
        assert resolved["status"] == "FALSE_ALARM"
        senior = fixtures.get_senior(ctx["senior"]["id"])
        assert senior["open_alert_count"] == 0


class TestAlertListing:
    def test_alerts_list_filtered_by_status_returns_subset(self, api):
        """PRD 4: "| GET | `/v1/alerts` | List alerts, filterable by
        `senior_id` / `status` / `alert_type` / `device_id` | PlatformAdmin,
        MonitoringAgent, Caregiver |"
        PRD 2.3: "Unless otherwise specified, every list endpoint returns
        resources sorted by `created_at` in ascending order."

        Design: Corner/endpoints/alerts_list_filtered_by_status_returns_subset
        """
        ctx = _active_senior_with_contact(timeout=7200)
        senior_id = ctx["senior"]["id"]
        first = raise_manual_alert(senior_id, "LOW")
        fixtures.caregiver_acknowledge(first["id"], ctx["caregiver"]["id"])
        fixtures.caregiver_resolve(first["id"], ctx["caregiver"]["id"])
        second = raise_manual_alert(senior_id, "HIGH")

        filtered = fixtures.list_alerts(senior_id=senior_id, status="RESOLVED")
        assert len(filtered) == 1
        assert filtered[0]["id"] == first["id"]

        unfiltered = fixtures.list_alerts(senior_id=senior_id)
        assert len(unfiltered) == 2
        assert [a["id"] for a in unfiltered] == [first["id"], second["id"]], (
            "unfiltered list must be ordered by created_at ascending"
        )


class TestOpenAlertCountInvariant:
    """open_alert_count is conserved across forward/compensating action pairs."""

    def _setup(self):
        return _active_senior_with_contact(timeout=3600)

    def test_open_alert_count_nets_zero_after_raise_resolve(self, api):
        """PRD 2.6: "A second derived field, `open_alert_count`, tallies the
        senior's alerts currently in `RAISED`, `NOTIFYING`, `ESCALATED`, or
        `ACKNOWLEDGED` status; it increments when such an alert opens and
        decrements when one resolves or is marked a false alarm."

        Design: Difficulty/compensating_invariant/inv_open_alert_count_raise_resolve_reopen_falsealarm
        """
        ctx = self._setup()
        senior_id = ctx["senior"]["id"]
        alert = raise_manual_alert(senior_id, "MEDIUM", note="manual")
        assert fixtures.get_senior(senior_id)["open_alert_count"] == 1
        fixtures.caregiver_acknowledge(alert["id"], ctx["caregiver"]["id"])
        assert fixtures.get_senior(senior_id)["open_alert_count"] == 1, (
            "ACKNOWLEDGED still counts as open"
        )
        fixtures.caregiver_resolve(alert["id"], ctx["caregiver"]["id"], note="handled")
        assert fixtures.get_senior(senior_id)["open_alert_count"] == 0, (
            "raise then resolve must net zero drift"
        )

    def test_open_alert_count_nets_zero_after_reopen_false_alarm(self, api):
        """PRD 2.6: "A second derived field, `open_alert_count`, tallies the
        senior's alerts currently in `RAISED`, `NOTIFYING`, `ESCALATED`, or
        `ACKNOWLEDGED` status; it increments when such an alert opens and
        decrements when one resolves or is marked a false alarm."
        PRD 3.5: "a `MonitoringAgent` may reopen an alert in `RESOLVED` or
        `FALSE_ALARM` (anything else yields `ERR_ALERT_NOT_ACTIONABLE`), which
        increments `reopen_count`, re-increments `open_alert_count`, and starts
        a fresh notification round — a new level-1 `SENT` notification and
        `escalation_level` reset to 1 when an eligible contact exists, or a
        quiet return to `RAISED` when none does."

        Design: Difficulty/compensating_invariant/inv_open_alert_count_raise_resolve_reopen_falsealarm
        """
        ctx = self._setup()
        senior_id = ctx["senior"]["id"]
        alert = raise_manual_alert(senior_id, "MEDIUM", note="manual")
        fixtures.caregiver_acknowledge(alert["id"], ctx["caregiver"]["id"])
        fixtures.caregiver_resolve(alert["id"], ctx["caregiver"]["id"], note="handled")
        assert fixtures.get_senior(senior_id)["open_alert_count"] == 0

        get_success_data(api.reopen_alert(alert["id"], AGENT))
        assert fixtures.get_senior(senior_id)["open_alert_count"] == 1
        fixtures.caregiver_acknowledge(alert["id"], ctx["caregiver"]["id"])
        final = get_success_data(
            api.mark_false_alarm(
                alert["id"],
                {"note": "sensor glitch"},
                make_caregiver_headers(ctx["caregiver"]["id"]),
            )
        )
        assert final["status"] == "FALSE_ALARM"
        assert fixtures.get_senior(senior_id)["open_alert_count"] == 0, (
            "reopen then false-alarm must also net zero drift"
        )
        assert final["reopen_count"] == 1
        all_alerts = fixtures.list_alerts(senior_id=senior_id)
        assert len(all_alerts) == 1
