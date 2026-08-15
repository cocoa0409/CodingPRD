"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def trader_headers():
    return TEST_USERS["trader_headers"]


@pytest.fixture
def risk_manager_headers():
    return TEST_USERS["risk_manager_headers"]


@pytest.fixture
def logistics_headers():
    return TEST_USERS["logistics_headers"]


@pytest.fixture
def warehouse_headers():
    return TEST_USERS["warehouse_headers"]


@pytest.fixture
def head_roaster_headers():
    return TEST_USERS["head_roaster_headers"]


@pytest.fixture
def roast_operator_headers():
    return TEST_USERS["roast_operator_headers"]


@pytest.fixture
def qa_grader_headers():
    return TEST_USERS["qa_grader_headers"]


@pytest.fixture
def fulfillment_planner_headers():
    return TEST_USERS["fulfillment_planner_headers"]


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]
