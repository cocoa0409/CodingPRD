"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def privacy_admin_headers():
    return TEST_USERS["privacy_admin_headers"]


@pytest.fixture
def data_steward_headers():
    return TEST_USERS["data_steward_headers"]


@pytest.fixture
def business_owner_headers():
    return TEST_USERS["business_owner_headers"]


@pytest.fixture
def legal_counsel_headers():
    return TEST_USERS["legal_counsel_headers"]


@pytest.fixture
def vendor_manager_headers():
    return TEST_USERS["vendor_manager_headers"]


@pytest.fixture
def consumer_headers():
    return TEST_USERS["consumer_headers"]
