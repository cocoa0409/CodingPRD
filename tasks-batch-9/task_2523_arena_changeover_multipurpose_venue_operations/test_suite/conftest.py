"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def director_headers():
    return TEST_USERS["director_headers"]


@pytest.fixture
def second_director_headers():
    return TEST_USERS["second_director_headers"]


@pytest.fixture
def booking_manager_headers():
    return TEST_USERS["booking_manager_headers"]


@pytest.fixture
def changeover_supervisor_headers():
    return TEST_USERS["changeover_supervisor_headers"]


@pytest.fixture
def second_supervisor_headers():
    return TEST_USERS["second_supervisor_headers"]


@pytest.fixture
def labor_coordinator_headers():
    return TEST_USERS["labor_coordinator_headers"]


@pytest.fixture
def anchor_tenant_rep_headers():
    return TEST_USERS["anchor_tenant_rep_headers"]
