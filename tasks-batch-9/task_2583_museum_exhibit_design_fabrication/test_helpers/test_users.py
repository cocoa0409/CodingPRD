"""Caller identities.

None of the six roles is backed by a persisted row, so an identity is just a
role name plus an opaque operator id. Distinct ids per role keep the five
segregation-of-duties pairings from tripping on ordinary setup traffic, and
``PM_SECOND`` gives a second ProjectManager operator for the cases where the
panel seat is legitimate but the package author is not.
"""

from prd_bench_local_runner.testing import build_user_headers

ROLE_PROJECT_MANAGER = "ProjectManager"
ROLE_CURATOR = "Curator"
ROLE_CONSERVATOR = "Conservator"
ROLE_ACCESSIBILITY = "AccessibilitySpecialist"
ROLE_FABRICATION_LEAD = "FabricationLead"
ROLE_MUSEUM_OPERATIONS = "MuseumOperations"

ALL_ROLES = [
    ROLE_PROJECT_MANAGER,
    ROLE_CURATOR,
    ROLE_CONSERVATOR,
    ROLE_ACCESSIBILITY,
    ROLE_FABRICATION_LEAD,
    ROLE_MUSEUM_OPERATIONS,
]

PANEL_ELIGIBLE_ROLES = [
    ROLE_CURATOR,
    ROLE_CONSERVATOR,
    ROLE_PROJECT_MANAGER,
    ROLE_ACCESSIBILITY,
    ROLE_FABRICATION_LEAD,
]

USER_PM = "pm-01"
USER_PM_SECOND = "pm-02"
USER_CURATOR = "cur-01"
USER_CONSERVATOR = "con-01"
USER_ACCESSIBILITY = "acc-01"
USER_FABRICATION = "fab-01"
USER_OPERATIONS = "ops-01"


def headers_for(role, user_id):
    """Build headers for an arbitrary (role, opaque user id) pairing."""
    return build_user_headers(user_id, role)


PM = headers_for(ROLE_PROJECT_MANAGER, USER_PM)
PM_SECOND = headers_for(ROLE_PROJECT_MANAGER, USER_PM_SECOND)
CURATOR = headers_for(ROLE_CURATOR, USER_CURATOR)
CONSERVATOR = headers_for(ROLE_CONSERVATOR, USER_CONSERVATOR)
ACCESSIBILITY = headers_for(ROLE_ACCESSIBILITY, USER_ACCESSIBILITY)
FABRICATION = headers_for(ROLE_FABRICATION_LEAD, USER_FABRICATION)
OPERATIONS = headers_for(ROLE_MUSEUM_OPERATIONS, USER_OPERATIONS)

HEADERS_BY_ROLE = {
    ROLE_PROJECT_MANAGER: PM,
    ROLE_CURATOR: CURATOR,
    ROLE_CONSERVATOR: CONSERVATOR,
    ROLE_ACCESSIBILITY: ACCESSIBILITY,
    ROLE_FABRICATION_LEAD: FABRICATION,
    ROLE_MUSEUM_OPERATIONS: OPERATIONS,
}

USER_ID_BY_ROLE = {
    ROLE_PROJECT_MANAGER: USER_PM,
    ROLE_CURATOR: USER_CURATOR,
    ROLE_CONSERVATOR: USER_CONSERVATOR,
    ROLE_ACCESSIBILITY: USER_ACCESSIBILITY,
    ROLE_FABRICATION_LEAD: USER_FABRICATION,
    ROLE_MUSEUM_OPERATIONS: USER_OPERATIONS,
}

ALL_ROLE_HEADERS = [HEADERS_BY_ROLE[role] for role in ALL_ROLES]

# Malformed identities used by the authentication probes.
NO_ROLE_HEADER = {"X-User-ID": USER_PM, "Content-Type": "application/json"}
NO_USER_ID_HEADER = {
    "X-User-Role": ROLE_CURATOR,
    "Content-Type": "application/json",
}
BLANK_USER_ID_HEADER = headers_for(ROLE_CURATOR, "")
UNKNOWN_ROLE_HEADER = headers_for("Registrar", USER_PM)
