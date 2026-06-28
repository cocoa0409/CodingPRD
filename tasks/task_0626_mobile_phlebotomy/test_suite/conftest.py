"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def ordering_provider_headers():
    return TEST_USERS["ordering_provider_headers"]


@pytest.fixture
def dispatcher_headers():
    return TEST_USERS["dispatcher_headers"]


@pytest.fixture
def lab_ops_headers():
    return TEST_USERS["lab_ops_headers"]


@pytest.fixture
def billing_agent_headers():
    return TEST_USERS["billing_agent_headers"]


@pytest.fixture
def phlebotomist_headers():
    return TEST_USERS["phlebotomist_headers"]
