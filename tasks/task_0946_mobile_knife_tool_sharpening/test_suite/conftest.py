"""Pytest fixtures exposing the domain test infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is owned by the runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def dispatcher_headers():
    return TEST_USERS["dispatcher_headers"]


@pytest.fixture
def clerk_headers():
    return TEST_USERS["billing_clerk_headers"]


@pytest.fixture
def account_owner_headers():
    """Shared AccountOwner headers. Ownership-gated calls must instead use
    make_account_owner_headers(account["id"])."""
    return TEST_USERS["account_owner_headers"]


@pytest.fixture
def technician_headers():
    """Shared Technician headers. Ownership-gated calls must instead use
    make_technician_headers(technician["id"])."""
    return TEST_USERS["technician_headers"]
