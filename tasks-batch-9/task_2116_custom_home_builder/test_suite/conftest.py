"""Pytest fixtures exposing the custom home builder test_helpers infrastructure."""

import pytest
from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    """The back-office operator; its X-User-ID is opaque."""
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def unknown_project_manager_headers():
    """ProjectManager role whose X-User-ID resolves to no StaffMember."""
    return TEST_USERS["unknown_project_manager_headers"]


@pytest.fixture
def unknown_client_headers():
    """Client role whose X-User-ID resolves to no homeowner record."""
    return TEST_USERS["unknown_client_headers"]


@pytest.fixture
def unknown_subcontractor_headers():
    """Subcontractor role whose X-User-ID resolves to no trade record."""
    return TEST_USERS["unknown_subcontractor_headers"]
