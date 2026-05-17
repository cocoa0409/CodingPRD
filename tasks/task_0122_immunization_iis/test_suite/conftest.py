"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH and server lifecycle. This conftest
wires per-role headers and the session-scoped API client.

PRD §2.1: all four roles are opaque - shared TEST_USERS headers are
canonical. Per-instance builders are used inside test bodies when the
SoD check on AdverseEvent (PRD §3.9) needs a specific X-User-ID.
"""
from __future__ import annotations

import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle owned by the runner."""
    return api_client


@pytest.fixture(autouse=True)
def _reset_state_between_tests():
    """Best-effort wipe of the implementation's in-memory store between
    tests. Implementations that do not expose /__test__/reset are
    tolerated; tests still pass as long as they create unique entities.
    """
    try:
        api_client._request("POST", "/__test__/reset", None, {})
    except Exception:
        pass
    yield


# ---------------------------------------------------------------------------
# Role headers - all four roles are opaque (PRD §2.1).
# ---------------------------------------------------------------------------
@pytest.fixture
def provider_clinician_headers():
    return TEST_USERS["provider_clinician_headers"]


@pytest.fixture
def provider_clinician_headers_alt():
    return TEST_USERS["provider_clinician_headers_alt"]


@pytest.fixture
def reviewing_clinician_headers():
    return TEST_USERS["reviewing_clinician_headers"]


@pytest.fixture
def reviewing_clinician_headers_alt():
    return TEST_USERS["reviewing_clinician_headers_alt"]


@pytest.fixture
def school_registrar_headers():
    return TEST_USERS["school_registrar_headers"]


@pytest.fixture
def public_health_officer_headers():
    return TEST_USERS["public_health_officer_headers"]
