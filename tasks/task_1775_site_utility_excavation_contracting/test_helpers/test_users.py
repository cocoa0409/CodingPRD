"""Pre-built role headers for every role in the PRD (§2.1, §4).

`UtilityOwnerRep` is entity-backed: its `X-User-ID` must equal the id of the
`UtilityOwner` the rep acts for (PRD §2.1). For any ownership-gated call use
``make_utility_owner_rep_headers(owner["id"])`` — never the shared constant.

The other five roles are opaque operator identities; the shared constants are
canonical for them.
"""

from prd_bench_local_runner.testing import build_user_headers

# Canonical opaque user identifiers used across the suite. Where segregation
# of duties applies, the reviewer/confirmer id always differs from the
# submitter/recorder id (PRD §2.1).
OPS_USER = "ops-1"
PM_USER = "pm-1"
PM_SECOND = "pm-2"
FOREMAN_USER = "foreman-1"
SAFETY_USER = "safety-1"
INSPECTOR_USER = "insp-1"
INSPECTOR_SECOND = "insp-2"

TEST_USERS = {
    "ops_admin_headers": build_user_headers(OPS_USER, "OpsAdmin"),
    "project_manager_headers": build_user_headers(PM_USER, "ProjectManager"),
    "foreman_headers": build_user_headers(FOREMAN_USER, "Foreman"),
    "safety_officer_headers": build_user_headers(SAFETY_USER, "SafetyOfficer"),
    "inspector_headers": build_user_headers(INSPECTOR_USER, "Inspector"),
    # Fallback only — never valid for an ownership-gated call, because the id
    # matches no real UtilityOwner. Use make_utility_owner_rep_headers instead.
    "utility_owner_rep_headers": build_user_headers(
        "test-owner-rep-1", "UtilityOwnerRep"
    ),
}

# Short aliases for module import convenience.
OPS_ADMIN = TEST_USERS["ops_admin_headers"]
PROJECT_MANAGER = TEST_USERS["project_manager_headers"]
FOREMAN = TEST_USERS["foreman_headers"]
SAFETY_OFFICER = TEST_USERS["safety_officer_headers"]
INSPECTOR = TEST_USERS["inspector_headers"]


def make_ops_admin_headers(user_id: str = OPS_USER) -> dict:
    return build_user_headers(user_id, "OpsAdmin")


def make_project_manager_headers(user_id: str = PM_USER) -> dict:
    return build_user_headers(user_id, "ProjectManager")


def make_foreman_headers(user_id: str = FOREMAN_USER) -> dict:
    return build_user_headers(user_id, "Foreman")


def make_safety_officer_headers(user_id: str = SAFETY_USER) -> dict:
    return build_user_headers(user_id, "SafetyOfficer")


def make_inspector_headers(user_id: str = INSPECTOR_USER) -> dict:
    return build_user_headers(user_id, "Inspector")


def make_utility_owner_rep_headers(owner_id: str) -> dict:
    """UtilityOwnerRep is entity-backed: pass the actual UtilityOwner.id."""
    return build_user_headers(owner_id, "UtilityOwnerRep")
