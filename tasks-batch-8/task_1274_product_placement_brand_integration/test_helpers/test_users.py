"""Pre-built role headers for every role in the PRD (§2.1).

BrandRep is entity-backed: its X-User-ID must equal the Brand's id whenever
the call is ownership-gated (brief create/submit/close, report dispute).
All other roles are opaque operator identifiers.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles: shared constants are the canonical form.
    "admin_headers": build_user_headers("admin-1", "AgencyAdmin"),
    "manager_headers": build_user_headers("mgr-1", "IntegrationManager"),
    # ProductionRep: two operators are needed for segregation-of-duties tests
    # (episode creator vs deciding representative).
    "production_headers": build_user_headers("prod-1", "ProductionRep"),
    "production_alt_headers": build_user_headers("prod-2", "ProductionRep"),
    "network_headers": build_user_headers("nsr-1", "NetworkStandardsReviewer"),
    "clearance_headers": build_user_headers("co-1", "ClearanceOfficer"),
    "clearance_alt_headers": build_user_headers("co-2", "ClearanceOfficer"),
    # VerificationAnalyst: two operators for filer-vs-verifier segregation.
    "verifier_headers": build_user_headers("ver-1", "VerificationAnalyst"),
    "verifier_alt_headers": build_user_headers("ver-2", "VerificationAnalyst"),
    # BrandRep is entity-backed; this shared constant is ONLY safe for tests
    # that do not exercise ownership (e.g. role-denial probes on other
    # resources). Ownership-gated calls MUST use make_brand_rep_headers.
    "brand_rep_headers": build_user_headers("test-brand-rep-1", "BrandRep"),
}


def make_brand_rep_headers(brand_id: str) -> dict:
    """BrandRep is entity-backed by Brand (PRD §2.1): X-User-ID must equal the
    Brand's id for ownership-gated calls (brief create/submit/close, dispute)."""
    return build_user_headers(brand_id, "BrandRep")


def make_production_rep_headers(user_id: str) -> dict:
    """ProductionRep is opaque; pick a stable operator id when a specific one
    is needed (e.g. the episode creator vs the deciding representative)."""
    return build_user_headers(user_id, "ProductionRep")


def make_verification_analyst_headers(user_id: str) -> dict:
    """VerificationAnalyst is opaque; filer and verifier must differ (PRD §3.7)."""
    return build_user_headers(user_id, "VerificationAnalyst")


def make_clearance_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ClearanceOfficer")


def make_network_reviewer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "NetworkStandardsReviewer")
