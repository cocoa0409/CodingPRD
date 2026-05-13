"""Pytest fixtures exposing test_helpers infrastructure for the IP Management API.

Server lifecycle, PYTHONPATH, and API_BASE_URL are managed by
prd-bench-local-runner. This file wires test_helpers into pytest fixtures so
test functions can request them by name.
"""

import pytest

from test_helpers import (
    TEST_USERS,
    ApiClient,
    api_client,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. The runner guarantees the server is up at
    API_BASE_URL."""
    return api_client


# ─────────────────────────────────────────────────────────────
# Opaque-role headers (PRD §2.1).
# ─────────────────────────────────────────────────────────────


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def admin_headers_alt():
    return TEST_USERS["admin_headers_alt"]


@pytest.fixture
def ip_manager_headers():
    return TEST_USERS["ip_manager_headers"]


@pytest.fixture
def ip_manager_headers_alt():
    return TEST_USERS["ip_manager_headers_alt"]


@pytest.fixture
def finance_manager_headers():
    return TEST_USERS["finance_manager_headers"]


@pytest.fixture
def counsel_headers():
    return TEST_USERS["counsel_headers"]


# ─────────────────────────────────────────────────────────────
# Entity-backed fallbacks (PRD §2.1).
# Safe ONLY for tests that do not exercise ownership.
# ─────────────────────────────────────────────────────────────


@pytest.fixture
def internal_agent_fallback_headers():
    return TEST_USERS["internal_agent_fallback"]


@pytest.fixture
def external_agent_fallback_headers():
    return TEST_USERS["external_agent_fallback"]
