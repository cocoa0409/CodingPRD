"""Pre-built role headers for every role named in PRD 2.1.

`DualCreditAdmin`, `HsCoordinator`, `CredentialReviewer`, `CollegeRegistrar` and
`Bursar` carry opaque operator identifiers that are never compared against any
entity's `id`. `Instructor` is the exception: `X-User-ID` must be the acting
Instructor entity's `id`, so ownership-gated calls MUST use
`make_instructor_headers(instructor["id"])` — the shared constant is only a
fallback for tests whose success does not depend on ownership. Reviewer ids are
also per-scenario ("rev-1", "rev-2", ...), so a builder is provided as well.
"""
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque identities — the shared constant is the canonical form.
    "admin_headers": build_user_headers("admin-op-1", "DualCreditAdmin"),
    "coordinator_headers": build_user_headers("coord-op-1", "HsCoordinator"),
    "reviewer_headers": build_user_headers("rev-1", "CredentialReviewer"),
    "registrar_headers": build_user_headers("registrar-op-1", "CollegeRegistrar"),
    "bursar_headers": build_user_headers("bursar-op-1", "Bursar"),
    # Entity-backed identity — fallback for non-ownership tests only.
    "instructor_headers": build_user_headers("test-instructor-1", "Instructor"),
}


def make_admin_headers(user_id: str = "admin-op-1") -> Dict[str, str]:
    return build_user_headers(user_id, "DualCreditAdmin")


def make_coordinator_headers(user_id: str = "coord-op-1") -> Dict[str, str]:
    return build_user_headers(user_id, "HsCoordinator")


def make_credential_reviewer_headers(user_id: str = "rev-1") -> Dict[str, str]:
    return build_user_headers(user_id, "CredentialReviewer")


def make_registrar_headers(user_id: str = "registrar-op-1") -> Dict[str, str]:
    return build_user_headers(user_id, "CollegeRegistrar")


def make_bursar_headers(user_id: str = "bursar-op-1") -> Dict[str, str]:
    return build_user_headers(user_id, "Bursar")


def make_instructor_headers(instructor_id: str) -> Dict[str, str]:
    """For Instructor (entity-backed). Pass the acting Instructor entity's id
    whenever the call is ownership-gated (credential applications, grades)."""
    return build_user_headers(instructor_id, "Instructor")


# Headers carrying neither X-User-ID nor X-User-Role — used to exercise the
# authentication rung directly.
NO_AUTH_HEADERS: Dict[str, str] = {"Content-Type": "application/json"}
