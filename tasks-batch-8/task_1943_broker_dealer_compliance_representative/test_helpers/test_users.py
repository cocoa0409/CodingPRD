"""Pre-built role headers for every role in the PRD (§2.1).

RegisteredRep is entity-backed: its X-User-ID must be the acting
RegisteredRepresentative's id, so ownership-gated calls MUST use
make_registered_rep_headers(rep["id"]) — never the shared constant.
Opaque roles (FirmAdmin, ComplianceAnalyst, CompliancePrincipal, Any) carry
operator identifiers; segregation-of-duties tests distinguish principals by id
("principal-a" vs "principal-b") and WSP drafters/publishers by id.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "firm_admin_headers": build_user_headers("firm-admin-1", "FirmAdmin"),
    "analyst_headers": build_user_headers("analyst-1", "ComplianceAnalyst"),
    "principal_a_headers": build_user_headers("principal-a", "CompliancePrincipal"),
    "principal_b_headers": build_user_headers("principal-b", "CompliancePrincipal"),
    "any_headers": build_user_headers("any-reader-1", "Any"),
    # Fallback for non-ownership RegisteredRep calls only (e.g. 400/404 probes).
    "rep_headers": build_user_headers("test-rep-unbound", "RegisteredRep"),
}


def make_firm_admin_headers(user_id: str) -> dict:
    """FirmAdmin (opaque)."""
    return build_user_headers(user_id, "FirmAdmin")


def make_analyst_headers(user_id: str) -> dict:
    """ComplianceAnalyst (opaque). Use a distinct id for WSP SoD drafting."""
    return build_user_headers(user_id, "ComplianceAnalyst")


def make_principal_headers(user_id: str) -> dict:
    """CompliancePrincipal (opaque). Use distinct ids for escalation SoD."""
    return build_user_headers(user_id, "CompliancePrincipal")


def make_registered_rep_headers(user_id: str) -> dict:
    """RegisteredRep (entity-backed: X-User-ID must be the rep's id).

    Pass the actual RegisteredRepresentative.id whenever the call is
    ownership-gated (OBA create/withdraw, attestation attest).
    """
    return build_user_headers(user_id, "RegisteredRep")


def make_any_headers(user_id: str) -> dict:
    """Any (umbrella read role)."""
    return build_user_headers(user_id, "Any")
