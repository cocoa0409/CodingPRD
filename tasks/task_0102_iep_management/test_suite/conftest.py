"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH and server lifecycle. This conftest
wires per-role headers and the session-scoped API client.

PRD §2.1 identity rules:
- DistrictAdmin / SchoolPsychologist / SpecialEducationTeacher /
  RelatedServiceProvider are OPAQUE — shared constants canonical.
- Parent is OWNERSHIP-GATED. The `parent_fallback_headers` fixture is
  ONLY safe for tests that do not exercise Parent ownership.
  Ownership-gated tests must mint headers via
  make_parent_headers(student["parent_user_id"]).
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
def psychologist_headers():
    return TEST_USERS["psychologist_headers"]


@pytest.fixture
def psychologist_headers_alt():
    return TEST_USERS["psychologist_headers_alt"]


@pytest.fixture
def teacher_headers():
    return TEST_USERS["teacher_headers"]


@pytest.fixture
def teacher_headers_alt():
    return TEST_USERS["teacher_headers_alt"]


@pytest.fixture
def provider_headers():
    return TEST_USERS["provider_headers"]


@pytest.fixture
def provider_headers_alt():
    return TEST_USERS["provider_headers_alt"]


# ---------------------------------------------------------------------------
# Parent fallback — ONLY safe when ownership is NOT exercised
# (header-missing tests, role-mismatch tests, NotFound paths).
# Ownership-gated calls MUST mint per-instance headers via
# make_parent_headers(student["parent_user_id"]).
# ---------------------------------------------------------------------------
@pytest.fixture
def parent_fallback_headers():
    return TEST_USERS["parent_headers"]
