"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def port_admin_headers():
    return TEST_USERS["port_admin_headers"]


@pytest.fixture
def port_dispatcher_headers():
    return TEST_USERS["port_dispatcher_headers"]


@pytest.fixture
def marine_surveyor_headers():
    return TEST_USERS["marine_surveyor_headers"]


@pytest.fixture
def claims_adjuster_headers():
    return TEST_USERS["claims_adjuster_headers"]


@pytest.fixture
def vessel_agent_headers():
    return TEST_USERS["vessel_agent_headers"]


@pytest.fixture
def pilot_headers():
    return TEST_USERS["pilot_headers"]


@pytest.fixture
def tug_captain_headers():
    return TEST_USERS["tug_captain_headers"]
