"""Pytest fixtures exposing test_helpers infrastructure.

The runner sets PYTHONPATH so test_helpers is importable and manages the
server lifecycle (restart before each test). Tests never start/stop the server.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def season_admin_headers():
    return TEST_USERS["season_admin_headers"]


@pytest.fixture
def box_office_agent_headers():
    return TEST_USERS["box_office_agent_headers"]


@pytest.fixture
def artistic_director_headers():
    return TEST_USERS["artistic_director_headers"]


@pytest.fixture
def patron_headers():
    return TEST_USERS["patron_headers"]
