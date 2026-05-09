"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def pickup_op_headers():
    return TEST_USERS["pickup_operator_headers"]


@pytest.fixture
def cs_agent_headers():
    return TEST_USERS["customer_service_headers"]
