"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle is managed by the runner; tests assume the API is reachable.
"""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def sponsor_headers():
    return TEST_USERS["sponsor_headers"]


@pytest.fixture
def sponsor2_headers():
    return TEST_USERS["sponsor2_headers"]


@pytest.fixture
def analyst_headers():
    return TEST_USERS["analyst_headers"]


@pytest.fixture
def officer_headers():
    return TEST_USERS["officer_headers"]


@pytest.fixture
def officer2_headers():
    return TEST_USERS["officer2_headers"]


@pytest.fixture
def finance_headers():
    return TEST_USERS["finance_headers"]


@pytest.fixture
def finance2_headers():
    return TEST_USERS["finance2_headers"]


@pytest.fixture
def audit_headers():
    return TEST_USERS["audit_headers"]
