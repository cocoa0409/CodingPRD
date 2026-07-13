"""Pytest fixtures exposing test_helpers infrastructure.

The prd-bench-local-runner sets PYTHONPATH so `test_helpers` is importable and
injects API_BASE_URL. It also restarts the server (fresh, empty DB) before every
individual test, so tests must build all preconditions from scratch.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["network_admin_headers"]


@pytest.fixture
def sponsor_headers():
    return TEST_USERS["sponsor_agent_headers"]


@pytest.fixture
def member_headers():
    return TEST_USERS["member_headers"]
