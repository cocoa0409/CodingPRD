"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def ops_headers():
    return TEST_USERS["ops_headers"]


@pytest.fixture
def box_office_headers():
    return TEST_USERS["box_office_headers"]


@pytest.fixture
def actor_headers():
    return TEST_USERS["actor_headers"]


@pytest.fixture
def guest_headers():
    return TEST_USERS["guest_headers"]
