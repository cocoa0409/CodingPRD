"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def library_admin_headers():
    return TEST_USERS["library_admin_headers"]


@pytest.fixture
def library_clerk_headers():
    return TEST_USERS["library_clerk_headers"]


@pytest.fixture
def returns_clerk_headers():
    return TEST_USERS["returns_clerk_headers"]


@pytest.fixture
def billing_manager_headers():
    return TEST_USERS["billing_manager_headers"]


@pytest.fixture
def rights_advisor_headers():
    return TEST_USERS["rights_advisor_headers"]


@pytest.fixture
def customer_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["customer_headers"]
