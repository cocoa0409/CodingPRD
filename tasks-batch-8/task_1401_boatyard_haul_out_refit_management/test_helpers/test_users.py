"""Pre-built role headers for every role in the PRD.

All five roles are opaque-identity roles (PRD section 2.1): X-User-ID is an
opaque operator identifier. For Owner it is additionally matched against the
vessel's stored `owner_user_id`, so ownership-gated calls must use
make_owner_headers(<vessel.owner_user_id>) — never a shared constant whose
X-User-ID matches no vessel.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for non-ownership tests (400/404 checks, opaque
# roles, and any call where the caller's identity need not match a vessel).
TEST_USERS = {
    "service_writer_headers": build_user_headers("sw-shared-1", "ServiceWriter"),
    "yard_manager_headers": build_user_headers("ym-shared-1", "YardManager"),
    "environmental_officer_headers": build_user_headers(
        "eo-shared-1", "EnvironmentalOfficer"),
    "accountant_headers": build_user_headers("ac-shared-1", "Accountant"),
    # Owner shared constant: only for tests that do NOT exercise ownership
    # (its X-User-ID matches no registered vessel's owner_user_id).
    "owner_headers": build_user_headers("owner-shared-1", "Owner"),
}


def make_service_writer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ServiceWriter")


def make_yard_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "YardManager")


def make_environmental_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "EnvironmentalOfficer")


def make_accountant_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Accountant")


def make_owner_headers(user_id: str) -> dict:
    """For Owner: pass the vessel's `owner_user_id` as user_id whenever the
    call is ownership-gated (approve, request-change, owner part creation,
    owner-scoped reads)."""
    return build_user_headers(user_id, "Owner")
