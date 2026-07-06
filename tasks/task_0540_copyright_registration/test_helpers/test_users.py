"""Pre-built role headers for every role in the PRD (§2.1).

All four roles have opaque identity — the server never compares X-User-ID to an
entity id (PRD §2.1). Ownership on owner-scoped application actions is checked by
comparing the acting X-User-ID against the applicant_user_id RECORDED at file
time, so a caller who created a resource must keep using the same X-User-ID to
pass ownership checks. The shared constants below fix one stable X-User-ID per
role; the builders let a test act as a *different* user of the same role
(e.g. the non-owner RightsHolder ownership test).
"""
from prd_bench_local_runner.testing import build_user_headers

# Stable per-role identities. RIGHTS_HOLDER_1 is the identity every fixture uses
# to create works/applications/licenses, so its ownership checks always pass.
RIGHTS_HOLDER_1_ID = "rh-user-1"
RIGHTS_HOLDER_2_ID = "rh-user-2"
EXAMINER_ID = "examiner-1"
COMPLAINANT_ID = "complainant-1"
ADMIN_ID = "admin-1"

TEST_USERS = {
    "rightsholder_headers": build_user_headers(RIGHTS_HOLDER_1_ID, "RightsHolder"),
    "rightsholder2_headers": build_user_headers(RIGHTS_HOLDER_2_ID, "RightsHolder"),
    "examiner_headers": build_user_headers(EXAMINER_ID, "Examiner"),
    "complainant_headers": build_user_headers(COMPLAINANT_ID, "Complainant"),
    "admin_headers": build_user_headers(ADMIN_ID, "Admin"),
    # Unknown role — used to exercise ERR_UNAUTHENTICATED.
    "unknown_role_headers": build_user_headers("nobody-1", "Nobody"),
}


def make_rightsholder_headers(user_id: str) -> dict:
    """RightsHolder acting as a specific X-User-ID (for ownership scenarios)."""
    return build_user_headers(user_id, "RightsHolder")


def make_examiner_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Examiner")


def make_complainant_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Complainant")


def make_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Admin")
