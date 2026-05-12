"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH and server lifecycle. This conftest just
wires per-role headers and the session-scoped api client.
"""
from __future__ import annotations
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


# ---------------------------------------------------------------------------
# Role-header fixtures. Per PRD §2.1:
#   - PlatformAdmin headers are opaque — safe to share.
#   - LabOwner and User headers are entity-backed; the fallback constants
#     below are only correct for tests that do NOT exercise ownership
#     (missing-auth, wrong-role, missing-resource scenarios). Ownership-
#     gated tests must use make_lab_owner_headers(user['id']) /
#     make_user_headers(user['id']) from test_helpers.
# ---------------------------------------------------------------------------
@pytest.fixture
def admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def admin_headers_alt():
    return TEST_USERS["platform_admin_headers_alt"]


@pytest.fixture
def lab_owner_headers_fallback():
    """Entity-backed fallback LabOwner headers. Use ONLY for tests that
    do not depend on ownership (per PRD §2.1)."""
    return TEST_USERS["lab_owner_headers"]


@pytest.fixture
def user_headers_fallback():
    """Entity-backed fallback User headers. Use ONLY for tests that do
    not depend on ownership (per PRD §2.1)."""
    return TEST_USERS["user_headers"]
