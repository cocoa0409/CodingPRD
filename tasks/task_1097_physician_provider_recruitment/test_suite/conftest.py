"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def recruiter_headers():
    return TEST_USERS["recruiter_headers"]


@pytest.fixture
def account_manager_headers():
    return TEST_USERS["account_manager_headers"]


@pytest.fixture
def credentialing_coordinator_headers():
    return TEST_USERS["credentialing_coordinator_headers"]


@pytest.fixture
def client_contact_headers():
    return TEST_USERS["client_contact_headers"]
