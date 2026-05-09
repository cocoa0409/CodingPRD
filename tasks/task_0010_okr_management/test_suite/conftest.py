"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


# Per-role headers — for opaque roles (PlatformAdmin, HRBP) and for non-ownership tests.
# Ownership-gated tests should call make_employee_headers / make_manager_headers with
# the actual User.id from a fixture.

@pytest.fixture
def admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def hrbp_headers():
    return TEST_USERS["hrbp_headers"]


@pytest.fixture
def employee_headers_unowned():
    """Shared Employee header — does NOT resolve to a real User. Use ONLY for tests
    that don't exercise ownership (e.g., 401/403/404 checks before any ownership lookup).
    """
    return TEST_USERS["employee_headers"]


@pytest.fixture
def manager_headers_unowned():
    """Shared Manager header — does NOT resolve to a real User. Use ONLY for tests
    that don't exercise ownership.
    """
    return TEST_USERS["manager_headers"]
