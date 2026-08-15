"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise
# ownership. For the entity_backed BrandRep role, use make_brand_rep_headers()
# with the actual Brand.id whenever the call is ownership-gated.
TEST_USERS = {
    "verifier_admin_headers": build_user_headers("test-admin-1", "VerifierAdmin"),
    "lab_analyst_1_headers": build_user_headers("lab-1", "LabAnalyst"),
    "lab_analyst_2_headers": build_user_headers("lab-2", "LabAnalyst"),
    "auditor_1_headers": build_user_headers("aud-1", "Auditor"),
    "auditor_2_headers": build_user_headers("aud-2", "Auditor"),
    "officer_1_headers": build_user_headers("eo-1", "EnforcementOfficer"),
    "officer_2_headers": build_user_headers("eo-2", "EnforcementOfficer"),
    # BrandRep shared constant is a fallback for non-ownership tests only.
    "brand_rep_headers": build_user_headers("test-brandrep-1", "BrandRep"),
}


def make_brand_rep_headers(brand_id: str) -> dict:
    """BrandRep is entity_backed:Brand — pass the actual Brand.id whenever the
    call is ownership-gated (product/ingredient/affidavit writes)."""
    return build_user_headers(brand_id, "BrandRep")
