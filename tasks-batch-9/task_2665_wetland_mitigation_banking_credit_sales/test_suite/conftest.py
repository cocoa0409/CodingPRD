"""Pytest fixtures exposing the test_helpers infrastructure."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def sponsor_headers():
    return TEST_USERS["sponsor_headers"]


@pytest.fixture
def permittee_headers():
    return TEST_USERS["permittee_headers"]


@pytest.fixture
def irt_member_headers():
    return TEST_USERS["irt_member_headers"]


@pytest.fixture
def irt_chair_headers():
    return TEST_USERS["irt_chair_headers"]


@pytest.fixture
def program_admin_headers():
    return TEST_USERS["program_admin_headers"]
