"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH (test_helpers is importable) and the server
lifecycle: the API server is killed and relaunched via start.sh before every
test, so each test starts against an empty database.
"""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def chief_headers():
    return TEST_USERS["chief_headers"]


@pytest.fixture
def officer_headers():
    return TEST_USERS["officer_headers"]


@pytest.fixture
def member_headers():
    return TEST_USERS["member_headers"]
