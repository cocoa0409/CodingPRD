"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH and server lifecycle. This conftest just
wires per-role headers and the session-scoped api client.

PRD §2.1 identity rules:
- Housekeeper is entity_backed → ownership-gated tests MUST use
  make_housekeeper_headers(housekeeper['id']).
- Supervisor, FrontDesk, Engineer, SystemIntegration are opaque
  → shared TEST_USERS constants are canonical.
"""
from __future__ import annotations
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the
    runner."""
    return api_client


# ---------------------------------------------------------------------------
# Opaque-role headers (canonical via shared constants)
# ---------------------------------------------------------------------------
@pytest.fixture
def supervisor_headers():
    return TEST_USERS["supervisor_headers"]


@pytest.fixture
def supervisor_headers_alt():
    """A second Supervisor X-User-ID; needed when two simultaneous
    supervisor actions must carry distinct opaque identifiers (e.g.,
    two /inspect operations racing on the same SUBMITTED task)."""
    return TEST_USERS["supervisor_headers_alt"]


@pytest.fixture
def supervisor_headers_alt2():
    return TEST_USERS["supervisor_headers_alt2"]


@pytest.fixture
def frontdesk_headers():
    return TEST_USERS["frontdesk_headers"]


@pytest.fixture
def frontdesk_headers_alt():
    return TEST_USERS["frontdesk_headers_alt"]


@pytest.fixture
def engineer_headers():
    return TEST_USERS["engineer_headers"]


@pytest.fixture
def system_integration_headers():
    return TEST_USERS["system_integration_headers"]


@pytest.fixture
def housekeeper_fallback_headers():
    """Fallback Housekeeper headers — X-User-ID 'housekeeper-fallback'.

    PRD §2.1: real Housekeeper X-User-ID must equal Housekeeper.id;
    this constant matches no real housekeeper, so use it only for tests
    that do NOT exercise ownership (missing-auth, wrong-role,
    missing-resource).
    """
    return TEST_USERS["housekeeper_headers"]
