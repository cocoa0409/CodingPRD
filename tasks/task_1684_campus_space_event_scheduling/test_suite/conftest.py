"""Pytest fixtures exposing the campus-scheduling test helpers."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def scheduler_headers():
    return TEST_USERS["scheduler_headers"]


@pytest.fixture
def service_coordinator_headers():
    return TEST_USERS["service_coordinator_headers"]


@pytest.fixture
def facilities_manager_headers():
    return TEST_USERS["facilities_manager_headers"]


@pytest.fixture
def finance_admin_headers():
    return TEST_USERS["finance_admin_headers"]
