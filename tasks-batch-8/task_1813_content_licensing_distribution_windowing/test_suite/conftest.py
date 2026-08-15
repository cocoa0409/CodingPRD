"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def rights_manager_headers():
    return TEST_USERS["rights_manager_headers"]


@pytest.fixture
def finance_analyst_headers():
    return TEST_USERS["finance_analyst_headers"]


@pytest.fixture
def finance_controller_headers():
    return TEST_USERS["finance_controller_headers"]


@pytest.fixture
def platform_buyer_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["platform_buyer_headers"]
