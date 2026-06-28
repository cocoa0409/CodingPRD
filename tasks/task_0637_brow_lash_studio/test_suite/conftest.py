"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle (start/stop, empty DB per test) is managed by prd-bench-local-runner.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def studio_manager_headers():
    return TEST_USERS["studio_manager_headers"]


@pytest.fixture
def front_desk_headers():
    return TEST_USERS["front_desk_headers"]


@pytest.fixture
def lash_tech_headers():
    return TEST_USERS["lash_tech_headers"]


@pytest.fixture
def member_headers():
    return TEST_USERS["member_headers"]
