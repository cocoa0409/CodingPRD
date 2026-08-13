"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def fleet_admin_headers():
    return TEST_USERS["fleet_admin_headers"]


@pytest.fixture
def fleet_admin_alt_headers():
    return TEST_USERS["fleet_admin_alt_headers"]


@pytest.fixture
def officer_headers():
    return TEST_USERS["officer_headers"]


@pytest.fixture
def officer_alt_headers():
    return TEST_USERS["officer_alt_headers"]


@pytest.fixture
def crewing_headers():
    return TEST_USERS["crewing_headers"]


@pytest.fixture
def crewing_alt_headers():
    return TEST_USERS["crewing_alt_headers"]


@pytest.fixture
def port_captain_headers():
    return TEST_USERS["port_captain_headers"]
