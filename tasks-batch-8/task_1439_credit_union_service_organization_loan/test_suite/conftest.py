"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def network_admin_headers():
    return TEST_USERS["network_admin_headers"]


@pytest.fixture
def regulator_headers():
    return TEST_USERS["regulator_headers"]


@pytest.fixture
def treasury_headers():
    return TEST_USERS["treasury_headers"]


@pytest.fixture
def cuso_officer_headers():
    return TEST_USERS["cuso_officer_headers"]


@pytest.fixture
def originator_headers():
    return TEST_USERS["originator_headers"]


@pytest.fixture
def buyer_headers():
    return TEST_USERS["buyer_headers"]
