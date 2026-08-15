"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle is managed by the runner; tests assume the API is reachable
at API_BASE_URL and starts against an empty database for every test.
"""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def union_rep_headers():
    return TEST_USERS["union_rep_headers"]


@pytest.fixture
def union_rep_2_headers():
    return TEST_USERS["union_rep_2_headers"]


@pytest.fixture
def fund_trustee_headers():
    return TEST_USERS["fund_trustee_headers"]


@pytest.fixture
def fund_trustee_2_headers():
    return TEST_USERS["fund_trustee_2_headers"]


@pytest.fixture
def arbitrator_headers():
    return TEST_USERS["arbitrator_headers"]


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]
