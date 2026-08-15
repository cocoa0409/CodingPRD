"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def program_director_headers():
    return TEST_USERS["program_director_headers"]


@pytest.fixture
def utility_analyst_headers():
    return TEST_USERS["utility_analyst_headers"]


@pytest.fixture
def utility_analyst_alt_headers():
    return TEST_USERS["utility_analyst_alt_headers"]


@pytest.fixture
def field_supervisor_headers():
    return TEST_USERS["field_supervisor_headers"]


@pytest.fixture
def field_supervisor_alt_headers():
    return TEST_USERS["field_supervisor_alt_headers"]


@pytest.fixture
def meter_technician_headers():
    return TEST_USERS["meter_technician_headers"]


@pytest.fixture
def investigator_headers():
    return TEST_USERS["investigator_headers"]


@pytest.fixture
def regulator_liaison_headers():
    return TEST_USERS["regulator_liaison_headers"]
