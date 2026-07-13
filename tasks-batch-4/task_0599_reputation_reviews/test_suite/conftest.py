"""Pytest fixtures exposing test_helpers infrastructure."""

import pytest

from test_helpers import (
    TEST_USERS,
    ApiClient,
    anonymous_headers,
    api_client,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is owned by the runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def admin2_headers():
    return TEST_USERS["admin2_headers"]


@pytest.fixture
def response_agent_headers():
    return TEST_USERS["response_agent_headers"]


@pytest.fixture
def response_agent2_headers():
    return TEST_USERS["response_agent2_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def business_owner_headers():
    return TEST_USERS["business_owner_headers"]


@pytest.fixture
def location_manager_headers():
    return TEST_USERS["location_manager_headers"]


@pytest.fixture
def anon_headers():
    return anonymous_headers()
