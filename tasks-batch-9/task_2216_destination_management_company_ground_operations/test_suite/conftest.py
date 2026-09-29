"""Shared pytest fixtures for the DMC Ground Operations API test suite."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """The HTTP client pointed at the running API."""
    return api_client


@pytest.fixture
def program_director_headers() -> dict:
    return TEST_USERS["program_director_headers"]


@pytest.fixture
def operations_coordinator_headers() -> dict:
    return TEST_USERS["operations_coordinator_headers"]


@pytest.fixture
def supplier_manager_headers() -> dict:
    return TEST_USERS["supplier_manager_headers"]


@pytest.fixture
def supplier_headers() -> dict:
    return TEST_USERS["supplier_headers"]


@pytest.fixture
def controller_headers() -> dict:
    return TEST_USERS["controller_headers"]


@pytest.fixture
def permit_officer_headers() -> dict:
    return TEST_USERS["permit_officer_headers"]
