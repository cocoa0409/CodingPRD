"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle (start/stop, per-test restart, PYTHONPATH) is managed by
prd-bench-local-runner. These fixtures only expose the API client and role headers.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS, ANON_HEADERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. The runner restarts the server before each test."""
    return api_client


@pytest.fixture
def manager_headers():
    return TEST_USERS["manager"]


@pytest.fixture
def frontdesk_headers():
    return TEST_USERS["frontdesk"]


@pytest.fixture
def proshop_headers():
    return TEST_USERS["proshop"]


@pytest.fixture
def member_headers():
    return TEST_USERS["member"]


@pytest.fixture
def anon_headers():
    return ANON_HEADERS
