"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def superintendent_headers():
    return TEST_USERS["superintendent_headers"]


@pytest.fixture
def dispatcher_headers():
    return TEST_USERS["dispatcher_headers"]


@pytest.fixture
def foreman_headers():
    return TEST_USERS["foreman_headers"]


@pytest.fixture
def adjuster_headers():
    return TEST_USERS["adjuster_headers"]


@pytest.fixture
def payroll_headers():
    return TEST_USERS["payroll_headers"]


@pytest.fixture
def billing_headers():
    return TEST_USERS["billing_headers"]
