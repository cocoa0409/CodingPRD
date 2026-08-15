"""Pytest fixtures exposing the test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def asset_accountant_headers():
    return TEST_USERS["asset_accountant_headers"]


@pytest.fixture
def controller_headers():
    return TEST_USERS["controller_headers"]


@pytest.fixture
def inventory_clerk_headers():
    return TEST_USERS["inventory_clerk_headers"]


@pytest.fixture
def tax_analyst_headers():
    return TEST_USERS["tax_analyst_headers"]
