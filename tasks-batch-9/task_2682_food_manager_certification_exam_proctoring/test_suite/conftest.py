"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def platform_admin_alt_headers():
    return TEST_USERS["platform_admin_alt_headers"]


@pytest.fixture
def scoring_admin_headers():
    return TEST_USERS["scoring_admin_headers"]


@pytest.fixture
def security_admin_headers():
    return TEST_USERS["security_admin_headers"]


@pytest.fixture
def provider_admin_headers():
    return TEST_USERS["provider_admin_headers"]


@pytest.fixture
def proctor_headers():
    return TEST_USERS["proctor_headers"]


@pytest.fixture
def candidate_headers():
    return TEST_USERS["candidate_headers"]


@pytest.fixture
def health_officer_headers():
    return TEST_USERS["health_officer_headers"]
