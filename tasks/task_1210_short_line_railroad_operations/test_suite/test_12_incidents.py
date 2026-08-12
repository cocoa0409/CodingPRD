"""Incident lifecycle: the reportable fork, FRA filing, and the non-absorbing
CLOSED state traversed twice (PRD §3.8)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    setup_investigating_incident,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["system_admin_headers"]
DISPATCH = TEST_USERS["dispatcher_headers"]
REGULATOR = TEST_USERS["regulator_officer_headers"]


class TestIncidentReportableCycle:
    def test_incident_reportable_first_loop(self, api, dispatcher_headers, regulator_officer_headers):
        """PRD §3.8: "Each incident carries a computed `fra_reportable` flag, true
        when the `incident_type` is `DERAILMENT`, `COLLISION`, or `HAZMAT`, or
        when the `estimated_damage_cents` reaches or exceeds the FRA
        damage-reporting threshold `FRA_DAMAGE_THRESHOLD_CENTS`."
        PRD §3.8: "A `RegulatorOfficer` files the FRA report for a reportable
        incident, assigning its `fra_report_number` and moving it to `FRA_FILED`;
        attempting the filing on a non-reportable incident is rejected with
        `ERR_INCIDENT_NOT_REPORTABLE`."

        Design: Difficulty/non_linear_state_machine/incident_close_reopen_cycle
        """
        ctx = setup_investigating_incident(incident_type="DERAILMENT", estimated_damage_cents=2000000)
        incident = ctx["incident"]
        assert incident["status"] == "INVESTIGATING"
        created = validate_success(api.get_incident(incident["id"], dispatcher_headers))
        assert created["fra_reportable"] is True, "DERAILMENT is always reportable"

        filed = validate_success(api.file_incident_fra_report(incident["id"], regulator_officer_headers))
        assert filed["status"] == "FRA_FILED"
        assert filed["fra_report_number"], "filing the FRA report must assign fra_report_number"

        closed = validate_success(api.close_incident(incident["id"], regulator_officer_headers))
        assert closed["status"] == "CLOSED", (
            f"an incident in FRA_FILED may be closed without further condition, got {closed['status']}"
        )

    def test_incident_reopen_second_loop(self, api, dispatcher_headers, regulator_officer_headers):
        """PRD §3.8: "Investigation is opened by a `Dispatcher`, moving `REPORTED`
        → `INVESTIGATING`, and the same action resumes a `REOPENED` incident back
        into `INVESTIGATING`."
        PRD §3.8: "A `CLOSED` incident may be reopened to `REOPENED` by a
        `RegulatorOfficer` when new facts emerge. The incident lifecycle has no
        terminal state; a closed file can always be revived."

        Design: Difficulty/non_linear_state_machine/incident_close_reopen_cycle
        """
        ctx = setup_investigating_incident(incident_type="DERAILMENT", estimated_damage_cents=2000000)
        incident = ctx["incident"]
        validate_success(api.file_incident_fra_report(incident["id"], regulator_officer_headers))
        validate_success(api.close_incident(incident["id"], regulator_officer_headers))

        reopened = validate_success(api.reopen_incident(incident["id"], regulator_officer_headers))
        assert reopened["status"] == "REOPENED", f"CLOSED must revive to REOPENED, got {reopened['status']}"
        investigating = validate_success(api.investigate_incident(incident["id"], dispatcher_headers))
        assert investigating["status"] == "INVESTIGATING", (
            f"the same action resumes a REOPENED incident into INVESTIGATING, got {investigating['status']}"
        )
        refiled = validate_success(api.file_incident_fra_report(incident["id"], regulator_officer_headers))
        assert refiled["status"] == "FRA_FILED"
        reclosed = validate_success(api.close_incident(incident["id"], regulator_officer_headers))
        assert reclosed["status"] == "CLOSED", (
            f"the second loop traversal must complete at CLOSED, got {reclosed['status']}"
        )


class TestIncidentCloseGate:
    def test_incident_close_reportable_requires_fra_report(self, api, regulator_officer_headers):
        """PRD §3.8: "Closing from `INVESTIGATING` is permitted only for a
        non-reportable incident — attempting to close a reportable one before its
        FRA report is filed fails with `ERR_FRA_REPORT_REQUIRED` — while an
        incident in `FRA_FILED` may be closed without further condition."

        Design: Corner/errors/incident_close_reportable_requires_fra_report
        """
        ctx = setup_investigating_incident(incident_type="DERAILMENT", estimated_damage_cents=5000000)
        resp = api.close_incident(ctx["incident"]["id"], regulator_officer_headers)
        validate_error(resp, ApiErrorId.ERR_FRA_REPORT_REQUIRED)
