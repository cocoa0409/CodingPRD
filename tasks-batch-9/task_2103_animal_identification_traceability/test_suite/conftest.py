"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def producer_headers():
    return TEST_USERS["producer_headers"]


@pytest.fixture
def state_official_headers():
    return TEST_USERS["state_official_headers"]


@pytest.fixture
def second_state_official_headers():
    return TEST_USERS["second_state_official_headers"]


@pytest.fixture
def trace_analyst_headers():
    return TEST_USERS["trace_analyst_headers"]


@pytest.fixture
def second_trace_analyst_headers():
    return TEST_USERS["second_trace_analyst_headers"]


@pytest.fixture
def supplier_rep_headers():
    return TEST_USERS["supplier_rep_headers"]


@pytest.fixture
def harvest_operator_headers():
    return TEST_USERS["harvest_operator_headers"]


@pytest.fixture
def program_admin_headers():
    return TEST_USERS["program_admin_headers"]


@pytest.fixture
def second_program_admin_headers():
    return TEST_USERS["second_program_admin_headers"]
