"""Pre-built role headers for every role in the PRD (§2.1).

Identity semantics (PRD §2.1): for `ProviderRep`, `X-User-ID` IS the acting
ProviderAccount's `id` — use `make_provider_rep_headers(provider_account["id"])`
for every call that creates or reads ownership-gated resources. The shared
`provider_rep_headers` constant is a fallback only for tests whose outcome does
not depend on owning a specific account (e.g. shape-level rejections).
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for non-ownership-gated calls.
TEST_USERS = {
    "plan_admin_headers": build_user_headers("test-plan-admin-1", "PlanAdmin"),
    "mpo_headers": build_user_headers("test-mpo-1", "MedicalPolicyOfficer"),
    # entity_backed role: fallback for non-ownership tests only.
    "provider_rep_headers": build_user_headers("test-provider-rep-1", "ProviderRep"),
    "case_manager_headers": build_user_headers("test-case-manager-1", "CaseManager"),
    "pharmacy_analyst_headers": build_user_headers(
        "test-pharmacy-analyst-1", "PharmacyAnalyst"
    ),
}


def make_plan_admin_headers(user_id: str = "test-plan-admin-1") -> dict:
    """PlanAdmin (opaque identity)."""
    return build_user_headers(user_id, "PlanAdmin")


def make_mpo_headers(user_id: str = "test-mpo-1") -> dict:
    """MedicalPolicyOfficer (opaque identity). Pass a distinctive id when a test
    asserts `override_by` on an override-approved claim (PRD §3.6)."""
    return build_user_headers(user_id, "MedicalPolicyOfficer")


def make_provider_rep_headers(user_id: str) -> dict:
    """ProviderRep (entity-backed by ProviderAccount). ALWAYS pass the actual
    ProviderAccount.id whenever the call is ownership-gated (PRD §2.1)."""
    return build_user_headers(user_id, "ProviderRep")


def make_case_manager_headers(user_id: str = "test-case-manager-1") -> dict:
    """CaseManager (opaque identity)."""
    return build_user_headers(user_id, "CaseManager")


def make_pharmacy_analyst_headers(user_id: str = "test-pharmacy-analyst-1") -> dict:
    """PharmacyAnalyst (opaque identity)."""
    return build_user_headers(user_id, "PharmacyAnalyst")
