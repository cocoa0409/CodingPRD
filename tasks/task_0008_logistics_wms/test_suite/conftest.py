"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def staff_headers():
    return TEST_USERS["staff_headers"]


@pytest.fixture
def staff_headers_alt():
    return TEST_USERS["staff_headers_alt"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["auditor_headers"]


@pytest.fixture
def auditor_headers_alt():
    return TEST_USERS["auditor_headers_alt"]


@pytest.fixture
def manager_headers():
    return TEST_USERS["manager_headers"]
