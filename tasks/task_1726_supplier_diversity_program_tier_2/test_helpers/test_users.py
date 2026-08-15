"""Pre-built role headers for every role in the PRD.

DiversityAdmin, DiversityAnalyst, BusinessUnitLead, and Auditor are opaque
identities: X-User-ID is not tied to any persisted entity, but the server
records it on resources (submitted_by_user_id, verified_by_user_id,
created_by_user_id, auditor_user_id, ...) and segregation-of-duties and
ownership clauses compare against those recorded strings — so the fixed
numbered identities below (admin-1 vs admin-2, analyst-1 vs analyst-2,
auditor-8 vs auditor-9, lead-1 vs lead-2) matter and must be threaded exactly.

PrimeContact is entity-backed by Supplier: X-User-ID IS the acting Supplier's
id. Ownership-gated tier-2 calls MUST use make_prime_contact_headers() with
the real supplier id; the shared prime fallback exists only for tests that do
not exercise ownership.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — canonical shared constants.
    "admin_1_headers": build_user_headers("admin-1", "DiversityAdmin"),
    "admin_2_headers": build_user_headers("admin-2", "DiversityAdmin"),
    "analyst_1_headers": build_user_headers("analyst-1", "DiversityAnalyst"),
    "analyst_2_headers": build_user_headers("analyst-2", "DiversityAnalyst"),
    "lead_1_headers": build_user_headers("lead-1", "BusinessUnitLead"),
    "lead_2_headers": build_user_headers("lead-2", "BusinessUnitLead"),
    "auditor_8_headers": build_user_headers("auditor-8", "Auditor"),
    "auditor_9_headers": build_user_headers("auditor-9", "Auditor"),
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "prime_headers": build_user_headers("test-prime-1", "PrimeContact"),
}


def make_diversity_admin_headers(user_id: str = "admin-1") -> dict:
    return build_user_headers(user_id, "DiversityAdmin")


def make_diversity_analyst_headers(user_id: str = "analyst-1") -> dict:
    return build_user_headers(user_id, "DiversityAnalyst")


def make_business_unit_lead_headers(user_id: str = "lead-1") -> dict:
    """For BusinessUnitLead (opaque, but scope-gated: X-User-ID must equal the
    event's BusinessUnit.lead_user_id on open/award/cancel/invite/respond)."""
    return build_user_headers(user_id, "BusinessUnitLead")


def make_auditor_headers(user_id: str = "auditor-9") -> dict:
    return build_user_headers(user_id, "Auditor")


def make_prime_contact_headers(supplier_id: str) -> dict:
    """For PrimeContact (entity_backed:Supplier). Pass the acting Supplier.id
    whenever the call is ownership-gated (create/edit/submit tier-2 reports)."""
    return build_user_headers(supplier_id, "PrimeContact")
