"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages server lifecycle and PYTHONPATH; this file only wires fixtures.
"""
import pytest
from test_helpers import (
    api_client,
    ApiClient,
    TEST_USERS,
    make_owner_agent_headers,
    make_state_hfa_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def owner_headers():
    """Shared OwnerAgent header constant (opaque identity, PRD §2.1)."""
    return TEST_USERS["owner_agent_headers"]


@pytest.fixture
def hfa_headers():
    """Shared StateHFA header constant (opaque identity, PRD §2.1)."""
    return TEST_USERS["state_hfa_headers"]


@pytest.fixture
def headers_factory():
    """Builder functions so segregation-of-duties tests can mint distinct identities."""
    return {
        "owner_agent": make_owner_agent_headers,
        "state_hfa": make_state_hfa_headers,
    }
