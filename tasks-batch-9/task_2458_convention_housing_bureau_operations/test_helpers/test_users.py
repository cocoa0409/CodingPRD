"""Pre-built role headers for the six roles the PRD recognises (PRD §2.1).

`BureauCoordinator`, `BureauController` and `ComplianceOfficer` are opaque
operator identities, so the shared constants below are their canonical form.
`HotelManager`, `EventOrganizer` and `Attendee` are entity-backed: their
`X-User-ID` must be the id of the acting `Hotel`, `Event` or `Attendee`, so
ownership-gated calls MUST use the per-instance builders.
"""

from prd_bench_local_runner.testing import build_user_headers

from .constants import TEST_DEFAULTS

TEST_USERS = {
    # Opaque operator identities — shared constants are the canonical form.
    "coordinator_headers": build_user_headers(
        TEST_DEFAULTS["COORDINATOR_ID"], "BureauCoordinator"
    ),
    "controller_headers": build_user_headers(
        TEST_DEFAULTS["CONTROLLER_ID"], "BureauController"
    ),
    "compliance_officer_headers": build_user_headers(
        TEST_DEFAULTS["COMPLIANCE_OFFICER_ID"], "ComplianceOfficer"
    ),
    # Entity-backed roles — these shared constants are only safe for tests that
    # do not exercise an ownership check (read endpoints, 400/404 paths, or a
    # deliberate ERR_NOT_RESOURCE_OWNER probe).
    "hotel_manager_headers": build_user_headers("hotel-anon", "HotelManager"),
    "event_organizer_headers": build_user_headers("event-anon", "EventOrganizer"),
    "attendee_headers": build_user_headers("att-anon", "Attendee"),
}


def make_coordinator_headers(user_id: str) -> dict:
    """For BureauCoordinator with a specific operator identifier (audit trail)."""
    return build_user_headers(user_id, "BureauCoordinator")


def make_controller_headers(user_id: str) -> dict:
    """For BureauController with a specific operator identifier (audit trail)."""
    return build_user_headers(user_id, "BureauController")


def make_compliance_officer_headers(user_id: str) -> dict:
    """For ComplianceOfficer with a specific operator identifier."""
    return build_user_headers(user_id, "ComplianceOfficer")


def make_hotel_manager_headers(hotel_id: str) -> dict:
    """For HotelManager. Pass the acting Hotel's id — ownership checks compare
    the block's hotel_id to X-User-ID."""
    return build_user_headers(hotel_id, "HotelManager")


def make_event_organizer_headers(event_id: str) -> dict:
    """For EventOrganizer. Pass the acting Event's id — ownership checks compare
    the block's event_id to X-User-ID."""
    return build_user_headers(event_id, "EventOrganizer")


def make_attendee_headers(attendee_id: str) -> dict:
    """For Attendee. Pass the acting Attendee's id — ownership checks compare
    the reservation's attendee_id to X-User-ID."""
    return build_user_headers(attendee_id, "Attendee")


def no_auth_headers() -> dict:
    """Headers carrying neither X-User-ID nor X-User-Role (PRD §2.1)."""
    return {"Content-Type": "application/json"}
