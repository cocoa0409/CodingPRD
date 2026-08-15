"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def parentbody_admin_headers():
    return TEST_USERS["parentbody_admin_headers"]


@pytest.fixture
def local_admin_headers():
    return TEST_USERS["local_admin_headers"]


@pytest.fixture
def secretary_treasurer_headers():
    return TEST_USERS["secretary_treasurer_headers"]


@pytest.fixture
def office_clerk_headers():
    return TEST_USERS["office_clerk_headers"]


@pytest.fixture
def member_headers():
    return TEST_USERS["member_headers"]
