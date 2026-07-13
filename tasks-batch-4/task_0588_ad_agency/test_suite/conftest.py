"""Pytest fixtures exposing test_helpers infrastructure."""

import pytest

from test_helpers import NO_AUTH_HEADERS, TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def agency_admin_headers():
    return TEST_USERS["agency_admin_headers"]


@pytest.fixture
def account_manager_headers():
    return TEST_USERS["account_manager_headers"]


@pytest.fixture
def creative_lead_headers():
    return TEST_USERS["creative_lead_headers"]


@pytest.fixture
def media_buyer_headers():
    return TEST_USERS["media_buyer_headers"]


@pytest.fixture
def client_reviewer_headers():
    return TEST_USERS["client_reviewer_headers"]


@pytest.fixture
def no_auth_headers():
    return NO_AUTH_HEADERS
