"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle is managed by the runner; tests assume the API is reachable.
"""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed externally."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def programmer_headers():
    return TEST_USERS["programmer_headers"]


@pytest.fixture
def licensing_headers():
    return TEST_USERS["licensing_headers"]


@pytest.fixture
def adops_headers():
    return TEST_USERS["adops_headers"]


@pytest.fixture
def reviewer_headers():
    return TEST_USERS["reviewer_headers"]


@pytest.fixture
def analyst_headers():
    return TEST_USERS["analyst_headers"]


@pytest.fixture
def controller_headers():
    return TEST_USERS["controller_headers"]
