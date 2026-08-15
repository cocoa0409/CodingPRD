"""Pre-built role headers for every role in the PRD.

Shipper is entity_backed: X-User-ID must equal the acting Shipper entity's id
on every ownership-gated call (booking create/cancel/roll, B/L surrender,
claim filing) — always use make_shipper_headers(shipper["id"]) there.

All desk roles (BookingCoordinator, DocumentationOfficer, ComplianceOfficer,
FinanceController, ClaimsAdjuster, OperationsManager) are opaque: X-User-ID is
recorded but never compared to an entity id. Segregation-of-duties pairs need
distinct user ids on each side, so fixtures use the per-role builders with
canonical ids ("co_1"/"co_2", "doc_1"/"doc_2", "adj_1"/"adj_2").
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that do not exercise
# shipper ownership (400-on-bad-payload, 404-on-missing-resource, wrong-role).
TEST_USERS = {
    "shipper_headers": build_user_headers("test-shipper-1", "Shipper"),
    "coordinator_headers": build_user_headers("bc_1", "BookingCoordinator"),
    "doc_officer_headers": build_user_headers("doc_1", "DocumentationOfficer"),
    "compliance_headers": build_user_headers("co_1", "ComplianceOfficer"),
    "finance_headers": build_user_headers("fc_1", "FinanceController"),
    "adjuster_headers": build_user_headers("adj_1", "ClaimsAdjuster"),
    "ops_headers": build_user_headers("ops_1", "OperationsManager"),
}


def make_shipper_headers(shipper_id: str) -> dict:
    """For Shipper (entity_backed:Shipper). Pass the actual Shipper.id
    whenever the call is ownership-gated."""
    return build_user_headers(shipper_id, "Shipper")


def make_coordinator_headers(user_id: str = "bc_1") -> dict:
    return build_user_headers(user_id, "BookingCoordinator")


def make_doc_officer_headers(user_id: str = "doc_1") -> dict:
    return build_user_headers(user_id, "DocumentationOfficer")


def make_compliance_headers(user_id: str = "co_1") -> dict:
    return build_user_headers(user_id, "ComplianceOfficer")


def make_finance_headers(user_id: str = "fc_1") -> dict:
    return build_user_headers(user_id, "FinanceController")


def make_adjuster_headers(user_id: str = "adj_1") -> dict:
    return build_user_headers(user_id, "ClaimsAdjuster")


def make_ops_headers(user_id: str = "ops_1") -> dict:
    return build_user_headers(user_id, "OperationsManager")
