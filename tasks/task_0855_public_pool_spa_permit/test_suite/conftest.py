"""Pytest fixtures exposing the test_helpers infrastructure."""

import pytest

from test_helpers import (
    ApiClient,
    TEST_USERS,
    api_client,
    make_operator_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is owned by the runner."""
    return api_client


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]


@pytest.fixture
def operator_headers():
    """Shared Operator headers. Only safe where ownership is not exercised."""
    return TEST_USERS["operator_headers"]


@pytest.fixture
def inspector_headers():
    return TEST_USERS["inspector_headers"]


@pytest.fixture
def inspector_two_headers():
    return TEST_USERS["inspector_two_headers"]


@pytest.fixture
def plan_reviewer_headers():
    return TEST_USERS["plan_reviewer_headers"]


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def operator_headers_for():
    """Factory returning Operator headers bound to a real operator id."""
    return make_operator_headers
