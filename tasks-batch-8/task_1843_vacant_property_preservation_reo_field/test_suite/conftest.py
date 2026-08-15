"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def vendor_admin_headers():
    return TEST_USERS["vendor_admin_headers"]


@pytest.fixture
def dispatcher_headers():
    return TEST_USERS["dispatcher_headers"]


@pytest.fixture
def quality_reviewer_headers():
    return TEST_USERS["quality_reviewer_headers"]


@pytest.fixture
def servicer_headers():
    return TEST_USERS["servicer_headers"]


@pytest.fixture
def field_crew_headers():
    return TEST_USERS["field_crew_headers"]
