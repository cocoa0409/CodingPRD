"""Incident reports and the derived room posture they drive."""
import pytest
from test_helpers import (
    api_client,
    validate_success, validate_error,
    make_officer_headers, make_ra_headers,
    setup_room_with_incident,
)

OFFICER = make_officer_headers()


def test_resolve_already_resolved_incident_invalid_state(api):
    """PRD §3.7: "The `HousingOfficer` resolves a report from either `OPEN` or
    `ESCALATED` to the terminal `RESOLVED`; resolution decrements the room's
    `open_incident_count` by 1 and may flip the room from `RESTRICTED` back to
    `OPEN` when no open incidents remain and the room carries no offline flag."

    Design: Corner/state_machines/resolve_already_resolved_incident_invalid_state
    """
    scn = setup_room_with_incident(severity="MINOR", term_label="FALL_RES")
    incident = scn["incident"]
    validate_success(api.resolve_incident(incident["id"], OFFICER), 200)
    # Resolving the terminal (RESOLVED) report again is an invalid transition.
    res = api.resolve_incident(incident["id"], OFFICER)
    validate_error(res, "ERR_INVALID_STATE")
    after = validate_success(api.get_incident_report(incident["id"], OFFICER), 200)
    assert after["status"] == "RESOLVED"


def test_incident_escalate_keeps_room_restricted_and_count_unchanged(api):
    """PRD §3.7: "An escalated report still counts as open, so the room's
    `open_incident_count` is unchanged, but the room's `status` is re-derived,
    which may restrict the room."
    PRD §2.5: "A room is `RESTRICTED` when it is fully booked (its
    `occupied_bed_count` has reached its `bed_capacity`) or when it carries an
    open safety incident, as detailed in §3.7".

    Design: Corner/state_machines/incident_open_to_escalated_restricts_room
    """
    scn = setup_room_with_incident(severity="MAJOR", term_label="FALL_ESC")
    incident, room, ra = scn["incident"], scn["room"], scn["ra"]
    escalated = validate_success(
        api.escalate_incident(incident["id"], make_ra_headers(ra["id"])), 200)
    assert escalated["status"] == "ESCALATED"
    room_after = validate_success(api.get_room(room["id"], OFFICER), 200)
    assert room_after["status"] == "RESTRICTED"
    assert room_after["open_incident_count"] == 1


def test_room_restores_to_open_after_critical_incident_resolved(api):
    """PRD §3.7: "A new report begins in `status` `OPEN`, increments the room's
    `open_incident_count` by 1, and re-derives the room's `status`: a `CRITICAL`
    incident restricts the room, moving it to `RESTRICTED`." ... "resolution
    decrements the room's `open_incident_count` by 1 and may flip the room from
    `RESTRICTED` back to `OPEN` when no open incidents remain and the room carries
    no offline flag."

    Design: Corner/cross_cutting_complexity_layers/derived_room_status_restores_to_open_after_incident_resolved
    """
    scn = setup_room_with_incident(severity="CRITICAL", term_label="FALL_RCN")
    incident, room = scn["incident"], scn["room"]
    restricted = validate_success(api.get_room(room["id"], OFFICER), 200)
    assert restricted["status"] == "RESTRICTED"
    assert restricted["open_incident_count"] == 1
    validate_success(api.resolve_incident(incident["id"], OFFICER), 200)
    room_after = validate_success(api.get_room(room["id"], OFFICER), 200)
    assert room_after["status"] == "OPEN"
    assert room_after["open_incident_count"] == 0
