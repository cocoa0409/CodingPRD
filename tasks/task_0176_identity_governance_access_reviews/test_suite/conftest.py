"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def catalog_admin_headers():
    return TEST_USERS["catalog_admin_headers"]


@pytest.fixture
def access_manager_headers():
    return TEST_USERS["access_manager_headers"]


@pytest.fixture
def access_approver_headers():
    return TEST_USERS["access_approver_headers"]


@pytest.fixture
def campaign_admin_headers():
    return TEST_USERS["campaign_admin_headers"]


@pytest.fixture
def certifier_headers():
    return TEST_USERS["certifier_headers"]
