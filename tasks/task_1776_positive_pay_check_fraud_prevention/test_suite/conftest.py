"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def bank_treasury_manager_headers():
    return TEST_USERS["bank_treasury_manager_headers"]


@pytest.fixture
def bank_ops_headers():
    return TEST_USERS["bank_ops_headers"]


@pytest.fixture
def customer_admin_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["customer_admin_headers"]


@pytest.fixture
def customer_manager_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["customer_manager_headers"]


@pytest.fixture
def customer_decision_maker_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["customer_decision_maker_headers"]


@pytest.fixture
def customer_viewer_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["customer_viewer_headers"]
