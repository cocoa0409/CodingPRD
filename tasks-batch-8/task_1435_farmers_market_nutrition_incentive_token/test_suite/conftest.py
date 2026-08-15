"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def program_admin_headers():
    return TEST_USERS["program_admin_headers"]


@pytest.fixture
def market_manager_headers():
    return TEST_USERS["market_manager_headers"]


@pytest.fixture
def booth_operator_headers():
    return TEST_USERS["booth_operator_headers"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["auditor_headers"]


@pytest.fixture
def vendor_headers():
    return TEST_USERS["vendor_headers"]


@pytest.fixture
def shopper_headers():
    return TEST_USERS["shopper_headers"]
