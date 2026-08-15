"""On-site incident triage lifecycle (PRD §3.7)."""
from test_helpers import (
    ApiErrorId,
    create_abroad_application,
    create_incident_payload,
    create_reported_incident,
    make_student_headers,
    validate_error,
    validate_success,
    api_client,
    COORD_A_HEADERS,
    SAFETY_HEADERS,
)


class TestIncidentTriageFlow:
    def test_incident_triage_flow_and_terminal_lockdown(self, api):
        """PRD §3.7: "The ladder runs `REPORTED` → `TRIAGED` → `ESCALATED` → `RESOLVED`,
        with one shortcut: a `TRIAGED` incident may move directly to `RESOLVED`. Both
        resolution paths — from `TRIAGED` and from `ESCALATED` — capture the payload's
        `resolution_notes` onto the incident, and those notes may be omitted or null.
        `RESOLVED` is terminal."

        Design: Corner/state_machines/incident_triage_flow_and_terminal_lockdown
        """
        program, student, application = create_abroad_application(
            student_overrides={"full_name": "Abroad Student", "email": "abroad@uni.edu"},
        )
        inc1 = create_reported_incident(
            application, reporter_student=student,
            severity="HIGH", description="lost passport",
        )
        assert inc1["status"] == "REPORTED"
        assert inc1["reported_by"] == student["id"], (
            "Incident is born REPORTED with reported_by stamped from the caller's X-User-ID"
        )
        inc2 = create_reported_incident(
            application, severity="LOW", description="noise complaint",
        )

        t1 = validate_success(
            api.transition_incident(inc1["id"], {"to_state": "TRIAGED"}, SAFETY_HEADERS)
        )
        assert t1["status"] == "TRIAGED"
        t2 = validate_success(
            api.transition_incident(inc1["id"], {"to_state": "ESCALATED"}, SAFETY_HEADERS)
        )
        assert t2["status"] == "ESCALATED"
        t3 = validate_success(
            api.transition_incident(
                inc1["id"],
                {"to_state": "RESOLVED", "resolution_notes": "consulate visit arranged"},
                SAFETY_HEADERS,
            )
        )
        assert t3["status"] == "RESOLVED"
        assert t3["resolution_notes"] == "consulate visit arranged"

        # RESOLVED is terminal.
        resp_terminal = api.transition_incident(
            inc1["id"], {"to_state": "TRIAGED"}, SAFETY_HEADERS,
        )
        validate_error(resp_terminal, ApiErrorId.ERR_INVALID_STATE)

        # REPORTED -> ESCALATED skip is rejected.
        resp_skip = api.transition_incident(
            inc2["id"], {"to_state": "ESCALATED"}, SAFETY_HEADERS,
        )
        validate_error(resp_skip, ApiErrorId.ERR_INVALID_STATE)

    def test_incident_requires_abroad_application(self, api):
        """PRD §3.7: "While students are abroad, incidents are reported against applications
        in `ABROAD` status; reporting against any other application status fails with
        `ERR_INVALID_STATE`."

        Design: Corner/state_machines/incident_triage_flow_and_terminal_lockdown
        """
        from test_helpers import create_committed_application

        program, student, application = create_committed_application()
        resp = api.create_incident(
            create_incident_payload(application["id"]),
            make_student_headers(student["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
