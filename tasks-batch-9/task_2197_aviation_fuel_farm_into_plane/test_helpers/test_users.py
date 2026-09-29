"""Pre-built role headers for every role the PRD defines.

For `AirlineRep` the `X-User-ID` is the id of the acting AirlineAccount, so ownership-gated
calls MUST use ``make_airline_rep_headers(account["id"])``. The other six roles carry an
opaque operator identifier that is never compared to any entity id, so the shared constants
below are the canonical form for them — except where segregation of duties requires two
distinct operator identifiers, which is why several numbered variants exist.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "admin_headers": build_user_headers("test-admin-1", "ConsortiumAdmin"),
    "admin2_headers": build_user_headers("test-admin-2", "ConsortiumAdmin"),
    "operator_headers": build_user_headers("test-operator-1", "FarmOperator"),
    "operator2_headers": build_user_headers("test-operator-2", "FarmOperator"),
    "inspector_headers": build_user_headers("test-inspector-1", "QualityInspector"),
    "inspector2_headers": build_user_headers("test-inspector-2", "QualityInspector"),
    "inspector3_headers": build_user_headers("test-inspector-3", "QualityInspector"),
    "agent_headers": build_user_headers("test-agent-1", "IntoPlaneAgent"),
    "agent2_headers": build_user_headers("test-agent-2", "IntoPlaneAgent"),
    # entity_backed role: this shared constant is only safe for tests that never reach an
    # ownership check (bad payload, missing resource, role-membership rejection).
    "airline_rep_headers": build_user_headers("test-airline-rep-1", "AirlineRep"),
    "environmental_headers": build_user_headers("test-enviro-1", "EnvironmentalOfficer"),
    "environmental2_headers": build_user_headers("test-enviro-2", "EnvironmentalOfficer"),
    "billing_headers": build_user_headers("test-billing-1", "BillingClerk"),
    "billing2_headers": build_user_headers("test-billing-2", "BillingClerk"),
    "billing3_headers": build_user_headers("test-billing-3", "BillingClerk"),
}


def make_airline_rep_headers(airline_account_id: str) -> dict:
    """For AirlineRep: X-User-ID is the id of the acting AirlineAccount."""
    return build_user_headers(airline_account_id, "AirlineRep")


def make_admin_headers(user_id: str = "test-admin-1") -> dict:
    return build_user_headers(user_id, "ConsortiumAdmin")


def make_operator_headers(user_id: str = "test-operator-1") -> dict:
    return build_user_headers(user_id, "FarmOperator")


def make_inspector_headers(user_id: str) -> dict:
    """Distinct inspector identities matter for segregation of duties."""
    return build_user_headers(user_id, "QualityInspector")


def make_agent_headers(user_id: str = "test-agent-1") -> dict:
    return build_user_headers(user_id, "IntoPlaneAgent")


def make_environmental_headers(user_id: str = "test-enviro-1") -> dict:
    return build_user_headers(user_id, "EnvironmentalOfficer")


def make_billing_headers(user_id: str) -> dict:
    """Distinct clerk identities matter for dispute-resolution segregation of duties."""
    return build_user_headers(user_id, "BillingClerk")


ROLE_TO_HEADERS = {
    "ConsortiumAdmin": TEST_USERS["admin_headers"],
    "FarmOperator": TEST_USERS["operator_headers"],
    "QualityInspector": TEST_USERS["inspector_headers"],
    "IntoPlaneAgent": TEST_USERS["agent_headers"],
    "AirlineRep": TEST_USERS["airline_rep_headers"],
    "EnvironmentalOfficer": TEST_USERS["environmental_headers"],
    "BillingClerk": TEST_USERS["billing_headers"],
}
