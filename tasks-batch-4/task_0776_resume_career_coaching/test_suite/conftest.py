"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def client_headers():
    return TEST_USERS["client_headers"]


@pytest.fixture
def coach_headers():
    return TEST_USERS["coach_headers"]


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]
