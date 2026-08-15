"""Pytest fixtures exposing the test_helpers infrastructure."""
import pytest

from test_helpers import (
    NO_AUTH_HEADERS,
    TEST_USERS,
    ApiClient,
    api_client,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def harvest_operator_headers():
    return TEST_USERS["harvest_operator_headers"]


@pytest.fixture
def grower_liaison_headers():
    return TEST_USERS["grower_liaison_headers"]


@pytest.fixture
def crew_boss_headers():
    return TEST_USERS["crew_boss_headers"]


@pytest.fixture
def billing_clerk_headers():
    return TEST_USERS["billing_clerk_headers"]


@pytest.fixture
def no_auth_headers():
    return dict(NO_AUTH_HEADERS)
