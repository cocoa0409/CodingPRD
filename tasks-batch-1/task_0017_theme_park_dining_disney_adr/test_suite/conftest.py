"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages server lifecycle (start/stop per test) and PYTHONPATH so
test_helpers is importable without sys.path manipulation.
"""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


# ─── Role-header fixtures (PRD §2.1) ──────────────────────────────────────

@pytest.fixture
def guest_headers():
    """Shared Guest header — safe ONLY for non-ownership tests.
    Ownership-gated tests must call make_guest_headers(guest_id) with the real id."""
    return TEST_USERS["guest_headers"]


@pytest.fixture
def restaurant_headers():
    """Shared Restaurant header — safe ONLY for non-ownership tests."""
    return TEST_USERS["restaurant_headers"]


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]
