"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def salvage_master_headers():
    return TEST_USERS["salvage_master_headers"]


@pytest.fixture
def contracts_officer_headers():
    return TEST_USERS["contracts_officer_headers"]


@pytest.fixture
def marine_surveyor_headers():
    return TEST_USERS["marine_surveyor_headers"]


@pytest.fixture
def property_surveyor_headers():
    return TEST_USERS["property_surveyor_headers"]


@pytest.fixture
def environmental_officer_headers():
    return TEST_USERS["environmental_officer_headers"]


@pytest.fixture
def operations_director_headers():
    return TEST_USERS["operations_director_headers"]


@pytest.fixture
def arbitrator_headers():
    return TEST_USERS["arbitrator_headers"]


@pytest.fixture
def insurer_surveyor_headers():
    return TEST_USERS["insurer_surveyor_headers"]
