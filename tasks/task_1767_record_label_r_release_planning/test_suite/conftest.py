"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def label_admin_headers():
    return TEST_USERS["label_admin_headers"]


@pytest.fixture
def anr_manager_headers():
    return TEST_USERS["anr_manager_headers"]


@pytest.fixture
def finance_headers():
    return TEST_USERS["finance_headers"]


@pytest.fixture
def marketing_headers():
    return TEST_USERS["marketing_headers"]


@pytest.fixture
def artist_portal_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["artist_portal_headers"]
