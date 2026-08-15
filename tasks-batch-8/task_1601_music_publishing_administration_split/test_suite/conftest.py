"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def publisher_admin_headers():
    return TEST_USERS["publisher_admin_headers"]


@pytest.fixture
def copyright_specialist_headers():
    return TEST_USERS["copyright_specialist_headers"]


@pytest.fixture
def royalty_analyst_headers():
    return TEST_USERS["royalty_analyst_headers"]


@pytest.fixture
def finance_manager_headers():
    return TEST_USERS["finance_manager_headers"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["auditor_headers"]


@pytest.fixture
def writer_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["writer_headers"]
