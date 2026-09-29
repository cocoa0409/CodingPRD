"""Pytest fixtures exposing the governance test kit."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def clerk_headers():
    return TEST_USERS["board_clerk_headers"]


@pytest.fixture
def analyst_headers():
    return TEST_USERS["policy_analyst_headers"]


@pytest.fixture
def superintendent_headers():
    return TEST_USERS["superintendent_headers"]


@pytest.fixture
def principal_headers():
    return TEST_USERS["school_principal_headers"]


@pytest.fixture
def legal_service_headers():
    return TEST_USERS["legal_update_service_headers"]


@pytest.fixture
def public_headers():
    return TEST_USERS["public_headers"]


@pytest.fixture
def president_headers():
    """Shared BoardPresident constant. Only for calls that perform no ownership check."""
    return TEST_USERS["board_president_headers"]


@pytest.fixture
def member_headers():
    """Shared BoardMember constant. Only for calls that perform no ownership check."""
    return TEST_USERS["board_member_headers"]
