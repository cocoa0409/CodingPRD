"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def admin_alt_headers():
    return TEST_USERS["admin_alt_headers"]


@pytest.fixture
def provider_headers():
    return TEST_USERS["provider_headers"]


@pytest.fixture
def observer_headers():
    return TEST_USERS["observer_headers"]


@pytest.fixture
def coach_headers():
    return TEST_USERS["coach_headers"]


@pytest.fixture
def reviewer_headers():
    return TEST_USERS["reviewer_headers"]


@pytest.fixture
def family_headers():
    return TEST_USERS["family_headers"]
