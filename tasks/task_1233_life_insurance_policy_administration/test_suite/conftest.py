"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def agent_headers():
    return TEST_USERS["agent_headers"]


@pytest.fixture
def underwriter_headers():
    return TEST_USERS["underwriter_headers"]


@pytest.fixture
def policy_issuer_headers():
    return TEST_USERS["policy_issuer_headers"]


@pytest.fixture
def policyholder_headers():
    return TEST_USERS["policyholder_headers"]
