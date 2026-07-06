"""Incident lifecycle, safety-posture cascade, resolve-triggered feed recompute."""
import pytest

from test_helpers import (
    get_success_data, validate_error,
    make_agency_officer_headers, make_resident_headers,
    setup_neighborhood_with_verified_residents,
    create_post, report_critical_incident, drive_neighborhood_to_emergency,
    set_clock, api_client, ADMIN,
    AGENCY_OFFICER_USER_ID,
)


class TestIncidentResolveCascadeDepth3:
    """Difficulty rule 4 — depth-3 cascade: RESOLVE -> count -> posture -> feed."""

    def test_resolve_cascades_to_open_posture_and_recomputes_post_score(self, api):
        """PRD §3.4: "the resolution cascades in three ordered steps:
        `resolved_at` is set to the current logical clock, the neighborhood's
        `unresolved_critical_count` is decremented by 1 if the incident's
        `severity` equals `CRITICAL`, and the neighborhood's `safety_posture`
        is recomputed; if the recomputed `safety_posture` is now `OPEN`,
        every `PUBLISHED` `Post` in the same neighborhood has its
        `local_relevance_score` recomputed as the third step of the cascade."

        Design: Difficulty/transitive_cascade/incident_resolve_cascades_unresolved_count_posture_and_feed_score_depth_3
        """
        set_clock("2026-06-01T00:00:00Z")
        n, mod, residents = setup_neighborhood_with_verified_residents(2)
        r1 = residents[0]
        reporter = residents[1]
        # Author SAFETY post first (under OPEN posture -> 2.10).
        p1 = create_post(r1["id"], n["id"], category="SAFETY",
                         title="help", body="hazard")
        assert p1["local_relevance_score"] == 2.10
        # Drive N1 to EMERGENCY with 3 CRITICAL incidents.
        i1 = report_critical_incident(reporter["id"], n["id"])
        i2 = report_critical_incident(reporter["id"], n["id"],
                                       category="TRAFFIC_HAZARD")
        i3 = report_critical_incident(reporter["id"], n["id"],
                                       category="ENVIRONMENTAL")
        n_em = get_success_data(api_client.get_neighborhood(n["id"], ADMIN))
        assert n_em["safety_posture"] == "EMERGENCY"
        # Acknowledge two and dismiss the first, resolve the third to drive to OPEN.
        officer_hdrs = make_agency_officer_headers(AGENCY_OFFICER_USER_ID)
        get_success_data(api_client.acknowledge_incident(i2["id"], officer_hdrs))
        get_success_data(api_client.acknowledge_incident(i3["id"], officer_hdrs))
        get_success_data(api_client.dismiss_incident(i1["id"], officer_hdrs))
        get_success_data(api_client.resolve_incident(i2["id"], officer_hdrs))
        # After the last RESOLVE, unresolved should be 0, posture OPEN.
        get_success_data(api_client.resolve_incident(i3["id"], officer_hdrs))
        n_final = get_success_data(api_client.get_neighborhood(n["id"], ADMIN))
        assert n_final["unresolved_critical_count"] == 0
        assert n_final["safety_posture"] == "OPEN"
        p1_final = get_success_data(api_client.get_post(p1["id"], ADMIN))
        # SAFETY under OPEN at age 0 -> 2.10.
        assert p1_final["local_relevance_score"] == 2.10, \
            f"Expected 2.10 after cascade returns posture to OPEN, got {p1_final['local_relevance_score']}"

    def test_resolve_decrements_unresolved_critical_count(self, api):
        """PRD §3.4: "the neighborhood's `unresolved_critical_count` is
        decremented by 1 if the incident's `severity` equals `CRITICAL`"

        Design: Difficulty/transitive_cascade/incident_resolve_cascades_unresolved_count_posture_and_feed_score_depth_3
        """
        set_clock("2026-06-01T00:00:00Z")
        n, mod, residents = setup_neighborhood_with_verified_residents(1)
        reporter = residents[0]
        i = report_critical_incident(reporter["id"], n["id"])
        n_after_report = get_success_data(api_client.get_neighborhood(n["id"], ADMIN))
        assert n_after_report["unresolved_critical_count"] == 1
        officer_hdrs = make_agency_officer_headers(AGENCY_OFFICER_USER_ID)
        get_success_data(api_client.acknowledge_incident(i["id"], officer_hdrs))
        get_success_data(api_client.resolve_incident(i["id"], officer_hdrs))
        n_final = get_success_data(api_client.get_neighborhood(n["id"], ADMIN))
        assert n_final["unresolved_critical_count"] == 0


class TestIncidentUnresolvedCountConservation:
    """Difficulty rule 9 compensating invariant on unresolved_critical_count."""

    def test_create_ack_resolve_returns_count_to_pre_state(self, api):
        """PRD §3.4: "When `severity=CRITICAL`, the containing neighborhood's
        `unresolved_critical_count` is incremented by 1 as part of the create
        response, and the neighborhood's `safety_posture` is recomputed"
        PRD §3.4: "the neighborhood's `unresolved_critical_count` is
        decremented by 1 if the incident's `severity` equals `CRITICAL`"

        Design: Difficulty/compensating_invariant/critical_incident_create_then_resolve_leaves_unresolved_critical_count_unchanged
        """
        set_clock("2026-06-01T00:00:00Z")
        n, mod, residents = setup_neighborhood_with_verified_residents(1)
        reporter = residents[0]
        n_pre = get_success_data(api_client.get_neighborhood(n["id"], ADMIN))
        count_pre = n_pre["unresolved_critical_count"]
        i = report_critical_incident(reporter["id"], n["id"])
        officer_hdrs = make_agency_officer_headers(AGENCY_OFFICER_USER_ID)
        get_success_data(api_client.acknowledge_incident(i["id"], officer_hdrs))
        get_success_data(api_client.resolve_incident(i["id"], officer_hdrs))
        n_final = get_success_data(api_client.get_neighborhood(n["id"], ADMIN))
        assert n_final["unresolved_critical_count"] == count_pre, \
            f"Conservation broken: pre={count_pre}, post={n_final['unresolved_critical_count']}"

    def test_posture_returns_to_open_after_full_cycle(self, api):
        """PRD §3.4: "In every other case the `safety_posture` is `OPEN`."

        Design: Difficulty/compensating_invariant/critical_incident_create_then_resolve_leaves_unresolved_critical_count_unchanged
        """
        set_clock("2026-06-01T00:00:00Z")
        n, mod, residents = setup_neighborhood_with_verified_residents(1)
        reporter = residents[0]
        i = report_critical_incident(reporter["id"], n["id"])
        officer_hdrs = make_agency_officer_headers(AGENCY_OFFICER_USER_ID)
        get_success_data(api_client.acknowledge_incident(i["id"], officer_hdrs))
        get_success_data(api_client.resolve_incident(i["id"], officer_hdrs))
        n_final = get_success_data(api_client.get_neighborhood(n["id"], ADMIN))
        assert n_final["safety_posture"] == "OPEN"


class TestIncidentResolveFromOpenReturnsInvalidState:
    """Corner: cannot resolve directly from OPEN — must ACKNOWLEDGE first."""

    def test_resolve_from_open_returns_invalid_state(self, api):
        """PRD §3.4: "The same officer (their id must equal
        `acknowledged_by_officer_id`) resolves an `ACKNOWLEDGED` incident,
        moving it to the terminal `RESOLVED` state"
        PRD §2.6: "State checks come next on any endpoint that drives a
        state machine: the target entity's current state must be a valid
        origin state (a valid `from` in the state machine) for the requested
        transition, or the request is rejected with `ERR_INVALID_STATE` (HTTP
        409)."

        Design: Corner/state_machines/incident_resolve_from_open_returns_invalid_state
        """
        set_clock("2026-06-01T00:00:00Z")
        n, mod, residents = setup_neighborhood_with_verified_residents(1)
        r = residents[0]
        from test_helpers import create_incident_payload
        i = get_success_data(api_client.create_incident(
            create_incident_payload(r["id"], n["id"], severity="WARNING",
                                    category="TRAFFIC_HAZARD"),
            make_resident_headers(r["id"]),
        ))
        # Attempt /resolve directly from OPEN -> 409 ERR_INVALID_STATE.
        officer_hdrs = make_agency_officer_headers(AGENCY_OFFICER_USER_ID)
        resp = api_client.resolve_incident(i["id"], officer_hdrs)
        validate_error(resp, "ERR_INVALID_STATE")


class TestIncidentGeofenceValidation:
    """Corner: incident lat/lng must lie inside neighborhood geofence."""

    def test_incident_outside_geofence_returns_location_error(self, api):
        """PRD §2.6: "Incident creation requires that `incident_lat` and
        `incident_lng` lie inside the target `Neighborhood`'s geofence
        circle, and event creation requires that `venue_lat` and `venue_lng`
        lie inside the target `Neighborhood`'s geofence circle."
        PRD §2.6: "Any of these produces `ERR_LOCATION_OUTSIDE_GEOFENCE`
        (HTTP 422)."

        Design: Corner/validations/incident_lat_lng_outside_geofence_returns_location_error
        """
        set_clock("2026-06-01T00:00:00Z")
        n, mod, residents = setup_neighborhood_with_verified_residents(
            1, neighborhood_overrides={"radius_meters": 500}
        )
        r = residents[0]
        # Report incident far outside the 500m radius.
        from test_helpers import create_incident_payload
        payload = create_incident_payload(
            r["id"], n["id"], severity="WARNING", category="TRAFFIC_HAZARD",
        )
        payload["incident_lat"] = 37.90  # ~16km north
        payload["incident_lng"] = -122.42
        resp = api_client.create_incident(payload, make_resident_headers(r["id"]))
        validate_error(resp, "ERR_LOCATION_OUTSIDE_GEOFENCE")
