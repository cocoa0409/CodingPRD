"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def ops_admin_headers():
    return TEST_USERS["ops_admin_headers"]


@pytest.fixture
def manager_headers():
    return TEST_USERS["manager_headers"]


@pytest.fixture
def coordinator_headers():
    return TEST_USERS["coordinator_headers"]


@pytest.fixture
def finance_headers():
    return TEST_USERS["finance_headers"]


@pytest.fixture
def equipment_headers():
    return TEST_USERS["equipment_headers"]


@pytest.fixture
def security_headers():
    return TEST_USERS["security_headers"]


@pytest.fixture
def approver_headers():
    return TEST_USERS["approver_headers"]


@pytest.fixture
def vendor_headers():
    return TEST_USERS["vendor_headers"]


@pytest.fixture
def any_headers():
    return TEST_USERS["any_headers"]


@pytest.fixture
def team_member_headers():
    return TEST_USERS["team_member_headers"]
