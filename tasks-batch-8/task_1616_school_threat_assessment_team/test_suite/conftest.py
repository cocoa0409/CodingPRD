"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def intake_coordinator_headers():
    return TEST_USERS["intake_coordinator_headers"]


@pytest.fixture
def threat_assessor_headers():
    return TEST_USERS["threat_assessor_headers"]


@pytest.fixture
def team_lead_headers():
    return TEST_USERS["team_lead_headers"]


@pytest.fixture
def district_admin_headers():
    return TEST_USERS["district_admin_headers"]
