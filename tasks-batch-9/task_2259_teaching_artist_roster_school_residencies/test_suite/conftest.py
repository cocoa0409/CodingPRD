"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def program_director_headers():
    return TEST_USERS["program_director_headers"]


@pytest.fixture
def roster_coordinator_headers():
    return TEST_USERS["roster_coordinator_headers"]


@pytest.fixture
def curriculum_specialist_headers():
    return TEST_USERS["curriculum_specialist_headers"]


@pytest.fixture
def teaching_artist_headers():
    return TEST_USERS["teaching_artist_headers"]


@pytest.fixture
def school_liaison_headers():
    return TEST_USERS["school_liaison_headers"]


@pytest.fixture
def fiscal_officer_headers():
    return TEST_USERS["fiscal_officer_headers"]
