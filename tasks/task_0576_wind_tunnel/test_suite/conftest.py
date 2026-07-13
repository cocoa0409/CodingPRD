"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle (start/stop/restart-before-each-test) is owned by
prd-bench-local-runner; these fixtures only hand tests a ready client and
pre-built role headers.
"""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client pointing at API_BASE_URL."""
    return api_client


@pytest.fixture
def manager_headers():
    return TEST_USERS["manager_headers"]


@pytest.fixture
def frontdesk_headers():
    return TEST_USERS["frontdesk_headers"]


@pytest.fixture
def flyer_headers():
    return TEST_USERS["flyer_headers"]


@pytest.fixture
def instructor_headers():
    return TEST_USERS["instructor_headers"]
