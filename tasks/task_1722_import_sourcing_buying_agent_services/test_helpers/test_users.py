"""Pre-built role headers for every role in the PRD.

Opaque-identity roles (PlatformAdmin, ComplianceOfficer) have a single shared
header set. Entity-backed roles (BuyerManager -> Buyer.id, SourcingAgent ->
Agent.id, FactoryRep -> Factory.id, Inspector -> Inspector.id) MUST be built
per acting entity via the make_*_headers builders whenever the call is
ownership-gated; the shared constants exist only for tests whose outcome does
not depend on the caller owning the subject resource (e.g. 400/404 probes).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — canonical shared form.
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "compliance_officer_headers": build_user_headers("test-compliance-officer-1", "ComplianceOfficer"),
    # Entity-backed roles — fallback only for non-ownership probes.
    "buyer_manager_headers": build_user_headers("test-buyer-1", "BuyerManager"),
    "sourcing_agent_headers": build_user_headers("test-agent-1", "SourcingAgent"),
    "factory_rep_headers": build_user_headers("test-factory-1", "FactoryRep"),
    "inspector_headers": build_user_headers("test-inspector-1", "Inspector"),
}


def make_buyer_manager_headers(buyer_id: str) -> dict:
    """BuyerManager is entity-backed by Buyer: pass the acting Buyer's id."""
    return build_user_headers(buyer_id, "BuyerManager")


def make_sourcing_agent_headers(agent_id: str) -> dict:
    """SourcingAgent is entity-backed by Agent: pass the acting Agent's id."""
    return build_user_headers(agent_id, "SourcingAgent")


def make_factory_rep_headers(factory_id: str) -> dict:
    """FactoryRep is entity-backed by Factory: pass the acting Factory's id."""
    return build_user_headers(factory_id, "FactoryRep")


def make_inspector_headers(inspector_id: str) -> dict:
    """Inspector is entity-backed by Inspector: pass the acting Inspector's id."""
    return build_user_headers(inspector_id, "Inspector")
