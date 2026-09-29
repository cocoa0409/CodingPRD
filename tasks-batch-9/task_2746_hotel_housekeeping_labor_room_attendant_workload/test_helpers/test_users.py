"""Identity headers for the six roles of PRD 2.1.

Two of the six roles are backed by a persisted entity: for `Supervisor` and
`RoomAttendant` the `X-User-ID` header must be the `id` of the acting
`Attendant` row.  Tests that exercise ownership, segregation of duties or
inspector qualification therefore MUST build their headers with
`make_supervisor_headers(attendant_id)` / `make_room_attendant_headers(
attendant_id)` rather than reusing the shared constants below.

The other four roles carry an opaque operator identifier that the server never
compares against an entity `id`, so the shared constants are always correct for
them.
"""

from __future__ import annotations

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_COMPLIANCE,
    ROLE_DIRECTOR,
    ROLE_FRONT_DESK,
    ROLE_LAUNDRY_LEAD,
    ROLE_ROOM_ATTENDANT,
    ROLE_SUPERVISOR,
)

# Opaque operator identifiers (PRD 2.1).
DIRECTOR_USER_ID = "director-user-1"
LAUNDRY_LEAD_USER_ID = "laundry-user-1"
FRONT_DESK_USER_ID = "frontdesk-user-1"
COMPLIANCE_USER_ID = "compliance-user-1"
SECOND_COMPLIANCE_USER_ID = "compliance-user-2"

# Placeholder entity ids for the two entity-backed roles.  These resolve to no
# Attendant row, so they are only ever valid on operations that never resolve
# the acting identity.
PLACEHOLDER_SUPERVISOR_ID = "supervisor-user-1"
PLACEHOLDER_ROOM_ATTENDANT_ID = "attendant-user-1"

DIRECTOR_HEADERS = build_user_headers(DIRECTOR_USER_ID, ROLE_DIRECTOR)
LAUNDRY_LEAD_HEADERS = build_user_headers(LAUNDRY_LEAD_USER_ID, ROLE_LAUNDRY_LEAD)
FRONT_DESK_HEADERS = build_user_headers(FRONT_DESK_USER_ID, ROLE_FRONT_DESK)
COMPLIANCE_HEADERS = build_user_headers(COMPLIANCE_USER_ID, ROLE_COMPLIANCE)
SECOND_COMPLIANCE_HEADERS = build_user_headers(
    SECOND_COMPLIANCE_USER_ID, ROLE_COMPLIANCE
)

TEST_USERS = {
    ROLE_DIRECTOR: DIRECTOR_HEADERS,
    ROLE_LAUNDRY_LEAD: LAUNDRY_LEAD_HEADERS,
    ROLE_FRONT_DESK: FRONT_DESK_HEADERS,
    ROLE_COMPLIANCE: COMPLIANCE_HEADERS,
    ROLE_SUPERVISOR: build_user_headers(PLACEHOLDER_SUPERVISOR_ID, ROLE_SUPERVISOR),
    ROLE_ROOM_ATTENDANT: build_user_headers(
        PLACEHOLDER_ROOM_ATTENDANT_ID, ROLE_ROOM_ATTENDANT
    ),
}


def make_supervisor_headers(attendant_id: str) -> dict[str, str]:
    """Headers for a `Supervisor` acting as the attendant row `attendant_id`."""
    return build_user_headers(attendant_id, ROLE_SUPERVISOR)


def make_room_attendant_headers(attendant_id: str) -> dict[str, str]:
    """Headers for a `RoomAttendant` acting as the attendant row `attendant_id`."""
    return build_user_headers(attendant_id, ROLE_ROOM_ATTENDANT)


def make_director_headers(user_id: str = DIRECTOR_USER_ID) -> dict[str, str]:
    """Headers for a `HousekeepingDirector` with an arbitrary operator id."""
    return build_user_headers(user_id, ROLE_DIRECTOR)


def make_compliance_headers(user_id: str = COMPLIANCE_USER_ID) -> dict[str, str]:
    """Headers for a `ComplianceOfficer` with an arbitrary operator id."""
    return build_user_headers(user_id, ROLE_COMPLIANCE)


def make_front_desk_headers(user_id: str = FRONT_DESK_USER_ID) -> dict[str, str]:
    """Headers for a `FrontDeskAgent` with an arbitrary operator id."""
    return build_user_headers(user_id, ROLE_FRONT_DESK)


def make_laundry_lead_headers(user_id: str = LAUNDRY_LEAD_USER_ID) -> dict[str, str]:
    """Headers for a `LaundryLead` with an arbitrary operator id."""
    return build_user_headers(user_id, ROLE_LAUNDRY_LEAD)


def make_headers(role: str, user_id: str) -> dict[str, str]:
    """Headers for an arbitrary role/user pair."""
    return build_user_headers(user_id, role)


def headers_missing_user_id(role: str = ROLE_DIRECTOR) -> dict[str, str]:
    """Headers that omit `X-User-ID` entirely (PRD 2.1 first ladder rung)."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_missing_role(user_id: str = DIRECTOR_USER_ID) -> dict[str, str]:
    """Headers that omit `X-User-Role` entirely (PRD 2.1 first ladder rung)."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_no_identity() -> dict[str, str]:
    """Headers carrying neither identity header."""
    return {"Content-Type": "application/json"}
