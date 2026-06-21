"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH (test_helpers importable) and server lifecycle.
"""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def league_admin_headers():
    return TEST_USERS["league_admin_headers"]


@pytest.fixture
def conduct_officer_headers():
    return TEST_USERS["conduct_officer_headers"]


@pytest.fixture
def team_captain_headers():
    return TEST_USERS["team_captain_headers"]


@pytest.fixture
def referee_headers():
    return TEST_USERS["referee_headers"]
