"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def fleet_admin_headers():
    return TEST_USERS["fleet_admin_headers"]


@pytest.fixture
def project_manager_headers():
    return TEST_USERS["project_manager_headers"]


@pytest.fixture
def dispatcher_headers():
    return TEST_USERS["dispatcher_headers"]


@pytest.fixture
def mechanic_headers():
    return TEST_USERS["mechanic_headers"]
