"""Pre-built authentication headers for every role the PRD recognises.

A ServiceMember caller identifies itself with the service member's own id, and a
TspCoordinator caller identifies itself with the id of the transportation service
provider it works for.  Both therefore need per-instance builders: the shared
constants below can only be used where the call is not ownership-gated.

MoveCounselor, ClaimsExaminer and ProgramAdmin are opaque staff identities, so the
shared constants are the canonical form for them.  Two distinct examiner identities
and two distinct administrator identities exist because settlement must be performed
by a different examiner than the reviewer, and a waiver must be granted by a
different administrator than the one who authorized the entitlement.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

# Opaque staff user ids.
COUNSELOR_USER_ID = "counselor-01"
COUNSELOR_ALT_USER_ID = "counselor-02"
ADMIN_USER_ID = "admin-01"
ADMIN_ALT_USER_ID = "admin-02"
EXAMINER_USER_ID = "examiner-01"
EXAMINER_ALT_USER_ID = "examiner-02"

# Fallback identities for calls that never touch an ownership check.
FALLBACK_SERVICE_MEMBER_USER_ID = "service-member-01"
FALLBACK_TSP_USER_ID = "tsp-coordinator-01"


TEST_USERS: Dict[str, Dict[str, str]] = {
    # ServiceMember is backed by a service member record: this shared constant is a
    # fallback for calls that do not exercise ownership (bad payloads, unknown ids).
    "service_member_headers": build_user_headers(
        FALLBACK_SERVICE_MEMBER_USER_ID, "ServiceMember"
    ),
    # TspCoordinator is backed by a provider record: same caveat as above.
    "tsp_coordinator_headers": build_user_headers(
        FALLBACK_TSP_USER_ID, "TspCoordinator"
    ),
    # Opaque roles — the shared constant is the canonical identity.
    "move_counselor_headers": build_user_headers(COUNSELOR_USER_ID, "MoveCounselor"),
    "move_counselor_alt_headers": build_user_headers(
        COUNSELOR_ALT_USER_ID, "MoveCounselor"
    ),
    "claims_examiner_headers": build_user_headers(EXAMINER_USER_ID, "ClaimsExaminer"),
    "claims_examiner_alt_headers": build_user_headers(
        EXAMINER_ALT_USER_ID, "ClaimsExaminer"
    ),
    "program_admin_headers": build_user_headers(ADMIN_USER_ID, "ProgramAdmin"),
    "program_admin_alt_headers": build_user_headers(ADMIN_ALT_USER_ID, "ProgramAdmin"),
}


def make_service_member_headers(service_member_id: str) -> Dict[str, str]:
    """Headers for a ServiceMember caller. Pass the service member's own id so that
    ownership-gated reads and cancellations resolve to this caller."""
    return build_user_headers(service_member_id, "ServiceMember")


def make_tsp_coordinator_headers(tsp_id: str) -> Dict[str, str]:
    """Headers for a TspCoordinator caller. Pass the id of the transportation service
    provider the coordinator acts for, because the provider record is the caller's
    identity for shipment operations."""
    return build_user_headers(tsp_id, "TspCoordinator")


def make_move_counselor_headers(user_id: str = COUNSELOR_USER_ID) -> Dict[str, str]:
    """Headers for a MoveCounselor caller."""
    return build_user_headers(user_id, "MoveCounselor")


def make_claims_examiner_headers(user_id: str = EXAMINER_USER_ID) -> Dict[str, str]:
    """Headers for a ClaimsExaminer caller."""
    return build_user_headers(user_id, "ClaimsExaminer")


def make_program_admin_headers(user_id: str = ADMIN_USER_ID) -> Dict[str, str]:
    """Headers for a ProgramAdmin caller."""
    return build_user_headers(user_id, "ProgramAdmin")


def headers_without_role(user_id: str = COUNSELOR_USER_ID) -> Dict[str, str]:
    """Headers that omit the role header entirely."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_with_unknown_role(
    role: str, user_id: str = COUNSELOR_USER_ID
) -> Dict[str, str]:
    """Headers carrying a role name the PRD does not declare."""
    return build_user_headers(user_id, role)
