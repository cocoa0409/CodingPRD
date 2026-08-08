"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def cartographer_headers():
    return TEST_USERS["cartographer_headers"]


@pytest.fixture
def demographer_headers():
    return TEST_USERS["demographer_headers"]


@pytest.fixture
def chair_headers():
    return TEST_USERS["chair_headers"]


@pytest.fixture
def clerk_headers():
    return TEST_USERS["clerk_headers"]


@pytest.fixture
def public_headers():
    return TEST_USERS["public_headers"]
