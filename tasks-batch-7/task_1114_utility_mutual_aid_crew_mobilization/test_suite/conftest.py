"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def program_admin_headers():
    return TEST_USERS["program_admin_headers"]


@pytest.fixture
def host_coordinator_headers():
    return TEST_USERS["host_coordinator_headers"]


@pytest.fixture
def responding_coordinator_headers():
    return TEST_USERS["responding_coordinator_headers"]


@pytest.fixture
def crew_supervisor_headers():
    return TEST_USERS["crew_supervisor_headers"]


@pytest.fixture
def host_safety_officer_headers():
    return TEST_USERS["host_safety_officer_headers"]


@pytest.fixture
def host_finance_headers():
    return TEST_USERS["host_finance_headers"]


@pytest.fixture
def responding_finance_headers():
    return TEST_USERS["responding_finance_headers"]
