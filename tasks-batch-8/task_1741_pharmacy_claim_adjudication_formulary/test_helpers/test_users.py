"""Pre-built role headers for every role in the PRD (§2.1).

Two roles are entity-backed: a Pharmacist's X-User-ID must be the acting Pharmacy's
id, and a Member's X-User-ID must be the acting Member's id. For those, always use
the per-instance builders with the real entity id whenever the call is
ownership-gated. The shared constants are safe for opaque roles and for tests whose
outcome does not depend on ownership (400-shape checks, 404 checks, etc.).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — canonical form.
    "pbm_admin_headers": build_user_headers("test-pbm-admin-1", "PbmAdmin"),
    "clinical_reviewer_headers": build_user_headers("test-reviewer-1", "ClinicalReviewer"),
    "auditor_headers": build_user_headers("test-auditor-1", "Auditor"),
    # Entity-backed roles — fallback only for non-ownership tests.
    "pharmacist_headers": build_user_headers("test-pharmacist-1", "Pharmacist"),
    "member_headers": build_user_headers("test-member-1", "Member"),
}


def make_pharmacist_headers(pharmacy_id: str) -> dict:
    """Pharmacist is entity-backed by Pharmacy: pass the real Pharmacy.id."""
    return build_user_headers(pharmacy_id, "Pharmacist")


def make_member_headers(member_id: str) -> dict:
    """Member is entity-backed by Member: pass the real Member.id."""
    return build_user_headers(member_id, "Member")
