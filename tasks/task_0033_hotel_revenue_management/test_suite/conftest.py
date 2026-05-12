"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle (start, readiness, shutdown) is managed by the
prd-bench-local-runner framework. PYTHONPATH points at the parent
directory so `test_helpers` is importable directly.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    api_client,
    ApiClient,
    TEST_USERS,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. The base URL is supplied by the runner."""
    return api_client


# --- All roles are opaque per PRD §2.1 — shared TEST_USERS constants. ---

@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def admin_headers_alt():
    return TEST_USERS["admin_headers_alt"]


@pytest.fixture
def analyst_headers():
    return TEST_USERS["analyst_headers"]


@pytest.fixture
def analyst_headers_alt():
    return TEST_USERS["analyst_headers_alt"]


@pytest.fixture
def manager_headers():
    return TEST_USERS["manager_headers"]


@pytest.fixture
def manager_headers_alt():
    return TEST_USERS["manager_headers_alt"]


@pytest.fixture
def agent_headers():
    return TEST_USERS["agent_headers"]


@pytest.fixture
def agent_headers_alt():
    return TEST_USERS["agent_headers_alt"]


@pytest.fixture
def clerk_headers():
    return TEST_USERS["clerk_headers"]


@pytest.fixture
def housekeeping_headers():
    return TEST_USERS["housekeeping_headers"]


@pytest.fixture
def guest_headers():
    return TEST_USERS["guest_headers"]
