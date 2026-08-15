"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for the eight opaque-identity roles and for any test
# whose success does not depend on the caller owning the subject resource.
TEST_USERS = {
    "project_manager_headers": build_user_headers("pm-001", "ProjectManager"),
    "qa_manager_headers": build_user_headers("qa-001", "QAManager"),
    "design_engineer_headers": build_user_headers("de-001", "DesignEngineer"),
    "shop_lead_headers": build_user_headers("sl-001", "ShopLead"),
    "test_technician_headers": build_user_headers("tt-001", "TestTechnician"),
    "controls_engineer_headers": build_user_headers("ce-001", "ControlsEngineer"),
    "field_engineer_headers": build_user_headers("fe-001", "FieldEngineer"),
    "shipping_clerk_headers": build_user_headers("sc-001", "ShippingClerk"),
    # entity_backed role: fallback only for non-ownership tests.
    "customer_headers": build_user_headers("cust-anon-1", "Customer"),
}


def make_customer_headers(customer_id: str) -> dict:
    """For Customer (entity_backed: Customer). Pass the actual Customer.id as
    customer_id whenever the call is ownership-gated (PRD §2.1)."""
    return build_user_headers(customer_id, "Customer")


def make_pm_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ProjectManager")


def make_qa_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "QAManager")


def make_designer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "DesignEngineer")


def make_shop_lead_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ShopLead")


def make_technician_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "TestTechnician")


def make_controls_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ControlsEngineer")


def make_field_engineer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "FieldEngineer")
