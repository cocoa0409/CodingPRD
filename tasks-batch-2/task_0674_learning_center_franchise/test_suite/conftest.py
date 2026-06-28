"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def franchise_admin_headers():
    return TEST_USERS["franchise_admin_headers"]


@pytest.fixture
def center_director_headers():
    return TEST_USERS["center_director_headers"]


@pytest.fixture
def instructor_headers():
    return TEST_USERS["instructor_headers"]


@pytest.fixture
def parent_headers():
    return TEST_USERS["parent_headers"]
