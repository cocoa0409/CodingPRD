"""Pre-built role headers for every role in the PRD (§2.1).

All three roles — ComplianceOfficer, HrsaAuditor, PharmacyOperator — are opaque
operator identifiers; none is backed by a persisted entity and the server never
compares X-User-ID to any entity's id (PRD §2.1). So the shared constants below are
the canonical form for every ownership-agnostic call.

The one place X-User-ID matters is the segregation-of-duties rule: a self-disclosed
finding may not be disputed by the same X-User-ID that created it (PRD §3.8). For
that scenario use make_compliance_officer_headers(user_id) to pin a specific id.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "compliance_officer_headers": build_user_headers("test-compliance-officer-1", "ComplianceOfficer"),
    "hrsa_auditor_headers": build_user_headers("test-hrsa-auditor-1", "HrsaAuditor"),
    "pharmacy_operator_headers": build_user_headers("test-pharmacy-operator-1", "PharmacyOperator"),
}


def make_compliance_officer_headers(user_id: str = "test-compliance-officer-1") -> dict:
    """ComplianceOfficer is opaque (PRD §2.1). Pin a specific X-User-ID for the
    segregation-of-duties rule on self-disclosure dispute (PRD §3.8)."""
    return build_user_headers(user_id, "ComplianceOfficer")


def make_hrsa_auditor_headers(user_id: str = "test-hrsa-auditor-1") -> dict:
    """HrsaAuditor is opaque (PRD §2.1)."""
    return build_user_headers(user_id, "HrsaAuditor")


def make_pharmacy_operator_headers(user_id: str = "test-pharmacy-operator-1") -> dict:
    """PharmacyOperator is opaque (PRD §2.1)."""
    return build_user_headers(user_id, "PharmacyOperator")


def make_unknown_role_headers(user_id: str = "ghost-1") -> dict:
    """A request carrying an X-User-Role that is not one of the three known roles;
    used to exercise ERR_UNAUTHENTICATED (PRD §2.1)."""
    return build_user_headers(user_id, "GhostRole")
