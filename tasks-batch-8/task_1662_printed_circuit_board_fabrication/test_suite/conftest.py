"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def customer_headers():
    return TEST_USERS["customer_headers"]


@pytest.fixture
def sales_engineer_headers():
    return TEST_USERS["sales_engineer_headers"]


@pytest.fixture
def cam_operator_headers():
    return TEST_USERS["cam_operator_headers"]


@pytest.fixture
def process_engineer_headers():
    return TEST_USERS["process_engineer_headers"]


@pytest.fixture
def quality_inspector_headers():
    return TEST_USERS["quality_inspector_headers"]


@pytest.fixture
def production_planner_headers():
    return TEST_USERS["production_planner_headers"]


@pytest.fixture
def fab_admin_headers():
    return TEST_USERS["fab_admin_headers"]
