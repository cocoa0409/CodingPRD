"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def sponsor_admin_headers():
    return TEST_USERS["sponsor_admin_headers"]


@pytest.fixture
def monitor_headers():
    return TEST_USERS["monitor_headers"]


@pytest.fixture
def investigator_headers():
    return TEST_USERS["investigator_headers"]
