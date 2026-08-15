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
def records_manager_headers():
    return TEST_USERS["records_manager_headers"]


@pytest.fixture
def legal_counsel_headers():
    return TEST_USERS["legal_counsel_headers"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["auditor_headers"]


@pytest.fixture
def custodian_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["custodian_headers"]
