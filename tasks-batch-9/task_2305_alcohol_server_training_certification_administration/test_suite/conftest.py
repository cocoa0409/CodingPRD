"""Pytest fixtures exposing the shared test infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def program_admin_headers():
    return TEST_USERS["program_admin_headers"]


@pytest.fixture
def state_regulator_headers():
    return TEST_USERS["state_regulator_headers"]


@pytest.fixture
def trainer_headers():
    return TEST_USERS["trainer_headers"]


@pytest.fixture
def employer_admin_headers():
    return TEST_USERS["employer_admin_headers"]


@pytest.fixture
def alcohol_server_headers():
    return TEST_USERS["alcohol_server_headers"]
