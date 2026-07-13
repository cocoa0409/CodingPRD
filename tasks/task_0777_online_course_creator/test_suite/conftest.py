"""Pytest fixtures exposing test_helpers infrastructure.

The server lifecycle (start/stop, per-test restart, empty DB) is owned by
prd-bench-local-runner; these fixtures only expose the client and role headers.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def creator_headers():
    """Shared-constant Creator headers — only for non-ownership tests."""
    return TEST_USERS["creator_headers"]


@pytest.fixture
def student_headers():
    """Shared-constant Student headers — only for non-ownership tests."""
    return TEST_USERS["student_headers"]
