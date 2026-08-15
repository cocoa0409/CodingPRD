"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle is managed by the runner; tests assume the API is
reachable at API_BASE_URL and starts from an empty database.
"""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client."""
    return api_client


@pytest.fixture
def officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def underwriter_headers():
    return TEST_USERS["underwriter_headers"]


@pytest.fixture
def policyholder_headers():
    return TEST_USERS["policyholder_headers"]
