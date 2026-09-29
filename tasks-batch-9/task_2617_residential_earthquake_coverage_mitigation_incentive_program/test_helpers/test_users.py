"""Identity headers for the seven roles.

Four roles are opaque: the API only checks that the acting identifier is present,
so shared constants are enough. Three roles are backed by a stored record --- a
participating insurer, a policyholder and a certified contractor --- and for
those the acting identifier must be the identifier of the very row the request
touches, otherwise ownership comparison rejects the call. Those three therefore
get builders that take the record's identifier.
"""
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# ─── Opaque-identity roles ────────────────────────────────────────────────────
# Any non-empty identifier satisfies these four roles.
TEST_USERS: Dict[str, Dict[str, str]] = {
    "program_admin": build_user_headers("admin-1", UserRole.PROGRAM_ADMIN.value),
    "program_admin_alt": build_user_headers("admin-9", UserRole.PROGRAM_ADMIN.value),
    "grant_reviewer": build_user_headers("rev-1", UserRole.GRANT_REVIEWER.value),
    "grant_reviewer_alt": build_user_headers("rev-2", UserRole.GRANT_REVIEWER.value),
    "field_inspector": build_user_headers("insp-1", UserRole.FIELD_INSPECTOR.value),
    "field_inspector_alt": build_user_headers("insp-2", UserRole.FIELD_INSPECTOR.value),
    "claim_adjuster": build_user_headers("adj-1", UserRole.CLAIM_ADJUSTER.value),
    "claim_adjuster_alt": build_user_headers("adj-2", UserRole.CLAIM_ADJUSTER.value),
}

PROGRAM_ADMIN_HEADERS = TEST_USERS["program_admin"]
PROGRAM_ADMIN_ALT_HEADERS = TEST_USERS["program_admin_alt"]
GRANT_REVIEWER_HEADERS = TEST_USERS["grant_reviewer"]
GRANT_REVIEWER_ALT_HEADERS = TEST_USERS["grant_reviewer_alt"]
FIELD_INSPECTOR_HEADERS = TEST_USERS["field_inspector"]
FIELD_INSPECTOR_ALT_HEADERS = TEST_USERS["field_inspector_alt"]
CLAIM_ADJUSTER_HEADERS = TEST_USERS["claim_adjuster"]
CLAIM_ADJUSTER_ALT_HEADERS = TEST_USERS["claim_adjuster_alt"]

# Acting identifiers on their own, for tests that assert which identity a record
# recorded against an action.
PROGRAM_ADMIN_USER_ID = "admin-1"
PROGRAM_ADMIN_ALT_USER_ID = "admin-9"
GRANT_REVIEWER_USER_ID = "rev-1"
GRANT_REVIEWER_ALT_USER_ID = "rev-2"
FIELD_INSPECTOR_USER_ID = "insp-1"
FIELD_INSPECTOR_ALT_USER_ID = "insp-2"
CLAIM_ADJUSTER_USER_ID = "adj-1"
CLAIM_ADJUSTER_ALT_USER_ID = "adj-2"


# ─── Record-backed roles ──────────────────────────────────────────────────────
def make_insurer_headers(insurer_id: str) -> Dict[str, str]:
    """Headers for a participating insurer acting on its own records."""
    return build_user_headers(insurer_id, UserRole.PARTICIPATING_INSURER.value)


def make_policyholder_headers(policyholder_id: str) -> Dict[str, str]:
    """Headers for a policyholder acting on its own records."""
    return build_user_headers(policyholder_id, UserRole.POLICYHOLDER.value)


def make_contractor_headers(contractor_id: str) -> Dict[str, str]:
    """Headers for a certified contractor acting on its own records."""
    return build_user_headers(contractor_id, UserRole.CERTIFIED_CONTRACTOR.value)


# ─── Malformed identity headers ───────────────────────────────────────────────
def make_headers_without_role(user_id: str) -> Dict[str, str]:
    """Headers that carry an acting identifier but name no role at all."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def make_headers_with_unknown_role(user_id: str, role: str = "AUDITOR") -> Dict[str, str]:
    """Headers naming a string that is not one of the seven roles."""
    return build_user_headers(user_id, role)


def make_headers_without_user_id(role: str) -> Dict[str, str]:
    """Headers that name a role but carry no acting identifier."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def make_headers_with_empty_user_id(role: str) -> Dict[str, str]:
    """Headers whose acting identifier is present but empty."""
    return {"X-User-ID": "", "X-User-Role": role, "Content-Type": "application/json"}
