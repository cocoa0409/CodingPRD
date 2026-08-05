"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages server lifecycle and PYTHONPATH; this file only wires fixtures.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


# Opaque-role headers (shared constants are the canonical form for these roles).
@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def concierge_headers():
    return TEST_USERS["concierge_headers"]


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]
