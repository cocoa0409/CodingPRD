"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def forester_headers():
    return TEST_USERS["forester_headers"]


@pytest.fixture
def planner_headers():
    return TEST_USERS["planner_headers"]


@pytest.fixture
def arborist_headers():
    return TEST_USERS["arborist_headers"]


@pytest.fixture
def arborist_b_headers():
    return TEST_USERS["arborist_b_headers"]


@pytest.fixture
def advocate_headers():
    return TEST_USERS["advocate_headers"]


@pytest.fixture
def analyst_headers():
    return TEST_USERS["analyst_headers"]


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def foreman_headers():
    return TEST_USERS["foreman_headers"]
