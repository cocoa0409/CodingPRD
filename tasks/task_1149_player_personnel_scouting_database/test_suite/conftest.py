"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def area_scout_headers():
    return TEST_USERS["area_scout_headers"]


@pytest.fixture
def scouting_director_headers():
    return TEST_USERS["scouting_director_headers"]


@pytest.fixture
def medical_staff_headers():
    return TEST_USERS["medical_staff_headers"]


@pytest.fixture
def general_manager_headers():
    return TEST_USERS["general_manager_headers"]
