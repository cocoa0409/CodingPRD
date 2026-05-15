"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH and server lifecycle. This conftest just
wires per-role headers and the session-scoped API client.

PRD §2.1 identity rules:
- HrUser/HiringManager/HrApprover/FinanceApprover are entity_backed:HrUser.
  Shared-constant fallbacks are kept for tests that fail BEFORE HR-binding
  integrity is consulted (e.g., missing-resource 404, malformed payload,
  wrong-role 403). Ownership-gated tests use make_hr_user_headers(id) etc.
- Candidate is entity_backed:Candidate. Shared-constant fallback kept for
  the registration POST itself (the row does not yet exist) and for
  payload-validation failures. Ownership-gated tests use
  make_candidate_headers(candidate['id']).
- HeadhunterUser is entity_backed:HeadhunterContract. Shared-constant
  fallback for non-ownership tests; otherwise make_headhunter_headers(id).
- PlatformAdmin is opaque — shared constants canonical.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiClient,
    TEST_USERS,
    api_client,
    reset_clock_to_epoch,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture(autouse=True)
def _reset_state_between_tests():
    """Wipe the implementation's in-memory store before each test so
    state cannot leak. The /__test__/reset endpoint is a test-infrastructure
    extension parallel to the PRD §3.9 test-driver endpoints; a 404 from
    an implementation that does not expose it is tolerated."""
    try:
        api_client._request("POST", "/__test__/reset", None, {})
    except Exception:
        pass
    yield


@pytest.fixture(autouse=True)
def _reset_logical_clock():
    """PRD §3.9: tests that don't touch the clock or sweep should observe
    a fresh logical clock anchored at TEST_EPOCH. Tolerate failures so
    tests that don't need the clock still proceed."""
    try:
        reset_clock_to_epoch()
    except Exception:
        pass
    yield


# ---------------------------------------------------------------------------
# PlatformAdmin (opaque — shared constants canonical, PRD §2.1)
# ---------------------------------------------------------------------------
@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def platform_admin_headers_alt():
    return TEST_USERS["platform_admin_headers_alt"]


# ---------------------------------------------------------------------------
# Fallback headers for entity_backed roles (non-ownership tests only).
# Ownership-gated tests must use the per-instance builders.
# ---------------------------------------------------------------------------
@pytest.fixture
def hr_user_fallback_headers():
    """For tests that fail before HR-binding integrity is consulted.
    Use make_hr_user_headers(hr_user['id']) for ownership-gated calls."""
    return TEST_USERS["hr_user_fallback_headers"]


@pytest.fixture
def candidate_fallback_headers():
    """For Candidate registration itself and payload-validation tests.
    Use make_candidate_headers(candidate['id']) for ownership-gated calls."""
    return TEST_USERS["candidate_fallback_headers"]


@pytest.fixture
def headhunter_fallback_headers():
    """For non-ownership Headhunter tests. Use
    make_headhunter_headers(contract['id']) for ownership-gated calls."""
    return TEST_USERS["headhunter_fallback_headers"]
