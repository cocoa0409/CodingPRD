"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH (so test_helpers is importable) and the server
lifecycle: it restarts the server with an empty DB before every test, so each
test starts from a clean slate.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def officer_headers():
    """Shared Officer fallback — non-ownership tests only."""
    return TEST_USERS["officer_headers"]


@pytest.fixture
def judge_headers():
    return TEST_USERS["judge_headers"]


@pytest.fixture
def compact_admin_headers():
    return TEST_USERS["compact_admin_headers"]
