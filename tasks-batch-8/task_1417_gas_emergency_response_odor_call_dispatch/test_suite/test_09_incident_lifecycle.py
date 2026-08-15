"""Incident lifecycle cycles: close/reopen recurrence, merge lockdown,
duplicate escalation cascade, reclassification, and preemption
(PRD §3.2, §3.3, §3.4)."""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    ApiErrorId,
    setup_territory, setup_territory_technician, intake_call, triage, dispatch,
    arrive, set_clock, get_incident, get_technician, create_report, get_report,
    setup_closed_incident,
    TEST_USERS, make_technician_headers,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]
SUPERVISOR = TEST_USERS["supervisor_headers"]


class TestIncidentCloseReopenRecurrenceCycle:
    def _closed_incident_fixture(self):
        """P2 incident fully closed at 01:00 after a 20-minute response."""
        terr, tech = setup_territory_technician(
            shift_end="2026-08-02T00:00:00Z")
        call, incident, disp = setup_closed_incident(
            terr["id"], tech["id"], priority="P2", pct_lel=1.0,
            with_action=True, arrive_at="2026-08-01T00:20:00Z",
            close_at="2026-08-01T01:00:00Z",
            address_line="44 Cedar St", caller_name="Fred",
            caller_phone="555-0105")
        return terr, tech, call, disp

    def test_recurrence_call_reopens_closed_incident(self, api):
        """PRD §3.2: "**RECURRENCE** — the same normalized address matches an
        incident whose most recent closure falls within the territory's
        recurrence window... That incident transitions `CLOSED → REOPENED`:
        `reopen_count` and `linked_call_count` each increase by one, the
        closed segment's adjusted elapsed time is archived into
        `prior_segment_adjusted_seconds`, `response_clock_started_at` resets
        to the recurrence call's `received_at`, `first_arrival_at` returns to
        null, `pause_total_seconds` resets to zero, `breach_class` recomputes
        to `NONE`, `make_safe_completed` flips back to false, and
        `entry_status` returns to `NOT_REQUIRED`".

        Design: Difficulty/non_linear_state_machine/incident_close_reopen_recurrence_cycle
        """
        terr, tech, call, disp = self._closed_incident_fixture()
        inc_id = call["incident_id"]
        set_clock("2026-08-01T10:00:00Z")  # 9h after closure, inside 72h window

        call2 = intake_call(terr["id"], address_line="44 Cedar St",
                            caller_name="Fred", caller_phone="555-0105")
        assert call2["classification"] == "RECURRENCE"
        assert call2["incident_id"] == inc_id, "same incident, not a new one"

        incident = get_incident(inc_id)
        assert incident["lifecycle_status"] == "REOPENED"
        assert incident["reopen_count"] == 1
        assert incident["linked_call_count"] == 2

    def test_reopen_archives_prior_segment_and_resets_clock(self, api):
        """PRD §3.2 RECURRENCE: "the closed segment's adjusted elapsed time is
        archived into `prior_segment_adjusted_seconds`,
        `response_clock_started_at` resets to the recurrence call's
        `received_at`, `first_arrival_at` returns to null, `pause_total_seconds`
        resets to zero, `breach_class` recomputes to `NONE`,
        `make_safe_completed` flips back to false".

        Design: Difficulty/non_linear_state_machine/incident_close_reopen_recurrence_cycle
        """
        terr, tech, call, disp = self._closed_incident_fixture()
        inc_id = call["incident_id"]
        set_clock("2026-08-01T10:00:00Z")

        intake_call(terr["id"], address_line="44 Cedar St",
                    caller_name="Fred", caller_phone="555-0105")
        incident = get_incident(inc_id)
        assert incident["prior_segment_adjusted_seconds"] == 1200, (
            "00:00 -> 00:20 arrival, no pauses")
        assert incident["response_clock_started_at"].startswith(
            "2026-08-01T10:00:00")
        assert incident["first_arrival_at"] is None
        assert incident["pause_total_seconds"] == 0
        assert incident["breach_class"] == "NONE"
        assert incident["make_safe_completed"] is False
        assert incident["entry_status"] == "NOT_REQUIRED"


class TestMergedIncidentTerminalLockdown:
    def _fixture_closed_then_new_primary_after_window(self):
        """Incident S closed at 00:20; at 2026-08-04T01:00 (past the 72h
        recurrence window) a same-address call spawns fresh PRIMARY incident
        T, triaged P2."""
        terr, tech = setup_territory_technician(
            shift_end="2026-08-05T00:00:00Z")
        call_s, incident_s, disp_s = setup_closed_incident(
            terr["id"], tech["id"], priority="P2", pct_lel=0.5,
            arrive_at="2026-08-01T00:20:00Z",
            address_line="13 Merge Ave", caller_name="M",
            caller_phone="555-0211")
        set_clock("2026-08-04T01:00:00Z")
        call_t = intake_call(terr["id"], address_line="13 Merge Ave",
                             caller_name="N", caller_phone="555-0212")
        triage(call_t["incident_id"], "P2")
        return terr, tech, call_s, call_t

    def test_call_after_recurrence_window_creates_new_primary(self, api):
        """PRD §3.2: "A call landing exactly at the window's end instant does
        not reopen — it spawns a brand-new `PRIMARY` incident instead." The
        recurrence window is "the half-open interval from `closed_at`
        inclusive to `closed_at` plus `recurrence_window_hours` exclusive" —
        a call beyond that interval is PRIMARY a fortiori.

        Design: Corner/state_machines/merged_incident_terminal_lockdown
        """
        terr, tech, call_s, call_t = \
            self._fixture_closed_then_new_primary_after_window()
        assert call_t["classification"] == "PRIMARY"
        assert call_t["incident_id"] != call_s["incident_id"]

    def test_closed_source_rejected_for_merge_and_triage(self, api):
        """PRD §3.3: "The source must be in `NEW`, `TRIAGED`, or `DISPATCHED`
        lifecycle status; any other source state is rejected with
        `ERR_INVALID_STATE` (HTTP 409)." and "Triage is legal only while the
        incident's `lifecycle_status` is `NEW` or `REOPENED` — otherwise the
        request fails with `ERR_INCIDENT_NOT_ACTIVE` (HTTP 409)".

        Design: Corner/state_machines/merged_incident_terminal_lockdown
        """
        terr, tech, call_s, call_t = \
            self._fixture_closed_then_new_primary_after_window()
        before = get_incident(call_s["incident_id"])

        resp = api_client.merge_incident(
            call_t["incident_id"], {"source_incident_id": call_s["incident_id"]},
            SUPERVISOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        after = get_incident(call_s["incident_id"])
        assert after["lifecycle_status"] == "CLOSED"
        assert after["version"] == before["version"], "failed merge must not mutate"

        resp = api_client.triage_incident(call_s["incident_id"],
                                          {"priority": "P1"}, DISPATCHER)
        validate_error(resp, ApiErrorId.ERR_INCIDENT_NOT_ACTIVE)


class TestMergeWithDifferentAddress:
    def test_merge_with_different_address_rejected(self, api):
        """PRD §3.3: "The target must exist, must not be `MERGED` or `CLOSED`,
        must be a different incident than the source, and must share the
        source's `normalized_address`; any violation is rejected with
        `ERR_MERGE_TARGET_INVALID` (HTTP 409)."

        Design: Corner/validations/merge_with_different_address_rejected
        """
        terr = setup_territory()
        call_a = intake_call(terr["id"], address_line="1 Diff St",
                             caller_name="Z1", caller_phone="555-0225",
                             location_context="OUTSIDE_STRUCTURE")
        triage(call_a["incident_id"], "P3")
        call_b = intake_call(terr["id"], address_line="2 Diff St",
                             caller_name="Z2", caller_phone="555-0226",
                             location_context="OUTSIDE_STRUCTURE")
        triage(call_b["incident_id"], "P3")

        resp = api_client.merge_incident(
            call_b["incident_id"], {"source_incident_id": call_a["incident_id"]},
            SUPERVISOR)
        validate_error(resp, ApiErrorId.ERR_MERGE_TARGET_INVALID)

        assert get_incident(call_a["incident_id"])["lifecycle_status"] == "TRIAGED"
        assert get_incident(call_b["incident_id"])["lifecycle_status"] == "TRIAGED"


class TestDuplicateCallPriorityEscalationCascade:
    def _fixture_p3_incident_with_draft_report(self):
        """P3 incident (odor outside, no symptoms) triaged, never dispatched;
        DRAFT report covering the period generated at 03:00; clock at 03:20
        (200 minutes elapsed)."""
        terr = setup_territory()
        call = intake_call(terr["id"], address_line="77 Maple Dr",
                           caller_name="Hank", caller_phone="555-0107",
                           location_context="OUTSIDE_STRUCTURE")
        inc_id = call["incident_id"]
        triage(inc_id, "P3")
        set_clock("2026-08-01T03:00:00Z")
        report = create_report(terr["id"])
        set_clock("2026-08-01T03:20:00Z")
        return terr, call, report

    def test_duplicate_call_escalates_incident_to_p1(self, api):
        """PRD §3.2 DUPLICATE: "The call is linked to that incident,
        `is_duplicate` is true, and the incident's `linked_call_count`
        increases by one. If the new call's `implied_priority` is strictly
        higher than the incident's current priority, the incident
        auto-escalates: its `priority` is raised — automatic escalation never
        lowers priority — its `threshold_minutes` recomputed, its
        `breach_class` re-evaluated".

        Design: Difficulty/transitive_cascade/duplicate_call_priority_escalation_cascade
        """
        terr, call, report = self._fixture_p3_incident_with_draft_report()
        inc_id = call["incident_id"]

        call2 = intake_call(terr["id"], address_line="77 Maple Dr",
                            caller_name="Ivy", caller_phone="555-0108",
                            location_context="INSIDE_STRUCTURE",
                            odor_reported=True, symptoms_reported=True)
        assert call2["classification"] == "DUPLICATE"
        assert call2["is_duplicate"] is True
        assert call2["incident_id"] == inc_id

        incident = get_incident(inc_id)
        assert incident["linked_call_count"] == 2
        assert incident["priority"] == "P1"
        assert incident["threshold_minutes"] == 30
        # 200 minutes elapsed vs 30-minute P1 threshold, no arrival.
        assert incident["breach_class"] == "NO_RESPONSE"

    def test_escalation_fires_auto_priority_notification_and_stales_report(self, api):
        """PRD §3.2 DUPLICATE: "reaching `P1` through escalation fires the
        same automatic notification rule. Any covering draft or rejected
        regulatory report is marked stale." §3.8: "The `AUTO_PRIORITY` rule
        fires whenever an incident's priority reaches `P1` ... it creates a
        draft notification on the `PUBLIC_ALERT` channel and sets the flag."

        Design: Difficulty/transitive_cascade/duplicate_call_priority_escalation_cascade
        """
        terr, call, report = self._fixture_p3_incident_with_draft_report()
        inc_id = call["incident_id"]

        intake_call(terr["id"], address_line="77 Maple Dr",
                    caller_name="Ivy", caller_phone="555-0108",
                    location_context="INSIDE_STRUCTURE",
                    odor_reported=True, symptoms_reported=True)

        data, meta = validate_paginated(api_client.list_notifications(
            inc_id, SUPERVISOR))
        assert meta["total_count"] == 1
        assert data[0]["origin"] == "AUTO_PRIORITY"
        assert data[0]["channel"] == "PUBLIC_ALERT"
        assert data[0]["status"] == "DRAFT"

        stale = get_report(report["id"])
        assert stale["needs_regeneration"] is True
        assert stale["status"] == "DRAFT"


class TestReclassificationBreachReportEvaluationOrder:
    def _fixture_p3_incident_with_report(self):
        """P3 incident created 00:00, triaged P3, never dispatched; DRAFT
        report generated at 03:00; clock at 03:20 (adjusted = 12000s)."""
        terr = setup_territory()
        call = intake_call(terr["id"], address_line="30 Birch Ln",
                           caller_name="Eve", caller_phone="555-0104",
                           location_context="OUTSIDE_STRUCTURE")
        inc_id = call["incident_id"]
        triage(inc_id, "P3")
        set_clock("2026-08-01T03:00:00Z")
        report = create_report(terr["id"])
        set_clock("2026-08-01T03:20:00Z")
        return terr, call, report

    def test_reclassify_recomputes_threshold_and_breach(self, api):
        """PRD §3.3: "A successful reclassification sets the `priority`,
        recomputes `threshold_minutes` from the territory's table for the new
        priority, re-evaluates `breach_class`". §2.7: "The `breach_class`
        field reports `NONE` when there is no breach, `RESPONDED_LATE` when
        the incident is in breach and a first arrival has been recorded, and
        `NO_RESPONSE` when the incident is in breach with no arrival yet."

        Design: Difficulty/combinatorial_formula/reclassification_breach_report_evaluation_order
        """
        terr, call, report = self._fixture_p3_incident_with_report()
        inc_id = call["incident_id"]
        current = get_incident(inc_id)
        assert current["adjusted_elapsed_seconds"] == 12000
        assert current["breach_class"] == "NONE"  # 12000 <= 240*60 at P3

        resp = api_client.reclassify_incident(
            inc_id,
            {"new_priority": "P1",
             "expected_incident_version": current["version"],
             "reason": "escalating caller volume"},
            SUPERVISOR)
        updated = validate_success(resp)
        assert updated["priority"] == "P1"
        assert updated["threshold_minutes"] == 30

        incident = get_incident(inc_id)
        assert incident["adjusted_elapsed_seconds"] == 12000
        assert incident["breach_class"] == "NO_RESPONSE"  # 12000 > 30*60, no arrival

    def test_reclassify_marks_covering_draft_report_stale(self, api):
        """PRD §3.3: a successful reclassification "marks covering draft or
        rejected reports stale". §3.8: "Whenever a covered incident changes —
        triage, reclassification, ... — every covering report still in `DRAFT`
        or `REJECTED` has its `needs_regeneration` flag set to true."

        Design: Difficulty/combinatorial_formula/reclassification_breach_report_evaluation_order
        """
        terr, call, report = self._fixture_p3_incident_with_report()
        inc_id = call["incident_id"]
        # At generation (03:00) the incident was pending: 180min < 240min.
        assert report["pending_count"] == 1
        assert report["determined_count"] == 0

        current = get_incident(inc_id)
        validate_success(api_client.reclassify_incident(
            inc_id,
            {"new_priority": "P1",
             "expected_incident_version": current["version"],
             "reason": "escalating caller volume"},
            SUPERVISOR))

        stale = get_report(report["id"])
        assert stale["needs_regeneration"] is True
        assert stale["status"] == "DRAFT", "snapshot itself unchanged until regenerate"
        assert stale["pending_count"] == 1, "frozen snapshot keeps old counts"


class TestPreemptConservesActiveAssignmentCount:
    def _fixture_preemption(self):
        """TECH1 EN_ROUTE on P2 incident A; P1 incident B TRIAGED with no
        assignment."""
        terr, tech = setup_territory_technician()
        call_a = intake_call(terr["id"], address_line="3 Z St",
                             caller_name="Vic", caller_phone="555-0121")
        triage(call_a["incident_id"], "P2")
        disp_a = dispatch(call_a["incident_id"], tech["id"])
        call_b = intake_call(terr["id"], address_line="4 W St",
                             caller_name="Wen", caller_phone="555-0122",
                             occupancy_type="SCHOOL", symptoms_reported=True,
                             hissing_reported=True)
        triage(call_b["incident_id"], "P1")
        return terr, tech, call_a, disp_a, call_b

    def test_preempt_repoints_technician_net_count_unchanged(self, api):
        """PRD §3.4: "Preemption is an atomic re-pointing: the old assignment
        becomes `PREEMPTED` and the technician's count decrements, while a
        brand-new assignment is auto-created on the target for the same
        technician, starting `EN_ROUTE` with `dispatched_at` stamped now and
        the count incrementing back — the technician's
        `active_assignment_count` is net unchanged. The response body carries
        this newly created assignment."

        Design: Difficulty/compensating_invariant/preempt_conserves_technician_active_assignment_count
        """
        terr, tech, call_a, disp_a, call_b = self._fixture_preemption()
        assert get_technician(tech["id"])["active_assignment_count"] == 1

        resp = api_client.preempt_dispatch(
            disp_a["id"],
            {"target_incident_id": call_b["incident_id"],
             "reason": "P1 school incident takes precedence"},
            SUPERVISOR)
        new_disp = validate_success(resp)
        assert new_disp["incident_id"] == call_b["incident_id"]
        assert new_disp["technician_id"] == tech["id"]
        assert new_disp["status"] == "EN_ROUTE"

        t = get_technician(tech["id"])
        assert t["active_assignment_count"] == 1, "invariant: -1 + 1 net zero"
        assert t["weighted_load"] == 4, "the single active assignment is P1-weighted"

        old = validate_success(api_client.get_dispatch(disp_a["id"], SUPERVISOR))
        assert old["status"] == "PREEMPTED"

    def test_preempt_cascades_source_awaiting_dispatch_and_target_dispatched(self, api):
        """PRD §3.4: "If the source incident is left with no active
        assignment, its `awaiting_dispatch` flag sets to true; if the target
        was `TRIAGED`, it automatically advances to `DISPATCHED`."

        Design: Difficulty/compensating_invariant/preempt_conserves_technician_active_assignment_count
        """
        terr, tech, call_a, disp_a, call_b = self._fixture_preemption()
        validate_success(api_client.preempt_dispatch(
            disp_a["id"],
            {"target_incident_id": call_b["incident_id"],
             "reason": "P1 school incident takes precedence"},
            SUPERVISOR))

        source = get_incident(call_a["incident_id"])
        assert source["awaiting_dispatch"] is True
        assert source["lifecycle_status"] == "DISPATCHED"

        target = get_incident(call_b["incident_id"])
        assert target["lifecycle_status"] == "DISPATCHED"
        assert target["awaiting_dispatch"] is False
