"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def coach_headers():
    return TEST_USERS["coach_headers"]


@pytest.fixture
def family_headers():
    return TEST_USERS["family_headers"]


@pytest.fixture
def contact_headers():
    return TEST_USERS["contact_headers"]
