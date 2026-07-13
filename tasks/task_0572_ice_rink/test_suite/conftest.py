"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle (start/stop/health) is owned by prd-bench-local-runner; these
fixtures only surface the shared API client and role headers.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. The runner restarts the server (empty DB)
    before every individual test."""
    return api_client


@pytest.fixture
def rink_manager_headers():
    return TEST_USERS["rink_manager_headers"]


@pytest.fixture
def front_desk_headers():
    return TEST_USERS["front_desk_headers"]


@pytest.fixture
def skater_headers():
    return TEST_USERS["skater_headers"]
