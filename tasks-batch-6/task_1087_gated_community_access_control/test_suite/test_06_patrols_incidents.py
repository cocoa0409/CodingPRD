"""Patrol shift scheduling (per-officer closed-interval buffer) and the incident
lifecycle from REPORTED through CLOSED.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    create_community, create_patrol, create_incident,
    ADMIN, OFFICER,
)


class TestPatrolBufferOverlap:
    """Tests for the patrol_officer_buffer_overlap_closed rule (see per-test Design tags)."""

    def test_shift_at_60min_gap_allowed(self, api):
        """PRD §3.6: "the gap measured between their nearest endpoints must be at
        least 60 minutes on either side. A gap of exactly 60 minutes is allowed;
        a gap of less than 60 minutes — including a direct overlap, which has a
        negative gap — is refused with `ERR_PATROL_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/patrol_officer_buffer_overlap_closed
        """
        community = create_community()
        p1 = create_patrol(community["id"], "off-1", start_at="2026-06-01T08:00:00Z",
                           end_at="2026-06-01T12:00:00Z", route="North")
        assert p1["status"] == "SCHEDULED"
        # P1 ends 12:00; new shift starts 13:00 -> gap exactly 60 minutes -> allowed.
        p3 = validate_success(api.create_patrol(
            {"community_id": community["id"], "officer_id": "off-1",
             "start_at": "2026-06-01T13:00:00Z", "end_at": "2026-06-01T17:00:00Z",
             "route": "South"}, OFFICER), expected_status=201)
        assert p3["status"] == "SCHEDULED"

    def test_shift_within_buffer_rejected(self, api):
        """PRD §3.6: "A gap of exactly 60 minutes is allowed; a gap of less than
        60 minutes — including a direct overlap, which has a negative gap — is
        refused with `ERR_PATROL_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/patrol_officer_buffer_overlap_closed
        """
        community = create_community()
        create_patrol(community["id"], "off-1", start_at="2026-06-01T08:00:00Z",
                      end_at="2026-06-01T12:00:00Z", route="North")
        create_patrol(community["id"], "off-1", start_at="2026-06-01T13:00:00Z",
                      end_at="2026-06-01T17:00:00Z", route="South")
        # New shift 12:30-12:50 -> 30-minute gap from P1 -> rejected.
        resp = api.create_patrol(
            {"community_id": community["id"], "officer_id": "off-1",
             "start_at": "2026-06-01T12:30:00Z", "end_at": "2026-06-01T12:50:00Z",
             "route": "Gap"}, OFFICER)
        validate_error(resp, ApiErrorId.ERR_PATROL_OVERLAP.value)


def test_incident_lifecycle_reported_to_closed(api):
    """PRD §3.6: "A new incident's `status` is `REPORTED`. A `SecurityOfficer`
    advances it from `REPORTED` to `INVESTIGATING` and from `INVESTIGATING` to
    `RESOLVED`; a `CommunityAdmin` then closes it from `RESOLVED` to the terminal
    `CLOSED`."

    Design: Corner/state_machines/incident_lifecycle_reported_to_closed
    """
    community = create_community()
    incident = create_incident(community["id"], incident_type="NOISE", severity="LOW",
                               description="Loud party at pool")
    assert incident["status"] == "REPORTED"
    validate_success(api.transition_incident(incident["id"], {"to_status": "INVESTIGATING"}, OFFICER))
    validate_success(api.transition_incident(incident["id"], {"to_status": "RESOLVED"}, OFFICER))
    closed = validate_success(api.transition_incident(incident["id"], {"to_status": "CLOSED"}, ADMIN))
    assert closed["status"] == "CLOSED"
