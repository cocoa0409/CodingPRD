"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def beach_captain_headers():
    return TEST_USERS["beach_captain_headers"]


@pytest.fixture
def lifeguard_headers():
    return TEST_USERS["lifeguard_headers"]


@pytest.fixture
def inspector_headers():
    return TEST_USERS["inspector_headers"]


@pytest.fixture
def parking_clerk_headers():
    return TEST_USERS["parking_clerk_headers"]


@pytest.fixture
def public_headers():
    return TEST_USERS["public_headers"]
