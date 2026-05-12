"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle (start, readiness, shutdown) is managed by the
prd-bench-local-runner framework. PYTHONPATH points at the parent directory
so `test_helpers` is importable directly.
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
    """Session-scoped API client. Server lifecycle owned by the runner."""
    return api_client


@pytest.fixture(autouse=True)
def _reset_state_before_each_test():
    """Reset all in-memory state and the simulated clock before each test.

    The implementation runs as a long-lived process across the whole pytest
    session. Tests are ordering-independent only if state is wiped between
    them (PRD §3.11 admin-only test-driving capability). The /_test/reset
    endpoint clears tables and resets the clock to a low sentinel so each
    test can advance to its preferred anchor (DEFAULT_T0 or otherwise).
    """
    api_client.test_reset(TEST_USERS["admin_headers"])
    yield


# --- Opaque-role headers (PRD §2.1) -------------------------------------
@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def admin_headers_alt():
    return TEST_USERS["admin_headers_alt"]


@pytest.fixture
def crisis_responder_headers():
    return TEST_USERS["crisis_responder_headers"]


@pytest.fixture
def crisis_responder_headers_alt():
    return TEST_USERS["crisis_responder_headers_alt"]


@pytest.fixture
def public_headers():
    return TEST_USERS["public_headers"]


# --- Entity-backed-role fallback headers (PRD §2.1) ---------------------
# Use only for tests that don't exercise an ownership comparison.
@pytest.fixture
def client_headers_fallback():
    return TEST_USERS["client_headers"]


@pytest.fixture
def counselor_headers_fallback():
    return TEST_USERS["counselor_headers"]


@pytest.fixture
def supervisor_headers_fallback():
    return TEST_USERS["supervisor_headers"]
