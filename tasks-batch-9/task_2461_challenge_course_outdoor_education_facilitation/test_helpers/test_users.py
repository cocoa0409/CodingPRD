"""Auth header builders for the five operating roles (PRD 2.1).

`ProgramDirector` carries an opaque operator identifier that the server never
compares against a stored row, so a single constant header dict is enough.

The other four roles are entity-backed: `X-User-ID` must be the `id` of a real
row (a `Facilitator` for `SafetyOfficer`, `Facilitator` and
`ProfessionalInspector`; a `GroupClient` for `GroupCoordinator`). Tests must
therefore build those headers from the identifier returned when the row was
created, which is what the `make_*_headers` builders below are for.
"""

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_FACILITATOR,
    ROLE_GROUP_COORDINATOR,
    ROLE_PROFESSIONAL_INSPECTOR,
    ROLE_PROGRAM_DIRECTOR,
    ROLE_SAFETY_OFFICER,
)

# Opaque operator identity: not tied to any persisted entity.
PROGRAM_DIRECTOR_USER_ID = "director-001"
PROGRAM_DIRECTOR = build_user_headers(PROGRAM_DIRECTOR_USER_ID, ROLE_PROGRAM_DIRECTOR)


def make_program_director_headers(user_id=PROGRAM_DIRECTOR_USER_ID):
    """Headers for operator management; the identifier stays opaque."""
    return build_user_headers(user_id, ROLE_PROGRAM_DIRECTOR)


def make_safety_officer_headers(facilitator_id):
    """Headers for a SAFETY_OFFICER facilitator row at LEVEL_3."""
    return build_user_headers(facilitator_id, ROLE_SAFETY_OFFICER)


def make_facilitator_headers(facilitator_id):
    """Headers for a STAFF_FACILITATOR facilitator row."""
    return build_user_headers(facilitator_id, ROLE_FACILITATOR)


def make_professional_inspector_headers(facilitator_id):
    """Headers for a CONTRACT_INSPECTOR facilitator row that is not an employee."""
    return build_user_headers(facilitator_id, ROLE_PROFESSIONAL_INSPECTOR)


def make_group_coordinator_headers(group_client_id):
    """Headers for the acting GroupClient row."""
    return build_user_headers(group_client_id, ROLE_GROUP_COORDINATOR)


def make_headers(role, user_id):
    """Headers for an arbitrary role/identifier pair."""
    return build_user_headers(user_id, role)
