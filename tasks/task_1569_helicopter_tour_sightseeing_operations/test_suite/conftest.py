"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def ops_admin_headers():
    return TEST_USERS["ops_admin_headers"]


@pytest.fixture
def dispatcher_headers():
    return TEST_USERS["dispatcher_headers"]


@pytest.fixture
def dispatcher_2_headers():
    return TEST_USERS["dispatcher_2_headers"]


@pytest.fixture
def booking_agent_headers():
    return TEST_USERS["booking_agent_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def community_reporter_headers():
    return TEST_USERS["community_reporter_headers"]


@pytest.fixture
def pilot_headers():
    return TEST_USERS["pilot_headers"]
