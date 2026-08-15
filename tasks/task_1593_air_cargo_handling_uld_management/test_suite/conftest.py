"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def capacity_controller_headers():
    return TEST_USERS["capacity_controller_headers"]


@pytest.fixture
def forwarder_agent_headers():
    return TEST_USERS["forwarder_agent_headers"]


@pytest.fixture
def ramp_operator_headers():
    return TEST_USERS["ramp_operator_headers"]


@pytest.fixture
def dg_inspector_headers():
    return TEST_USERS["dg_inspector_headers"]


@pytest.fixture
def customs_officer_headers():
    return TEST_USERS["customs_officer_headers"]


@pytest.fixture
def claims_adjuster_headers():
    return TEST_USERS["claims_adjuster_headers"]
