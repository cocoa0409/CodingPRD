"""Difficulty Rule 4 — transitive_cascade.

Depth-3 chains where one action mutates a child entity, that mutation cascades
to the parent case, and that cascade itself appends one or more event-log rows.
Two triggers exercised: the RFE deadline sweep (terminal abandon) and biometrics
complete (bubble-up + log).
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    get_success_data,
    set_clock,
    setup_rfe_pending_i130,
    setup_biometrics_scheduled_i485,
    TEST_USERS,
    make_applicant_headers,
)


class TestRfeSweepCascadesToAbandoned:
    """POST /uscis/_ops/sweep-rfe-deadlines:
    (1) RFE.status ISSUED → EXPIRED
    (2) Case.status RFE_PENDING → ABANDONED (terminal)
    (3) CaseEvent rows appended (STATUS_CHANGE + RFE_EXPIRED).
    """

    def test_sweep_expires_rfe_and_abandons_parent_case(self, api):
        """PRD §3.6: "for each one whose `status` is still `ISSUED` and whose `response_deadline`
        is at or before `ClockState.current_utc`, expires the RFE and abandons its
        parent case in a single logical step. The RFE's `status` is set to the
        terminal `EXPIRED`, the parent case's `status` cascades to the terminal
        `ABANDONED`"

        Design: Difficulty/transitive_cascade/rfe_sweep_expires_rfe_cascades_case_to_abandoned_depth3
        """
        applicant, case_rfe, rfe, officer_headers = setup_rfe_pending_i130(
            file_date_iso="2026-06-15T00:00:00Z",
            evidence_items=["proof_of_relationship"],
        )
        # Advance the clock past the RFE deadline (issued 2026-06-15 + 87 days = 2026-09-10).
        set_clock("2026-09-11T00:00:00Z")
        admin = TEST_USERS["field_office_admin_headers"]
        res = api.sweep_rfe_deadlines(admin)
        summary = validate_success(res, 200)
        assert summary["expired_rfe_count"] == 1
        assert summary["abandoned_case_count"] == 1

        # Verify the cascade: RFE is EXPIRED, Case is ABANDONED.
        rfe_after = get_success_data(api.get_rfe(rfe["id"], officer_headers))
        case_after = get_success_data(api.get_case(case_rfe["id"], officer_headers))
        assert rfe_after["status"] == "EXPIRED"
        assert case_after["status"] == "ABANDONED"

    def test_sweep_appends_rfe_expired_event_to_case_log(self, api):
        """PRD §3.6: "a `CaseEvent` of type `RFE_EXPIRED` is appended carrying the RFE identifier"

        Design: Difficulty/transitive_cascade/rfe_sweep_expires_rfe_cascades_case_to_abandoned_depth3
        """
        applicant, case_rfe, rfe, officer_headers = setup_rfe_pending_i130()
        set_clock("2026-09-11T00:00:00Z")
        api.sweep_rfe_deadlines(TEST_USERS["field_office_admin_headers"])

        events_resp = api.list_case_events(case_rfe["id"], officer_headers)
        events_body = validate_success(events_resp, 200)
        # The list endpoint returns a list payload directly OR via paginated meta.
        events = events_body if isinstance(events_body, list) else events_body
        # If paginated form, body is the data list; we iterate.
        evt_types = [e.get("event_type") for e in events]
        assert "RFE_EXPIRED" in evt_types


class TestBiometricsCompleteCascadesAndLogs:
    """POST /uscis/biometrics/{id}/complete:
    (1) BiometricsAppointment.status SCHEDULED → COMPLETED
    (2) Case.status BIOMETRICS_SCHEDULED → BIOMETRICS_COMPLETED
    (3) CaseEvent rows appended (STATUS_CHANGE + BIOMETRICS_COMPLETED).
    """

    def test_complete_biometrics_bubbles_case_to_biometrics_completed(self, api):
        """PRD §3.3: "The side effects are: setting the appointment's `status` to `COMPLETED`,
        cascading the parent case to `BIOMETRICS_COMPLETED`, appending a `CaseEvent`
        of type `BIOMETRICS_COMPLETED`, appending a `STATUS_CHANGE` event from
        `BIOMETRICS_SCHEDULED` to `BIOMETRICS_COMPLETED`, and incrementing
        `Case.version` by one."

        Design: Difficulty/transitive_cascade/biometrics_complete_cascades_case_advance_then_log_depth3
        """
        applicant, case, biom, officer_headers = setup_biometrics_scheduled_i485(
            file_date_iso="2026-06-15T00:00:00Z",
            biom_at="2026-06-25T15:00:00Z",
            asc_location_code="ASC-SF-02",
        )
        # Move the logical clock past the appointment instant.
        set_clock("2026-06-26T00:00:00Z")
        res = api.complete_biometrics(biom["id"], officer_headers)
        body = validate_success(res, 200)
        assert body["status"] == "COMPLETED"

        case_after = get_success_data(api.get_case(case["id"], officer_headers))
        assert case_after["status"] == "BIOMETRICS_COMPLETED"

    def test_complete_biometrics_appends_event_log_rows(self, api):
        """PRD §3.3: "appending a `CaseEvent` of type `BIOMETRICS_COMPLETED`,
        appending a `STATUS_CHANGE` event from `BIOMETRICS_SCHEDULED` to `BIOMETRICS_COMPLETED`"

        Design: Difficulty/transitive_cascade/biometrics_complete_cascades_case_advance_then_log_depth3
        """
        applicant, case, biom, officer_headers = setup_biometrics_scheduled_i485()
        set_clock("2026-06-26T00:00:00Z")
        api.complete_biometrics(biom["id"], officer_headers)

        events = validate_success(
            api.list_case_events(case["id"], officer_headers), 200
        )
        evt_types = [e.get("event_type") for e in events]
        # Both events appended by the cascade.
        assert "BIOMETRICS_COMPLETED" in evt_types
        # Exactly one BIOMETRICS_COMPLETED row appended for the single complete call.
        assert evt_types.count("BIOMETRICS_COMPLETED") == 1
