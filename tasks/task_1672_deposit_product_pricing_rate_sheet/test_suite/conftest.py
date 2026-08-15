"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle is managed externally; the client targets API_BASE_URL.
"""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. The server is guaranteed running."""
    return api_client


@pytest.fixture
def analyst_headers():
    return TEST_USERS["analyst_headers"]


@pytest.fixture
def committee_headers():
    return TEST_USERS["committee_headers"]


@pytest.fixture
def treasury_headers():
    return TEST_USERS["treasury_headers"]


@pytest.fixture
def banker_headers():
    return TEST_USERS["banker_headers"]


@pytest.fixture
def compliance_headers():
    return TEST_USERS["compliance_headers"]


@pytest.fixture
def channel_headers():
    return TEST_USERS["channel_headers"]


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]
