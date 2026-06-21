"""Pre-built role headers for every role in the PRD (§2.1).

All five roles (Registrar, Teacher, Administrator, StateReportingOfficer, Parent)
are opaque operator identities — X-User-ID is never compared against an entity id
(PRD §2.1). The server does record X-User-ID on certain resources (referring_user_id,
drafter_user_id, adjudicator_user_id, guardian set), and two checks compare an acting
identity against such a recorded value: discipline segregation of duties (§2.10) and
the parent-portal guardian check (§2.4). Tests that exercise those checks must control
the exact X-User-ID, so this module exposes a per-role builder in addition to the
shared constants.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for tests that do not depend on a specific opaque identity.
TEST_USERS = {
    "registrar_headers": build_user_headers("registrar-1", "Registrar"),
    "teacher_headers": build_user_headers("teacher-1", "Teacher"),
    "administrator_headers": build_user_headers("admin-1", "Administrator"),
    "state_reporting_officer_headers": build_user_headers("officer-1", "StateReportingOfficer"),
    "parent_headers": build_user_headers("parent-1", "Parent"),
}


# Per-identity builders — for tests that must pin a specific opaque X-User-ID
# (segregation of duties, the guardian check, adjudicator matching).
def make_registrar_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Registrar")


def make_teacher_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Teacher")


def make_administrator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Administrator")


def make_state_reporting_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "StateReportingOfficer")


def make_parent_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Parent")
