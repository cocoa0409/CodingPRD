"""Pytest fixtures exposing the test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def agency_admin_headers():
    return TEST_USERS["agency_admin_headers"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["auditor_headers"]


@pytest.fixture
def rep_headers():
    """Shared Rep fallback — entity-backed, resolves to nothing; negative probes only."""
    return TEST_USERS["rep_headers"]


@pytest.fixture
def principal_ops_headers():
    """Shared PrincipalOps fallback — entity-backed; negative probes only."""
    return TEST_USERS["principal_ops_headers"]
