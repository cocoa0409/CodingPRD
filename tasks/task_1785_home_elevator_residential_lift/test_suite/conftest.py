"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def dealer_admin_headers():
    return TEST_USERS["dealer_admin_headers"]


@pytest.fixture
def coordinator_headers():
    return TEST_USERS["coordinator_headers"]


@pytest.fixture
def grant_officer_headers():
    return TEST_USERS["grant_officer_headers"]


@pytest.fixture
def regulator_headers():
    return TEST_USERS["regulator_headers"]


@pytest.fixture
def homeowner_headers():
    return TEST_USERS["homeowner_headers"]


@pytest.fixture
def other_homeowner_headers():
    return TEST_USERS["other_homeowner_headers"]
