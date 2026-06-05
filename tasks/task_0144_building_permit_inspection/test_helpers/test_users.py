"""Pre-built role headers for every role in the PRD (§2.1).

Two of the five roles are entity-backed: when X-User-Role is PlanReviewer the
X-User-ID is the PlanReviewer entity's id, and likewise for Inspector. Ownership
and segregation-of-duties checks compare those ids. The remaining three roles
(Applicant, PermitClerk, BuildingOfficial) carry opaque operator identifiers not
tied to any persisted entity.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants. Safe for opaque roles (Applicant/PermitClerk/BuildingOfficial)
# and for non-ownership tests. Entity-backed roles MUST use the per-instance
# builders below whenever a call is ownership- or segregation-gated.
TEST_USERS = {
    "applicant_headers": build_user_headers("operator-applicant-1", "Applicant"),
    "clerk_headers": build_user_headers("operator-clerk-1", "PermitClerk"),
    "official_headers": build_user_headers("operator-official-1", "BuildingOfficial"),
    # Entity-backed fallbacks for non-ownership tests only (e.g. 403/404 probes).
    "reviewer_headers": build_user_headers("test-reviewer-1", "PlanReviewer"),
    "inspector_headers": build_user_headers("test-inspector-1", "Inspector"),
}


def make_applicant_headers(user_id: str = "operator-applicant-1") -> dict:
    return build_user_headers(user_id, "Applicant")


def make_clerk_headers(user_id: str = "operator-clerk-1") -> dict:
    return build_user_headers(user_id, "PermitClerk")


def make_official_headers(user_id: str = "operator-official-1") -> dict:
    return build_user_headers(user_id, "BuildingOfficial")


def make_reviewer_headers(user_id: str) -> dict:
    """For PlanReviewer (entity_backed:PlanReviewer). Pass the PlanReviewer.id
    as user_id whenever the call is ownership-gated (open/decide review,
    attach correction notice)."""
    return build_user_headers(user_id, "PlanReviewer")


def make_inspector_headers(user_id: str) -> dict:
    """For Inspector (entity_backed:Inspector). Pass the Inspector.id as user_id
    whenever the call is segregation-gated (record FINAL inspection result)."""
    return build_user_headers(user_id, "Inspector")
