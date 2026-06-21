"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def floor_manager_headers():
    return TEST_USERS["floor_manager_headers"]


@pytest.fixture
def door_host_headers():
    return TEST_USERS["door_host_headers"]


@pytest.fixture
def bartender_headers():
    return TEST_USERS["bartender_headers"]


@pytest.fixture
def security_officer_headers():
    return TEST_USERS["security_officer_headers"]
