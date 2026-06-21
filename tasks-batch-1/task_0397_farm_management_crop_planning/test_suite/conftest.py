"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def farm_manager_headers():
    return TEST_USERS["farm_manager_headers"]


@pytest.fixture
def agronomist_headers():
    return TEST_USERS["agronomist_headers"]


@pytest.fixture
def applicator_headers():
    return TEST_USERS["applicator_headers"]


@pytest.fixture
def sales_agent_headers():
    return TEST_USERS["sales_agent_headers"]
