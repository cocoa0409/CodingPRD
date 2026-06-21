"""Pytest fixtures exposing test_helpers infrastructure for the Trophy, Awards & Engraving suite."""
import pytest
from test_helpers import (
    api_client,
    ApiClient,
    TEST_USERS,
    make_customer_headers,
    make_staff_headers,
    make_manager_headers,
    make_anonymous_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]


@pytest.fixture
def customer_headers():
    return TEST_USERS["customer_headers"]


@pytest.fixture
def staff_headers():
    return TEST_USERS["staff_headers"]


@pytest.fixture
def manager_headers():
    return TEST_USERS["manager_headers"]


@pytest.fixture
def cust_headers_for():
    """Returns the per-instance Customer header builder for ownership-gated calls."""
    return make_customer_headers
