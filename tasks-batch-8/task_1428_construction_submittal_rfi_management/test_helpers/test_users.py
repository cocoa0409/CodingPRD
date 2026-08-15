"""Pre-built role headers for every role in the PRD (§2.1).

Identity semantics (PRD §2.1): Reviewer and SubcontractorRep are
entity-backed — their X-User-ID must equal the acting Reviewer /
Subcontractor entity's id whenever an ownership check applies, so those
calls MUST use make_reviewer_headers(entity_id) /
make_subcontractor_rep_headers(entity_id). The other four roles are
opaque operator identifiers; the shared constants are canonical for them.
SoD scenarios (PRD §3.6) additionally need explicit operator ids, hence
make_*_headers builders for the opaque roles too.
"""
from prd_bench_local_runner.testing import build_user_headers

# Named operator personas for segregation-of-duties scenarios (PRD §3.6):
# the engineer who prices must differ from the manager who accepts.
PE_USER_ID = "op-pe-1"
PM_USER_ID = "op-pm-1"

TEST_USERS = {
    # Opaque roles: shared constants are canonical.
    "platform_admin_headers": build_user_headers("op-pa-1", "PlatformAdmin"),
    "project_manager_headers": build_user_headers(PM_USER_ID, "ProjectManager"),
    "project_engineer_headers": build_user_headers(PE_USER_ID, "ProjectEngineer"),
    "owner_rep_headers": build_user_headers("op-or-1", "OwnerRep"),
    # Entity-backed roles: fallbacks for non-ownership tests only.
    "reviewer_headers": build_user_headers("reviewer-unbound-1", "Reviewer"),
    "subcontractor_rep_headers": build_user_headers(
        "subcontractor-unbound-1", "SubcontractorRep"
    ),
}


def make_platform_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_project_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ProjectManager")


def make_project_engineer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ProjectEngineer")


def make_owner_rep_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "OwnerRep")


def make_reviewer_headers(user_id: str) -> dict:
    """Reviewer is entity_backed — pass the actual Reviewer.id whenever the
    call is ownership-gated (revision return, RFI answer; PRD §2.1)."""
    return build_user_headers(user_id, "Reviewer")


def make_subcontractor_rep_headers(user_id: str) -> dict:
    """SubcontractorRep is entity_backed — pass the actual Subcontractor.id
    whenever the call is ownership-gated (revision submit, acknowledge; PRD §2.1)."""
    return build_user_headers(user_id, "SubcontractorRep")
