"""Pytest fixtures exposing test_helpers infrastructure."""

import pytest

from test_helpers import NO_AUTH_HEADERS, TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's job."""
    return api_client


@pytest.fixture
def customer_headers():
    """Shared Customer constant. PRD §2.1 makes the Customer role entity-backed, so
    this is only usable where the call does NOT depend on owning the resource."""
    return TEST_USERS["customer_headers"]


@pytest.fixture
def optician_headers():
    return TEST_USERS["optician_headers"]


@pytest.fixture
def store_associate_headers():
    return TEST_USERS["store_associate_headers"]


@pytest.fixture
def lab_tech_headers():
    return TEST_USERS["lab_tech_headers"]


@pytest.fixture
def benefits_admin_headers():
    return TEST_USERS["benefits_admin_headers"]


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def no_auth_headers():
    return NO_AUTH_HEADERS
