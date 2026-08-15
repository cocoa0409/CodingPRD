"""Pytest fixtures exposing the test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def linen_manager_headers():
    return TEST_USERS["linen_manager_headers"]


@pytest.fixture
def linen_manager_2_headers():
    return TEST_USERS["linen_manager_2_headers"]


@pytest.fixture
def evs_operator_headers():
    return TEST_USERS["evs_operator_headers"]


@pytest.fixture
def laundry_vendor_headers():
    return TEST_USERS["laundry_vendor_headers"]


@pytest.fixture
def infection_control_officer_headers():
    return TEST_USERS["infection_control_officer_headers"]


@pytest.fixture
def unit_clerk_headers():
    return TEST_USERS["unit_clerk_headers"]
