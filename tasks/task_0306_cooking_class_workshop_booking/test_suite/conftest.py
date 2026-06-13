"""Pytest fixtures exposing test_helpers infrastructure.

The runner handles PYTHONPATH so `test_helpers` is importable directly, and it
manages server lifecycle (a fresh empty-database server before every test).
"""
import pytest

from test_helpers import (
    api_client,
    ApiClient,
    TEST_USERS,
    make_studio_admin_headers,
    make_instructor_headers,
    make_member_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def studio_admin_headers():
    return TEST_USERS["studio_admin_headers"]


@pytest.fixture
def instructor_headers_shared():
    """Shared Instructor constant — use ONLY for tests that do not exercise
    Instructor ownership (negative auth/role tests)."""
    return TEST_USERS["instructor_headers"]


@pytest.fixture
def member_headers_shared():
    """Shared Member constant — use ONLY for tests that do not exercise Member
    ownership (negative auth/role tests)."""
    return TEST_USERS["member_headers"]


@pytest.fixture
def headers_factory():
    """Factory exposing per-role builder functions so tests can mint per-entity
    headers threaded with the real entity id."""
    return {
        "studio_admin": make_studio_admin_headers,
        "instructor": make_instructor_headers,
        "member": make_member_headers,
    }
