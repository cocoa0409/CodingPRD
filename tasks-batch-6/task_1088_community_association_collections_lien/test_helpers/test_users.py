"""Pre-built role headers for every role in the PRD.

CollectionsAgent, ComplianceOfficer, and TrustAccountant are opaque operator
identities — their X-User-ID is not compared to any persisted entity.
AssociationManager is entity_backed:Association — its X-User-ID must equal the
acting Association's id, so ownership-gated reads use make_association_manager_headers.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "collections_agent_headers": build_user_headers("agent-1", "CollectionsAgent"),
    "compliance_officer_headers": build_user_headers("officer-1", "ComplianceOfficer"),
    "trust_accountant_headers": build_user_headers("trustee-1", "TrustAccountant"),
}

# Anonymous / unauthenticated request: no role header at all.
ANON_HEADERS = {"Content-Type": "application/json"}


def make_collections_agent_headers(user_id: str = "agent-1") -> dict:
    return build_user_headers(user_id, "CollectionsAgent")


def make_compliance_officer_headers(user_id: str) -> dict:
    """For ComplianceOfficer. Distinct user_ids drive the maker-checker SoD
    (a referral's officer must differ from the lien's recording officer)."""
    return build_user_headers(user_id, "ComplianceOfficer")


def make_trust_accountant_headers(user_id: str = "trustee-1") -> dict:
    return build_user_headers(user_id, "TrustAccountant")


def make_association_manager_headers(association_id: str) -> dict:
    """For AssociationManager (entity_backed:Association). Pass the acting
    Association.id as X-User-ID so ownership checks resolve to that association."""
    return build_user_headers(association_id, "AssociationManager")
