"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH (so test_helpers is importable) and the server
lifecycle (restarting the server before every test). These fixtures just wire
the shared client and role headers into pytest.
"""
import pytest
from test_helpers import (
    api_client, ApiClient, TEST_USERS,
    make_member_headers, make_instructor_headers, make_chief_instructor_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def front_desk_headers():
    return TEST_USERS["front_desk_headers"]


@pytest.fixture
def instructor_headers():
    return TEST_USERS["instructor_headers"]


@pytest.fixture
def chief_instructor_headers():
    return TEST_USERS["chief_instructor_headers"]


@pytest.fixture
def member_headers():
    return TEST_USERS["member_headers"]
