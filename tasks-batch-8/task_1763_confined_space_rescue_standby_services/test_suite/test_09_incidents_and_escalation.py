"""Incident reporting, triage, escalation cascades, and the reopen loop
(PRD §3.6)."""
from test_helpers import (
    ApiErrorId,
    create_ops_team,
    make_personnel,
    read_permit,
    read_roster_entry,
    read_space,
    read_standby,
    report_incident,
    schedule_roster,
    schedule_standby,
    set_clock,
    setup_active_permit,
    suspend_permit,
    validate_error,
    validate_success,
)

DAY = "2026-08-03"


def _suspended_permit_with_incident(api, severity="MINOR", kind="EQUIPMENT",
                                    description="Radio battery low"):
    """ACTIVE permit at 05:30 -> manual suspend -> incident REPORTED on the
    SUSPENDED permit (reporting on a suspended permit fires no cascade)."""
    ctx = setup_active_permit(at=f"{DAY}T05:30:00Z")
    team = ctx["team"]
    suspend_permit(ctx["permit"]["id"], team["supervisor_headers"])
    incident = report_incident(ctx["permit"]["id"], team["supervisor_headers"],
                               severity=severity, kind=kind,
                               description=description)
    return ctx, incident


class TestIncidentReopenLoop:
    def test_incident_reopen_retriage_cycle(self, api):
        """PRD §3.6: "A `SafetyOfficer` then triages a `REPORTED` or
        `REOPENED` incident (any other state is `ERR_INCIDENT_INVALID_STATE`),
        stamping `triaged_by` and optionally reclassifying `severity` via an
        optional input."; "Resolution moves a `TRIAGED` or `ESCALATED` incident
        to `RESOLVED`, capturing `resolution_notes` and `resolved_by`"; "A
        `RESOLVED` incident may later be reopened by a `SafetyOfficer`
        supplying a `reason`, moving it to `REOPENED`, from which triage may
        begin again."

        Design: Difficulty/non_linear_state_machine/incident_reopen_retriage_cycle
        """
        ctx, incident = _suspended_permit_with_incident(api)
        team = ctx["team"]
        inc_id = incident["id"]
        assert incident["status"] == "REPORTED"

        triaged = validate_success(
            api.triage_incident(inc_id, team["officer_headers"]))
        assert triaged["status"] == "TRIAGED"

        resolved = validate_success(
            api.resolve_incident(inc_id, "Winch re-inspected, no defect",
                                 team["officer_headers"]))
        assert resolved["status"] == "RESOLVED"

        reopened = validate_success(
            api.reopen_incident(inc_id, "Second defect found on re-test",
                                team["officer_headers"]))
        assert reopened["status"] == "REOPENED"

        # The loop is re-entrant: triage is legal again from REOPENED.
        retriaged = validate_success(
            api.triage_incident(inc_id, team["officer_headers"]))
        assert retriaged["status"] == "TRIAGED"
        assert retriaged["escalation_level"] == 0, (
            "escalate was never invoked during the loop")

    def test_incident_cycle_preserves_identities_and_permit(self, api):
        """PRD §3.6: "The new incident starts `REPORTED` with `reported_by`
        from the reporter's identity"; "Resolution moves a `TRIAGED` or
        `ESCALATED` incident to `RESOLVED`, capturing `resolution_notes` and
        `resolved_by`"; "reporting on an `ACTIVE` permit forces an emergency
        suspension of that permit with the evacuation/deployment cascade
        described above" — a report on an already-SUSPENDED permit forces
        nothing.

        Design: Difficulty/non_linear_state_machine/incident_reopen_retriage_cycle
        """
        ctx, incident = _suspended_permit_with_incident(api)
        team = ctx["team"]
        inc_id = incident["id"]
        assert incident["reported_by"] == team["supervisor"]["id"]

        validate_success(api.triage_incident(inc_id, team["officer_headers"]))
        resolved = validate_success(
            api.resolve_incident(inc_id, "Winch re-inspected, no defect",
                                 team["officer_headers"]))
        assert resolved["resolved_by"] == team["officer"]["id"]
        assert resolved["triaged_by"] == team["officer"]["id"]

        permit = read_permit(ctx["permit"]["id"])
        assert permit["status"] == "SUSPENDED", (
            "the incident workflow on an already-suspended permit fires no "
            "cascade")
        assert permit["suspension_count"] == 1, (
            "only the manual suspension is counted")


class TestIncidentEscalationCascade:
    def _setup_escalation_scene(self, api):
        """SUSPENDED permit at 10:00 with: one SCHEDULED roster entry
        (11:00-19:00), one ON_STANDBY assignment (r1 05:00-20:00), one
        SCHEDULED assignment (r2 11:00-20:00), one VERIFIED VENTILATION
        verification, and a TRIAGED CRITICAL incident."""
        team = create_team_with_second_rescuer()
        set_clock(f"{DAY}T05:30:00Z")
        ctx = setup_active_permit(
            at=f"{DAY}T05:30:00Z", team=team,
            space_overrides={"ventilation_required": True})
        team = ctx["team"]
        permit_id = ctx["permit"]["id"]

        # Second rescuer with a disjoint later window, never checked in.
        sa2 = schedule_standby(permit_id, team["lead_headers"],
                               team["rescuer2"]["id"],
                               standby_start_at=f"{DAY}T11:00:00Z",
                               standby_end_at=f"{DAY}T20:00:00Z")
        # Scheduled entrant entry starting at 11:00, never checked in.
        ro_ent = schedule_roster(permit_id, team["supervisor_headers"],
                                 team["entrant"]["id"],
                                 assignment_role="ENTRANT",
                                 scheduled_start_at=f"{DAY}T11:00:00Z",
                                 scheduled_end_at=f"{DAY}T19:00:00Z")

        set_clock(f"{DAY}T10:00:00Z")
        suspend_permit(permit_id, team["supervisor_headers"])
        incident = report_incident(permit_id, team["supervisor_headers"],
                                   severity="CRITICAL", kind="ENTRAPMENT",
                                   description="Ladder collapse at entry hatch")
        validate_success(api.triage_incident(incident["id"],
                                             team["officer_headers"]))
        ctx.update({"sa2": sa2, "ro_ent": ro_ent, "incident": incident})
        return ctx

    def test_escalation_cancels_permit_with_incident_reason(self, api):
        """PRD §3.6: "Escalating a `TRIAGED` incident moves it to `ESCALATED`,
        increments `escalation_level` by one, and fires the escalation cascade:
        the parent permit, if in `DRAFT`, `ISSUED`, `ACTIVE`, or `SUSPENDED`,
        is cancelled with `close_reason` `INCIDENT`".

        Design: Difficulty/transitive_cascade/incident_escalation_two_hop_cascade
        """
        ctx = self._setup_escalation_scene(api)
        escalated = validate_success(api.escalate_incident(
            ctx["incident"]["id"], ctx["team"]["officer_headers"]))
        assert escalated["status"] == "ESCALATED"
        assert escalated["escalation_level"] == 1

        permit = read_permit(ctx["permit"]["id"])
        assert permit["status"] == "CANCELLED", "hop 1: permit cancelled"
        assert permit["close_reason"] == "INCIDENT"

    def test_escalation_cascades_to_children(self, api):
        """PRD §3.6: "the cancellation's own side effects fire as the second
        link — on-duty roster entries are evacuated with `checked_out_at`
        stamped, scheduled roster entries are cancelled, on-standby assignments
        are deployed with `deployed_at` stamped, scheduled assignments are
        cancelled, verifications in `PENDING` or `VERIFIED` are voided, and a
        `CANCELLATION_FEE` line becomes billable when the permit had
        `actual_entry_at` set. When the incident's `severity` is `CRITICAL`,
        the parent space itself moves to `OUT_OF_SERVICE`."

        Design: Difficulty/transitive_cascade/incident_escalation_two_hop_cascade
        """
        ctx = self._setup_escalation_scene(api)
        validate_success(api.escalate_incident(
            ctx["incident"]["id"], ctx["team"]["officer_headers"]))

        assert read_roster_entry(ctx["ro_ent"]["id"])["status"] == "CANCELLED"
        assert read_standby(ctx["sa2"]["id"])["status"] == "CANCELLED", (
            "the SCHEDULED assignment is cancelled by the cascade")
        sa1 = read_standby(ctx["standby"]["id"])
        assert sa1["status"] == "DEPLOYED", (
            "the ON_STANDBY assignment escalates to DEPLOYED")
        assert sa1["deployed_at"] is not None
        iso = validate_success(api.get_isolation_verification(
            ctx["isolations"][0]["id"], ctx["team"]["officer_headers"]))
        assert iso["status"] == "VOIDED"
        assert read_space(ctx["space"]["id"])["status"] == "OUT_OF_SERVICE", (
            "CRITICAL severity side effect on the parent space")


class TestIncidentInvalidTransitions:
    def test_incident_reopen_from_triaged_invalid(self, api):
        """PRD §3.6: "A `RESOLVED` incident may later be reopened by a
        `SafetyOfficer` supplying a `reason`, moving it to `REOPENED`, from
        which triage may begin again." — reopen is defined only from
        `RESOLVED`; on a `TRIAGED` incident the request fails with the incident
        state error `ERR_INCIDENT_INVALID_STATE` ("A `SafetyOfficer` then
        triages a `REPORTED` or `REOPENED` incident (any other state is
        `ERR_INCIDENT_INVALID_STATE`), stamping `triaged_by` and optionally
        reclassifying `severity` via an optional input").

        Design: Corner/state_machines/corner_incident_reopen_from_triaged_invalid
        """
        ctx, incident = _suspended_permit_with_incident(api)
        team = ctx["team"]
        validate_success(api.triage_incident(incident["id"],
                                             team["officer_headers"]))
        resp = api.reopen_incident(incident["id"], "premature",
                                   team["officer_headers"])
        validate_error(resp, ApiErrorId.ERR_INCIDENT_INVALID_STATE)
        after = validate_success(api.get_incident(incident["id"],
                                                  team["officer_headers"]))
        assert after["status"] == "TRIAGED"


def create_team_with_second_rescuer():
    team = create_ops_team()
    team["rescuer2"] = make_personnel("Rescuer Two", ["RESCUER"],
                                      certifications=["CONFINED_SPACE_RESCUE"])
    return team
