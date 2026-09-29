"""Pytest fixtures exposing the shared test infrastructure."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client; server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def steward_headers():
    return TEST_USERS["steward_headers"]


@pytest.fixture
def grievant_headers():
    return TEST_USERS["grievant_headers"]


@pytest.fixture
def analyst_headers():
    return TEST_USERS["analyst_headers"]


@pytest.fixture
def second_analyst_headers():
    return TEST_USERS["second_analyst_headers"]


@pytest.fixture
def director_headers():
    return TEST_USERS["director_headers"]


@pytest.fixture
def second_director_headers():
    return TEST_USERS["second_director_headers"]


@pytest.fixture
def negotiator_headers():
    return TEST_USERS["negotiator_headers"]


@pytest.fixture
def administrator_headers():
    return TEST_USERS["administrator_headers"]
