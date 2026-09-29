"""Auth headers for the five opaque roles of PRD 2.1.

No resource in this system is owned by a user (PRD 2.1), so a single shared
header dict per role is enough. Two rules do compare a later caller's
`X-User-ID` against a recorded identifier (PRD 2.10), so a handful of
distinct identifiers per role are provided for segregation-of-duties work.
"""

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_EPA_REGIONAL_REVIEWER,
    ROLE_FIELD_TECHNICIAN,
    ROLE_NETWORK_ADMIN,
    ROLE_PROGRAM_MANAGER,
    ROLE_QA_OFFICER,
)

TEST_USERS = {
    "network_admin": {"user_id": "admin-1", "role": ROLE_NETWORK_ADMIN},
    "field_technician": {"user_id": "tech-1", "role": ROLE_FIELD_TECHNICIAN},
    "qa_officer": {"user_id": "qa-1", "role": ROLE_QA_OFFICER},
    "qa_officer_2": {"user_id": "qa-2", "role": ROLE_QA_OFFICER},
    "program_manager": {"user_id": "pm-1", "role": ROLE_PROGRAM_MANAGER},
    "program_manager_2": {"user_id": "pm-2", "role": ROLE_PROGRAM_MANAGER},
    "epa_reviewer": {"user_id": "epa-1", "role": ROLE_EPA_REGIONAL_REVIEWER},
}

ADMIN_HEADERS = build_user_headers("admin-1", ROLE_NETWORK_ADMIN)
TECH_HEADERS = build_user_headers("tech-1", ROLE_FIELD_TECHNICIAN)
QA_HEADERS = build_user_headers("qa-1", ROLE_QA_OFFICER)
QA2_HEADERS = build_user_headers("qa-2", ROLE_QA_OFFICER)
PM_HEADERS = build_user_headers("pm-1", ROLE_PROGRAM_MANAGER)
PM2_HEADERS = build_user_headers("pm-2", ROLE_PROGRAM_MANAGER)
EPA_HEADERS = build_user_headers("epa-1", ROLE_EPA_REGIONAL_REVIEWER)

HEADERS_BY_ROLE = {
    ROLE_NETWORK_ADMIN: ADMIN_HEADERS,
    ROLE_FIELD_TECHNICIAN: TECH_HEADERS,
    ROLE_QA_OFFICER: QA_HEADERS,
    ROLE_PROGRAM_MANAGER: PM_HEADERS,
    ROLE_EPA_REGIONAL_REVIEWER: EPA_HEADERS,
}


def headers_for(user_id: str, role: str):
    """Build headers for an arbitrary opaque operator identifier and role."""
    return build_user_headers(user_id, role)


NO_HEADERS = {"Content-Type": "application/json"}
ROLE_ONLY_HEADERS = {"X-User-Role": ROLE_NETWORK_ADMIN, "Content-Type": "application/json"}
USER_ONLY_HEADERS = {"X-User-ID": "admin-1", "Content-Type": "application/json"}
BAD_ROLE_HEADERS = build_user_headers("admin-1", "SuperUser")
