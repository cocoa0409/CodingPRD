"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def system_admin_headers():
    return TEST_USERS["system_admin_headers"]


@pytest.fixture
def athletic_trainer_headers():
    return TEST_USERS["athletic_trainer_headers"]


@pytest.fixture
def athletic_director_headers():
    return TEST_USERS["athletic_director_headers"]


@pytest.fixture
def school_nurse_headers():
    return TEST_USERS["school_nurse_headers"]


@pytest.fixture
def physician_headers():
    return TEST_USERS["physician_headers"]


@pytest.fixture
def team_coach_headers():
    return TEST_USERS["team_coach_headers"]


@pytest.fixture
def parent_guardian_headers():
    return TEST_USERS["parent_guardian_headers"]
