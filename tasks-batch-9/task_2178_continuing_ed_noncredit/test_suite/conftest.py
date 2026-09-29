"""Pytest fixtures exposing the test_helpers infrastructure."""

import pytest

from test_helpers import (
    ANONYMOUS_HEADERS,
    TEST_USERS,
    ApiClient,
    api_client,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def program_admin_headers():
    return TEST_USERS["program_admin_headers"]


@pytest.fixture
def program_admin_2_headers():
    return TEST_USERS["program_admin_2_headers"]


@pytest.fixture
def registrar_headers():
    return TEST_USERS["registrar_headers"]


@pytest.fixture
def learner_headers():
    return TEST_USERS["learner_headers"]


@pytest.fixture
def instructor_headers():
    return TEST_USERS["instructor_headers"]


@pytest.fixture
def corporate_sponsor_headers():
    return TEST_USERS["corporate_sponsor_headers"]


@pytest.fixture
def anonymous_headers():
    return ANONYMOUS_HEADERS
