"""Pytest fixtures exposing the test_helpers infrastructure."""
import pytest

from test_helpers import (
    NO_AUTH_HEADERS,
    TEST_USERS,
    ApiClient,
    api_client,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def emergency_director_headers():
    return TEST_USERS["emergency_director_headers"]


@pytest.fixture
def dispatcher_headers():
    return TEST_USERS["dispatcher_headers"]


@pytest.fixture
def telemetry_gateway_headers():
    return TEST_USERS["telemetry_gateway_headers"]


@pytest.fixture
def system_operator_headers():
    return TEST_USERS["system_operator_headers"]


@pytest.fixture
def system_operator_2_headers():
    return TEST_USERS["system_operator_2_headers"]


@pytest.fixture
def mutual_aid_coordinator_headers():
    return TEST_USERS["mutual_aid_coordinator_headers"]


@pytest.fixture
def materials_manager_headers():
    return TEST_USERS["materials_manager_headers"]


@pytest.fixture
def claims_officer_headers():
    return TEST_USERS["claims_officer_headers"]


@pytest.fixture
def claims_officer_2_headers():
    return TEST_USERS["claims_officer_2_headers"]


@pytest.fixture
def regulator_headers():
    return TEST_USERS["regulator_headers"]


@pytest.fixture
def field_crew_lead_headers():
    return TEST_USERS["field_crew_lead_headers"]


@pytest.fixture
def no_auth_headers():
    return dict(NO_AUTH_HEADERS)
