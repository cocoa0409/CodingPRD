"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def pm_headers():
    """ProgramManager (opaque role) headers."""
    return TEST_USERS["program_manager_headers"]


@pytest.fixture
def contractor_headers():
    """Shared Contractor-role headers — non-ownership calls only."""
    return TEST_USERS["contractor_headers"]


@pytest.fixture
def inspector_headers():
    """Shared Inspector-role headers — non-ownership calls only."""
    return TEST_USERS["inspector_headers"]


@pytest.fixture
def customer_headers():
    """Shared Customer-role headers — non-ownership calls only."""
    return TEST_USERS["customer_headers"]
