"""Pre-built role headers for every role in the PRD (§2.1).

Identity semantics (PRD §2.1): DistrictAdmin / Registrar / SiteTechnician use
opaque operator ids. Family is entity-backed: X-User-ID must equal the id of
the acting StudentAccount for any student-scoped call, so tests and fixtures
MUST build Family headers via make_family_headers(student["id"]).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — shared constants are the canonical form.
    "admin_headers": build_user_headers("test-admin-1", "DistrictAdmin"),
    "registrar_headers": build_user_headers("test-registrar-1", "Registrar"),
    "tech_headers": build_user_headers("test-tech-1", "SiteTechnician"),
    # Entity-backed role: fallback for non-ownership tests ONLY (e.g. RBAC
    # denial where rejection happens before any ownership check).
    "family_headers": build_user_headers("test-family-1", "Family"),
}


def make_family_headers(student_id: str) -> dict:
    """Family is entity-backed by StudentAccount (PRD §2.1): pass the actual
    StudentAccount.id whenever the call is ownership-gated."""
    return build_user_headers(student_id, "Family")
