"""Pytest fixtures exposing test_helpers infrastructure.

The runner restarts the API server before every test, so each test builds its
own state from scratch via the helpers.
"""
import pytest

from test_helpers import (
    ApiClient,
    TEST_USERS,
    api_client,
    make_business_owner_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def officer_a_headers():
    return TEST_USERS["officer_a_headers"]


@pytest.fixture
def officer_b_headers():
    return TEST_USERS["officer_b_headers"]


@pytest.fixture
def manager_1_headers():
    return TEST_USERS["manager_1_headers"]


@pytest.fixture
def secretary_1_headers():
    return TEST_USERS["secretary_1_headers"]


@pytest.fixture
def admin_1_headers():
    return TEST_USERS["admin_1_headers"]


@pytest.fixture
def owner_headers_factory():
    """Factory fixture: build entity-backed BusinessOwner headers for a real owner id."""
    return make_business_owner_headers
