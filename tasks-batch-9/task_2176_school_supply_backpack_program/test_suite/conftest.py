"""Pytest fixtures exposing the test_helpers infrastructure."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def program_director_headers():
    return TEST_USERS["program_director_headers"]


@pytest.fixture
def program_director_alt_headers():
    return TEST_USERS["program_director_alt_headers"]


@pytest.fixture
def warehouse_lead_headers():
    return TEST_USERS["warehouse_lead_headers"]


@pytest.fixture
def donor_relations_headers():
    return TEST_USERS["donor_relations_headers"]


@pytest.fixture
def school_liaison_headers():
    return TEST_USERS["school_liaison_headers"]


@pytest.fixture
def site_coordinator_headers():
    return TEST_USERS["site_coordinator_headers"]
