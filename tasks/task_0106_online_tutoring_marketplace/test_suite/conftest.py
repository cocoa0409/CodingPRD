"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH and server lifecycle. This conftest wires
per-role headers and the session-scoped API client.

PRD §2.1 identity rules:
- PlatformAdmin / CredentialVerifier / PlatformArbiter are OPAQUE —
  shared constants canonical for these operator-only roles.
- Tutor / Student / Parent are ENTITY-BACKED. The fallback headers in
  TEST_USERS are ONLY for tests that do not exercise ownership.
  Ownership-gated tests must mint headers via make_tutor_headers /
  make_student_headers / make_parent_headers using the actual
  entity ids returned by the create endpoints.
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
# Opaque-role headers — shared constants canonical (PRD §2.1).
# ---------------------------------------------------------------------------
@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def admin_headers_alt():
    return TEST_USERS["admin_headers_alt"]


@pytest.fixture
def verifier_headers():
    return TEST_USERS["verifier_headers"]


@pytest.fixture
def verifier_headers_alt():
    return TEST_USERS["verifier_headers_alt"]


@pytest.fixture
def arbiter_headers():
    return TEST_USERS["arbiter_headers"]


@pytest.fixture
def arbiter_headers_alt():
    return TEST_USERS["arbiter_headers_alt"]


# ---------------------------------------------------------------------------
# Entity-backed fallback headers — ONLY safe when ownership is NOT
# exercised. Ownership-gated calls MUST mint per-instance headers via
# make_tutor_headers / make_student_headers / make_parent_headers.
# ---------------------------------------------------------------------------
@pytest.fixture
def tutor_fallback_headers():
    return TEST_USERS["tutor_headers"]


@pytest.fixture
def student_fallback_headers():
    return TEST_USERS["student_headers"]


@pytest.fixture
def parent_fallback_headers():
    return TEST_USERS["parent_headers"]
