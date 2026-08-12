"""Pre-built role headers for every role in the PRD (§2.1).

Shared constants are safe for calls whose success does not depend on the
caller owning the subject resource. For entity-backed roles on
ownership/segregation-of-duties-gated calls, use the per-instance builders
with the acting Contact's id.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # opaque role: shared constant is the canonical form.
    "resilience_admin_headers": build_user_headers("test-admin-1", "ResilienceAdmin"),
    # entity-backed roles: shared constants are fallbacks for non-ownership
    # tests only; prefer the make_*_headers builders with a real Contact id.
    "bia_analyst_headers": build_user_headers("test-bia-analyst-1", "BIAAnalyst"),
    "plan_author_headers": build_user_headers("test-plan-author-1", "PlanAuthor"),
    "plan_approver_headers": build_user_headers("test-plan-approver-1", "PlanApprover"),
    "risk_committee_headers": build_user_headers("test-risk-committee-1", "RiskCommittee"),
    "exercise_officer_headers": build_user_headers("test-exercise-officer-1", "ExerciseOfficer"),
    "site_coordinator_headers": build_user_headers("test-site-coordinator-1", "SiteCoordinator"),
    "vendor_manager_headers": build_user_headers("test-vendor-manager-1", "VendorManager"),
    "crisis_officer_headers": build_user_headers("test-crisis-officer-1", "CrisisOfficer"),
    "attestation_signer_headers": build_user_headers("test-attestation-signer-1", "AttestationSigner"),
}


def make_bia_analyst_headers(user_id: str) -> dict:
    """BIAAnalyst is entity-backed by Contact; pass the acting Contact's id."""
    return build_user_headers(user_id, "BIAAnalyst")


def make_plan_author_headers(user_id: str) -> dict:
    """PlanAuthor is entity-backed by Contact; pass the acting Contact's id."""
    return build_user_headers(user_id, "PlanAuthor")


def make_plan_approver_headers(user_id: str) -> dict:
    """PlanApprover is entity-backed by Contact; pass the acting Contact's id."""
    return build_user_headers(user_id, "PlanApprover")


def make_risk_committee_headers(user_id: str) -> dict:
    """RiskCommittee is entity-backed by Contact; pass the acting Contact's id."""
    return build_user_headers(user_id, "RiskCommittee")


def make_exercise_officer_headers(user_id: str) -> dict:
    """ExerciseOfficer is entity-backed by Contact; pass the acting Contact's id."""
    return build_user_headers(user_id, "ExerciseOfficer")


def make_site_coordinator_headers(user_id: str) -> dict:
    """SiteCoordinator is entity-backed by Contact; pass the acting Contact's id."""
    return build_user_headers(user_id, "SiteCoordinator")


def make_vendor_manager_headers(user_id: str) -> dict:
    """VendorManager is entity-backed by Contact; pass the acting Contact's id."""
    return build_user_headers(user_id, "VendorManager")


def make_crisis_officer_headers(user_id: str) -> dict:
    """CrisisOfficer is entity-backed by Contact; pass the acting Contact's id."""
    return build_user_headers(user_id, "CrisisOfficer")


def make_attestation_signer_headers(user_id: str) -> dict:
    """AttestationSigner is entity-backed by Contact; pass the acting Contact's id."""
    return build_user_headers(user_id, "AttestationSigner")
