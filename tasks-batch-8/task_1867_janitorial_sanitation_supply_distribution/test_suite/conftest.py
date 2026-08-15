"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def distributor_admin_headers():
    return TEST_USERS["distributor_admin_headers"]


@pytest.fixture
def sales_rep_headers():
    return TEST_USERS["sales_rep_headers"]


@pytest.fixture
def facility_manager_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["facility_manager_headers"]


@pytest.fixture
def field_technician_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["field_technician_headers"]
