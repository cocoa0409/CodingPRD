"""Incident reporting: filing rules, investigation workflow, segregation of
duties on close, and the CRITICAL severity cascade across the fleet."""
from test_helpers import (
    ApiErrorId,
    assign_drone,
    create_show,
    file_incident,
    get_show,
    get_success_data,
    setup_authorized_show,
    setup_executed_show,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS, make_safety_officer_headers

PLANNER = TEST_USERS["planner_headers"]
FLEET = TEST_USERS["fleet_manager_headers"]
SAFETY = TEST_USERS["safety_officer_headers"]


class TestIncidentWorkflow:
    def test_incident_close_before_investigate_returns_invalid_state(self, api):
        """PRD: "Closing an investigation takes an `outcome` of `CONFIRMED` or
        `REJECTED`, requires the report to be `UNDER_INVESTIGATION` (else
        `ERR_INVALID_STATE`)"
        PRD: "Manual **IncidentReport** filing is a `SafetyOfficer` act against
        an `EXECUTED` show (else `ERR_INVALID_STATE`)"

        Design: Corner/state_machines/incident_close_before_investigate_returns_invalid_state
        """
        ctx = setup_executed_show(
            show_overrides={"drone_count_planned": 1},
            design_overrides={"drone_count": 1, "duration_sec": 300})
        incident = file_incident(ctx["show"]["id"], filer_user_id="so-1",
                                 description="Single drone drifted")
        assert incident["status"] == "FILED"

        # FILED cannot skip the investigation step.
        resp = api.close_incident(incident["id"], {"outcome": "CONFIRMED"},
                                  make_safety_officer_headers("so-2"))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_incident_close_sod_and_major_requires_drone(self, api):
        """PRD: "A `SafetyOfficer` closing an incident report must not be the
        user who filed it: the caller must differ from the report's
        `filed_by_user_id`."
        PRD: "A `MAJOR` report must name the specific airframe via `drone_id` —
        omitting it is rejected with `ERR_DRONE_REQUIRED`"
        PRD: "Manual **IncidentReport** filing is a `SafetyOfficer` act against
        an `EXECUTED` show (else `ERR_INVALID_STATE`)"

        Design: Corner/validations/incident_close_sod_and_major_requires_drone
        """
        ctx = setup_executed_show(
            show_overrides={"drone_count_planned": 1},
            design_overrides={"drone_count": 1, "duration_sec": 300})
        show_id = ctx["show"]["id"]
        incident = file_incident(show_id, filer_user_id="so-1",
                                 description="Minor drift")
        get_success_data(api.investigate_incident(
            incident["id"], make_safety_officer_headers("so-1")))

        # The filer cannot close their own report.
        resp = api.close_incident(incident["id"], {"outcome": "CONFIRMED"},
                                  make_safety_officer_headers("so-1"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        # MAJOR requires the specific airframe.
        resp = api.create_incident_report(
            {"show_event_id": show_id, "severity": "MAJOR",
             "description": "Drone lost link over crowd"},
            make_safety_officer_headers("so-2"))
        validate_error(resp, ApiErrorId.ERR_DRONE_REQUIRED)

        # Incidents may only be filed against EXECUTED shows.
        show2 = create_show(ctx["site"]["id"], name="Show S2",
                            window_start="2026-08-12T19:00:00Z",
                            window_end="2026-08-12T19:30:00Z",
                            drone_count_planned=2)
        resp = api.create_incident_report(
            {"show_event_id": show2["id"], "severity": "MINOR",
             "description": "Premature report"},
            make_safety_officer_headers("so-1"))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestCriticalIncidentCascade:
    def _executed_and_ready_shows(self):
        """Show A EXECUTED (3 flown drones, back to AVAILABLE at 90% charge);
        Show B READY with two of those drones on its grid."""
        ctx_a = setup_executed_show(
            show_overrides={"name": "Show A", "drone_count_planned": 3},
            design_overrides={"drone_count": 3},
            with_flight_logs=True, battery_consumed_pct=10,
            max_altitude_reached_ft=290, max_deviation_m=1.0)
        d1, d2, _ = ctx_a["drones"]
        ctx_b = setup_authorized_show(
            show_overrides={"name": "Show B",
                            "window_start": "2026-08-12T19:00:00Z",
                            "window_end": "2026-08-12T19:30:00Z",
                            "drone_count_planned": 2},
            design_overrides={"drone_count": 2},
            auth_overrides={"window_start": "2026-08-12T18:00:00Z",
                            "window_end": "2026-08-12T21:00:00Z"})
        asg_b1 = assign_drone(ctx_b["show"]["id"], d1["id"], 0, 0)
        asg_b2 = assign_drone(ctx_b["show"]["id"], d2["id"], 0, 1)
        ctx_b["assignments"] = [asg_b1, asg_b2]
        return ctx_a, ctx_b

    def test_close_confirmed_grounds_drones_and_downgrades_future_show(self, api):
        """PRD: "For `CRITICAL`, every drone that has a flight log for the show
        is grounded, and each such grounding voids that drone's `ASSIGNED`
        launch-grid slots on other shows — decrementing those shows'
        `assigned_count` and dropping any `READY` show among them to
        `AUTHORIZED` with posture recomputed"

        Design: Difficulty/transitive_cascade/critical_incident_grounding_cascade
        """
        ctx_a, ctx_b = self._executed_and_ready_shows()
        show_b = get_show(ctx_b["show"]["id"])
        assert show_b["lifecycle_status"] == "READY", "setup held before close"

        incident = file_incident(ctx_a["show"]["id"], filer_user_id="so-1",
                                 severity="CRITICAL",
                                 description="Mid-air collision during finale")
        get_success_data(api.investigate_incident(
            incident["id"], make_safety_officer_headers("so-1")))
        closed = validate_success(api.close_incident(
            incident["id"], {"outcome": "CONFIRMED"},
            make_safety_officer_headers("so-2")))
        assert closed["status"] == "CLOSED_CONFIRMED"

        d1 = ctx_a["drones"][0]
        drone_after = validate_success(api.get_drone(d1["id"], FLEET))
        assert drone_after["status"] == "GROUNDED", \
            "link 1: CRITICAL grounds every drone that flew the show"
        asg_after = validate_success(api.get_launch_grid_assignment(
            ctx_b["assignments"][0]["id"], FLEET))
        assert asg_after["status"] == "VOIDED", \
            "link 2: grounding voids its future ASSIGNED slot"
        show_b_after = get_show(ctx_b["show"]["id"])
        assert show_b_after["lifecycle_status"] == "AUTHORIZED"
        assert show_b_after["assigned_count"] == 0
        assert show_b_after["readiness_posture"] == "NOT_READY", \
            "link 3: the incomplete grid drops READY back to AUTHORIZED"

    def test_close_confirmed_revokes_executed_shows_authorization(self, api):
        """PRD: "while the show's `APPROVED` airspace authorization is revoked,
        itself cascading any show pinning it back to `PLANNING` per §3.3."

        Design: Difficulty/transitive_cascade/critical_incident_grounding_cascade
        """
        ctx_a, ctx_b = self._executed_and_ready_shows()
        assert get_show(ctx_b["show"]["id"])["lifecycle_status"] == "READY"

        incident = file_incident(ctx_a["show"]["id"], filer_user_id="so-1",
                                 severity="CRITICAL",
                                 description="Mid-air collision during finale")
        get_success_data(api.investigate_incident(
            incident["id"], make_safety_officer_headers("so-1")))
        closed = validate_success(api.close_incident(
            incident["id"], {"outcome": "CONFIRMED"},
            make_safety_officer_headers("so-2")))
        assert closed["status"] == "CLOSED_CONFIRMED"

        auth_after = validate_success(
            api.get_authorization(ctx_a["auth"]["id"], PLANNER))
        assert auth_after["status"] == "REVOKED", \
            "sibling hop: the executed show's APPROVED authorization is revoked"
