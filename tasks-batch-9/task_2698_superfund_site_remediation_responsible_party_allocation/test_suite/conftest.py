"""Pytest configuration exposing the test_helpers infrastructure.

The runner owns the server lifecycle and resets the database before every test,
so each test starts against an empty service whose clock reads the startup
instant.
"""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client
from test_helpers.fixtures import *  # noqa: F401,F403  (composite scenario fixtures)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client; the runner owns the server lifecycle."""
    return api_client


@pytest.fixture
def users() -> dict:
    """The pre-built role headers, keyed by role nickname."""
    return TEST_USERS
