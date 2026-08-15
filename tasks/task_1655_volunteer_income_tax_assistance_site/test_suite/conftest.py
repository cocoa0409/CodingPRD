"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def sponsor_admin_headers():
    return TEST_USERS["sponsor_admin_headers"]


@pytest.fixture
def site_coordinator_headers():
    """Shared SiteCoordinator headers — only for calls that do not exercise
    the own-site binding. Site operations require
    make_site_coordinator_headers(coordinator["id"])."""
    return TEST_USERS["site_coordinator_headers"]


@pytest.fixture
def preparer_headers():
    """Shared Preparer headers — only for calls that are not ownership-gated.
    Return lifecycle steps require make_preparer_headers(return preparer id)."""
    return TEST_USERS["preparer_headers"]


@pytest.fixture
def quality_reviewer_headers():
    return TEST_USERS["quality_reviewer_headers"]


@pytest.fixture
def screener_headers():
    return TEST_USERS["screener_headers"]
