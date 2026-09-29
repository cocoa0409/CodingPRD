"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def waterway_admin_headers():
    return TEST_USERS["waterway_admin_headers"]


@pytest.fixture
def tariff_analyst_headers():
    return TEST_USERS["tariff_analyst_headers"]


@pytest.fixture
def rate_authority_headers():
    return TEST_USERS["rate_authority_headers"]


@pytest.fixture
def towboat_dispatcher_headers():
    return TEST_USERS["towboat_dispatcher_headers"]


@pytest.fixture
def lock_master_headers():
    return TEST_USERS["lock_master_headers"]


@pytest.fixture
def harbor_agent_headers():
    return TEST_USERS["harbor_agent_headers"]


@pytest.fixture
def contract_manager_headers():
    return TEST_USERS["contract_manager_headers"]


@pytest.fixture
def claims_adjuster_headers():
    return TEST_USERS["claims_adjuster_headers"]


@pytest.fixture
def shipper_headers():
    return TEST_USERS["shipper_headers"]
