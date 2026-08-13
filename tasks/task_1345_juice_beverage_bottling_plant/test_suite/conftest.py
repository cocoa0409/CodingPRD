"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def plant_manager_headers():
    return TEST_USERS["plant_manager_headers"]


@pytest.fixture
def finance_clerk_headers():
    return TEST_USERS["finance_clerk_headers"]


@pytest.fixture
def product_developer_headers():
    return TEST_USERS["product_developer_headers"]


@pytest.fixture
def label_reviewer_headers():
    return TEST_USERS["label_reviewer_headers"]


@pytest.fixture
def blend_operator_headers():
    return TEST_USERS["blend_operator_headers"]


@pytest.fixture
def qa_inspector_headers():
    return TEST_USERS["qa_inspector_headers"]


@pytest.fixture
def production_planner_headers():
    return TEST_USERS["production_planner_headers"]


@pytest.fixture
def warehouse_lead_headers():
    return TEST_USERS["warehouse_lead_headers"]


@pytest.fixture
def customer_service_rep_headers():
    return TEST_USERS["customer_service_rep_headers"]
