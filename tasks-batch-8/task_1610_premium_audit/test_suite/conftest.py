"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def insured_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["insured_headers"]


@pytest.fixture
def auditor_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["auditor_headers"]


@pytest.fixture
def audit_manager_headers():
    return TEST_USERS["audit_manager_headers"]


@pytest.fixture
def underwriter_headers():
    return TEST_USERS["underwriter_headers"]


@pytest.fixture
def billing_clerk_headers():
    return TEST_USERS["billing_clerk_headers"]
