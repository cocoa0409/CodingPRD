"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]


@pytest.fixture
def coordinator_headers():
    return TEST_USERS["coordinator_headers"]


@pytest.fixture
def funder_admin_headers():
    return TEST_USERS["funder_admin_headers"]


@pytest.fixture
def caregiver_headers():
    return TEST_USERS["caregiver_headers"]


@pytest.fixture
def provider_headers():
    return TEST_USERS["provider_headers"]
