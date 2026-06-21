"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages server lifecycle and PYTHONPATH, so test_helpers is importable
directly. The server database is empty at the start of every test.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def fleet_manager_headers():
    return TEST_USERS["fleet_manager_headers"]


@pytest.fixture
def rental_agent_headers():
    return TEST_USERS["rental_agent_headers"]


@pytest.fixture
def member_headers():
    return TEST_USERS["member_headers"]
