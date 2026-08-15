"""Pre-built role headers for every role in the PRD (§2.1).

CenterAdmin, ProgramManager, DesignLead, ShopTechnician, QualityInspector and
FinanceClerk are opaque identities: the server does not compare their
X-User-ID to any entity id, so shared constants are safe for them.

CustomerRep is entity-backed: its X-User-ID must equal the acting Customer's
id whenever the call is ownership-checked, so ownership-gated calls MUST use
make_customer_rep_headers(customer["id"]) — never the shared constant.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for CustomerRep tests that do
# NOT exercise ownership (e.g., role-denied checks).
TEST_USERS = {
    "center_admin_headers": build_user_headers("admin-1", "CenterAdmin"),
    "program_manager_headers": build_user_headers("pm-1", "ProgramManager"),
    "design_lead_headers": build_user_headers("designer-1", "DesignLead"),
    "shop_technician_headers": build_user_headers("tech-1", "ShopTechnician"),
    "quality_inspector_headers": build_user_headers("qi-1", "QualityInspector"),
    "finance_clerk_headers": build_user_headers("fin-1", "FinanceClerk"),
    # entity_backed role: fallback for non-ownership tests only.
    "customer_rep_headers": build_user_headers("test-customer-rep-1", "CustomerRep"),
}


def make_customer_rep_headers(user_id: str) -> dict:
    """For CustomerRep (entity-backed by Customer). Pass the actual
    Customer.id as user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "CustomerRep")


def make_shop_technician_headers(user_id: str) -> dict:
    """ShopTechnician with a controlled X-User-ID (recorded as
    prepared_by_user_id on weight records; needed for sign-off rules)."""
    return build_user_headers(user_id, "ShopTechnician")


def make_quality_inspector_headers(user_id: str) -> dict:
    """QualityInspector with a controlled X-User-ID (compared against
    prepared_by_user_id at weight-record sign-off)."""
    return build_user_headers(user_id, "QualityInspector")
