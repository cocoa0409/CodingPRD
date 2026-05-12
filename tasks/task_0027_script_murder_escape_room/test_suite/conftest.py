"""Pytest fixtures exposing test_helpers infrastructure.

The runner injects PYTHONPATH so test_helpers is importable; this file simply
exposes the shared fixtures every test needs.
"""
from __future__ import annotations

import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def admin_headers_alt():
    return TEST_USERS["platform_admin_headers_alt"]


@pytest.fixture
def moderator_headers():
    return TEST_USERS["content_moderator_headers"]


@pytest.fixture
def moderator_headers_alt():
    return TEST_USERS["content_moderator_headers_alt"]


@pytest.fixture
def gateway_headers():
    return TEST_USERS["payment_gateway_headers"]


@pytest.fixture
def player_fallback_headers():
    """Player-role headers with a non-matching X-User-ID. Use ONLY for tests
    that don't exercise ownership (e.g., 400-on-bad-payload, forbidden-role,
    or 404-on-missing-resource probes)."""
    return TEST_USERS["player_headers"]


@pytest.fixture
def venue_operator_fallback_headers():
    """VenueOperator-role headers with a non-matching X-User-ID. Use ONLY for
    tests that don't exercise ownership."""
    return TEST_USERS["venue_operator_headers"]


@pytest.fixture
def host_fallback_headers():
    return TEST_USERS["host_headers"]


@pytest.fixture
def npc_fallback_headers():
    return TEST_USERS["npc_headers"]


@pytest.fixture
def script_author_fallback_headers():
    return TEST_USERS["script_author_headers"]
