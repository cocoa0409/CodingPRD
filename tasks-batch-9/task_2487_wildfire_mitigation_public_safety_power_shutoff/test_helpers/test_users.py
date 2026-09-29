"""Identity headers for the eight roles the PRD defines (§2.1).

Every request carries `X-User-ID` and `X-User-Role`.  For all eight roles the
`X-User-ID` is an opaque operator identifier that is never resolved to a row, so
the builders below take any string.  Distinct identifiers matter only where the
segregation-of-duties gates of §2.9 compare a recorded identifier against a
later caller's identifier.
"""

from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# Canonical operator identities.
PLANNER_PRIMARY = "planner_1"
ANALYST_PRIMARY = "analyst_1"
DUTY_OFFICER_PRIMARY = "duty_officer_1"
DUTY_OFFICER_SECONDARY = "duty_officer_9"
LIAISON_PRIMARY = "liaison_1"
REVIEWER_ALPHA = "reviewer_alpha"
REVIEWER_BETA = "reviewer_beta"
REVIEWER_GAMMA = "reviewer_gamma"
REVIEWER_DELTA = "reviewer_delta"
SUPERVISOR_PRIMARY = "supervisor_1"
INSPECTOR_PRIMARY = "inspector_1"
ENGINEER_PRIMARY = "engineer_1"

# Crew-lead identifiers recorded in `patrol_lead_user_id` request bodies.
CREW_LEAD_1 = "crew_lead_1"
CREW_LEAD_2 = "crew_lead_2"
CREW_LEAD_3 = "crew_lead_3"


def make_grid_planner_headers(user_id=PLANNER_PRIMARY):
    return build_user_headers(user_id, UserRole.GRID_PLANNER.value)


def make_meteorology_analyst_headers(user_id=ANALYST_PRIMARY):
    return build_user_headers(user_id, UserRole.METEOROLOGY_ANALYST.value)


def make_duty_officer_headers(user_id=DUTY_OFFICER_PRIMARY):
    return build_user_headers(user_id, UserRole.PSPS_DUTY_OFFICER.value)


def make_community_liaison_headers(user_id=LIAISON_PRIMARY):
    return build_user_headers(user_id, UserRole.COMMUNITY_LIAISON.value)


def make_regulatory_reviewer_headers(user_id=REVIEWER_ALPHA):
    return build_user_headers(user_id, UserRole.REGULATORY_REVIEWER.value)


def make_patrol_supervisor_headers(user_id=SUPERVISOR_PRIMARY):
    return build_user_headers(user_id, UserRole.FIELD_PATROL_SUPERVISOR.value)


def make_asset_inspector_headers(user_id=INSPECTOR_PRIMARY):
    return build_user_headers(user_id, UserRole.ASSET_INSPECTOR.value)


def make_transmission_engineer_headers(user_id=ENGINEER_PRIMARY):
    return build_user_headers(user_id, UserRole.TRANSMISSION_ENGINEER.value)


# Convenience aliases for the identities used most often.
PLANNER_HEADERS = make_grid_planner_headers()
ANALYST_HEADERS = make_meteorology_analyst_headers()
OFFICER_HEADERS = make_duty_officer_headers()
OFFICER_2_HEADERS = make_duty_officer_headers(DUTY_OFFICER_SECONDARY)
LIAISON_HEADERS = make_community_liaison_headers()
REVIEWER_HEADERS = make_regulatory_reviewer_headers(REVIEWER_ALPHA)
REVIEWER_2_HEADERS = make_regulatory_reviewer_headers(REVIEWER_BETA)
REVIEWER_3_HEADERS = make_regulatory_reviewer_headers(REVIEWER_GAMMA)
REVIEWER_4_HEADERS = make_regulatory_reviewer_headers(REVIEWER_DELTA)
SUPERVISOR_HEADERS = make_patrol_supervisor_headers()
INSPECTOR_HEADERS = make_asset_inspector_headers()
ENGINEER_HEADERS = make_transmission_engineer_headers()


HEADERS_BY_ROLE = {
    UserRole.GRID_PLANNER.value: PLANNER_HEADERS,
    UserRole.METEOROLOGY_ANALYST.value: ANALYST_HEADERS,
    UserRole.PSPS_DUTY_OFFICER.value: OFFICER_HEADERS,
    UserRole.COMMUNITY_LIAISON.value: LIAISON_HEADERS,
    UserRole.REGULATORY_REVIEWER.value: REVIEWER_HEADERS,
    UserRole.FIELD_PATROL_SUPERVISOR.value: SUPERVISOR_HEADERS,
    UserRole.ASSET_INSPECTOR.value: INSPECTOR_HEADERS,
    UserRole.TRANSMISSION_ENGINEER.value: ENGINEER_HEADERS,
}


def headers_for(role):
    """Headers for a role named either by its enum member or by its wire string."""
    key = role.value if hasattr(role, "value") else role
    return HEADERS_BY_ROLE[key]


def headers_excluding(*roles):
    """Every role's headers except the named ones — the RBAC denial sweep."""
    excluded = {r.value if hasattr(r, "value") else r for r in roles}
    return {
        role: headers
        for role, headers in HEADERS_BY_ROLE.items()
        if role not in excluded
    }


# Malformed identity headers used by the authentication tests of §2.8 priority 1-2.
NO_HEADERS = {}
MISSING_ROLE_HEADERS = {"X-User-ID": PLANNER_PRIMARY}
MISSING_USER_HEADERS = {"X-User-Role": UserRole.GRID_PLANNER.value}
EMPTY_ROLE_HEADERS = {"X-User-ID": PLANNER_PRIMARY, "X-User-Role": ""}
EMPTY_USER_HEADERS = {"X-User-ID": "", "X-User-Role": UserRole.GRID_PLANNER.value}
UNDECLARED_ROLE_HEADERS = {
    "X-User-ID": PLANNER_PRIMARY,
    "X-User-Role": "WildfireCzar",
}
