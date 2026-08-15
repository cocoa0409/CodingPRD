"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def equipment_manager_headers():
    return TEST_USERS["equipment_manager_headers"]


@pytest.fixture
def team_admin_headers():
    return TEST_USERS["team_admin_headers"]


@pytest.fixture
def laundry_vendor_headers():
    return TEST_USERS["laundry_vendor_headers"]
