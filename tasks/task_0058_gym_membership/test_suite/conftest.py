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
#   - PlatformAdmin, StaffOps, system are OPAQUE — shared constants OK.
#   - Member and Trainer are entity_backed — tests that exercise ownership
#     MUST use make_member_headers(member['id']) /
#     make_trainer_headers(trainer['id']).
# ---------------------------------------------------------------------------
@pytest.fixture
def pa_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def pa_headers_alt():
    return TEST_USERS["platform_admin_headers_alt"]


@pytest.fixture
def so_headers():
    return TEST_USERS["staff_ops_headers"]


@pytest.fixture
def so_headers_alt():
    return TEST_USERS["staff_ops_headers_alt"]


@pytest.fixture
def sys_headers():
    return TEST_USERS["system_headers"]


@pytest.fixture
def member_headers_fallback():
    """Fallback Member headers — opaque X-User-ID 'member-fallback'.

    Per PRD §2.1 ownership checks compare X-User-ID to the resource's
    member foreign-key; this constant matches no real Member.id, so use
    it ONLY for tests that do not exercise ownership (missing-auth,
    wrong-role, missing-resource).
    """
    return TEST_USERS["member_headers"]


@pytest.fixture
def trainer_headers_fallback():
    return TEST_USERS["trainer_headers"]
