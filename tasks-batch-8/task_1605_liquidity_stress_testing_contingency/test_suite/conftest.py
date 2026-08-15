"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle is managed by prd-bench-local-runner; tests assume the
server is already running and reachable at API_BASE_URL.
"""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def analyst_headers():
    return TEST_USERS["analyst_headers"]


@pytest.fixture
def analyst_9_headers():
    return TEST_USERS["analyst_9_headers"]


@pytest.fixture
def officer_headers():
    return TEST_USERS["officer_headers"]


@pytest.fixture
def officer_2_headers():
    return TEST_USERS["officer_2_headers"]


@pytest.fixture
def officer_3_headers():
    return TEST_USERS["officer_3_headers"]


@pytest.fixture
def committee_headers():
    return TEST_USERS["committee_headers"]


@pytest.fixture
def committee_9_headers():
    return TEST_USERS["committee_9_headers"]


@pytest.fixture
def ops_headers():
    return TEST_USERS["ops_headers"]


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]
