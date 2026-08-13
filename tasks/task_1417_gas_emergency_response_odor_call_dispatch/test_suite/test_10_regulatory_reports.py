"""Regulatory reporting: snapshot input-set filtering, empty denominators,
the submit/reject/regenerate cycle, and derived-field staleness
(PRD §3.8)."""
from test_helpers import (
    api_client, validate_success, validate_error,
    ApiErrorId,
    setup_territory, setup_territory_technician, intake_call, triage,
    set_clock, create_report, get_report, setup_closed_incident,
    TEST_USERS,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]
SUPERVISOR = TEST_USERS["supervisor_headers"]
REGULATOR = TEST_USERS["regulator_headers"]


class TestReportSubmitRejectRegenerateLoop:
    def _fixture_report_with_one_compliant_incident(self):
        """One closed P2 incident (20-minute response, compliant) inside the
        period; DRAFT report for [2026-08-01, 2026-08-02)."""
        terr, tech = setup_territory_technician(
            shift_end="2026-08-02T00:00:00Z")
        call, incident, disp = setup_closed_incident(
            terr["id"], tech["id"], priority="P2", pct_lel=0.5,
            arrive_at="2026-08-01T00:20:00Z",
            address_line="1 Walnut St", caller_name="Gail",
            caller_phone="555-0106")
        report = create_report(terr["id"])
        return terr, tech, call, report

    def test_reject_then_regenerate_returns_to_draft(self, api):
        """PRD §3.8: "rejection likewise requires `SUBMITTED`, moves the
        report to `REJECTED`, and stores the supplied `reason` as the report's
        `reject_reason`. A `Supervisor` regenerates a report in `DRAFT` or
        `REJECTED` — any other state fails with `ERR_INVALID_STATE` — which
        recomputes every count and rate at the current logical time, re-stamps
        `generated_at`, clears `needs_regeneration` to false, increments
        `regeneration_count`, and returns a `REJECTED` report to `DRAFT`."

        Design: Difficulty/non_linear_state_machine/report_submit_reject_regenerate_loop
        """
        terr, tech, call, report = \
            self._fixture_report_with_one_compliant_incident()
        rep_id = report["id"]

        submitted = validate_success(api_client.submit_report(rep_id, SUPERVISOR))
        assert submitted["status"] == "SUBMITTED"
        assert submitted["submitted_at"] is not None

        rejected = validate_success(api_client.reject_report(
            rep_id, {"reason": "period boundary mismatch"}, REGULATOR))
        assert rejected["status"] == "REJECTED"
        assert rejected["reject_reason"] == "period boundary mismatch"

        regenerated = validate_success(api_client.regenerate_report(rep_id,
                                                                    SUPERVISOR))
        assert regenerated["status"] == "DRAFT"
        assert regenerated["regeneration_count"] == 1
        assert regenerated["needs_regeneration"] is False

    def test_resubmit_after_regenerate_then_accept(self, api):
        """PRD §3.8: "acceptance requires `SUBMITTED` (otherwise
        `ERR_INVALID_STATE`) and moves the report to `ACCEPTED`, terminal" and
        the snapshot figures: "`compliant_count_adjusted` counts determined
        incidents whose adjusted elapsed is at most the threshold in seconds"
        with `compliance_rate_adjusted` "divided by `determined_count`".

        Design: Difficulty/non_linear_state_machine/report_submit_reject_regenerate_loop
        """
        terr, tech, call, report = \
            self._fixture_report_with_one_compliant_incident()
        rep_id = report["id"]

        validate_success(api_client.submit_report(rep_id, SUPERVISOR))
        validate_success(api_client.reject_report(
            rep_id, {"reason": "period boundary mismatch"}, REGULATOR))
        validate_success(api_client.regenerate_report(rep_id, SUPERVISOR))
        resubmitted = validate_success(api_client.submit_report(rep_id,
                                                                SUPERVISOR))
        assert resubmitted["status"] == "SUBMITTED"

        accepted = validate_success(api_client.accept_report(rep_id, REGULATOR))
        assert accepted["status"] == "ACCEPTED"

        final = get_report(rep_id)
        assert final["incident_count"] == 1
        assert final["determined_count"] == 1
        assert final["compliant_count_adjusted"] == 1
        assert final["compliance_rate_adjusted"] == 1.0


class TestReportExcludesPendingAndMergedIncidents:
    def test_inflight_incident_counts_as_pending_not_determined(self, api):
        """PRD §3.8: "The candidate set is the territory's incidents whose
        `response_clock_started_at` falls inside the period, excluding
        `MERGED` incidents; the `incident_count` is the size of that set. An
        incident counts as determined when its outcome is known at generation
        time: either its `first_arrival_at` is set, or its adjusted elapsed
        already exceeds its threshold in seconds. The `determined_count`
        tallies determined incidents and the `pending_count` is the
        remainder."

        Design: Corner/calculations/report_excludes_pending_and_merged_incidents
        """
        terr, tech = setup_territory_technician()
        # Incident A: closed, compliant 20-minute response.
        call_a, incident_a, disp_a = setup_closed_incident(
            terr["id"], tech["id"], priority="P2", pct_lel=0.5,
            arrive_at="2026-08-01T00:20:00Z",
            address_line="23 Rep St", caller_name="U1", caller_phone="555-0219")
        # Incident B: P3 created at 01:00, triaged, still in-flight at 02:00
        # (elapsed 60 min <= 240-min threshold -> undetermined).
        set_clock("2026-08-01T01:00:00Z")
        call_b = intake_call(terr["id"], address_line="24 Rep St",
                             caller_name="U2", caller_phone="555-0220",
                             location_context="OUTSIDE_STRUCTURE")
        triage(call_b["incident_id"], "P3")
        set_clock("2026-08-01T02:00:00Z")

        report = create_report(terr["id"])
        assert report["incident_count"] == 2
        assert report["determined_count"] == 1
        assert report["pending_count"] == 1
        assert report["compliant_count_adjusted"] == 1
        assert report["compliance_rate_adjusted"] == 1.0


class TestReportEmptyDenominatorYieldsNullRate:
    def test_no_determined_incidents_yields_null_rates(self, api):
        """PRD §3.8: "The `compliance_rate_adjusted` and `compliance_rate_raw`
        are the corresponding counts divided by `determined_count`, each
        expressed to four decimal places rounded half up, and each null when
        `determined_count` is zero."

        Design: Corner/calculations/report_empty_denominator_yields_null_rate
        """
        terr = setup_territory()
        set_clock("2026-08-01T01:00:00Z")
        call = intake_call(terr["id"], address_line="25 Null St",
                           caller_name="V", caller_phone="555-0221",
                           location_context="PUBLIC_SPACE", odor_reported=False,
                           symptoms_reported=False, hissing_reported=False)
        triage(call["incident_id"], "P4")
        set_clock("2026-08-01T02:00:00Z")  # 60 min < 1440-min P4 threshold

        report = create_report(terr["id"])
        assert report["incident_count"] == 1
        assert report["determined_count"] == 0
        assert report["pending_count"] == 1
        assert report["compliance_rate_raw"] is None
        assert report["compliance_rate_adjusted"] is None


class TestDraftReportMarkedStaleOnNewIncident:
    def test_new_incident_in_period_marks_draft_report_stale(self, api):
        """PRD §3.8: "Whenever a covered incident changes — ... — or a new
        incident appears in the period, every covering report still in `DRAFT`
        or `REJECTED` has its `needs_regeneration` flag set to true."

        Design: Corner/cross_cutting_layers/draft_report_marked_stale_on_new_incident_in_period
        """
        terr = setup_territory()
        report = create_report(terr["id"])
        assert report["incident_count"] == 0
        assert report["determined_count"] == 0
        assert report["needs_regeneration"] is False

        intake_call(terr["id"], address_line="15 Stale St", caller_name="Z15",
                    caller_phone="555-0239", location_context="OUTSIDE_STRUCTURE")

        stale = get_report(report["id"])
        assert stale["needs_regeneration"] is True
        assert stale["incident_count"] == 0, "snapshot itself unchanged"

        regenerated = validate_success(api_client.regenerate_report(
            report["id"], SUPERVISOR))
        assert regenerated["needs_regeneration"] is False
        assert regenerated["regeneration_count"] == 1
        assert regenerated["incident_count"] == 1


class TestSubmitFrozenReportNotMarkedStale:
    def test_submitted_report_ignores_later_incidents(self, api):
        """PRD §3.8: "Reports in `SUBMITTED` or `ACCEPTED` are frozen and
        never acquire the flag." and "Successful submission stamps
        `submitted_at` and freezes the snapshot."

        Design: Corner/cross_cutting_layers/submit_frozen_report_not_marked_stale
        """
        terr = setup_territory()
        report = create_report(terr["id"])
        submitted = validate_success(api_client.submit_report(report["id"],
                                                              SUPERVISOR))
        assert submitted["status"] == "SUBMITTED"

        intake_call(terr["id"], address_line="16 Frozen St", caller_name="Z16",
                    caller_phone="555-0240", location_context="OUTSIDE_STRUCTURE")

        frozen = get_report(report["id"])
        assert frozen["status"] == "SUBMITTED"
        assert frozen["needs_regeneration"] is False
        assert frozen["incident_count"] == 0, "snapshot frozen at submit"


class TestImmediateConsistencyAfterTriage:
    def test_triage_response_body_shows_mutation_immediately(self, api):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify
        a resource will return the created or updated resource object in the
        data field." §3.3: triage "moves the incident to `TRIAGED`. The
        submitted `priority` replaces the current one, the incident `version`
        increments". §2.5: "`updated_at` refreshes on any mutation of the
        resource" against the logical clock (§2.4).

        Design: Corner/consistency_model/immediate_consistency_after_triage
        """
        terr = setup_territory()
        call = intake_call(terr["id"], address_line="17 Imm St",
                           caller_name="Z17", caller_phone="555-0241")

        resp = api_client.triage_incident(call["incident_id"],
                                          {"priority": "P2"}, DISPATCHER)
        updated = validate_success(resp)
        assert updated["lifecycle_status"] == "TRIAGED"
        assert updated["priority"] == "P2"
        assert updated["version"] == 2, "creation version 1 + one triage increment"
        assert updated["updated_at"].startswith("2026-08-01T00:00:00"), (
            "updated_at refreshes at the triage logical time")
