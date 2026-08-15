"""Pytest fixtures exposing the test_helpers infrastructure.

The runner owns server lifecycle and PYTHONPATH; the suite assumes the API is
already reachable at API_BASE_URL with an empty database per test.
"""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def secretary_1_headers():
    return TEST_USERS["secretary_1_headers"]


@pytest.fixture
def secretary_2_headers():
    return TEST_USERS["secretary_2_headers"]


@pytest.fixture
def filing_coordinator_headers():
    return TEST_USERS["filing_coordinator_headers"]


@pytest.fixture
def compliance_auditor_headers():
    return TEST_USERS["compliance_auditor_headers"]


@pytest.fixture
def authorized_officer_headers():
    return TEST_USERS["authorized_officer_headers"]


@pytest.fixture
def registered_agent_user_headers():
    return TEST_USERS["registered_agent_user_headers"]
