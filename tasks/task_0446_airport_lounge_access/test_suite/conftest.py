"""Pytest fixtures exposing test_helpers infrastructure.

The runner sets PYTHONPATH so `test_helpers` is importable, injects API_BASE_URL,
and restarts the server before every test. These fixtures just wire helpers in.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def network_admin_headers():
    return TEST_USERS["network_admin_headers"]


@pytest.fixture
def lounge_agent_headers():
    """Shared LoungeAgent constant — for tests that do NOT exercise lounge
    ownership. Ownership-gated agent calls must use make_lounge_agent_headers."""
    return TEST_USERS["lounge_agent_headers"]


@pytest.fixture
def member_headers():
    """Shared Member constant — for tests that do NOT exercise resource
    ownership. Ownership-gated member calls must use make_member_headers."""
    return TEST_USERS["member_headers"]
