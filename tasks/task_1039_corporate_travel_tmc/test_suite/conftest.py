"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def travel_manager_headers():
    return TEST_USERS["travel_manager_headers"]


@pytest.fixture
def finance_officer_headers():
    return TEST_USERS["finance_officer_headers"]


@pytest.fixture
def system_headers():
    return TEST_USERS["system_headers"]


@pytest.fixture
def traveler_headers():
    return TEST_USERS["traveler_headers"]


@pytest.fixture
def approver_headers():
    return TEST_USERS["approver_headers"]
