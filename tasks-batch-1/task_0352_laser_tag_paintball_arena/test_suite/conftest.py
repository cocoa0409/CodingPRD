"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def arena_manager_headers():
    return TEST_USERS["arena_manager_headers"]


@pytest.fixture
def front_desk_headers():
    return TEST_USERS["front_desk_headers"]


@pytest.fixture
def field_marshal_headers():
    return TEST_USERS["field_marshal_headers"]


@pytest.fixture
def league_director_headers():
    return TEST_USERS["league_director_headers"]
