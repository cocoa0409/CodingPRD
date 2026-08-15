"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def race_director_headers():
    return TEST_USERS["race_director_headers"]


@pytest.fixture
def timing_operator_headers():
    return TEST_USERS["timing_operator_headers"]


@pytest.fixture
def registration_clerk_headers():
    return TEST_USERS["registration_clerk_headers"]


@pytest.fixture
def race_official_headers():
    return TEST_USERS["race_official_headers"]


@pytest.fixture
def certification_officer_headers():
    return TEST_USERS["certification_officer_headers"]


@pytest.fixture
def spectator_headers():
    return TEST_USERS["spectator_headers"]
