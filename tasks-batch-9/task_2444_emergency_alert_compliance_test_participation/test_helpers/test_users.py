"""Pre-built role headers for every role in the PRD (§2.1).

All four roles carry an opaque `X-User-ID`: the server never compares it to any
row's `id`. It does, however, compare the StationEngineer identifier against a
station's `engineer_user_ids` array and the CertifyingOfficer identifier against
a station's `certification_officer_user_id`, so the fixtures register stations
with exactly these identifiers.
"""

from prd_bench_local_runner.testing import build_user_headers

ADMIN_USER_ID = "adm-1"
ENGINEER_USER_ID = "eng-1"
OFFICER_USER_ID = "cert-1"
INSPECTOR_USER_ID = "insp-1"
# One human holding both the engineer and the certifying-officer duty, which is
# what makes the segregation-of-duties rule of PRD §2.12 reachable.
DUAL_ROLE_USER_ID = "dual-1"

TEST_USERS = {
    "admin_headers": build_user_headers(ADMIN_USER_ID, "ComplianceAdmin"),
    "engineer_headers": build_user_headers(ENGINEER_USER_ID, "StationEngineer"),
    "officer_headers": build_user_headers(OFFICER_USER_ID, "CertifyingOfficer"),
    "inspector_headers": build_user_headers(INSPECTOR_USER_ID, "FieldInspector"),
    "dual_engineer_headers": build_user_headers(DUAL_ROLE_USER_ID, "StationEngineer"),
    "dual_officer_headers": build_user_headers(DUAL_ROLE_USER_ID, "CertifyingOfficer"),
}

ADMIN = TEST_USERS["admin_headers"]
ENGINEER = TEST_USERS["engineer_headers"]
OFFICER = TEST_USERS["officer_headers"]
INSPECTOR = TEST_USERS["inspector_headers"]
DUAL_ENGINEER = TEST_USERS["dual_engineer_headers"]
DUAL_OFFICER = TEST_USERS["dual_officer_headers"]


def make_admin_headers(user_id: str) -> dict:
    """ComplianceAdmin headers for an arbitrary opaque operator identifier."""
    return build_user_headers(user_id, "ComplianceAdmin")


def make_engineer_headers(user_id: str) -> dict:
    """StationEngineer headers; `user_id` must appear in the target station's
    `engineer_user_ids` for ownership-gated writes to pass."""
    return build_user_headers(user_id, "StationEngineer")


def make_officer_headers(user_id: str) -> dict:
    """CertifyingOfficer headers; `user_id` must equal the target station's
    `certification_officer_user_id` for ownership-gated writes to pass."""
    return build_user_headers(user_id, "CertifyingOfficer")


def make_inspector_headers(user_id: str) -> dict:
    """FieldInspector headers; inspection requests carry no ownership check."""
    return build_user_headers(user_id, "FieldInspector")
