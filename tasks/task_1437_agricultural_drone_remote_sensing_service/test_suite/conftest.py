"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def ops_admin_headers():
    return TEST_USERS["ops_admin_headers"]


@pytest.fixture
def flight_coordinator_headers():
    return TEST_USERS["flight_coordinator_headers"]


@pytest.fixture
def remote_pilot_headers():
    return TEST_USERS["remote_pilot_headers"]


@pytest.fixture
def agronomist_headers():
    return TEST_USERS["agronomist_headers"]


@pytest.fixture
def grower_headers():
    return TEST_USERS["grower_headers"]


@pytest.fixture
def claims_adjuster_headers():
    return TEST_USERS["claims_adjuster_headers"]


@pytest.fixture
def processing_engine_headers():
    return TEST_USERS["processing_engine_headers"]
