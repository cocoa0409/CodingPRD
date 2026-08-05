"""Pre-built role headers for every role in the PRD (§2.1).

The Permittee role is entity_backed: X-User-ID must equal the acting Permittee
entity's id, so ownership-gated calls MUST use make_permittee_headers(permittee_id).
The other four roles are opaque — X-User-ID is any operator string.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise
# Permittee ownership (e.g. 401/403/404 on-error paths).
TEST_USERS = {
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "permittee_headers": build_user_headers("test-permittee-1", "Permittee"),
    # opaque roles: shared constant is the canonical form.
    "curb_planner_headers": build_user_headers("planner1", "CurbPlanner"),
    "permit_approver_headers": build_user_headers("approver1", "PermitApprover"),
    "enforcement_officer_headers": build_user_headers("officer1", "EnforcementOfficer"),
    "platform_admin_headers": build_user_headers("admin1", "PlatformAdmin"),
}


# --- Per-instance builder — required for the entity_backed Permittee role. ---
def make_permittee_headers(user_id: str) -> dict:
    """For Permittee (entity_backed:Permittee). Pass the actual Permittee.id as
    user_id whenever the call is ownership-gated (create/confirm/cancel/fulfill
    own permit or reservation, pay/dispute own citation)."""
    return build_user_headers(user_id, "Permittee")


# --- Opaque-role builders — let a test pin a specific X-User-ID (e.g. SoD). ---
def make_curb_planner_headers(user_id: str = "planner1") -> dict:
    return build_user_headers(user_id, "CurbPlanner")


def make_permit_approver_headers(user_id: str = "approver1") -> dict:
    return build_user_headers(user_id, "PermitApprover")


def make_enforcement_officer_headers(user_id: str = "officer1") -> dict:
    return build_user_headers(user_id, "EnforcementOfficer")


def make_platform_admin_headers(user_id: str = "admin1") -> dict:
    return build_user_headers(user_id, "PlatformAdmin")
