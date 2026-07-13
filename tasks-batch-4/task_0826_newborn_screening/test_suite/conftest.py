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
def lab_technician_headers():
    return TEST_USERS["lab_technician_headers"]


@pytest.fixture
def follow_up_coordinator_headers():
    return TEST_USERS["follow_up_coordinator_headers"]
