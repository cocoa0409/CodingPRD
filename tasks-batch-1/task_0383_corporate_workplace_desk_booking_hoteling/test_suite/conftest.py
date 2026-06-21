"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def facility_manager_headers():
    return TEST_USERS["facility_manager_headers"]


@pytest.fixture
def employee_headers():
    return TEST_USERS["employee_headers"]


@pytest.fixture
def receptionist_headers():
    return TEST_USERS["receptionist_headers"]


@pytest.fixture
def analyst_headers():
    return TEST_USERS["analyst_headers"]
