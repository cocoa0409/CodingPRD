"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH so `test_helpers` is importable without sys.path
hacks. Server lifecycle (start/stop, per-test restart) is owned by the runner.
"""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. The runner restarts the server before each
    test, so the underlying API is fresh for every test even though the client
    object itself is reused."""
    return api_client


@pytest.fixture
def plan_admin_headers() -> dict:
    return TEST_USERS["plan_admin_headers"]


@pytest.fixture
def custodian_headers() -> dict:
    return TEST_USERS["custodian_headers"]


@pytest.fixture
def participant_headers_fallback() -> dict:
    return TEST_USERS["participant_headers_fallback"]
