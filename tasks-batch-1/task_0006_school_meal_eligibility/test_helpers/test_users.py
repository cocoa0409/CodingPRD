"""Pre-built role headers for every role in the PRD.

Per PRD §2.1:
- `Parent` is the only entity_backed role: X-User-ID must equal the acting
  Household.id. For any ownership-gated call (application submit/appeal/withdraw,
  parent-account top-up, transaction dispute), tests MUST call
  `make_parent_headers(household_id)` so the FK ownership check passes. The
  shared `parent_headers` constant is only safe for tests that do NOT exercise
  ownership (e.g. a Parent attempting a SchoolStaff-only endpoint to provoke
  403, or a Parent invoking an opaque-role endpoint).
- `SchoolStaff`, `DistrictReviewer`, `USDAAuditor`, and `PlatformAdmin` are
  opaque operator identities: the server records X-User-ID for audit but does
  not compare it to any entity's id. The shared constants are canonical for
  those roles.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS: dict = {
    # opaque roles — shared constant is canonical
    "school_staff_headers": build_user_headers("test-school-staff", "SchoolStaff"),
    "district_reviewer_headers": build_user_headers(
        "test-district-reviewer", "DistrictReviewer"
    ),
    "usda_auditor_headers": build_user_headers("test-usda-auditor", "USDAAuditor"),
    "platform_admin_headers": build_user_headers("test-platform-admin", "PlatformAdmin"),
    # entity_backed Parent — fallback for non-ownership tests only
    "parent_headers": build_user_headers("test-parent-fallback", "Parent"),
}


def make_parent_headers(household_id: str) -> dict:
    """Required for any Parent-role call whose target is owned by the household —
    POST /applications/{id}/submit, /appeal, /withdraw; POST /parent-accounts/{id}/topup;
    POST /service-transactions/{id}/dispute; PATCH /households/{id} as Parent; etc.
    """
    return build_user_headers(household_id, "Parent")


def make_unauthenticated_headers() -> dict:
    """Headers that deliberately omit X-User-Role to trigger ERR_UNAUTHENTICATED."""
    return {"Content-Type": "application/json"}


def make_role_headers(role: str, user_id: str = "test-opaque") -> dict:
    """General-purpose builder for opaque roles. Useful for tests that need
    a non-canonical user_id under an opaque role."""
    return build_user_headers(user_id, role)
