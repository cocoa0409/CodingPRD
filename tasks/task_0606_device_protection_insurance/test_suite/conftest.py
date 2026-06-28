"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def adjuster_headers():
    return TEST_USERS["claims_adjuster_headers"]


@pytest.fixture
def logistics_headers():
    return TEST_USERS["logistics_agent_headers"]


@pytest.fixture
def subscriber_headers():
    return TEST_USERS["subscriber_headers"]
